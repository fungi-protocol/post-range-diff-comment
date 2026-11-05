#!/usr/bin/env python3
"""Pick the range-diff comments old enough to hide.

Reads one GraphQL comment node per line and prints the ids to minimize.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

MARKER = "<!-- post-range-diff-comment "


def main(argv: list[str]) -> int:
    comments = [json.loads(line) for line in sys.stdin if line.strip()]
    days = float(argv[0])
    for node_id in outdated(comments, now=datetime.now(timezone.utc), days=days):
        print(node_id)
    return 0


def outdated(comments: list[dict], *, now: datetime, days: float) -> list[str]:
    cutoff = now - timedelta(days=days)
    return [
        c["id"]
        for c in comments
        # Only comments this token wrote, so a person's comment is never hidden.
        if c["viewerDidAuthor"]
        and c["body"].startswith(MARKER)
        and not c["isMinimized"]
        and datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00")) <= cutoff
    ]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
