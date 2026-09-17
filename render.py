#!/usr/bin/env python3
"""Render `git range-diff --no-color` output as a collapsed GitHub comment."""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, replace

# Pair numbers are right-aligned to the width of the longer range, so a header
# starts with at most a few spaces.  Interdiff lines are indented by exactly
# four, which keeps them from ever matching.
HEADER = re.compile(
    r"^ {0,3}(?P<lnum>\d+|-):\s+(?P<lsha>[0-9a-f]+|-+)"
    r"\s+(?P<op>[=!<>])\s+"
    r"(?P<rnum>\d+|-):\s+(?P<rsha>[0-9a-f]+|-+)"
    r"(?: (?P<subject>.*))?$"
)
BODY_INDENT = "    "
SHORT_SHA = 10
OP_LABEL = {"!": "modified", "=": "unchanged", "<": "dropped", ">": "added"}


@dataclass(frozen=True)
class Pair:
    lnum: str
    lsha: str
    op: str
    rnum: str
    rsha: str
    subject: str
    body: tuple[str, ...] = ()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo-url", required=True, help="e.g. https://github.com/owner/repo"
    )
    ap.add_argument("--before", required=True, help="head commit before the force push")
    ap.add_argument("--after", required=True, help="head commit after the force push")
    ap.add_argument(
        "--old-range",
        required=True,
        help="first range-diff argument, shown for reproduction",
    )
    ap.add_argument(
        "--new-range",
        required=True,
        help="second range-diff argument, shown for reproduction",
    )
    ap.add_argument(
        "--max-bytes",
        type=int,
        default=65000,
        help="GitHub caps comment bodies at 65536 bytes",
    )
    args = ap.parse_args(argv)

    pairs = parse(sys.stdin.read())
    sys.stdout.write(
        render(
            pairs,
            repo_url=args.repo_url,
            before=args.before,
            after=args.after,
            old_range=args.old_range,
            new_range=args.new_range,
            max_bytes=args.max_bytes,
        )
    )
    return 0


def parse(text: str) -> list[Pair]:
    pairs: list[Pair] = []
    bodies: list[list[str]] = []
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            g = m.groupdict()
            pairs.append(
                Pair(
                    g["lnum"],
                    g["lsha"],
                    g["op"],
                    g["rnum"],
                    g["rsha"],
                    g["subject"] or "",
                )
            )
            bodies.append([])
            continue
        if not pairs:
            raise ValueError(
                f"range-diff output does not start with a header line: {line!r}"
            )
        bodies[-1].append(line.removeprefix(BODY_INDENT))
    return [
        replace(p, body=tuple(strip_trailing_blank(b))) for p, b in zip(pairs, bodies)
    ]


def render(
    pairs: list[Pair],
    *,
    repo_url: str,
    before: str,
    after: str,
    old_range: str,
    new_range: str,
    max_bytes: int,
) -> str:
    counts = {op: sum(1 for p in pairs if p.op == op) for op in OP_LABEL}
    tally = (
        ", ".join(f"{n} {OP_LABEL[op]}" for op, n in counts.items() if n)
        or "no commits"
    )
    head = [
        f"<!-- post-range-diff-comment before={before} after={after} -->",
        "<details>",
        (
            f"<summary><b>range-diff</b> for force push {sha_html(before, repo_url)} → "
            f"{sha_html(after, repo_url)}: {tally}</summary>"
        ),
        "",
        f"<sup>reproduce: <code>git range-diff {html.escape(old_range)} {html.escape(new_range)}</code></sup>",
    ]
    note = "<i>Some interdiffs were truncated to fit; the full range-diff is in the job summary.</i>"

    def assemble(pairs: list[Pair], truncated: bool) -> str:
        parts = (
            head
            + (["", note] if truncated else [])
            + ["", render_pairs(pairs, repo_url), "", "</details>", ""]
        )
        return "\n".join(parts)

    out = assemble(pairs, False)
    truncated = False
    while len(out.encode()) > max_bytes and any(len(p.body) > 1 for p in pairs):
        pairs = halve_largest_body(pairs)
        truncated = True
        out = assemble(pairs, truncated)
    if len(out.encode()) > max_bytes:
        tail = "\n\n… (truncated)\n\n</details>\n"
        out = (
            out.encode()[: max_bytes - len(tail.encode())].decode(errors="ignore")
            + tail
        )
    return out


def render_pairs(pairs: list[Pair], repo_url: str) -> str:
    width = max((len(n) for p in pairs for n in (p.lnum, p.rnum)), default=1)
    blocks: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            blocks.append("<br>\n".join(run))
            run.clear()

    for p in pairs:
        head = header_html(p, repo_url, width)
        if p.op != "!":
            run.append(head)
            continue
        flush()
        fence = fence_for(p.body)
        blocks.append(
            f"<details>\n<summary>{head}</summary>\n\n{fence}diff\n"
            + "\n".join(p.body)
            + f"\n{fence}\n\n</details>"
        )
    flush()
    return "\n\n".join(blocks)


def header_html(p: Pair, repo_url: str, width: int) -> str:
    left = f"{p.lnum.rjust(width)}: {sha_html(p.lsha, repo_url)}"
    right = f"{p.rnum.rjust(width)}: {sha_html(p.rsha, repo_url)}"
    return f"<code>{left} {p.op} {right}</code> {html.escape(p.subject)}"


def sha_html(sha: str, repo_url: str) -> str:
    if set(sha) == {"-"}:
        return "-" * SHORT_SHA
    return f'<a href="{repo_url}/commit/{sha}">{sha[:SHORT_SHA]}</a>'


def fence_for(lines: tuple[str, ...]) -> str:
    longest = max(
        (len(run) for line in lines for run in re.findall(r"`+", line)), default=0
    )
    return "`" * max(3, longest + 1)


def halve_largest_body(pairs: list[Pair]) -> list[Pair]:
    largest = max(pairs, key=lambda p: len("\n".join(p.body)))
    keep = (len(largest.body) - 1) // 2
    shrunk = replace(largest, body=largest.body[:keep] + ("… (truncated)",))
    return [shrunk if p is largest else p for p in pairs]


def strip_trailing_blank(lines: list[str]) -> list[str]:
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    return lines[:end]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
