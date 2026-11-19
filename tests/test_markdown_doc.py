import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on the path)

import unittest

import markdown_doc
from markdown_doc import ImageRef, LinkRef


def urls(md):
    return [(link.url, link.text, link.tag) for link in markdown_doc.web_links(md)]


def texts(md):
    return [block.text for block in markdown_doc.visible_blocks(md)]


class SplitTitleTests(unittest.TestCase):
    def test_split_title(self):
        title, body = markdown_doc.split_title("# My Title\n\nBody text\n")
        self.assertEqual(title, "My Title")
        self.assertEqual(body, "\nBody text\n")

    def test_title_after_other_lines_keeps_them(self):
        title, body = markdown_doc.split_title("Intro\n\n# T\nmore\n")
        self.assertEqual(title, "T")
        self.assertEqual(body, "Intro\n\nmore\n")

    def test_only_the_first_title_is_taken(self):
        title, body = markdown_doc.split_title("# One\n# Two\n")
        self.assertEqual((title, body), ("One", "# Two\n"))

    def test_sub_headings_and_tags_are_not_titles(self):
        md = "## Sub\n#Tag\ntext\n"
        self.assertEqual(markdown_doc.split_title(md), (None, md))

    def test_heading_inside_a_fence_is_skipped(self):
        md = "```\n# x\n```\n# Real\nafter\n"
        self.assertEqual(markdown_doc.split_title(md), ("Real", "```\n# x\n```\nafter\n"))
        md = "~~~sh\n# x\n~~~\ntext\n"
        self.assertEqual(markdown_doc.split_title(md), (None, md))

    def test_no_heading(self):
        md = "just text\n\nmore\n"
        self.assertEqual(markdown_doc.split_title(md), (None, md))
        self.assertEqual(markdown_doc.split_title(""), (None, ""))

    def test_title_trimmed_and_closing_hashes_dropped(self):
        self.assertEqual(markdown_doc.split_title("#   Spaced out  \nx")[0], "Spaced out")
        self.assertEqual(markdown_doc.split_title("# Closed #\nx")[0], "Closed")
        self.assertEqual(markdown_doc.split_title("# C#\nx")[0], "C#")

    def test_empty_heading_is_not_a_title(self):
        md = "# \ntext\n"
        self.assertEqual(markdown_doc.split_title(md), (None, md))

    def test_windows_line_endings(self):
        title, body = markdown_doc.split_title("# T\r\nbody\r\n")
        self.assertEqual((title, body), ("T", "body\r\n"))


class LocalImagesTests(unittest.TestCase):
    def test_local_images(self):
        md = (
            "![a](images/x.png)\n"
            '![b](<images/y z.png> "t")\n'
            "![web](https://example.com/p.png)\n"
            "![Web](HTTP://example.com/q.png)\n"
            "![d](data:image/png;base64,AAAA)\n"
            "![again](images/x.png)\n"
        )
        got = markdown_doc.local_images(md, "/docs")
        self.assertEqual(got, [
            ImageRef("a", "images/x.png", os.path.join("/docs", "images", "x.png"), "x.png"),
            ImageRef("b", "images/y z.png", os.path.join("/docs", "images", "y z.png"), "y z.png"),
        ])

    def test_path_is_normalized_and_name_is_unquoted(self):
        got = markdown_doc.local_images("![c](./pics/../pics/a%20b.png)", "/docs/sub")
        self.assertEqual(got, [ImageRef(
            "c", "./pics/../pics/a%20b.png",
            os.path.join("/docs", "sub", "pics", "a b.png"), "a b.png")])

    def test_image_with_title_and_empty_alt(self):
        got = markdown_doc.local_images('![](x.png "caption")', "/d")
        self.assertEqual(got, [ImageRef("", "x.png", os.path.join("/d", "x.png"), "x.png")])

    def test_image_inside_a_link_counts(self):
        got = markdown_doc.local_images("[![i](p.png)](https://example.com/c)", "/d")
        self.assertEqual([i.src for i in got], ["p.png"])

    def test_images_in_code_are_not_images(self):
        md = "```\n![a](in-fence.png)\n```\n`![b](in-span.png)`\n![c](real.png)\n"
        self.assertEqual([i.src for i in markdown_doc.local_images(md, "/d")], ["real.png"])

    def test_no_images(self):
        self.assertEqual(markdown_doc.local_images("plain [link](https://example.com)", "/d"), [])


class WebLinksTests(unittest.TestCase):
    def test_links_with_tags(self):
        md = (
            '[a](https://example.com/1 "plain") '
            "[b](https://example.com/2 'block') "
            '[c](https://example.com/3 "embed") '
            '[d](https://example.com/4 "Embed Wide") '
            '[e](https://example.com/5 "something else") '
            "[f](https://example.com/6)"
        )
        self.assertEqual(urls(md), [
            ("https://example.com/1", "a", "plain"),
            ("https://example.com/2", "b", "block"),
            ("https://example.com/3", "c", "embed"),
            ("https://example.com/4", "d", "embed wide"),
            ("https://example.com/5", "e", None),
            ("https://example.com/6", "f", None),
        ])

    def test_linkref_fields(self):
        got = markdown_doc.web_links('[the spec](https://example.com/s "block")')
        self.assertEqual(got, [LinkRef("https://example.com/s", "the spec", "block")])

    def test_angle_destination_and_balanced_parens(self):
        md = "[a](<https://example.com/a b>) [w](https://example.com/w_(x)) tail"
        self.assertEqual([u for u, _, _ in urls(md)],
                         ["https://example.com/a b", "https://example.com/w_(x)"])

    def test_autolink_and_bare_url(self):
        md = "<https://example.com/a>\n\nsee https://example.com/b.\n"
        self.assertEqual(urls(md), [
            ("https://example.com/a", "https://example.com/a", None),
            ("https://example.com/b", "https://example.com/b", None),
        ])

    def test_bare_url_ends(self):
        cases = {
            "(see https://example.com/a) next": "https://example.com/a",
            "https://example.com/w_(x) next": "https://example.com/w_(x)",
            "(https://example.com/w_(x))": "https://example.com/w_(x)",
            'He said "https://example.com/q".': "https://example.com/q",
            "https://example.com/z, then": "https://example.com/z",
            "https://example.com/z?!": "https://example.com/z",
            "https://example.com/q?x=1;": "https://example.com/q?x=1",
            "https://example.com/a<b>x</b>": "https://example.com/a",
            "**https://example.com/bold**": "https://example.com/bold",
            "https://example.com/p”": "https://example.com/p",
        }
        for md, want in cases.items():
            with self.subTest(md=md):
                self.assertEqual([u for u, _, _ in urls(md)], [want])

    def test_url_with_path_and_query_is_whole(self):
        md = "go to https://example.com/a/b?c=d&e=f#frag now"
        self.assertEqual([u for u, _, _ in urls(md)], ["https://example.com/a/b?c=d&e=f#frag"])

    def test_link_text_url_is_not_counted_twice(self):
        md = "[https://example.com/a](https://example.com/a)"
        self.assertEqual(urls(md), [("https://example.com/a", "https://example.com/a", None)])

    def test_link_text_markdown_is_stripped(self):
        got = markdown_doc.web_links("[**bold** `code`](https://example.com/a)")
        self.assertEqual(got[0].text, "bold code")

    def test_links_skipped(self):
        md = (
            "`[x](https://example.com/in-code)` and `https://example.com/bare-code`\n"
            "```\n[y](https://example.com/in-fence)\nhttps://example.com/fence-bare\n```\n"
            "~~~\n<https://example.com/tilde>\n~~~\n"
            "![img](https://example.com/img.png)\n"
            "[![i](p.png)](https://example.com/wraps-image)\n"
            "[mail](mailto:a@example.com) <mailto:b@example.com> [top](#section)\n"
            "[rel](other.md) [rel2](../docs/x.md) [ftp](ftp://example.com/f)\n"
            "[ref] and [text][ref] and (parens)\n"
        )
        self.assertEqual(urls(md), [])

    def test_links_order_and_duplicates(self):
        md = (
            "[a](https://example.com/x) then <https://example.com/y> then "
            '[b](https://example.com/x "block") then https://example.com/x\n'
        )
        self.assertEqual(urls(md), [
            ("https://example.com/x", "a", None),
            ("https://example.com/y", "https://example.com/y", None),
            ("https://example.com/x", "b", "block"),
            ("https://example.com/x", "https://example.com/x", None),
        ])

    def test_title_line_is_included(self):
        md = "# See [site](https://example.com/t)\n\nBody https://example.com/b\n"
        self.assertEqual([u for u, _, _ in urls(md)],
                         ["https://example.com/t", "https://example.com/b"])

    def test_code_span_with_backtick_run(self):
        md = "``a ` https://example.com/in`` and https://example.com/out"
        self.assertEqual([u for u, _, _ in urls(md)], ["https://example.com/out"])

    def test_unclosed_fence_hides_the_rest(self):
        md = "https://example.com/a\n```\nhttps://example.com/hidden\n"
        self.assertEqual([u for u, _, _ in urls(md)], ["https://example.com/a"])

    def test_a_longer_fence_is_not_closed_by_a_shorter_one(self):
        md = "````\n```\nhttps://example.com/hidden\n```\n````\nhttps://example.com/shown\n"
        self.assertEqual([u for u, _, _ in urls(md)], ["https://example.com/shown"])

    def test_escaped_bracket_is_not_a_link(self):
        self.assertEqual(urls(r"\[x](https://example.com/e)")[0][0], "https://example.com/e")
        self.assertEqual(urls(r"\[x](https://example.com/e)")[0][1], "https://example.com/e")


class VisibleBlocksTests(unittest.TestCase):
    def test_visible_blocks(self):
        md = (
            "# Title\n"
            "\n"
            "## Heading **one**\n"
            "\n"
            "First line of a paragraph\n"
            "second line of it.\n"
            "\n"
            "- item one\n"
            "- item two\n"
            "  continued here\n"
            "1. first\n"
            "2) second\n"
            "\n"
            "| Col A | Col B |\n"
            "|-------|:-----:|\n"
            "| a1 | b1 |\n"
            "| a2 | b2 |\n"
            "\n"
            "```python\n"
            "code here\n"
            "```\n"
            "\n"
            "![alt](images/x.png)\n"
            "\n"
            "Last paragraph.\n"
        )
        self.assertEqual(texts(md), [
            "Heading one",
            "First line of a paragraph second line of it.",
            "item one",
            "item two continued here",
            "first",
            "second",
            "Col A", "Col B",
            "a1", "b1",
            "a2", "b2",
            "Last paragraph.",
        ])

    def test_blocks_have_no_offsets(self):
        block = markdown_doc.visible_blocks("hello world")[0]
        self.assertEqual((block.text, block.starts, block.ends), ("hello world", [], []))

    def test_inline_markup_is_stripped(self):
        md = (
            "**b** and __b2__ and _i_ and *i2* and ~~s~~ and `c` and [t](https://example.com/u) "
            "and snake_case_name and a_b_c and 2 * 3 * 4\n"
        )
        self.assertEqual(texts(md), [
            "b and b2 and i and i2 and s and c and t and snake_case_name and a_b_c and 2 * 3 * 4"
        ])

    def test_nested_and_triple_emphasis(self):
        self.assertEqual(texts("***both*** and **bold _it_** and _a **b** c_"),
                         ["both and bold it and a b c"])

    def test_escapes(self):
        self.assertEqual(texts(r"a \*star\* and \_under\_ and \[br\] and 5 \> 3 and a\\b"),
                         ["a *star* and _under_ and [br] and 5 > 3 and a\\b"])

    def test_code_span_keeps_its_text_verbatim(self):
        self.assertEqual(texts("run `a_b *c* [d](e)` now"), ["run a_b *c* [d](e) now"])
        self.assertEqual(texts("``a ` b`` end"), ["a ` b end"])

    def test_quotes_and_task_markers_removed(self):
        md = "> quoted text\n> more of it\n\n> > nested\n\n- [ ] todo\n- [x] done\n* [X] also\n"
        self.assertEqual(texts(md), ["quoted text more of it", "nested", "todo", "done", "also"])

    def test_blockquote_with_list_and_heading(self):
        self.assertEqual(texts("> ## Quoted heading\n> - item\n"), ["Quoted heading", "item"])

    def test_title_excluded_and_other_h1_kept(self):
        self.assertEqual(texts("# Title\n\ntext\n\n# Second\n"), ["text", "Second"])
        self.assertEqual(texts("# Only a title\n"), [])

    def test_text_is_normalized(self):
        md = "It’s “quoted”  and&nbsp;spaced &amp; done here\n"
        self.assertEqual(texts(md), ["It's \"quoted\" and spaced & done here"])

    def test_links_and_images_inline(self):
        md = (
            "see [the **spec**](https://example.com/s \"block\") and ![pic](a.png) "
            "and <https://example.com/auto> and [![i](p.png)](https://example.com/c) and "
            "[ref text][ref] end\n"
        )
        self.assertEqual(texts(md), ["see the spec and and https://example.com/auto and and ref text end"])

    def test_bare_url_text_is_kept(self):
        self.assertEqual(texts("go to **https://example.com/a_b_** now"),
                         ["go to https://example.com/a_b_ now"])
        self.assertEqual(texts("see https://example.com/_x_/ ok"), ["see https://example.com/_x_/ ok"])

    def test_html_is_removed(self):
        md = (
            "Some <b>bold</b> and <span class=\"x\">span</span> text<br>next<br/>line\n"
            "\n"
            "<!-- hidden -->visible <!-- gone --> end\n"
            "\n"
            "<!--\nmulti\nline\n-->\n"
            "after comment\n"
            "\n"
            "<div>\n"
            "inside div\n"
            "</div>\n"
        )
        self.assertEqual(texts(md), [
            "Some bold and span text next line",
            "visible end",
            "after comment",
            "inside div",
        ])

    def test_less_than_in_text_is_kept(self):
        self.assertEqual(texts("a < b and c > d"), ["a < b and c > d"])

    def test_rules_and_separators_dropped(self):
        md = "above\n\n---\n\n***\n\n___\n\n- - -\n\nbelow\n"
        self.assertEqual(texts(md), ["above", "below"])

    def test_setext_heading_is_its_own_block(self):
        self.assertEqual(texts("Heading text\n============\nbody here\n"), ["Heading text", "body here"])
        self.assertEqual(texts("Sub heading\n-----------\nbody here\n"), ["Sub heading", "body here"])

    def test_table_cells_each_a_block(self):
        md = (
            "Intro\n"
            "Name | Value\n"
            "--- | ---\n"
            "**x** | `y`\n"
            "pipe \\| inside | | last\n"
            "\n"
            "After\n"
        )
        self.assertEqual(texts(md), [
            "Intro",
            "Name", "Value", "x", "y", "pipe | inside", "last",
            "After",
        ])

    def test_pipe_in_a_paragraph_is_not_a_table(self):
        self.assertEqual(texts("a | b and c | d\n"), ["a | b and c | d"])

    def test_fences_dropped_with_tildes_and_nested_info(self):
        md = "before\n~~~\n# not a heading\n- not an item\n~~~\nafter\n```js\nx\n```\nend\n"
        self.assertEqual(texts(md), ["before", "after", "end"])

    def test_fence_ends_a_paragraph(self):
        self.assertEqual(texts("one\n```\ncode\n```\ntwo\n"), ["one", "two"])

    def test_hard_break_backslash_and_trailing_spaces(self):
        self.assertEqual(texts("line one\\\nline two  \nline three\n"),
                         ["line one line two line three"])

    def test_hash_without_space_is_text(self):
        self.assertEqual(texts("#Tag and more\n"), ["#Tag and more"])

    def test_numbers_and_stars_are_not_lists(self):
        self.assertEqual(texts("1.5 million users\n*emphasis* start\n"),
                         ["1.5 million users emphasis start"])

    def test_empty_blocks_dropped(self):
        self.assertEqual(texts("-\n\n![only](a.png)\n\n<br>\n\n[ref]: https://example.com/r\n\n|  |  |\n|--|--|\n"), [])

    def test_closing_hashes_on_heading(self):
        self.assertEqual(texts("## Heading ##\n"), ["Heading"])

    def test_nested_list_items(self):
        self.assertEqual(texts("- top\n    - nested\n        1. deeper\n"), ["top", "nested", "deeper"])

    def test_windows_line_endings(self):
        self.assertEqual(texts("# T\r\n\r\npara one\r\nstill\r\n\r\n- a\r\n- b\r\n"),
                         ["para one still", "a", "b"])

    def test_footnote_text_is_kept_but_link_definitions_are_not(self):
        self.assertEqual(texts("text[^1]\n\n[^1]: the note\n\n[ref]: https://example.com/r \"t\"\n"),
                         ["text[^1]", "[^1]: the note"])

    def test_empty_document(self):
        self.assertEqual(markdown_doc.visible_blocks(""), [])


if __name__ == "__main__":
    unittest.main()
