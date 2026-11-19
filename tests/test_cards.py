"""Tests for scripts/cards.py: smart-link cards and Jira macros turned into links."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

import cards
from markdown_doc import LinkRef

ZERO = {"made": 0, "tagged": 0, "plain": 0, "keptPlainForComment": 0}


def counts(**changes):
    result = dict(ZERO)
    result.update(changes)
    return result


def card(url, appearance="inline", extra=""):
    return ('<a href="%s" data-card-appearance="%s"%s>%s</a>'
            % (url, appearance, extra, url))


class ModuleTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(cards.CARD_ATTRS, ("data-card-appearance", "data-layout", "data-width"))
        self.assertIs(cards.CARD_WRAP_OK, True)

    def test_cards_are_never_unmade(self):
        self.assertFalse(hasattr(cards, "unmake_cards"))


class MakeCardsTests(unittest.TestCase):
    def test_default_inline(self):
        body = '<p>See <a href="https://example.com/x">words</a> now.</p>'
        out, got = cards.make_cards(body, [LinkRef("https://example.com/x", "words", None)])
        self.assertEqual(out, '<p>See <a href="https://example.com/x" '
                              'data-card-appearance="inline">https://example.com/x</a> now.</p>')
        self.assertEqual(got, counts(made=1))

    def test_no_link_ref_left_defaults_to_inline(self):
        body = '<p><a href="https://example.com/x">words</a></p>'
        out, got = cards.make_cards(body, [])
        self.assertEqual(out, "<p>" + card("https://example.com/x") + "</p>")
        self.assertEqual(got, counts(made=1))

    def test_body_without_links_is_unchanged(self):
        body = "<p>No links &amp; no cards.</p>"
        self.assertEqual(cards.make_cards(body, []), (body, counts()))

    def test_tags(self):
        body = ('<p><a href="https://example.com/b">b words</a> '
                '<a href="https://example.com/e">e words</a> '
                '<a href="https://example.com/w">w words</a> '
                '<a href="https://example.com/p">p words</a> '
                '<a href="https://example.com/d">d words</a></p>')
        links = [
            LinkRef("https://example.com/b", "b words", "block"),
            LinkRef("https://example.com/e", "e words", "embed"),
            LinkRef("https://example.com/w", "w words", "embed wide"),
            LinkRef("https://example.com/p", "p words", "plain"),
            LinkRef("https://example.com/d", "d words", None),
        ]
        out, got = cards.make_cards(body, links)
        self.assertEqual(
            out,
            "<p>" + card("https://example.com/b", "block") + " "
            + card("https://example.com/e", "embed") + " "
            + '<a href="https://example.com/w" data-card-appearance="embed" data-layout="wide">'
              "https://example.com/w</a> "
            + '<a href="https://example.com/p">p words</a> '
            + card("https://example.com/d") + "</p>")
        self.assertEqual(got, counts(made=4, tagged=3, plain=1))

    def test_embed_layout_with_a_dash(self):
        body = '<p><a href="https://example.com/w">w</a></p>'
        out, _ = cards.make_cards(body, [LinkRef("https://example.com/w", "w", "embed full-width")])
        self.assertIn('data-card-appearance="embed" data-layout="full-width"', out)

    def test_same_url_two_tags_in_order(self):
        body = ('<p><a href="https://example.com/s">one</a> and '
                '<a href="https://example.com/s">two</a> and '
                '<a href="https://example.com/s">three</a></p>')
        links = [
            LinkRef("https://example.com/s", "one", "block"),
            LinkRef("https://example.com/s", "two", "plain"),
            LinkRef("https://example.com/s", "three", None),
        ]
        out, got = cards.make_cards(body, links)
        self.assertEqual(
            out,
            "<p>" + card("https://example.com/s", "block") + ' and '
            '<a href="https://example.com/s">two</a> and '
            + card("https://example.com/s") + "</p>")
        self.assertEqual(got, counts(made=2, tagged=1, plain=1))

    def test_matches_by_url_not_by_position(self):
        body = ('<p><a href="https://example.com/a">a</a> '
                '<a href="https://example.com/b">b</a></p>')
        links = [LinkRef("https://example.com/b", "b", "block"),
                 LinkRef("https://example.com/a", "a", "embed")]
        out, _ = cards.make_cards(body, links)
        self.assertEqual(out, "<p>" + card("https://example.com/a", "embed") + " "
                         + card("https://example.com/b", "block") + "</p>")

    def test_trailing_slash_and_entities_do_not_break_the_match(self):
        body = ('<p><a href="https://example.com/dir/">d</a> '
                '<a href="https://example.com/q?a=1&amp;b=2">q</a></p>')
        links = [LinkRef("https://example.com/dir", "d", "block"),
                 LinkRef("https://example.com/q?a=1&b=2", "q", "embed")]
        out, got = cards.make_cards(body, links)
        self.assertIn('href="https://example.com/dir/" data-card-appearance="block"', out)
        self.assertIn('href="https://example.com/q?a=1&amp;b=2" data-card-appearance="embed"', out)
        self.assertEqual(got, counts(made=2, tagged=2))

    def test_code_untouched(self):
        inline = '<p><code><a href="https://example.com/c">c</a></code></p>'
        block = '<pre><a href="https://example.com/p">p</a></pre>'
        macro = ('<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA['
                 '<a href="https://example.com/m">m</a>]]></ac:plain-text-body></ac:structured-macro>')
        body = inline + block + macro
        self.assertEqual(cards.make_cards(body, []), (body, counts()))

    def test_code_links_do_not_use_up_link_refs(self):
        body = ('<p><code><a href="https://example.com/s">c</a></code> '
                '<a href="https://example.com/s">real</a></p>')
        out, got = cards.make_cards(body, [LinkRef("https://example.com/s", "real", "block")])
        self.assertEqual(out, ('<p><code><a href="https://example.com/s">c</a></code> '
                               + card("https://example.com/s", "block") + "</p>"))
        self.assertEqual(got, counts(made=1, tagged=1))

    def test_non_web_untouched(self):
        body = ('<p><a href="mailto:someone@example.com">mail</a> '
                '<a href="#x">same page</a> '
                '<a href="/wiki/spaces/ABC/pages/1">relative</a> '
                '<a href="ftp://example.com/f">ftp</a> '
                '<a name="anchor">no href</a></p>')
        self.assertEqual(cards.make_cards(body, []), (body, counts()))

    def test_uppercase_scheme_is_a_web_link(self):
        body = '<p><a href="HTTPS://example.com/u">u</a></p>'
        out, got = cards.make_cards(body, [])
        self.assertEqual(out, "<p>" + card("HTTPS://example.com/u") + "</p>")
        self.assertEqual(got, counts(made=1))

    def test_image_link_untouched(self):
        body = ('<p><a href="https://example.com/i"><ac:image><ri:attachment ri:filename="a.png"/>'
                '</ac:image></a> <a href="https://example.com/j"><img src="x.png"/></a></p>')
        self.assertEqual(cards.make_cards(body, []), (body, counts()))

    def test_image_links_do_not_use_up_link_refs(self):
        body = ('<p><a href="https://example.com/s"><ac:image><ri:attachment ri:filename="a.png"/>'
                '</ac:image></a> <a href="https://example.com/s">words</a></p>')
        out, _ = cards.make_cards(body, [LinkRef("https://example.com/s", "words", "block")])
        self.assertTrue(out.endswith(card("https://example.com/s", "block") + "</p>"))

    def test_existing_card_untouched(self):
        body = ('<p>' + card("https://example.com/c", "block")
                + ' <a href="https://example.com/e" data-card-appearance="embed" data-layout="wide">'
                  'https://example.com/e</a></p>')
        self.assertEqual(cards.make_cards(body, []), (body, counts()))

    def test_running_twice_changes_nothing_more(self):
        body = '<p><a href="https://example.com/x">words</a></p>'
        links = [LinkRef("https://example.com/x", "words", "block")]
        once, _ = cards.make_cards(body, links)
        twice, got = cards.make_cards(once, links)
        self.assertEqual(twice, once)
        self.assertEqual(got, counts())

    def test_escaping(self):
        body = '<p><a href="https://example.com/q?a=1&amp;b=2">words</a></p>'
        out, _ = cards.make_cards(body, [])
        self.assertEqual(out, '<p><a href="https://example.com/q?a=1&amp;b=2" '
                              'data-card-appearance="inline">https://example.com/q?a=1&amp;b=2</a></p>')

    def test_angle_brackets_in_the_url_are_escaped_in_the_text(self):
        body = '<p><a href="https://example.com/a&lt;b&gt;">words</a></p>'
        out, _ = cards.make_cards(body, [])
        self.assertTrue(out.endswith(">https://example.com/a&lt;b&gt;</a></p>"))

    def test_formatting_inside_the_link_goes_with_it(self):
        body = '<p><a href="https://example.com/x"><strong>bold</strong> words</a></p>'
        out, _ = cards.make_cards(body, [])
        self.assertEqual(out, "<p>" + card("https://example.com/x") + "</p>")

    def test_other_attributes_are_kept(self):
        body = '<p><a class="k" href="https://example.com/x" title="My page">words</a></p>'
        out, _ = cards.make_cards(body, [])
        self.assertEqual(out, '<p><a class="k" href="https://example.com/x" title="My page" '
                              'data-card-appearance="inline">https://example.com/x</a></p>')

    def test_tag_title_attribute_removed(self):
        body = ('<p><a href="https://example.com/a" title="embed wide">a</a> '
                '<a href="https://example.com/b" title="Block">b</a> '
                '<a href="https://example.com/c" title="plain">c</a> '
                '<a href="https://example.com/d" title="plain">d</a></p>')
        links = [LinkRef("https://example.com/a", "a", "embed wide"),
                 LinkRef("https://example.com/b", "b", "block"),
                 LinkRef("https://example.com/c", "c", "plain")]
        out, got = cards.make_cards(body, links)
        self.assertNotIn("title=", out)
        self.assertIn('<a href="https://example.com/c">c</a>', out)  # plain-tagged: link kept, title gone
        self.assertIn(card("https://example.com/d"), out)  # title said plain, the file had no tag
        self.assertIn('data-card-appearance="embed" data-layout="wide"', out)
        self.assertEqual(got, counts(made=3, tagged=2, plain=1))

    def test_tag_comes_from_the_file_not_the_title(self):
        body = '<p><a href="https://example.com/a" title="block">a</a></p>'
        out, _ = cards.make_cards(body, [LinkRef("https://example.com/a", "a", None)])
        self.assertEqual(out, "<p>" + card("https://example.com/a") + "</p>")

    def test_tag_title_on_code_and_non_web_links_is_left(self):
        body = ('<p><code><a href="https://example.com/a" title="block">a</a></code> '
                '<a href="mailto:x@example.com" title="plain">m</a></p>')
        self.assertEqual(cards.make_cards(body, []), (body, counts()))


class MarkerTests(unittest.TestCase):
    URL = "https://example.com/m"

    def test_marker_in_link(self):
        body = ('<p>See <a href="%s"><ac:inline-comment-marker ac:ref="R1">words</ac:inline-comment-marker>'
                '</a> here.</p>' % self.URL)
        out, got = cards.make_cards(body, [])
        self.assertEqual(out, '<p>See <ac:inline-comment-marker ac:ref="R1">%s'
                              '</ac:inline-comment-marker> here.</p>' % card(self.URL))
        self.assertEqual(got, counts(made=1))

    def test_marker_in_link_when_wrapping_is_not_allowed(self):
        body = ('<p><a href="%s" title="block"><ac:inline-comment-marker ac:ref="R1">words'
                '</ac:inline-comment-marker></a></p>' % self.URL)
        with mock.patch.object(cards, "CARD_WRAP_OK", False):
            out, got = cards.make_cards(body, [LinkRef(self.URL, "words", "block")])
        self.assertEqual(out, '<p><a href="%s"><ac:inline-comment-marker ac:ref="R1">words'
                              '</ac:inline-comment-marker></a></p>' % self.URL)
        self.assertEqual(got, counts(keptPlainForComment=1))

    def test_two_markers_nest_once_each(self):
        body = ('<p><a href="%s"><ac:inline-comment-marker ac:ref="R1">one</ac:inline-comment-marker> '
                '<ac:inline-comment-marker ac:ref="R2">two</ac:inline-comment-marker> '
                '<ac:inline-comment-marker ac:ref="R1">three</ac:inline-comment-marker></a></p>' % self.URL)
        out, got = cards.make_cards(body, [LinkRef(self.URL, "x", "block")])
        self.assertEqual(out, '<p><ac:inline-comment-marker ac:ref="R1">'
                              '<ac:inline-comment-marker ac:ref="R2">%s'
                              '</ac:inline-comment-marker></ac:inline-comment-marker></p>'
                         % card(self.URL, "block"))
        self.assertEqual(got, counts(made=1, tagged=1))

    def test_marker_around_the_link_stays_as_it_is(self):
        body = ('<p><ac:inline-comment-marker ac:ref="R1"><a href="%s">words</a>'
                '</ac:inline-comment-marker></p>' % self.URL)
        out, got = cards.make_cards(body, [])
        self.assertEqual(out, '<p><ac:inline-comment-marker ac:ref="R1">%s'
                              '</ac:inline-comment-marker></p>' % card(self.URL))
        self.assertEqual(got, counts(made=1))

    def test_plain_tag_with_a_marker_stays_a_plain_link(self):
        body = ('<p><a href="%s"><ac:inline-comment-marker ac:ref="R1">words'
                '</ac:inline-comment-marker></a></p>' % self.URL)
        out, got = cards.make_cards(body, [LinkRef(self.URL, "words", "plain")])
        self.assertEqual(out, body)
        self.assertEqual(got, counts(plain=1))

    def test_marker_that_leaves_the_link_keeps_the_link_as_it_is(self):
        body = ('<p><a href="%s">one <ac:inline-comment-marker ac:ref="R1">two</a> three'
                '</ac:inline-comment-marker></p>' % self.URL)
        self.assertEqual(cards.make_cards(body, []), (body, counts()))


class JiraMacroTests(unittest.TestCase):
    URL = "https://example.atlassian.net/browse/ABC-123"

    @staticmethod
    def macro(key, extra=""):
        return ('<ac:structured-macro ac:name="jira" ac:schema-version="1" ac:macro-id="m1">'
                '<ac:parameter ac:name="server">System Jira</ac:parameter>'
                '<ac:parameter ac:name="key">%s</ac:parameter>%s</ac:structured-macro>' % (key, extra))

    def test_jira_macro_to_link(self):
        body = "<p>Tracked in " + self.macro("ABC-123") + " today.</p>"
        view = '<p>Tracked in <a href="%s" class="jira-issue-key">ABC-123</a></p>' % self.URL
        out, made, unresolved = cards.jira_macros_to_links(body, view)
        self.assertEqual(out, '<p>Tracked in <a href="%s">%s</a> today.</p>' % (self.URL, self.URL))
        self.assertEqual((made, unresolved), (1, []))

    def test_jira_macro_unresolved(self):
        body = "<p>" + self.macro("ABC-999") + "</p>"
        view = '<p><a href="%s">ABC-123</a></p>' % self.URL
        out, made, unresolved = cards.jira_macros_to_links(body, view)
        self.assertEqual(out, body)
        self.assertEqual((made, unresolved), (0, ["ABC-999"]))

    def test_a_longer_key_does_not_match(self):
        body = "<p>" + self.macro("ABC-12") + "</p>"
        view = '<a href="https://example.atlassian.net/browse/ABC-123">x</a>'
        out, made, unresolved = cards.jira_macros_to_links(body, view)
        self.assertEqual((out, made, unresolved), (body, 0, ["ABC-12"]))

    def test_jira_list_macro_left(self):
        listing = ('<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
                   'project = ABC</ac:parameter></ac:structured-macro>')
        body = "<p>" + listing + "</p>"
        view = '<a href="%s">ABC-123</a>' % self.URL
        self.assertEqual(cards.jira_macros_to_links(body, view), (body, 0, []))

    def test_other_macros_left(self):
        body = ('<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">ABC-123'
                '</ac:parameter></ac:structured-macro>')
        view = '<a href="%s">ABC-123</a>' % self.URL
        self.assertEqual(cards.jira_macros_to_links(body, view), (body, 0, []))

    def test_each_macro_is_replaced_and_missing_keys_listed_once(self):
        body = ("<p>" + self.macro("ABC-123") + self.macro("XYZ-1") + self.macro("ABC-123")
                + self.macro("XYZ-1") + "</p>")
        view = '<a href="%s">x</a>' % self.URL
        out, made, unresolved = cards.jira_macros_to_links(body, view)
        link = '<a href="%s">%s</a>' % (self.URL, self.URL)
        self.assertEqual(out, "<p>" + link + self.macro("XYZ-1") + link + self.macro("XYZ-1") + "</p>")
        self.assertEqual((made, unresolved), (2, ["XYZ-1"]))

    def test_first_matching_link_wins_on_any_host_and_the_key_is_trimmed(self):
        body = "<p>" + self.macro("  ABC-123 \n") + "</p>"
        view = ('<a href="https://other.example.org/browse/ABC-123">first</a>'
                '<a href="%s">second</a>' % self.URL)
        out, made, _ = cards.jira_macros_to_links(body, view)
        self.assertEqual(out, '<p><a href="https://other.example.org/browse/ABC-123">'
                              'https://other.example.org/browse/ABC-123</a></p>')
        self.assertEqual(made, 1)

    def test_no_view_means_nothing_resolves(self):
        body = "<p>" + self.macro("ABC-123") + "</p>"
        self.assertEqual(cards.jira_macros_to_links(body, ""), (body, 0, ["ABC-123"]))

    def test_body_without_macros_is_unchanged(self):
        body = "<p>Plain.</p>"
        self.assertEqual(cards.jira_macros_to_links(body, "<p>Plain.</p>"), (body, 0, []))


if __name__ == "__main__":
    unittest.main()
