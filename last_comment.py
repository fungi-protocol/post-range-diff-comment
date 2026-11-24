#!/usr/bin/env python3
"""Find the head of the most recent range-diff comment or draft marker.

Reads one GraphQL comment node per line and prints the `after=` head of the
newest range-diff comment or minimized draft marker this token wrote, or
nothing if there is none.
"""

from __future__ import annotations

import json
import re
import sys

import outdated

AFTER = re.compile(r" after=([0-9a-f]{7,64}) ")


def main(argv: list[str]) -> int:
    comments = [json.loads(line) for line in sys.stdin if line.strip()]
    head = last_head(comments)
    if head:
        print(head)
    return 0


def last_head(comments: list[dict]) -> str | None:
    comments = [
        c
        for c in comments
        if c.get("viewerDidAuthor") and c["body"].startswith(outdated.MARKER)
    ]
    if not comments:
        return None
    last = max(comments, key=lambda c: c["createdAt"])
    match = AFTER.search(last["body"])
    if not match:
        raise ValueError(
            f"the last range-diff comment or draft marker {last['id']}"
            " has no after= head"
        )
    return match.group(1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
