"""Tests for scripts/storage.py, the storage XHTML tokenizer."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

from storage import Token, apply_edits, element_ranges, open_elements, set_attr, tokenize


class TokenizeTests(unittest.TestCase):
    def test_kinds_and_offsets(self):
        body = '<p class="x">Hi &amp; <strong>you</strong><br/></p>'
        tokens = tokenize(body)
        self.assertEqual(
            [t.kind for t in tokens],
            ["start", "text", "start", "text", "end", "empty", "end"],
        )
        self.assertEqual(
            [body[t.start:t.end] for t in tokens],
            ['<p class="x">', "Hi &amp; ", "<strong>", "you", "</strong>", "<br/>", "</p>"],
        )
        # The tokens tile the body: no gaps, no overlaps.
        self.assertEqual(tokens[0].start, 0)
        self.assertEqual(tokens[-1].end, len(body))
        for before, after in zip(tokens, tokens[1:]):
            self.assertEqual(before.end, after.start)
        self.assertEqual([t.name for t in tokens],
                         ["p", "", "strong", "", "strong", "br", "p"])

    def test_empty_body(self):
        self.assertEqual(tokenize(""), [])

    def test_token_is_a_frozen_dataclass(self):
        token = tokenize("<p>")[0]
        self.assertIsInstance(token, Token)
        with self.assertRaises(Exception):
            token.kind = "end"

    def test_attrs_decoded(self):
        body = '<a href="https://example.com/?a=1&amp;b=2" title="x &lt; y">l</a>'
        tag = tokenize(body)[0]
        self.assertEqual(tag.attrs["href"], "https://example.com/?a=1&b=2")
        self.assertEqual(tag.attrs["title"], "x < y")

    def test_attr_names_lowercased(self):
        tag = tokenize('<ac:image AC:Width="400" Ac:Align="center">')[0]
        self.assertEqual(tag.attrs, {"ac:width": "400", "ac:align": "center"})

    def test_single_quoted_unquoted_and_valueless_attrs(self):
        tag = tokenize("<input a='1 &amp; 2' b=3 disabled>")[0]
        self.assertEqual(tag.kind, "start")
        self.assertEqual(tag.attrs, {"a": "1 & 2", "b": "3", "disabled": ""})

    def test_quoted_gt_in_attribute(self):
        body = '<ac:parameter ac:name="x>y">v</ac:parameter>'
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["start", "text", "end"])
        self.assertEqual(body[tokens[0].start:tokens[0].end], '<ac:parameter ac:name="x>y">')
        self.assertEqual(tokens[0].attrs, {"ac:name": "x>y"})

    def test_empty_tag_with_attributes(self):
        body = '<ri:attachment ri:filename="a.png" />'
        tokens = tokenize(body)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].kind, "empty")
        self.assertEqual(tokens[0].name, "ri:attachment")
        self.assertEqual(tokens[0].attrs, {"ri:filename": "a.png"})

    def test_cdata_one_token(self):
        body = "<ac:plain-text-body><![CDATA[if a < b && c ]] d]]></ac:plain-text-body>"
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["start", "cdata", "end"])
        self.assertEqual(body[tokens[1].start:tokens[1].end], "<![CDATA[if a < b && c ]] d]]>")

    def test_comment_token(self):
        body = "a<!-- note <b>not a tag</b> -->b"
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["text", "comment", "text"])
        self.assertEqual(body[tokens[1].start:tokens[1].end], "<!-- note <b>not a tag</b> -->")

    def test_other_tokens(self):
        body = '<?xml version="1.0"?><!DOCTYPE html>x'
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["other", "other", "text"])
        self.assertEqual(body[tokens[0].start:tokens[0].end], '<?xml version="1.0"?>')
        self.assertEqual(body[tokens[1].start:tokens[1].end], "<!DOCTYPE html>")

    def test_names_lowercased(self):
        tokens = tokenize("<AC:Image></AC:Image><BR/>")
        self.assertEqual([t.name for t in tokens], ["ac:image", "ac:image", "br"])
        self.assertEqual([t.kind for t in tokens], ["start", "end", "empty"])

    def test_stray_lt_is_text_and_merges(self):
        body = "if a < b and c <= d then <p>x</p>"
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["text", "start", "text", "end"])
        self.assertEqual(body[tokens[0].start:tokens[0].end], "if a < b and c <= d then ")

    def test_unterminated_constructs_are_text(self):
        for body in ("a <!-- never closed", "a <![CDATA[ never closed", "a <p never closed"):
            tokens = tokenize(body)
            self.assertEqual([t.kind for t in tokens], ["text"], body)
            self.assertEqual(tokens[0].end, len(body))

    def test_newlines_inside_tag_and_comment(self):
        body = '<a\n  href="u"\n>x</a><!--\nmulti\nline\n-->'
        tokens = tokenize(body)
        self.assertEqual([t.kind for t in tokens], ["start", "text", "end", "comment"])
        self.assertEqual(tokens[0].attrs, {"href": "u"})

    def test_tiles_a_realistic_body(self):
        body = (
            '<h1>T</h1><p>a &lt; b <ac:inline-comment-marker ac:ref="r1">hi</ac:inline-comment-marker></p>'
            '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[x < y]]></ac:plain-text-body>'
            '</ac:structured-macro><ac:image ac:align="center"><ri:attachment ri:filename="a.png" /></ac:image>'
        )
        tokens = tokenize(body)
        self.assertEqual("".join(body[t.start:t.end] for t in tokens), body)
        self.assertEqual(tokens[0].start, 0)
        self.assertEqual(tokens[-1].end, len(body))


class ElementRangesTests(unittest.TestCase):
    def test_nested(self):
        body = "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>"
        tokens = tokenize(body)
        ranges = element_ranges(tokens, "li")
        self.assertEqual(len(ranges), 3)
        # Document order by start index; inner li closes before outer.
        texts = [body[tokens[s].start:tokens[e].end] for s, e in ranges]
        self.assertEqual(texts, ["<li>a<ul><li>b</li></ul></li>", "<li>b</li>", "<li>c</li>"])
        uls = element_ranges(tokens, "ul")
        self.assertEqual([body[tokens[s].start:tokens[e].end] for s, e in uls],
                         [body, "<ul><li>b</li></ul>"])

    def test_empty_tag_is_a_single_index_range(self):
        tokens = tokenize("<p>a<br/>b</p>")
        self.assertEqual(element_ranges(tokens, "br"), [(2, 2)])
        self.assertEqual(element_ranges(tokens, "p"), [(0, 4)])

    def test_name_is_case_insensitive_and_other_names_ignored(self):
        tokens = tokenize("<AC:Image>x</ac:image><p></p>")
        self.assertEqual(element_ranges(tokens, "ac:image"), [(0, 2)])
        self.assertEqual(element_ranges(tokens, "AC:IMAGE"), [(0, 2)])
        self.assertEqual(element_ranges(tokens, "span"), [])

    def test_unclosed_start_is_skipped(self):
        tokens = tokenize("<p>one<p>two</p>")
        self.assertEqual(element_ranges(tokens, "p"), [(2, 4)])

    def test_stray_end_is_skipped(self):
        tokens = tokenize("</p><p>x</p>")
        self.assertEqual(element_ranges(tokens, "p"), [(1, 3)])


class OpenElementsTests(unittest.TestCase):
    def test_open_elements(self):
        tokens = tokenize("<td><p><strong>x</strong></p></td>")
        text_index = [i for i, t in enumerate(tokens) if t.kind == "text"][0]
        enclosing = open_elements(tokens, text_index)
        self.assertEqual(enclosing, [0, 1, 2])
        self.assertEqual([tokens[i].name for i in enclosing], ["td", "p", "strong"])

    def test_closed_elements_do_not_enclose(self):
        tokens = tokenize("<p><b>a</b>b</p>")
        b_text = [i for i, t in enumerate(tokens) if t.kind == "text"][1]
        self.assertEqual([tokens[i].name for i in open_elements(tokens, b_text)], ["p"])

    def test_empty_tags_and_comments_do_not_enclose(self):
        tokens = tokenize("<p><br/><!-- c -->x</p>")
        text_index = [i for i, t in enumerate(tokens) if t.kind == "text"][0]
        self.assertEqual(open_elements(tokens, text_index), [0])

    def test_top_level_has_no_enclosing_elements(self):
        tokens = tokenize("x<p>y</p>")
        self.assertEqual(open_elements(tokens, 0), [])

    def test_stray_end_does_not_break_the_stack(self):
        tokens = tokenize("<p></em>x</p>")
        text_index = [i for i, t in enumerate(tokens) if t.kind == "text"][0]
        self.assertEqual(open_elements(tokens, text_index), [0])


class SetAttrTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(
            set_attr('<a href="u">', "data-card-appearance", "inline"),
            '<a href="u" data-card-appearance="inline">',
        )

    def test_add_to_tag_without_attributes(self):
        self.assertEqual(set_attr("<p>", "class", "x"), '<p class="x">')

    def test_replace_keeps_other_attributes_order_and_spacing(self):
        tag = '<a  href="u"   data-card-appearance="inline"  title=\'t\'>'
        self.assertEqual(
            set_attr(tag, "data-card-appearance", "block"),
            '<a  href="u"   data-card-appearance="block"  title=\'t\'>',
        )

    def test_replace_single_quoted_and_unquoted_values(self):
        self.assertEqual(set_attr("<a x='1' y=2>", "x", "9"), '<a x="9" y=2>')
        self.assertEqual(set_attr("<a x='1' y=2>", "y", "9"), "<a x='1' y=\"9\">")

    def test_replace_valueless_attribute(self):
        self.assertEqual(set_attr("<input disabled>", "disabled", "disabled"),
                         '<input disabled="disabled">')

    def test_name_match_is_case_insensitive(self):
        self.assertEqual(set_attr('<a HREF="u">', "href", "v"), '<a HREF="v">')

    def test_remove_restores_the_original(self):
        original = '<a href="u">'
        added = set_attr(original, "data-card-appearance", "inline")
        self.assertEqual(set_attr(added, "data-card-appearance", None), original)

    def test_remove_middle_attribute(self):
        self.assertEqual(set_attr('<a a="1" b="2" c="3">', "b", None), '<a a="1" c="3">')

    def test_remove_missing_attribute_is_a_no_op(self):
        self.assertEqual(set_attr('<a href="u">', "title", None), '<a href="u">')

    def test_value_is_escaped(self):
        self.assertEqual(set_attr("<a>", "title", 'a"b'), '<a title="a&quot;b">')
        self.assertEqual(set_attr("<a>", "href", "https://example.com/?a=1&b=2"),
                         '<a href="https://example.com/?a=1&amp;b=2">')
        self.assertEqual(set_attr("<a>", "title", "x<y"), '<a title="x&lt;y">')

    def test_escaped_value_round_trips_through_the_tokenizer(self):
        tag = set_attr("<a>", "title", 'say "x" & <y>')
        self.assertEqual(tokenize(tag)[0].attrs["title"], 'say "x" & <y>')

    def test_empty_tag_keeps_slash(self):
        self.assertEqual(set_attr("<br/>", "class", "x"), '<br class="x"/>')
        self.assertEqual(set_attr("<br />", "class", "x"), '<br class="x" />')
        self.assertEqual(set_attr('<ri:attachment ri:filename="a.png" />', "ri:version-at-save", "1"),
                         '<ri:attachment ri:filename="a.png" ri:version-at-save="1" />')
        self.assertEqual(set_attr('<br class="x"/>', "class", None), "<br/>")

    def test_gt_inside_existing_value_is_kept(self):
        self.assertEqual(set_attr('<ac:parameter ac:name="x>y">', "ac:other", "1"),
                         '<ac:parameter ac:name="x>y" ac:other="1">')

    def test_rejects_text_that_is_not_a_start_or_empty_tag(self):
        for bad in ("</a>", "text", "<!-- c -->", ""):
            with self.assertRaises(ValueError, msg=bad):
                set_attr(bad, "x", "1")


class ApplyEditsTests(unittest.TestCase):
    def test_apply_edits(self):
        body = "0123456789"
        # Offsets refer to the original body, whatever order they come in.
        self.assertEqual(apply_edits(body, [(0, 2, "AB-"), (5, 7, ""), (8, 8, "!")]),
                         "AB-2347!89")
        self.assertEqual(apply_edits(body, [(8, 8, "!"), (5, 7, ""), (0, 2, "AB-")]),
                         "AB-2347!89")

    def test_no_edits(self):
        self.assertEqual(apply_edits("abc", []), "abc")

    def test_adjacent_edits_are_not_overlap(self):
        self.assertEqual(apply_edits("abcdef", [(0, 3, "X"), (3, 6, "Y")]), "XY")

    def test_inserts_at_the_same_point_keep_their_order(self):
        self.assertEqual(apply_edits("ab", [(1, 1, "X"), (1, 1, "Y")]), "aXYb")

    def test_overlap_raises(self):
        with self.assertRaises(ValueError):
            apply_edits("abcdef", [(0, 4, "X"), (3, 6, "Y")])
        with self.assertRaises(ValueError):
            apply_edits("abcdef", [(1, 5, "X"), (2, 3, "Y")])
        with self.assertRaises(ValueError):
            apply_edits("abcdef", [(1, 4, "X"), (2, 2, "Y")])
        with self.assertRaises(ValueError):
            apply_edits("abcdef", [(1, 3, "X"), (1, 3, "Y")])

    def test_out_of_range_raises(self):
        for edit in ((-1, 2, "x"), (2, 99, "x"), (4, 2, "x")):
            with self.assertRaises(ValueError, msg=str(edit)):
                apply_edits("abcdef", [edit])

    def test_does_not_mutate_the_edit_list(self):
        edits = [(4, 5, "b"), (0, 1, "a")]
        apply_edits("abcdef", edits)
        self.assertEqual(edits, [(4, 5, "b"), (0, 1, "a")])

    def test_edits_from_tokens(self):
        body = '<p>one</p><a href="u">x</a>'
        tokens = tokenize(body)
        link = [t for t in tokens if t.kind == "start" and t.name == "a"][0]
        new = set_attr(body[link.start:link.end], "data-card-appearance", "inline")
        self.assertEqual(apply_edits(body, [(link.start, link.end, new)]),
                         '<p>one</p><a href="u" data-card-appearance="inline">x</a>')


if __name__ == "__main__":
    unittest.main()
