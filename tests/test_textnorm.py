import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on the path)

import unittest

import textnorm


class TextNormTests(unittest.TestCase):
    def test_curly_quotes(self):
        self.assertEqual(textnorm.normalize("‘a’ “b”"), "'a' \"b\"")

    def test_all_quotes_in_table_are_straightened(self):
        for curly, straight in textnorm.QUOTES.items():
            self.assertEqual(textnorm.normalize("x" + curly + "y"), "x" + straight + "y")

    def test_spaces(self):
        # NBSP, thin space, narrow no-break space
        self.assertEqual(textnorm.normalize("a b"), "a b")
        self.assertEqual(textnorm.normalize("a b"), "a b")
        self.assertEqual(textnorm.normalize("a b"), "a b")

    def test_every_special_space_becomes_a_plain_space(self):
        special = [" ", " ", " ", "　"]
        special += [chr(cp) for cp in range(0x2000, 0x200B)]
        for ch in special:
            with self.subTest(codepoint=hex(ord(ch))):
                text, starts, ends = textnorm.normalize_map("a" + ch + "b")
                self.assertEqual(text, "a b")
                self.assertEqual((starts[1], ends[1]), (1, 2))

    def test_entities_mapped(self):
        text, starts, ends = textnorm.normalize_map("a&amp;b")
        self.assertEqual(text, "a&b")
        self.assertEqual(starts, [0, 1, 6])
        self.assertEqual(ends, [1, 6, 7])

    def test_numeric_entity(self):
        text, starts, ends = textnorm.normalize_map("&#8217;")
        self.assertEqual(text, "'")
        self.assertEqual((starts, ends), ([0], [7]))

    def test_hex_numeric_entity(self):
        text, starts, ends = textnorm.normalize_map("x&#x1F600;y")
        self.assertEqual(text, "x\U0001F600y")
        self.assertEqual(starts, [0, 1, 10])
        self.assertEqual(ends, [1, 10, 11])
        self.assertEqual(textnorm.normalize("&#X41;"), "A")

    def test_named_entities(self):
        self.assertEqual(textnorm.normalize("&lt;b&gt; &quot;x&quot; &rsquo;"), "<b> \"x\" '")

    def test_entity_is_decoded_once(self):
        self.assertEqual(textnorm.normalize("&amp;lt;"), "&lt;")
        self.assertEqual(textnorm.normalize("&amp;amp;"), "&amp;")

    def test_entity_that_decodes_to_two_chars_shares_one_span(self):
        text, starts, ends = textnorm.normalize_map("a&NotEqualTilde;b")
        self.assertEqual(len(text), 4)
        self.assertEqual(starts, [0, 1, 1, 16])
        self.assertEqual(ends, [1, 16, 16, 17])

    def test_incomplete_or_unknown_entities_stay_literal(self):
        for raw in ["a & b", "a&b", "&amp", "&bogus;", "&#xZZ;", "&#;", "&#x;", "&;", "AT&T;",
                    "&#0;", "&#1114112;", "&#xD800;", "&#" + "9" * 20 + ";"]:
            with self.subTest(raw=raw):
                text, starts, ends = textnorm.normalize_map(raw)
                self.assertEqual(text, raw)
                self.assertEqual(starts, list(range(len(raw))))
                self.assertEqual(ends, list(range(1, len(raw) + 1)))

    def test_bare_ampersand_maps_to_itself(self):
        text, starts, ends = textnorm.normalize_map("a & b&amp;c")
        self.assertEqual(text, "a & b&c")
        self.assertEqual(starts, [0, 1, 2, 3, 4, 5, 10])
        self.assertEqual(ends, [1, 2, 3, 4, 5, 10, 11])

    def test_entity_that_decodes_to_a_special_space(self):
        self.assertEqual(textnorm.normalize("a&nbsp;b"), "a b")
        self.assertEqual(textnorm.normalize("a&#160;b"), "a b")

    def test_entity_that_decodes_to_a_dropped_char(self):
        self.assertEqual(textnorm.normalize("a&#8203;b"), "ab")
        self.assertEqual(textnorm.normalize("a&#xFEFF;b"), "ab")

    def test_whitespace_run(self):
        text, starts, ends = textnorm.normalize_map("a \n\t b")
        self.assertEqual(text, "a b")
        self.assertEqual(starts, [0, 1, 5])
        self.assertEqual(ends, [1, 5, 6])

    def test_run_mixing_entities_and_special_spaces(self):
        text, starts, ends = textnorm.normalize_map("a&nbsp;  b")
        self.assertEqual(text, "a b")
        self.assertEqual(starts, [0, 1, 9])
        self.assertEqual(ends, [1, 9, 10])

    def test_zero_width_char_inside_a_run_does_not_split_it(self):
        text, starts, ends = textnorm.normalize_map("a ​ b")
        self.assertEqual(text, "a b")
        self.assertEqual((starts[1], ends[1]), (1, 4))

    def test_strip_ends(self):
        text, starts, ends = textnorm.normalize_map("  a  ")
        self.assertEqual(text, "a")
        self.assertEqual((starts, ends), ([2], [3]))

    def test_strip_ends_with_special_spaces_and_entities(self):
        text, starts, ends = textnorm.normalize_map("&nbsp;　a b &#32;\n")
        self.assertEqual(text, "a b")
        self.assertEqual(starts, [7, 8, 9])
        self.assertEqual(ends, [8, 9, 10])

    def test_empty_and_blank_input(self):
        self.assertEqual(textnorm.normalize_map(""), ("", [], []))
        self.assertEqual(textnorm.normalize_map(" \n ​ "), ("", [], []))

    def test_zero_width_dropped(self):
        text, starts, ends = textnorm.normalize_map("a​b")
        self.assertEqual(text, "ab")
        self.assertEqual(starts, [0, 2])
        self.assertEqual(ends, [1, 3])

    def test_every_zero_width_char_is_dropped(self):
        for ch in ["​", "‌", "‍", "⁠", "﻿"]:
            with self.subTest(codepoint=hex(ord(ch))):
                self.assertEqual(textnorm.normalize("a" + ch + "b"), "ab")

    def test_emoji(self):
        raw = "a \U0001F600 b"
        text, starts, ends = textnorm.normalize_map(raw)
        self.assertEqual(text, raw)
        self.assertIn("\U0001F600", text)
        self.assertEqual(len(starts), len(text))
        self.assertEqual(len(ends), len(text))

    def test_map_points_back_to_the_raw_text(self):
        raw = "  “Hi&nbsp;&nbsp;there” &amp; \U0001F600\n\tbye  "
        text, starts, ends = textnorm.normalize_map(raw)
        self.assertEqual(text, "\"Hi there\" & \U0001F600 bye")
        self.assertEqual(len(starts), len(text))
        self.assertEqual(len(ends), len(text))
        for i in range(len(text)):
            self.assertLess(starts[i], ends[i])
            if i:
                self.assertLessEqual(ends[i - 1], starts[i])
        # a match on "there" turns back into the exact raw slice
        i = text.index("there")
        self.assertEqual(raw[starts[i]:ends[i + 4]], "there")
        # the doubled &nbsp; is one space covering both entities
        j = text.index(" there")
        self.assertEqual(raw[starts[j]:ends[j]], "&nbsp;&nbsp;")

    def test_normalize_matches_map(self):
        for raw in ["", "plain", "a&amp;b", "  “x”  y​ ", "a & b", "&#8217;\n\n",
                    "a\U0001F600‍ b"]:
            with self.subTest(raw=raw):
                self.assertEqual(textnorm.normalize(raw), textnorm.normalize_map(raw)[0])


if __name__ == "__main__":
    unittest.main()
