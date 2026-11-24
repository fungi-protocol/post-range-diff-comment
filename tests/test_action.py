import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from test_outdated import comment

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = os.environ.get("POST_RANGE_DIFF_EXECUTABLE")
COMMENT_URL = "https://github.com/test/repo/pull/1#issuecomment-1"


class ActionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.origin = self.root / "origin"
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.com",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        self.git("init", "-q", "-b", "main", str(self.origin), cwd=self.root)
        self.commit("base\n", "base")
        self.git("checkout", "-q", "-b", "topic")
        self.before = self.commit("old\n", "change")
        self.git("branch", "old", self.before)
        self.after = self.commit("new\n", "change", amend=True)

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ["git", *args], cwd=cwd or self.origin, env=self.env, text=True
        ).strip()

    def commit(self, content, message, amend=False, path="file"):
        (self.origin / path).write_text(content)
        self.git("add", path)
        self.git("commit", "-q", "-m", message, *(["--amend"] if amend else []))
        return self.git("rev-parse", "HEAD")

    def run_action(
        self,
        *,
        shallow=False,
        packaged=False,
        forced=True,
        base_ref="main",
        rewound=(),
        comments=None,
        post_fails=False,
        wrap_width="",
        draft=False,
        event_action="synchronize",
        before=None,
    ):
        # Stands in for GitHub: the old tips of the base branch, the comments
        # of the pull request, and a record of the ones it was asked to hide.
        stub = self.root / "stub"
        stub.mkdir()
        (stub / "comments").write_text(
            "".join(json.dumps(c) + "\n" for c in comments or ())
        )
        post = "exit 1" if post_fails else f"echo NEW {COMMENT_URL}"
        gh = stub / "gh"
        gh.write_text(f"""#!/bin/sh
case "$*" in
*minimizeComment*) echo "$*" >>"{stub}/hidden" ;;
*graphql*) cat "{stub}/comments" ;;
*/activity*) printf '%s\\n' {" ".join(rewound)} ;;
*)
  for arg in "$@"; do
    case "$arg" in
    body=@*) cp "${{arg#body=@}}" "{stub}/posted" ;;
    esac
  done
  {post}
  ;;
esac
""")
        gh.chmod(0o755)
        posting = comments is not None
        checkout = self.root / "checkout"
        self.git(
            "clone",
            "-q",
            *(["--depth=1"] if shallow else []),
            self.origin.as_uri(),
            str(checkout),
            cwd=self.root,
        )
        output = self.root / "output"
        summary = self.root / "summary"
        env = dict(
            self.env,
            BEFORE=self.before if before is None else before,
            AFTER=self.after,
            DRAFT=str(draft).lower(),
            EVENT_ACTION=event_action,
            BASE_REF=base_ref,
            PR_NUMBER="1",
            GITHUB_REPOSITORY="test/repo",
            GITHUB_SERVER_URL="https://github.com",
            GITHUB_OUTPUT=str(output),
            GITHUB_STEP_SUMMARY=str(summary),
            POST_COMMENT=str(posting).lower(),
            GH_TOKEN="token",
            HIDE_AFTER_DAYS="3",
            WRAP_WIDTH=wrap_width,
            PATH=f"{stub}{os.pathsep}{os.environ['PATH']}",
        )
        command = (
            [PACKAGE]
            if packaged
            else ["bash", str(ROOT / "post-range-diff-comment.sh")]
        )
        result = subprocess.run(
            command,
            cwd=checkout,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, int(post_fails), result.stderr)
        self.assertTrue(output.exists(), result.stderr)
        posted = (
            f"comment-url={COMMENT_URL}\n"
            if posting
            and not post_fails
            and (forced or event_action == "converted_to_draft")
            else ""
        )
        self.assertEqual(output.read_text(), f"forced={str(forced).lower()}\n{posted}")
        if not forced:
            self.assertFalse(summary.exists())
        elif not posting:
            self.assertIn("<b>range-diff</b>", result.stdout)
            self.assertIn(self.before, result.stdout)
            self.assertIn(self.after, result.stdout)
            if not wrap_width:
                self.assertTrue(result.stdout.endswith(summary.read_text()))
        return result.stdout

    def test_force_push_full_checkout(self):
        out = self.run_action()
        self.assertIn("; 1 commit; same base <a", out)
        self.assertIn("</a> +1 -1 1f < -:", out)

    def test_draft_push_posts_nothing(self):
        out = self.run_action(draft=True, forced=False, comments=[])
        self.assertNotIn("NEW", out)
        self.assertNotIn("<b>range-diff</b>", out)
        self.assertFalse((self.root / "stub" / "posted").exists())

    def test_converted_to_draft_posts_marker(self):
        out = self.run_action(
            draft=True, event_action="converted_to_draft", comments=[], forced=False
        )
        posted = (self.root / "stub" / "posted").read_text()
        self.assertTrue(posted.startswith("<!-- post-range-diff-comment "))
        self.assertIn(f"after={self.after}", posted)
        self.assertNotIn("<b>range-diff</b>", out)
        self.assertNotIn("<details>", posted)

    def test_converted_to_draft_posts_minimized_marker(self):
        self.run_action(
            draft=True, event_action="converted_to_draft", comments=[], forced=False
        )
        hidden = (self.root / "stub" / "hidden").read_text()
        self.assertIn("id=NEW", hidden)
        self.assertIn("minimizeComment", hidden)

    def test_converted_to_draft_without_before(self):
        self.run_action(
            draft=True,
            event_action="converted_to_draft",
            comments=[],
            forced=False,
            before="",
        )
        posted = (self.root / "stub" / "posted").read_text()
        self.assertIn(f"after={self.after}", posted)

    def test_ready_for_review_after_converted_to_draft(self):
        old_head = self.before
        marker = comment("MARKER", "2026-01-01T00:00:00Z", isMinimized=True)
        marker["body"] = f"<!-- post-range-diff-comment after={old_head} -->"
        # The draft period moved the head on; the marker is the only record.
        self.before = self.commit("draft\n", "change", amend=True)
        self.after = self.commit("ready\n", "change", amend=True)
        out = self.run_action(comments=[marker], event_action="ready_for_review")
        posted = (self.root / "stub" / "posted").read_text()
        self.assertIn(f"before={old_head} after={self.after}", posted)
        self.assertIn(COMMENT_URL, out)

    def test_ready_for_review_posts_from_last_comment(self):
        old_head = self.before
        last = comment("LAST", "2026-01-01T00:00:00Z")
        last["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'0' * 40} after={old_head} -->\n<details>"
        )
        # The draft period moved the head on; its before must not be used.
        self.before = self.commit("draft\n", "change", amend=True)
        self.after = self.commit("ready\n", "change", amend=True)
        # Newer comments that are not this action's range-diff are ignored.
        chatter = comment("CHATTER", "2026-02-01T00:00:00Z", body="looks good")
        someone_else = comment("OTHER", "2026-03-01T00:00:00Z", viewerDidAuthor=False)
        someone_else["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'1' * 40} after={'2' * 40} -->\n<details>"
        )
        out = self.run_action(
            comments=[last, chatter, someone_else], event_action="ready_for_review"
        )
        posted = (self.root / "stub" / "posted").read_text()
        self.assertIn(f"before={old_head} after={self.after}", posted)
        self.assertNotIn(f"before={self.before}", posted)
        self.assertIn("for force push", posted)
        self.assertNotIn("fast-forward catch-up", posted)
        self.assertIn(COMMENT_URL, out)

    def test_ready_for_review_after_fast_forward_draft(self):
        old_head = self.after
        last = comment("LAST", "2026-01-01T00:00:00Z")
        last["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'0' * 40} after={old_head} -->\n<details>"
        )
        # The draft period only added commits, so the head is a descendant.
        self.before = self.commit("draft\n", "draft")
        self.after = self.commit("ready\n", "ready")
        self.git("merge-base", "--is-ancestor", old_head, self.after)
        out = self.run_action(comments=[last], event_action="ready_for_review")
        posted = (self.root / "stub" / "posted").read_text()
        self.assertIn(f"before={old_head} after={self.after}", posted)
        self.assertIn("for fast-forward catch-up", posted)
        self.assertNotIn("for force push", posted)
        self.assertIn(COMMENT_URL, out)

    def test_ready_for_review_uses_most_recent_range_diff(self):
        older = comment("OLDER", "2026-01-01T00:00:00Z")
        older["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'0' * 40} after={self.before} -->\n<details>"
        )
        mid = self.commit("mid\n", "change", amend=True)
        newer = comment("NEWER", "2026-02-01T00:00:00Z")
        newer["body"] = (
            "<!-- post-range-diff-comment "
            f"before={self.before} after={mid} -->\n<details>"
        )
        self.after = self.commit("ready\n", "change", amend=True)
        out = self.run_action(comments=[older, newer], event_action="ready_for_review")
        posted = (self.root / "stub" / "posted").read_text()
        self.assertIn(f"before={mid} after={self.after}", posted)
        self.assertNotIn(f"before={self.before}", posted)
        self.assertIn(COMMENT_URL, out)

    def test_ready_for_review_without_new_commits_posts_nothing(self):
        last = comment("LAST", "2026-01-01T00:00:00Z")
        last["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'0' * 40} after={self.after} -->\n<details>"
        )
        out = self.run_action(
            comments=[last], event_action="ready_for_review", forced=False
        )
        self.assertNotIn("NEW", out)
        self.assertFalse((self.root / "stub" / "posted").exists())

    def test_ready_for_review_does_not_hide_old_comments(self):
        old = comment("OLD", "2000-01-01T00:00:00Z")
        last = comment("LAST", "2026-01-01T00:00:00Z")
        last["body"] = (
            "<!-- post-range-diff-comment "
            f"before={'0' * 40} after={self.before} -->\n<details>"
        )
        self.after = self.commit("ready\n", "change", amend=True)
        out = self.run_action(comments=[old, last], event_action="ready_for_review")
        self.assertIn(COMMENT_URL, out)
        self.assertFalse((self.root / "stub" / "hidden").exists())

    def test_rebase_onto_newer_base(self):
        self.git("checkout", "-q", "main")
        self.commit("other\n", "advance base", path="other")
        self.git("checkout", "-q", "topic")
        self.git("rebase", "-q", "main")
        self.after = self.git("rev-parse", "HEAD")
        self.assertIn("(descendant, 1 commit ahead)", self.run_action())

    def test_rewritten_parent_in_a_stack(self):
        self.git("checkout", "-q", "-b", "child")
        self.before = self.commit("child\n", "child", path="child")
        self.git("checkout", "-q", "topic")
        old_parent = self.after
        new_parent = self.commit("newer\n", "change", amend=True)
        self.git("checkout", "-q", "child")
        self.git("rebase", "-q", "--onto", "topic", "child~1")
        self.after = self.git("rev-parse", "HEAD")
        collected = "0123456789" * 4
        out = self.run_action(base_ref="topic", rewound=[collected, old_parent])
        self.assertIn(f"git range-diff {old_parent[:7]}", out)
        self.assertIn("1 unchanged; 1 commit; base <a", out)
        self.assertIn(f'{new_parent}">', out)
        self.assertIn("(diverged, 1 ahead and 1 behind)", out)

    def test_unrelated_base_is_not_described(self):
        self.git("checkout", "-q", "main")
        self.commit("rewritten\n", "base", amend=True, path="other")
        self.git("checkout", "-q", "topic")
        self.git("rebase", "-q", "--onto", "main", "topic~1")
        self.after = self.git("rev-parse", "HEAD")
        self.assertNotIn("base <a", self.run_action())

    def test_series_an_old_base_tip_contained(self):
        self.git("checkout", "-q", "-b", "child")
        self.before = self.commit("child\n", "child", path="child")
        self.git("branch", "merged", self.before)
        self.after = self.commit("child again\n", "child", amend=True, path="child")
        self.run_action(base_ref="topic", rewound=[self.before])

    def test_old_range_diff_comments_are_hidden(self):
        old = comment("OLD", "2000-01-01T00:00:00Z")
        new = comment("NEW", "2999-01-01T00:00:00Z")
        self.run_action(comments=[old, new])
        hidden = (self.root / "stub" / "hidden").read_text()
        self.assertIn("id=OLD", hidden)
        self.assertNotIn("id=NEW", hidden)

    def test_the_posted_comment_is_never_hidden(self):
        self.run_action(comments=[comment("NEW", "2000-01-01T00:00:00Z")])
        self.assertFalse((self.root / "stub" / "hidden").exists())

    def test_a_failed_post_hides_nothing(self):
        old = comment("OLD", "2000-01-01T00:00:00Z")
        self.run_action(comments=[old], post_fails=True)
        self.assertFalse((self.root / "stub" / "hidden").exists())

    def test_wrap_width_reaches_the_comment(self):
        self.after = self.commit("old\n" + "x" * 40 + "\n", "change", amend=True)
        out = self.run_action(wrap_width="20")
        self.assertIn("\n++" + "x" * 18 + "\n++" + "x" * 18 + "\n++xxxx\n", out)
        summary = (self.root / "summary").read_text()
        self.assertIn("\n++" + "x" * 40 + "\n", summary)

    def test_force_push_shallow_checkout(self):
        self.run_action(shallow=True)

    def test_fast_forward_is_skipped(self):
        self.before = self.after
        self.after = self.commit("next\n", "next")
        self.run_action(forced=False)

    @unittest.skipUnless(PACKAGE, "installed package not supplied")
    def test_installed_package_full_checkout(self):
        self.run_action(packaged=True)

    @unittest.skipUnless(PACKAGE, "installed package not supplied")
    def test_installed_package_shallow_checkout(self):
        self.run_action(packaged=True, shallow=True)


if __name__ == "__main__":
    unittest.main()
