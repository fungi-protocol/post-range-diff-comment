import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = os.environ.get("POST_RANGE_DIFF_EXECUTABLE")


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
    ):
        # Stands in for the activity log: prints the old tips of the base branch.
        stub = self.root / "stub"
        stub.mkdir()
        gh = stub / "gh"
        gh.write_text("#!/bin/sh\n" + "".join(f"echo {tip}\n" for tip in rewound))
        gh.chmod(0o755)
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
            BEFORE=self.before,
            AFTER=self.after,
            BASE_REF=base_ref,
            PR_NUMBER="1",
            GITHUB_REPOSITORY="test/repo",
            GITHUB_SERVER_URL="https://github.com",
            GITHUB_OUTPUT=str(output),
            GITHUB_STEP_SUMMARY=str(summary),
            POST_COMMENT="false",
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
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists(), result.stderr)
        self.assertEqual(output.read_text(), f"forced={str(forced).lower()}\n")
        if forced:
            self.assertIn("<b>range-diff</b>", result.stdout)
            self.assertIn(self.before, result.stdout)
            self.assertIn(self.after, result.stdout)
            self.assertTrue(result.stdout.endswith(summary.read_text()))
        else:
            self.assertFalse(summary.exists())
        return result.stdout

    def test_force_push_full_checkout(self):
        self.run_action()

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
        self.assertIn(f"{new_parent[:7]}..{self.after[:7]}</code>", out)
        self.assertIn(": 1 unchanged</summary>", out)

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
