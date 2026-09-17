import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import render

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REPO = "https://github.com/fungi-protocol/post-range-diff-comment"
BEFORE = "deecb4b7a41ec39b40cdfc935ab28eb769c3aead"
AFTER = "031a72677e2ee12123ab2c8ef794bc3d0c521d8b"


def render_basic(max_bytes=65000):
    pairs = render.parse((FIXTURES / "basic.txt").read_text())
    return render.render(
        pairs,
        repo_url=REPO,
        before=BEFORE,
        after=AFTER,
        old_range="9b127fb^..deecb4b",
        new_range="9b127fb^..031a726",
        max_bytes=max_bytes,
        pushed_at="2026-09-17T00:10:17Z",
    )


class ParseTest(unittest.TestCase):
    def test_pairs(self):
        pairs = render.parse((FIXTURES / "basic.txt").read_text())
        self.assertEqual([p.op for p in pairs], ["=", "!", "<", ">"])
        self.assertEqual(
            [p.subject for p in pairs], ["add b", "tweak a, add c", "add d", "add e"]
        )
        self.assertEqual(pairs[0].body, ())
        self.assertEqual(pairs[1].body[0], "@@ Metadata")
        self.assertEqual(pairs[1].body[-1], "  l5")
        self.assertEqual(pairs[2].rsha, "-" * 40)

    def test_wide_numbering(self):
        text = " 9:  aaaa = 10:  bbbb subject\n10:  cccc <  -:  ---- gone\n"
        pairs = render.parse(text)
        self.assertEqual([(p.lnum, p.rnum) for p in pairs], [("9", "10"), ("10", "-")])

    def test_body_line_that_looks_like_a_header_stays_a_body(self):
        text = "1:  aaaa ! 1:  bbbb s\n    -:  cccc = 1:  dddd not a header\n"
        pairs = render.parse(text)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].body, ("-:  cccc = 1:  dddd not a header",))


class RenderTest(unittest.TestCase):
    def test_listing_is_one_aligned_pre_block(self):
        pairs = render.parse("1:  aaaa = 1:  aaaa first\n10:  bbbb < -:  ---- tenth\n")
        out = render.render_listing(pairs, REPO)
        self.assertEqual(out.count("<pre>"), 1)
        self.assertIn("\n 1:  <a", out)
        self.assertIn("\n10:  <a", out)

    def test_relative_time(self):
        self.assertEqual(
            render.relative_time("2026-09-17T00:10:17Z"),
            '<relative-time datetime="2026-09-17T00:10:17Z">September 17, 2026 00:10 UTC</relative-time>',
        )

    def test_golden(self):
        expected = (FIXTURES / "basic.md").read_text()
        self.assertEqual(render_basic(), expected)

    def test_subject_is_escaped(self):
        pairs = render.parse("1:  aaaa = 1:  aaaa <script>&\n")
        out = render.render_listing(pairs, REPO)
        self.assertIn("&lt;script&gt;&amp;", out)
        self.assertNotIn("<script>", out)

    def test_fence_grows_past_backticks_in_body(self):
        pairs = render.parse("1:  aaaa ! 1:  bbbb s\n    +```diff\n    +x\n")
        out = render.render_interdiffs(pairs)
        self.assertIn("\n````diff\n", out)
        self.assertIn("\n````\n", out)

    def test_truncation_fits_and_is_noted(self):
        full = render_basic()
        cap = len(full.encode()) - 100
        out = render_basic(max_bytes=cap)
        self.assertLessEqual(len(out.encode()), cap)
        self.assertIn("truncated", out)
        self.assertTrue(out.rstrip().endswith("</details>"))


if __name__ == "__main__":
    unittest.main()
