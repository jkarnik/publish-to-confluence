"""Tests for scripts/visible_text.py, the visible text blocks of a storage body."""
import html
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

from textnorm import normalize
from visible_text import BLOCK_TAGS, Block, blocks


def texts(body):
    return [b.text for b in blocks(body)]


class BlockMapTests(unittest.TestCase):
    def assert_map(self, body):
        """Every block's maps line up with its text and point at real, in-order body spans."""
        for block in blocks(body):
            self.assertEqual(len(block.starts), len(block.text))
            self.assertEqual(len(block.ends), len(block.text))
            previous = 0
            for i, ch in enumerate(block.text):
                self.assertLessEqual(previous, block.starts[i])
                self.assertLess(block.starts[i], block.ends[i])
                previous = block.starts[i]
                if ch != " ":  # a space may stand for a whole run of whitespace or a <br/>
                    self.assertEqual(normalize(html.unescape(body[block.starts[i]:block.ends[i]])), ch)

    def test_paragraph_map(self):
        body = "<p>Hello &amp; welcome,  to the &rsquo;test&rsquo; page</p><p>Second one</p>"
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["Hello & welcome, to the 'test' page", "Second one"])
        self.assert_map(body)
        first = result[0]
        self.assertEqual(first.starts[0], len("<p>"))
        self.assertEqual(body[first.starts[0]:first.ends[0]], "H")
        # The collapsed double space maps to the whole run.
        gap = first.text.index(", ") + 1
        self.assertEqual(body[first.starts[gap]:first.ends[gap]], "  ")
        # Offsets are into the whole body, not the block.
        second = result[1]
        self.assertEqual(body[second.starts[0]:second.ends[0]], "S")
        self.assertEqual(body[second.starts[-1]:second.ends[-1]], "e")
        self.assertGreater(second.starts[0], first.ends[-1])

    def test_inline_formatting_one_block(self):
        body = '<p>plain <strong>bold</strong> <code>code</code> <a href="u">link</a></p>'
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["plain bold code link"])
        self.assertIsInstance(result[0], Block)
        self.assert_map(body)
        b = result[0]
        at = b.text.index("bold")
        self.assertEqual(body[b.starts[at]:b.ends[at]], "b")
        self.assertEqual(body[b.starts[at + 3]:b.ends[at + 3]], "d")
        at = b.text.index("link")
        self.assertEqual(body[b.starts[at]:b.ends[at + 3]], "link")

    def test_inline_tags_are_transparent(self):
        for tag in ("em", "u", "s", "sub", "sup", "span"):
            body = "<p>a<%s>b</%s>c</p>" % (tag, tag)
            self.assertEqual(texts(body), ["abc"], tag)
            self.assertNotIn(tag, BLOCK_TAGS)

    def test_markers_transparent(self):
        marker = '<ac:inline-comment-marker ac:ref="abc-1">hello</ac:inline-comment-marker>'
        body = "<p>Say %s world</p>" % marker
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["Say hello world"])
        self.assert_map(body)
        b = result[0]
        at = b.text.index("hello")
        self.assertEqual(b.starts[at], body.index("hello"))
        self.assertEqual(b.ends[at + 4], body.index("hello") + len("hello"))
        # A marker in the middle of a word does not split it.
        mid = '<p>foo<ac:inline-comment-marker ac:ref="x">bar</ac:inline-comment-marker>baz</p>'
        self.assertEqual(texts(mid), ["foobarbaz"])
        self.assert_map(mid)
        # A marker around a whole paragraph's text is still one block.
        self.assertEqual(texts('<p><ac:inline-comment-marker ac:ref="y">all</ac:inline-comment-marker></p>'), ["all"])

    def test_entities(self):
        body = "<p>A &amp; B&nbsp;C &rsquo;x &#169; &#x41;</p>"
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["A & B C 'x © A"])
        b = result[0]
        for ch, entity in (("&", "&amp;"), ("'", "&rsquo;"), ("©", "&#169;"), ("A", "&#x41;")):
            at = b.text.rindex(ch)
            self.assertEqual(body[b.starts[at]:b.ends[at]], entity)
        # The non-breaking space is one plain space covering its whole entity.
        at = b.text.index("B C") + 1
        self.assertEqual(b.text[at], " ")
        self.assertEqual(body[b.starts[at]:b.ends[at]], "&nbsp;")
        self.assert_map(body)

    def test_table_cells(self):
        body = "<table><tbody><tr><td><p>x</p></td><td>y</td></tr></tbody></table>"
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["x", "y"])
        self.assertEqual(body[result[1].starts[0]:result[1].ends[0]], "y")
        self.assert_map(body)
        header = "<table><tr><th>Name</th><th>Value</th></tr><tr><td>a</td><td></td></tr></table>"
        self.assertEqual(texts(header), ["Name", "Value", "a"])

    def test_nested_lists(self):
        body = "<ul><li>one<ul><li>two</li><li>three</li></ul>more</li><li>four</li></ul>"
        self.assertEqual(texts(body), ["one", "two", "three", "more", "four"])
        self.assert_map(body)
        ordered = "<ol><li><p>first</p></li><li>second</li></ol>"
        self.assertEqual(texts(ordered), ["first", "second"])

    def test_headings_and_whitespace_only_blocks(self):
        body = "<h1>Title</h1>\n<p> </p>\n<h2>Sub &amp; more</h2>\n<p>Body</p>"
        self.assertEqual(texts(body), ["Title", "Sub & more", "Body"])
        self.assert_map(body)

    def test_br_is_space(self):
        body = "<p>line one<br/>line two</p>"
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["line one line two"])
        b = result[0]
        at = b.text.index("one line") + 3
        self.assertEqual(body[b.starts[at]:b.ends[at]], "<br/>")
        self.assert_map(body)
        # A <br/> next to real whitespace collapses into one space that covers both.
        spaced = "<p>one <br/>two</p>"
        result = blocks(spaced)
        self.assertEqual([b.text for b in result], ["one two"])
        self.assertEqual(spaced[result[0].starts[3]:result[0].ends[3]], " <br/>")
        # A <br/> does not end the block, and a leading or trailing one adds nothing.
        self.assertEqual(texts("<p><br/>x<br/></p>"), ["x"])
        self.assertEqual(texts("<p>a<br/><br/>b</p>"), ["a b"])

    def test_task_body_visible(self):
        body = (
            "<ac:task-list>"
            "<ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status>"
            "<ac:task-body>Do <strong>this</strong> &amp; that</ac:task-body></ac:task>"
            "<ac:task><ac:task-id>2</ac:task-id><ac:task-status>complete</ac:task-status>"
            "<ac:task-body><span>Second</span> one</ac:task-body></ac:task>"
            "</ac:task-list>"
        )
        result = blocks(body)
        self.assertIn("ac:task-body", BLOCK_TAGS)
        # The task id and status never show up as text.
        self.assertEqual([b.text for b in result], ["Do this & that", "Second one"])
        b = result[0]
        self.assertEqual(body[b.starts[0]:b.ends[0]], "D")
        self.assertEqual(body[b.starts[-1]:b.ends[-1]], "t")
        self.assert_map(body)

    def test_code_macro_hidden(self):
        body = (
            "<p>Before</p>"
            '<ac:structured-macro ac:name="code" ac:schema-version="1">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            "<ac:plain-text-body><![CDATA[x = '<b>bold</b>' & more]]></ac:plain-text-body>"
            "</ac:structured-macro>"
            "<p>After</p>"
        )
        self.assertEqual(texts(body), ["Before", "After"])
        self.assert_map(body)
        # A <pre> block is hidden the same way, and still separates the text around it.
        self.assertEqual(texts("<p>one</p><pre>code &amp; more</pre><p>two</p>"), ["one", "two"])
        self.assertEqual(texts("before<pre>code</pre>after"), ["before", "after"])
        # CDATA on its own is never visible.
        self.assertEqual(texts("<p>a<![CDATA[hidden]]>b</p>"), ["ab"])

    def test_macros_hidden(self):
        jira = (
            '<ac:structured-macro ac:name="jira" ac:schema-version="1">'
            '<ac:parameter ac:name="key">ABC-123</ac:parameter></ac:structured-macro>'
        )
        status = (
            '<ac:structured-macro ac:name="status">'
            '<ac:parameter ac:name="title">DONE</ac:parameter>'
            '<ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro>'
        )
        body = "<p>See %s for details, now %s ok</p>" % (jira, status)
        result = blocks(body)
        # The hidden elements vanish and the spaces around them collapse. The block stays whole.
        self.assertEqual([b.text for b in result], ["See for details, now ok"])
        b = result[0]
        at = b.text.index("for")
        self.assertEqual(body[b.starts[at]:b.ends[at]], "f")
        self.assertGreater(b.starts[at], body.index(jira) + len(jira) - 1)
        self.assert_map(body)
        # In the middle of a word, the pieces join.
        mid = "<p>foo%sbar</p>" % jira
        self.assertEqual(texts(mid), ["foobar"])
        self.assert_map(mid)
        # An empty macro tag is just skipped.
        self.assertEqual(texts('<p>a <ac:structured-macro ac:name="toc"/> b</p>'), ["a b"])
        # A macro with a rich-text body hides all of it, and its paragraphs make no blocks.
        info = (
            '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
            "<p>Inside note</p><p>More</p></ac:rich-text-body></ac:structured-macro>"
        )
        self.assertEqual(texts("<p>Top</p>%s<p>Bottom</p>" % info), ["Top", "Bottom"])
        self.assertEqual(texts("<p>x %s y</p>" % info), ["x y"])
        # A macro inside a macro of the same name hides everything up to the outer end.
        nested = (
            '<ac:structured-macro ac:name="expand"><ac:rich-text-body>'
            '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>deep</p></ac:rich-text-body>'
            "</ac:structured-macro><p>still hidden</p></ac:rich-text-body></ac:structured-macro>"
        )
        self.assertEqual(texts("<p>a</p>%s<p>b</p>" % nested), ["a", "b"])
        self.assertEqual(texts("<p>a %s b</p>" % nested), ["a b"])

    def test_cards_hidden_links_visible(self):
        card = '<a href="https://example.atlassian.net/wiki/x" data-card-appearance="inline">https://example.atlassian.net/wiki/x</a>'
        link = '<a href="https://example.com/docs">the docs</a>'
        body = "<p>See %s and %s now</p>" % (card, link)
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["See and the docs now"])
        b = result[0]
        at = b.text.index("the docs")
        self.assertEqual(body[b.starts[at]:b.ends[at + 7]], "the docs")
        self.assert_map(body)
        # Block and embed cards, and an empty card tag, are hidden too.
        for appearance in ("block", "embed"):
            tag = '<a data-card-appearance="%s" href="https://example.atlassian.net/y">label</a>' % appearance
            self.assertEqual(texts("<p>one %s two</p>" % tag), ["one two"], appearance)
        self.assertEqual(texts('<p>a <a data-card-appearance="inline" href="u"/> b</p>'), ["a b"])
        # A comment marker around a hidden card contributes no text, and one around a link keeps it.
        marked = '<ac:inline-comment-marker ac:ref="m1">%s</ac:inline-comment-marker>' % card
        self.assertEqual(texts("<p>Look %s here</p>" % marked), ["Look here"])
        self.assertEqual(texts("<p>Only %s</p>" % marked), ["Only"])
        marked_link = '<ac:inline-comment-marker ac:ref="m2">%s</ac:inline-comment-marker>' % link
        self.assertEqual(texts("<p>Look %s here</p>" % marked_link), ["Look the docs here"])
        # A card that is the whole paragraph leaves no block.
        self.assertEqual(texts("<p>%s</p><p>next</p>" % card), ["next"])

    def test_images_and_emoticons_hidden(self):
        image = '<ac:image ac:alt="chart" ac:width="400"><ri:attachment ri:filename="chart.png"/></ac:image>'
        body = (
            "<p>Look %s here %s ok" % (image, '<ac:emoticon ac:name="smile" ac:emoji-shortname=":smile:"/>')
            + ' on <time datetime="2026-11-19"/> and <time datetime="2026-01-02">Jan 2</time> done</p>'
        )
        result = blocks(body)
        self.assertEqual([b.text for b in result], ["Look here ok on and done"])
        self.assert_map(body)
        # A bare ri: element (page, user or attachment reference) adds nothing.
        refs = '<p>a<ri:user ri:account-id="u1"/>b<ri:page ri:content-title="T"></ri:page>c</p>'
        self.assertEqual(texts(refs), ["abc"])
        # An image on its own leaves no block; a url image is hidden the same way.
        self.assertEqual(texts("<p>%s</p><p>x</p>" % image), ["x"])
        url_image = '<ac:image><ri:url ri:value="https://example.com/a.png"/></ac:image>'
        self.assertEqual(texts("<p>p %s q</p>" % url_image), ["p q"])


    def test_empty_and_plain_bodies(self):
        self.assertEqual(blocks(""), [])
        self.assertEqual(blocks("<p></p><p>  </p>"), [])
        # Text with no block tag around it is still one block.
        self.assertEqual(texts("just text"), ["just text"])


if __name__ == "__main__":
    unittest.main()
