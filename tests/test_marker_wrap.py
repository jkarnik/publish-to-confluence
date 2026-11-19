"""Tests for scripts/marker_wrap.py, the write side of inline-comment markers."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

from marker_wrap import wrap
from storage import tokenize
from visible_text import blocks


def open_tag(ref="R"):
    return '<ac:inline-comment-marker ac:ref="%s">' % ref


CLOSE = "</ac:inline-comment-marker>"


def wrap_text(body, needle, ref="R", block_index=0):
    """Wrap the first occurrence of needle in the visible text of one block."""
    block = blocks(body)[block_index]
    start = block.text.index(needle)
    return wrap(body, block, start, start + len(needle), ref)


class WrapTests(unittest.TestCase):
    def test_wrap_one_run(self):
        body = "<p>a b c d</p>"
        self.assertEqual(
            wrap_text(body, "b c"),
            "<p>a " + open_tag() + "b c" + CLOSE + " d</p>",
        )

    def test_wrap_across_bold(self):
        body = "<p>Probe one: the plain words and <strong>the bold words</strong> sit together here.</p>"
        self.assertEqual(
            wrap_text(body, "plain words and the bold words sit"),
            "<p>Probe one: the " + open_tag() + "plain words and " + CLOSE
            + "<strong>" + open_tag() + "the bold words" + CLOSE + "</strong>"
            + open_tag() + " sit" + CLOSE + " together here.</p>",
        )

    def test_wrap_never_splits_entity(self):
        body = "<p>Tom &amp; Jerry &amp; Co</p>"
        self.assertEqual(
            wrap_text(body, "Tom &"),
            "<p>" + open_tag() + "Tom &amp;" + CLOSE + " Jerry &amp; Co</p>",
        )
        self.assertEqual(
            wrap_text(body, "& Jerry"),
            "<p>Tom " + open_tag() + "&amp; Jerry" + CLOSE + " &amp; Co</p>",
        )

    def test_wrap_inside_link_text(self):
        body = '<p>see <a href="https://example.atlassian.net/x">the link text</a> now</p>'
        self.assertEqual(
            wrap_text(body, "link text"),
            '<p>see <a href="https://example.atlassian.net/x">the ' + open_tag() + "link text" + CLOSE
            + "</a> now</p>",
        )
        self.assertEqual(
            wrap_text(body, "see the link"),
            "<p>" + open_tag() + "see " + CLOSE + '<a href="https://example.atlassian.net/x">'
            + open_tag() + "the link" + CLOSE + " text</a> now</p>",
        )

    def test_wrap_collapsed_whitespace(self):
        body = "<p>a \n  b</p>"
        block = blocks(body)[0]
        self.assertEqual(block.text, "a b")
        self.assertEqual(wrap(body, block, 0, 3, "R"), "<p>" + open_tag() + "a \n  b" + CLOSE + "</p>")

    def test_wrap_collapsed_whitespace_between_tags(self):
        body = "<p>a <strong> b</strong></p>"
        block = blocks(body)[0]
        self.assertEqual(block.text, "a b")
        result = wrap(body, block, 0, 3, "R")
        self.assertEqual(
            result,
            "<p>" + open_tag() + "a " + CLOSE + "<strong>" + open_tag() + " b" + CLOSE + "</strong></p>",
        )

    def test_visible_text_unchanged(self):
        bodies = [
            ("<p>a b c d</p><p>second  &amp; third</p>", "b c", 0),
            ("<p>the plain <strong>bold</strong> <em>ital</em> end</p>", "plain bold ital", 0),
            ('<p>x</p><p>go <a href="https://example.atlassian.net/y">here &amp; there</a> ok</p>', "here & there", 1),
            ("<p>one<br/>two three</p>", "one two", 0),
        ]
        for body, needle, index in bodies:
            with self.subTest(body=body):
                before = [b.text for b in blocks(body)]
                result = wrap_text(body, needle, block_index=index)
                self.assertNotEqual(result, body)
                self.assertEqual([b.text for b in blocks(result)], before)

    def test_result_tokenizes(self):
        body = "<p>a <strong>b c</strong> d &amp; e</p>"
        result = wrap_text(body, "a b c d &")
        tokens = tokenize(result)
        starts = [t for t in tokens if t.kind == "start" and t.name == "ac:inline-comment-marker"]
        ends = [t for t in tokens if t.kind == "end" and t.name == "ac:inline-comment-marker"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(len(ends), 3)
        self.assertTrue(all(t.attrs == {"ac:ref": "R"} for t in starts))
        self.assertEqual("".join(result[t.start:t.end] for t in tokens), result)

    def test_trims_edge_spaces(self):
        body = "<p>a <strong>b</strong> c</p>"
        block = blocks(body)[0]
        self.assertEqual(block.text, "a b c")
        # chars 1..4 are " b " : the spaces are trimmed away, so no marker touches the tags
        self.assertEqual(
            wrap(body, block, 1, 4, "R"),
            "<p>a <strong>" + open_tag() + "b" + CLOSE + "</strong> c</p>",
        )

    def test_space_only_span_returns_body_unchanged(self):
        body = "<p>a <strong> </strong>b</p>"
        block = blocks(body)[0]
        self.assertEqual(wrap(body, block, 1, 2, "R"), body)
        self.assertEqual(wrap(body, block, 0, 0, "R"), body)

    def test_ref_is_escaped(self):
        body = "<p>a b c</p>"
        result = wrap_text(body, "b", ref='x"<&>')
        self.assertEqual(result, "<p>a " + open_tag("x&quot;&lt;&amp;&gt;") + "b" + CLOSE + " c</p>")
        marker = [t for t in tokenize(result) if t.kind == "start" and t.name == "ac:inline-comment-marker"][0]
        self.assertEqual(marker.attrs["ac:ref"], 'x"<&>')

    def test_second_block_offsets(self):
        body = "<p>first one</p><p>second two</p>"
        self.assertEqual(
            wrap_text(body, "second", block_index=1),
            "<p>first one</p><p>" + open_tag() + "second" + CLOSE + " two</p>",
        )

    def test_hidden_macro_text_is_not_wrapped(self):
        body = (
            '<p>before <ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[secret]]>'
            "</ac:plain-text-body></ac:structured-macro> after</p>"
        )
        block = blocks(body)[0]
        self.assertEqual(block.text, "before after")
        result = wrap(body, block, 0, len(block.text), "R")
        self.assertEqual(
            result,
            "<p>" + open_tag() + "before " + CLOSE
            + '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[secret]]>'
            "</ac:plain-text-body></ac:structured-macro>" + open_tag() + " after" + CLOSE + "</p>",
        )
        self.assertEqual([b.text for b in blocks(result)], ["before after"])

    def test_wrap_across_line_break(self):
        body = "<p>one<br/>two</p>"
        self.assertEqual(
            wrap_text(body, "one two"),
            "<p>" + open_tag() + "one" + CLOSE + "<br/>" + open_tag() + "two" + CLOSE + "</p>",
        )

    def test_whitespace_only_middle_piece_is_wrapped(self):
        body = "<p><strong>bold</strong> <em>ital</em></p>"
        self.assertEqual(
            wrap_text(body, "bold ital"),
            "<p><strong>" + open_tag() + "bold" + CLOSE + "</strong>" + open_tag() + " " + CLOSE
            + "<em>" + open_tag() + "ital" + CLOSE + "</em></p>",
        )


if __name__ == "__main__":
    unittest.main()
