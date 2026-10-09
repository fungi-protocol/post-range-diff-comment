#!/usr/bin/env python3
"""Render `git range-diff --no-color` output as a collapsed GitHub comment."""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

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


@dataclass
class Stat:
    added: int = 0
    removed: int = 0
    files: int = 0


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
        "--old-base",
        required=True,
        help="where the old series forked from the base, empty if unknown",
    )
    ap.add_argument(
        "--new-base", required=True, help="where the new series forks from the base"
    )
    ap.add_argument(
        "--base-behind",
        type=int,
        required=True,
        help="commits in the old base missing from the new one",
    )
    ap.add_argument(
        "--base-ahead",
        type=int,
        required=True,
        help="commits in the new base missing from the old one",
    )
    ap.add_argument(
        "--stats",
        type=Path,
        required=True,
        help="`git log --format=%%H --numstat` of both ranges",
    )
    ap.add_argument(
        "--max-bytes",
        type=int,
        default=65000,
        help="GitHub caps comment bodies at 65536 bytes",
    )
    ap.add_argument(
        "--pushed-at", required=True, help="when the push happened, ISO 8601 UTC"
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
            old_base=args.old_base,
            new_base=args.new_base,
            base_behind=args.base_behind,
            base_ahead=args.base_ahead,
            stats=parse_stats(args.stats.read_text()),
            max_bytes=args.max_bytes,
            pushed_at=args.pushed_at,
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


def parse_stats(text: str) -> dict[str, Stat]:
    stats: dict[str, Stat] = {}
    for line in text.splitlines():
        if "\t" not in line:
            if line:
                stat = stats[line] = Stat()
            continue
        # numstat prints "-" for the line counts of a binary file.
        added, removed, _path = line.split("\t", 2)
        stat.added += int(added.replace("-", "0"))
        stat.removed += int(removed.replace("-", "0"))
        stat.files += 1
    return stats


def render(
    pairs: list[Pair],
    *,
    repo_url: str,
    before: str,
    after: str,
    old_range: str,
    new_range: str,
    max_bytes: int,
    pushed_at: str,
    old_base: str,
    new_base: str,
    base_behind: int,
    base_ahead: int,
    stats: dict[str, Stat],
) -> str:
    counts = {op: sum(1 for p in pairs if p.op == op) for op in OP_LABEL}
    tally = (
        ", ".join(f"{n} {OP_LABEL[op]}" for op, n in counts.items() if n)
        or "no commits"
    )
    overview = [tally, describe_series(pairs)]
    if old_base:
        overview.append(
            describe_base(old_base, new_base, base_behind, base_ahead, repo_url)
        )
    head = [
        f"<!-- post-range-diff-comment before={before} after={after} -->",
        "<details>",
        (
            f"<summary><b>range-diff</b> for force push {sha_html(before, repo_url)} → "
            f"{sha_html(after, repo_url)} {relative_time(pushed_at)}: {'; '.join(overview)}</summary>"
        ),
        "",
        f"<sup>reproduce: <code>git range-diff {html.escape(old_range)} {html.escape(new_range)}</code></sup>",
    ]
    note = "<i>Some interdiffs were truncated to fit; the full range-diff is in the job summary.</i>"

    def assemble(pairs: list[Pair], truncated: bool) -> str:
        parts = (
            head
            + (["", note] if truncated else [])
            + ["", render_listing(pairs, repo_url, stats)]
            + (
                ["", render_interdiffs(pairs)]
                if any(p.op == "!" for p in pairs)
                else []
            )
            + ["", "</details>", ""]
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


def render_listing(pairs: list[Pair], repo_url: str, stats: dict[str, Stat]) -> str:
    width = number_width(pairs)
    stat = stat_column(pairs, stats)
    lines = [
        f"{p.lnum.rjust(width)}:  {sha_html(p.lsha, repo_url)}{stat(p.lsha)} {p.op} "
        f"{p.rnum.rjust(width)}:  {sha_html(p.rsha, repo_url)}{stat(p.rsha)} {html.escape(p.subject)}"
        for p in pairs
    ]
    return "<pre>\n" + "\n".join(lines) + "\n</pre>"


def stat_column(pairs: list[Pair], stats: dict[str, Stat]) -> Callable[[str], str]:
    cells = {
        sha: (f"+{s.added}", f"-{s.removed}", f"{s.files}f")
        for p in pairs
        for sha in (p.lsha, p.rsha)
        if (s := stats.get(sha))
    }
    widths = [max(map(len, column)) for column in zip(*cells.values())]

    def column(sha: str) -> str:
        cell = cells.get(sha, [""] * len(widths))
        return "".join(f" {part:>{width}}" for part, width in zip(cell, widths))

    return column


def render_interdiffs(pairs: list[Pair]) -> str:
    width = number_width(pairs)
    blocks = []
    for p in pairs:
        if p.op != "!":
            continue
        head = f"{p.lnum.rjust(width)}:  {p.lsha[:SHORT_SHA]} ! {p.rnum.rjust(width)}:  {p.rsha[:SHORT_SHA]}"
        fence = fence_for(p.body)
        blocks.append(
            f"<details>\n<summary><code>{head}</code> {html.escape(p.subject)}</summary>\n\n"
            f"{fence}diff\n" + "\n".join(p.body) + f"\n{fence}\n\n</details>"
        )
    return "\n\n".join(blocks)


def describe_series(pairs: list[Pair]) -> str:
    old = sum(p.lnum != "-" for p in pairs)
    new = sum(p.rnum != "-" for p in pairs)
    return commits(new) if old == new else f"{old} → {commits(new)}"


def describe_base(old: str, new: str, behind: int, ahead: int, repo_url: str) -> str:
    if old == new:
        return f"same base {sha_html(old, repo_url)}"
    if not behind:
        relation = f"descendant, {commits(ahead)} ahead"
    elif not ahead:
        relation = f"ancestor, {commits(behind)} behind"
    else:
        relation = f"diverged, {ahead} ahead and {behind} behind"
    return f"base {sha_html(old, repo_url)} → {sha_html(new, repo_url)} ({relation})"


def commits(n: int) -> str:
    return f"{n} commit" if n == 1 else f"{n} commits"


def number_width(pairs: list[Pair]) -> int:
    return max((len(n) for p in pairs for n in (p.lnum, p.rnum)), default=1)


def relative_time(iso: str) -> str:
    when = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return f'<relative-time datetime="{when:%Y-%m-%dT%H:%M:%SZ}">{when:%B %-d, %Y %H:%M} UTC</relative-time>'


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
