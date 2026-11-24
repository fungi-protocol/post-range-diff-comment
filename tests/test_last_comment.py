import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from test_outdated import comment

import last_comment

HEAD = "a" * 40


def range_diff(node_id, created, after=HEAD, **changed):
    body = (
        f"<!-- post-range-diff-comment before={'0' * 40} after={after} -->\n<details>"
    )
    return comment(node_id, created, body=body, **changed)


class LastCommentTest(unittest.TestCase):
    def test_newest_range_diff_comment(self):
        comments = [
            range_diff("older", "2026-01-01T00:00:00Z", after="b" * 40),
            range_diff("newer", "2026-02-01T00:00:00Z", after="c" * 40),
        ]
        self.assertEqual(last_comment.last_head(comments), "c" * 40)

    def test_ignores_other_comments(self):
        comments = [
            range_diff("someone else's", "2026-03-01T00:00:00Z", viewerDidAuthor=False),
            comment("chatter", "2026-04-01T00:00:00Z", body="looks good"),
            range_diff("ours", "2026-01-01T00:00:00Z"),
        ]
        self.assertEqual(last_comment.last_head(comments), HEAD)

    def test_no_range_diff_comment(self):
        self.assertIsNone(last_comment.last_head([]))
        self.assertIsNone(
            last_comment.last_head(
                [comment("chatter", "2026-01-01T00:00:00Z", body="looks good")]
            )
        )

    def test_minimized_marker_is_found(self):
        marker = comment("marker", "2026-01-01T00:00:00Z", isMinimized=True)
        marker["body"] = f"<!-- post-range-diff-comment after={HEAD} -->"
        self.assertEqual(last_comment.last_head([marker]), HEAD)

    def test_comment_without_a_head(self):
        broken = comment("broken", "2026-01-01T00:00:00Z")
        with self.assertRaises(ValueError):
            last_comment.last_head([broken])


if __name__ == "__main__":
    unittest.main()
