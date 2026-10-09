import pathlib
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import outdated

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def comment(node_id, created, **changed):
    return {
        "id": node_id,
        "createdAt": created,
        "isMinimized": False,
        "viewerDidAuthor": True,
        "body": outdated.MARKER + "before=a after=b -->\n<details>",
    } | changed


class OutdatedTest(unittest.TestCase):
    def pick(self, *comments):
        return outdated.outdated(list(comments), now=NOW, days=3)

    def test_age(self):
        picked = self.pick(
            comment("old", "2026-10-01T00:00:00Z"),
            comment("just old enough", "2026-10-05T12:00:00Z"),
            comment("recent", "2026-10-05T12:00:01Z"),
        )
        self.assertEqual(picked, ["old", "just old enough"])

    def test_only_its_own_visible_range_diffs(self):
        old = "2026-10-01T00:00:00Z"
        picked = self.pick(
            comment("someone else's", old, viewerDidAuthor=False),
            comment("another comment", old, body="looks good"),
            comment("already hidden", old, isMinimized=True),
        )
        self.assertEqual(picked, [])


if __name__ == "__main__":
    unittest.main()
