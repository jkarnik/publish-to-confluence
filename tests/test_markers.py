"""Tests for scripts/markers.py, the read side of inline-comment markers."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

from markers import anchor_for, refs
from matcher import CONTEXT, Anchor


def marker(ref, inner):
    return '<ac:inline-comment-marker ac:ref="%s">%s</ac:inline-comment-marker>' % (ref, inner)


CARD = ('<a href="https://example.atlassian.net/browse/ABC-123" '
        'data-card-appearance="inline">https://example.atlassian.net/browse/ABC-123</a>')


class RefsTests(unittest.TestCase):
    def test_refs(self):
        body = ("<p>one " + marker("R1", "two") + " three</p>"
                "<p><strong>" + marker("R2", "four") + "</strong>" + marker("R1", " five") + "</p>"
                '<p><ac:link ac:ref="not-a-marker">six</ac:link></p>')
        self.assertEqual(refs(body), {"R1", "R2"})

    def test_refs_none(self):
        self.assertEqual(refs("<p>No markers here</p>"), set())

    def test_refs_empty_marker_tag(self):
        self.assertEqual(refs('<p>a<ac:inline-comment-marker ac:ref="R9"/>b</p>'), {"R9"})


class AnchorTests(unittest.TestCase):
    def test_anchor_middle_of_paragraph(self):
        body = "<p>The quick brown " + marker("R1", "fox jumps") + " over the lazy dog</p>"
        self.assertEqual(anchor_for(body, "R1", "ignored"),
                         Anchor("fox jumps", "The quick brown", "over the lazy dog", block=0))

    def test_context_is_at_most_32_chars(self):
        left = "a" * 20 + " " + "b" * 20
        right = "c" * 20 + " " + "d" * 20
        body = "<p>" + left + " " + marker("R1", "target") + " " + right + "</p>"
        found = anchor_for(body, "R1", "")
        self.assertEqual(found.text, "target")
        self.assertLessEqual(len(found.before), CONTEXT)
        self.assertLessEqual(len(found.after), CONTEXT)
        self.assertEqual(found.before, (left + " ")[-CONTEXT:].strip(" "))
        self.assertEqual(found.after, (" " + right)[:CONTEXT].strip(" "))

    def test_anchor_multi_piece(self):
        body = ("<p>Start here plain " + marker("R1", "words and ")
                + "<strong>" + marker("R1", "the bold") + "</strong> then the end</p>")
        self.assertEqual(anchor_for(body, "R1", ""),
                         Anchor("words and the bold", "Start here plain", "then the end", block=0))

    def test_multi_piece_before_from_first_after_from_last(self):
        body = ("<p>alpha " + marker("R1", "beta ") + "gamma " + marker("R1", "delta") + " epsilon</p>")
        found = anchor_for(body, "R1", "")
        self.assertEqual(found.before, "alpha")
        self.assertEqual(found.after, "epsilon")
        self.assertEqual(found.text, "beta delta")

    def test_pieces_in_different_blocks_join_with_one_space(self):
        body = ("<p>Intro " + marker("R1", "ends the first") + "</p>"
                "<p>" + marker("R1", "starts the second") + " outro</p>")
        self.assertEqual(anchor_for(body, "R1", ""),
                         Anchor("ends the first starts the second", "Intro", "outro", block=0))

    def test_other_refs_are_ignored(self):
        body = "<p>one " + marker("R1", "alpha") + " two " + marker("R2", "beta") + " three</p>"
        self.assertEqual(anchor_for(body, "R2", ""), Anchor("beta", "one alpha two", "three", block=0))

    def test_anchor_card_uses_selection(self):
        body = "<p>See " + marker("R1", CARD) + " for details</p>"
        found = anchor_for(body, "R1", "ABC-123  card")
        self.assertEqual(found.text, "ABC-123 card")
        self.assertEqual(found.before, "See")
        self.assertEqual(found.after, "for details")

    def test_card_marker_at_paragraph_edges_uses_neighbor_blocks(self):
        body = "<p>Before block</p><p>" + marker("R1", CARD) + "</p><p>After block</p>"
        self.assertEqual(anchor_for(body, "R1", "the card"),
                         Anchor("the card", "Before block", "After block"))

    def test_card_marker_at_end_of_document(self):
        body = "<p>Only text</p><p>" + marker("R1", CARD) + "</p>"
        self.assertEqual(anchor_for(body, "R1", "the card"), Anchor("the card", "Only text", ""))

    def test_marker_inside_a_link(self):
        body = ('<p>Read <a href="https://example.atlassian.net/wiki">'
                + marker("R1", "the guide") + "</a> today</p>")
        self.assertEqual(anchor_for(body, "R1", ""), Anchor("the guide", "Read", "today", block=0))

    def test_text_is_normalized(self):
        body = "<p>Say " + marker("R1", "&ldquo;caf&eacute;&rdquo;&nbsp;&amp;   tea") + " now</p>"
        self.assertEqual(anchor_for(body, "R1", "").text, '"café" & tea')

    def test_hidden_text_inside_marker_is_left_out(self):
        body = ("<p>Run " + marker("R1", "this "
                '<ac:structured-macro ac:name="code"><ac:plain-text-body>x = 1</ac:plain-text-body>'
                "</ac:structured-macro> now") + " please</p>")
        self.assertEqual(anchor_for(body, "R1", "").text, "this now")

    def test_no_marker_none(self):
        body = "<p>Plain " + marker("R1", "text") + "</p>"
        self.assertIsNone(anchor_for(body, "R2", "text"))
        self.assertIsNone(anchor_for("<p>Plain</p>", "R1", "text"))

    def test_table_cell_context(self):
        body = ("<table><tbody><tr><th>Name</th><th>Owner</th></tr>"
                "<tr><td>Router</td><td>" + marker("R1", "Alice") + "</td><td>Primary</td></tr>"
                "</tbody></table>")
        self.assertEqual(anchor_for(body, "R1", ""),
                         Anchor("Alice", "Name Owner Router", "Primary", block=3))

    def test_empty_marker_tag_uses_its_position(self):
        body = '<p>left side<ac:inline-comment-marker ac:ref="R1"/> right side</p>'
        self.assertEqual(anchor_for(body, "R1", "picked"), Anchor("picked", "left side", "right side"))

    def test_unclosed_marker_is_found(self):
        body = '<p>left side <ac:inline-comment-marker ac:ref="R1"> right side</p>'
        self.assertEqual(anchor_for(body, "R1", "picked").text, "picked")

    def test_anchor_block_index(self):
        body = ("<p>First paragraph here</p><p>Second " + marker("R1", "paragraph target") + " ends</p>"
                "<p>Third paragraph</p>")
        self.assertEqual(anchor_for(body, "R1", "").block, 1)

    def test_anchor_block_index_skips_blocks_with_no_visible_text(self):
        body = ("<p>Intro</p><p>" + CARD + "</p>"
                '<ac:structured-macro ac:name="code"><ac:plain-text-body>x = 1</ac:plain-text-body>'
                "</ac:structured-macro><p>Last " + marker("R1", "one") + "</p>")
        self.assertEqual(anchor_for(body, "R1", "").block, 1)

    def test_anchor_block_index_in_table_cell(self):
        body = ("<table><tbody><tr><th>Name</th><th>Owner</th></tr>"
                "<tr><td>Router</td><td>" + marker("R1", "Alice") + "</td><td>Primary</td></tr>"
                "</tbody></table>")
        self.assertEqual(anchor_for(body, "R1", "").block, 3)

    def test_anchor_block_is_that_of_the_first_visible_char(self):
        body = ("<p>Intro " + marker("R1", "ends the first") + "</p>"
                "<p>" + marker("R1", "starts the second") + " outro</p>")
        self.assertEqual(anchor_for(body, "R1", "").block, 0)
        body = ("<p>Intro</p><p>" + marker("R1", CARD) + "</p>"
                "<p>" + marker("R1", "second piece") + " outro</p>")
        self.assertEqual(anchor_for(body, "R1", "card").block, 1)

    def test_card_only_anchor_block_unknown(self):
        body = "<p>Before block</p><p>" + marker("R1", CARD) + "</p><p>After block</p>"
        self.assertEqual(anchor_for(body, "R1", "the card").block, -1)
        body = "<p>" + marker("R1", CARD) + "</p>"
        self.assertEqual(anchor_for(body, "R1", "the card").block, -1)

    def test_empty_marker_tag_block_unknown(self):
        body = '<p>left side<ac:inline-comment-marker ac:ref="R1"/> right side</p>'
        self.assertEqual(anchor_for(body, "R1", "picked").block, -1)

    def test_no_visible_text_anywhere(self):
        body = "<p>" + marker("R1", CARD) + "</p>"
        self.assertEqual(anchor_for(body, "R1", "the card"), Anchor("the card", "", ""))


if __name__ == "__main__":
    unittest.main()
