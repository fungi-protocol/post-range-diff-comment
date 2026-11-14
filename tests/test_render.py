import argparse
import itertools
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import render

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REPO = "https://github.com/fungi-protocol/post-range-diff-comment"
BEFORE = "deecb4b7a41ec39b40cdfc935ab28eb769c3aead"
AFTER = "031a72677e2ee12123ab2c8ef794bc3d0c521d8b"
OLD_BASE = "1111111111111111111111111111111111111111"
NEW_BASE = "2222222222222222222222222222222222222222"


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
        old_base=OLD_BASE,
        new_base=NEW_BASE,
        base_behind=0,
        base_ahead=12,
        stats=render.parse_stats((FIXTURES / "basic.numstat").read_text()),
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
        out = render.render_listing(pairs, REPO, {})
        self.assertEqual(out.count("<pre>"), 1)
        self.assertIn("\n 1:  <a", out)
        self.assertIn("\n10:  <a", out)

    def test_stats_are_summed_per_commit(self):
        stats = render.parse_stats(
            "aaaa\n\n3\t1\ta\n-\t-\ta => b\nbbbb\ncccc\n\n0\t12\tc\n"
        )
        self.assertEqual(stats["aaaa"], render.Stat(added=3, removed=1, files=2))
        self.assertEqual(stats["bbbb"], render.Stat())
        self.assertEqual(stats["cccc"], render.Stat(removed=12, files=1))

    def test_listing_aligns_stats(self):
        pairs = render.parse("1:  aaaa ! 1:  bbbb one\n2:  cccc < -:  ---- two\n")
        stats = {"aaaa": render.Stat(5, 0, 1), "bbbb": render.Stat(120, 7, 10)}
        first, second = render.render_listing(pairs, REPO, stats).splitlines()[1:3]
        self.assertIn("aaaa</a>   +5 -0  1f ! 1:", first)
        self.assertIn("bbbb</a> +120 -7 10f one", first)
        self.assertIn("cccc</a>             < -:  ----------             two", second)

    def test_relative_time(self):
        self.assertEqual(
            render.relative_time("2026-09-17T00:10:17Z"),
            '<relative-time datetime="2026-09-17T00:10:17Z">September 17, 2026 00:10 UTC</relative-time>',
        )

    def test_golden(self):
        expected = (FIXTURES / "basic.md").read_text()
        self.assertEqual(render_basic(), expected)

    def test_series_length(self):
        grown = render.parse("1:  aaaa = 1:  aaaa a\n-:  ---- > 2:  bbbb b\n")
        self.assertEqual(render.describe_series(grown), "1 → 2 commits")
        self.assertEqual(render.describe_series(grown[:1]), "1 commit")

    def test_base_relation(self):
        def base(new, behind, ahead):
            return render.describe_base(OLD_BASE, new, behind, ahead, REPO)

        self.assertTrue(base(OLD_BASE, 0, 0).startswith("same base <a"))
        self.assertIn("(descendant, 1 commit ahead)", base(NEW_BASE, 0, 1))
        self.assertIn("(ancestor, 2 commits behind)", base(NEW_BASE, 2, 0))
        self.assertIn("(diverged, 3 ahead and 2 behind)", base(NEW_BASE, 2, 3))

    def test_subject_is_escaped(self):
        pairs = render.parse("1:  aaaa = 1:  aaaa <script>&\n")
        out = render.render_listing(pairs, REPO, {})
        self.assertIn("&lt;script&gt;&amp;", out)
        self.assertNotIn("<script>", out)

    def test_fence_grows_past_backticks_in_body(self):
        pairs = render.parse("1:  aaaa ! 1:  bbbb s\n    +```diff\n    +x\n")
        out = render.render_interdiffs(pairs)
        self.assertIn("\n````diff\n", out)
        self.assertIn("\n````\n", out)

    def test_long_lines_wrap_with_their_markers(self):
        self.assertEqual(render.wrap("++abcdefgh", 6), ["++abcd", "++efgh"])
        self.assertEqual(render.wrap(" -abcd", 6), [" -abcd"])
        self.assertEqual(render.wrap("++ab cdef", 6), ["++ab ", "++cdef"])
        self.assertEqual(render.wrap("++ab cdefgh", 6), ["++ab ", "++cdef", "++gh"])
        self.assertEqual(render.wrap("++  abcdef", 8), ["++  abcd", "++  ef"])
        self.assertEqual(render.wrap("-  ab cd", 6), ["-  ab ", "-  cd"])
        self.assertEqual(render.wrap("@@ ab cd", 6), ["@@ ab ", "cd"])
        self.assertEqual(render.wrap("+    abcdef", 4), ["+ ab", "+ cd", "+ ef"])
        self.assertEqual(
            render.wrap("++a" + " " * 10 + "abc", 6),
            ["++a   ", "++    ", "++   ", "++abc"],
        )
        self.assertEqual(render.wrap("++abcdefgh", None), ["++abcdefgh"])

    def test_wrap_width_leaves_room_for_markers(self):
        self.assertEqual(render.wrap_width("4"), 4)
        for arg in ("3", "0", "-1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                render.wrap_width(arg)

    def test_wrapping_keeps_the_text(self):
        # Every line up to 7 characters over a small alphabet, at every width:
        # the pieces fit, start with the markers and indentation, and rejoin
        # to the line, less the indentation past half the width.
        # Every piece but the last ends at a space or is cut at the width, and
        # a cut at the width splits only a word longer than a piece holds.
        for n in range(8):
            for chars in itertools.product(" +-@a", repeat=n):
                line = "".join(chars)
                for width in range(render.MIN_WRAP_WIDTH, 9):
                    pieces = render.wrap(line, width)
                    markers = render.hang(line, width)
                    self.assertTrue(all(len(p) <= width for p in pieces))
                    self.assertTrue(all(p.startswith(markers) for p in pieces))
                    if pieces == [line]:
                        continue
                    rest = line[render.HANG.match(line).end() :]
                    self.assertEqual("".join(p[len(markers) :] for p in pieces), rest)
                    for p in pieces[:-1]:
                        self.assertTrue(p.endswith(" ") or len(p) == width)
                    texts = [p[len(markers) :] for p in pieces]
                    for a, b in itertools.pairwise(texts):
                        if not a.endswith(" ") and not b.startswith(" "):
                            word = a.rsplit(" ", 1)[-1] + b.split(" ", 1)[0]
                            self.assertGreater(len(word), width - len(markers))

    def test_wrapped_lines_are_truncated_by_line(self):
        # The line fits unwrapped, but its wrapped pieces do not.  Halving
        # them keeps the fence closed, which a byte cut would not.
        text = "1:  aaaaaaa ! 1:  bbbbbbb s\n    ++" + "x" * 63500 + "\n"
        out = render.render(
            render.parse(text),
            repo_url=REPO,
            before=BEFORE,
            after=AFTER,
            old_range="a..b",
            new_range="a..c",
            max_bytes=65000,
            pushed_at="2026-09-17T00:10:17Z",
            old_base="",
            new_base="",
            base_behind=0,
            base_ahead=0,
            stats={},
            wrap_width=80,
        )
        self.assertLessEqual(len(out.encode()), 65000)
        self.assertIn("Some interdiffs were truncated", out)
        self.assertEqual(out.count("```"), 2)

    def test_truncation_fits_and_is_noted(self):
        full = render_basic()
        cap = len(full.encode()) - 100
        out = render_basic(max_bytes=cap)
        self.assertLessEqual(len(out.encode()), cap)
        self.assertIn("truncated", out)
        self.assertTrue(out.rstrip().endswith("</details>"))


if __name__ == "__main__":
    unittest.main()
