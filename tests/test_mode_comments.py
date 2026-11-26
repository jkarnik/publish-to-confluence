"""Tests for scripts/mode_comments.py: the `comments` mode."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unittest

import helpers
import mode_comments

PAGE = "100"

MARKDOWN = """# Test page

The quick brown fox jumps over the lazy dog near the river bank today.

| Name | Notes |
|---|---|
| Alpha | The retry limit is five attempts before failing |

Another paragraph with a loose highlight here and more words after it.
"""


def marker(ref, inner):
    return '<ac:inline-comment-marker ac:ref="%s">%s</ac:inline-comment-marker>' % (ref, inner)


def body(para=None, cell=None, last="Another paragraph with a loose highlight here and more words after it."):
    """The page as it stands: a paragraph comment (R1), a table-cell comment (R2), plain text."""
    if para is None:
        para = "The quick brown " + marker("R1", "fox jumps over") + " the lazy dog near the river bank today."
    if cell is None:
        cell = "The retry limit is " + marker("R2", "five attempts") + " before failing"
    return ("<p>" + para + "</p>"
            "<table><tbody><tr><th>Name</th><th>Notes</th></tr>"
            "<tr><td>Alpha</td><td>" + cell + "</td></tr></tbody></table>"
            "<p>" + last + "</p>")


def comment(cid, status="open", ref=None, selection=None):
    return {"id": cid, "status": status, "ref": ref, "selection": selection}


PARA = comment("c1", ref="R1", selection="fox jumps over")
CELL = comment("c2", ref="R2", selection="five attempts")
LOOSE = comment("c3", ref=None, selection="a loose highlight")


def run(comments, page_body=None, markdown=MARKDOWN, fail=None):
    client = helpers.FakeClient(
        pages={PAGE: helpers.page(body() if page_body is None else page_body, page_id=PAGE)},
        comments={PAGE: comments}, fail=fail)
    with helpers.TempDir() as folder:
        path = os.path.join(folder, "doc.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        return mode_comments.run(PAGE, path, client)


def by_id(entries):
    return {entry["id"]: entry for entry in entries}


class OpenCommentTests(unittest.TestCase):
    def test_unchanged_will_reattach(self):
        out, code = run([PARA, CELL, LOOSE])
        self.assertEqual(code, 0)
        self.assertEqual(out["pageId"], PAGE)
        self.assertEqual(out["resolved"], [])
        self.assertEqual(out["willDetach"], 0)
        self.assertEqual(out["open"], [
            {"id": "c1", "text": "fox jumps over", "status": "willReattach", "reason": None, "to": None},
            {"id": "c2", "text": "five attempts", "status": "willReattach", "reason": None, "to": None},
            {"id": "c3", "text": "a loose highlight", "status": "willReattach", "reason": None, "to": None},
        ])

    def test_reworded_will_move(self):
        md = MARKDOWN.replace("fox jumps over", "fox leaps over")
        out, code = run([PARA], markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c1", "text": "fox jumps over", "status": "willMove", "reason": None, "to": "fox leaps over"}])
        self.assertEqual(out["willDetach"], 0)

    def test_moved_in_a_table_cell_names_the_new_wording(self):
        md = MARKDOWN.replace("five attempts before failing", "five tries before failing")
        page_body = body(cell="The retry limit is " + marker("R2", "five attempts before failing"))
        out, _ = run([comment("c2", ref="R2", selection="five attempts before failing")],
                     page_body=page_body, markdown=md)
        self.assertEqual(out["open"], [{"id": "c2", "text": "five attempts before failing",
                                        "status": "willMove", "reason": None, "to": "five tries before failing"}])

    def test_deleted_will_detach(self):
        md = MARKDOWN.replace("The quick brown fox jumps over the lazy dog near the river bank today.",
                              "A completely different opening sentence about something else.")
        out, code = run([PARA, CELL], markdown=md)
        self.assertEqual(code, 0)
        entries = by_id(out["open"])
        self.assertEqual(entries["c1"], {"id": "c1", "text": "fox jumps over", "status": "willDetach",
                                         "reason": "textGone", "to": None})
        self.assertEqual(entries["c2"]["status"], "willReattach")
        self.assertEqual(out["willDetach"], 1)

    def test_ambiguous_will_detach_with_reason(self):
        # The phrase now appears twice, and neither spot has the old surroundings.
        md = MARKDOWN.replace("The quick brown fox jumps over the lazy dog near the river bank today.",
                              "Red fox jumps over a fence quickly.")
        md = md.replace("Another paragraph with a loose highlight here and more words after it.",
                        "Blue fox jumps over a gate slowly.")
        out, _ = run([PARA], markdown=md)
        entry = out["open"][0]
        self.assertEqual(entry["status"], "willDetach")
        self.assertEqual(entry["reason"], "ambiguous")
        self.assertEqual(out["willDetach"], 1)

    def test_no_marker_stays_detached(self):
        md = MARKDOWN.replace("loose highlight", "scattered emphasis")
        out, code = run([LOOSE], markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c3", "text": "a loose highlight", "status": "staysDetached", "reason": "textGone", "to": None}])
        self.assertEqual(out["willDetach"], 0)

    def test_no_marker_exact_will_reattach(self):
        out, _ = run([LOOSE])
        self.assertEqual(out["open"][0]["status"], "willReattach")
        self.assertEqual(out["open"][0]["text"], "a loose highlight")

    def test_no_marker_one_word_stays_detached_and_is_not_asked_about(self):
        # "highlight" appears once on the page, but a marker-free highlight under three
        # words never re-attaches by itself.
        out, code = run([comment("c3", ref=None, selection="highlight")])
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c3", "text": "highlight", "status": "staysDetached", "reason": "ambiguous", "to": None}])
        self.assertEqual(out["willDetach"], 0)

    def test_no_marker_three_words_will_reattach(self):
        out, code = run([comment("c3", ref=None, selection="loose highlight here")])
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c3", "text": "loose highlight here", "status": "willReattach", "reason": None, "to": None}])
        self.assertEqual(out["willDetach"], 0)

    def test_no_marker_never_moves(self):
        # Reworded, but without a marker there are no surroundings, so nothing may move.
        md = MARKDOWN.replace("fox jumps over", "fox leaps over")
        out, _ = run([comment("c4", ref=None, selection="fox jumps over")], markdown=md)
        self.assertEqual(out["open"][0]["status"], "staysDetached")
        self.assertEqual(out["open"][0]["reason"], "textGone")
        self.assertIsNone(out["open"][0]["to"])

    def test_ref_whose_marker_is_gone_counts_as_no_marker(self):
        page_body = body(para="The quick brown fox jumps over the lazy dog near the river bank today.")
        md = MARKDOWN.replace("fox jumps over", "fox leaps over")
        out, _ = run([PARA], page_body=page_body, markdown=md)
        self.assertEqual(out["open"][0]["status"], "staysDetached")
        self.assertEqual(out["willDetach"], 0)

    def test_ref_whose_marker_is_gone_still_matches_exactly(self):
        page_body = body(para="The quick brown fox jumps over the lazy dog near the river bank today.")
        out, _ = run([PARA], page_body=page_body)
        self.assertEqual(out["open"][0]["status"], "willReattach")

    def test_comment_without_ref_or_selection_stays_detached(self):
        out, code = run([comment("c5", ref=None, selection=None), comment("c6", ref=None, selection="")])
        self.assertEqual(code, 0)
        for entry in out["open"]:
            self.assertEqual(entry["status"], "staysDetached")
            self.assertIsNone(entry["reason"])
            self.assertIsNone(entry["to"])
            self.assertEqual(entry["text"], "")
        self.assertEqual(out["willDetach"], 0)

    def test_dangling_and_reopened_count_as_open(self):
        out, _ = run([comment("c1", status="dangling", ref="R1", selection="fox jumps over"),
                      comment("c2", status="reopened", ref="R2", selection="five attempts"),
                      comment("c3", status="open", ref=None, selection="loose highlight")])
        self.assertEqual([entry["id"] for entry in out["open"]], ["c1", "c2", "c3"])
        self.assertEqual(out["resolved"], [])

    def test_marker_around_card_uses_selection(self):
        card = ('<a href="https://example.atlassian.net/browse/ABC-123" data-card-appearance="inline">'
                'https://example.atlassian.net/browse/ABC-123</a>')
        page_body = body(last="See " + marker("R3", card) + " for details about the rollout plan today.")
        md = MARKDOWN.replace("Another paragraph with a loose highlight here and more words after it.",
                              "See ABC-123 card for details about the rollout plan today.")
        out, code = run([comment("c7", ref="R3", selection="ABC-123  card")], page_body=page_body, markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c7", "text": "ABC-123 card", "status": "willReattach", "reason": None, "to": None}])

    def test_highlight_across_bold_is_one_anchor(self):
        para = ("The quick " + marker("R1", "brown ") + "<strong>" + marker("R1", "fox jumps") + "</strong>"
                + " over the lazy dog near the river bank today.")
        out, _ = run([comment("c1", ref="R1", selection="brown fox jumps")], page_body=body(para=para))
        self.assertEqual(out["open"][0]["text"], "brown fox jumps")
        self.assertEqual(out["open"][0]["status"], "willReattach")

    def test_will_detach_counts_only_will_detach(self):
        md = MARKDOWN.replace("The quick brown fox jumps over the lazy dog near the river bank today.",
                              "A completely different opening sentence about something else.")
        md = md.replace("five attempts", "a handful of tries").replace("loose highlight", "scattered emphasis")
        out, _ = run([PARA, CELL, LOOSE], markdown=md)
        statuses = {entry["id"]: entry["status"] for entry in out["open"]}
        self.assertEqual(statuses["c1"], "willDetach")
        self.assertEqual(statuses["c3"], "staysDetached")
        self.assertEqual(out["willDetach"], sum(1 for s in statuses.values() if s == "willDetach"))


ITEMS = ("uplink", "downlink", "backup")


def item_body(commented=None, highlight="packet loss on the {name} interface"):
    """The page's list of three look-alike alerts; `commented` names the item whose `highlight` holds marker R1."""
    items = []
    for name in ITEMS:
        text = "Alert when packet loss on the %s interface exceeds 5%%." % name
        if name == commented:
            text = text.replace(highlight.format(name=name), marker("R1", highlight.format(name=name)))
        items.append("<li>" + text + "</li>")
    return "<h2>Alerting requirements</h2><ul>" + "".join(items) + "</ul><p>Out of scope for now.</p>"


def item_markdown(gone=None):
    lines = ["- Alert when packet loss on the %s interface exceeds 5%%." % name
             for name in ITEMS if name != gone]
    return "# Test page\n\n## Alerting requirements\n\n" + "\n".join(lines) + "\n\nOut of scope for now.\n"


class SiblingTests(unittest.TestCase):
    def test_deleted_list_item_will_detach(self):
        for gone in ITEMS:
            selection = "packet loss on the %s interface" % gone
            out, code = run([comment("c1", ref="R1", selection=selection)],
                            page_body=item_body(commented=gone), markdown=item_markdown(gone=gone))
            self.assertEqual(code, 0, gone)
            self.assertEqual(out["open"], [{"id": "c1", "text": selection, "status": "willDetach",
                                            "reason": "textGone", "to": None}], gone)
            self.assertEqual(out["willDetach"], 1, gone)

    def test_resolved_comment_in_a_deleted_list_item_is_not_found(self):
        # "interface exceeds 5%" is in every item, so once its own item is gone the resolved
        # comment must not re-attach to a sibling.
        for gone in ITEMS:
            out, _ = run([comment("r1", status="resolved", ref="R1", selection="interface exceeds 5%")],
                         page_body=item_body(commented=gone, highlight="interface exceeds 5%"),
                         markdown=item_markdown(gone=gone))
            self.assertEqual(out["resolved"], [{"id": "r1", "text": "interface exceeds 5%", "status": "notFound"}], gone)

    def test_untouched_list_keeps_every_comment_in_its_own_item(self):
        for name in ITEMS:
            selection = "packet loss on the %s interface" % name
            out, _ = run([comment("c1", ref="R1", selection=selection)],
                         page_body=item_body(commented=name), markdown=item_markdown())
            self.assertEqual(out["open"][0]["status"], "willReattach", name)


class ResolvedCommentTests(unittest.TestCase):
    def test_resolved_listed_separately(self):
        md = MARKDOWN.replace("five attempts", "a handful of tries")
        resolved_ok = comment("r1", status="resolved", ref="R1", selection="fox jumps over")
        resolved_gone = comment("r2", status="resolved", ref="R2", selection="five attempts")
        out, code = run([PARA, resolved_ok, resolved_gone], markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual([entry["id"] for entry in out["open"]], ["c1"])
        self.assertEqual(out["resolved"], [
            {"id": "r1", "text": "fox jumps over", "status": "willReattach"},
            {"id": "r2", "text": "five attempts", "status": "notFound"},
        ])
        self.assertEqual(out["willDetach"], 0)

    def test_resolved_never_moves_or_counts(self):
        md = MARKDOWN.replace("fox jumps over", "fox leaps over")
        out, _ = run([comment("r1", status="resolved", ref="R1", selection="fox jumps over")], markdown=md)
        self.assertEqual(out["open"], [])
        self.assertEqual(out["resolved"], [{"id": "r1", "text": "fox jumps over", "status": "notFound"}])
        self.assertEqual(out["willDetach"], 0)

    def test_resolved_without_marker_uses_selection(self):
        out, _ = run([comment("r1", status="resolved", ref=None, selection="a loose highlight"),
                      comment("r2", status="resolved", ref=None, selection=None)])
        self.assertEqual(out["resolved"], [
            {"id": "r1", "text": "a loose highlight", "status": "willReattach"},
            {"id": "r2", "text": "", "status": "notFound"},
        ])


class FailureTests(unittest.TestCase):
    def test_read_failure(self):
        out, code = run([PARA], fail={"read_page": (500, "boom")})
        self.assertEqual(code, 1)
        self.assertEqual(set(out), {"pageId", "error"})
        self.assertEqual(out["pageId"], PAGE)
        self.assertIn("500", out["error"])
        self.assertIn("page", out["error"])

    def test_comment_list_failure(self):
        out, code = run([PARA], fail={"inline_comments": (403, "no")})
        self.assertEqual(code, 1)
        self.assertEqual(set(out), {"pageId", "error"})
        self.assertIn("403", out["error"])
        self.assertIn("comment", out["error"])

    def test_missing_page(self):
        client = helpers.FakeClient()
        with helpers.TempDir() as folder:
            path = os.path.join(folder, "doc.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(MARKDOWN)
            out, code = mode_comments.run("999", path, client)
        self.assertEqual(code, 1)
        self.assertIn("404", out["error"])

    def test_missing_file(self):
        client = helpers.FakeClient(pages={PAGE: helpers.page(body(), page_id=PAGE)}, comments={PAGE: [PARA]})
        with helpers.TempDir() as folder:
            out, code = mode_comments.run(PAGE, os.path.join(folder, "nope.md"), client)
        self.assertEqual(code, 1)
        self.assertEqual(set(out), {"pageId", "error"})
        self.assertIn("nope.md", out["error"])


SPEC_ITEMS = [("Flow export spec", "draft, owner to be confirmed"),
              ("Alert routing spec", "approved, owner to be confirmed"),
              ("Device discovery spec", "draft, owner to be confirmed"),
              ("Path analysis spec", "in review, owner to be confirmed")]


def card(url):
    return '<a href="%s" data-card-appearance="inline">%s</a>' % (url, url)


class LinkWordsTests(unittest.TestCase):
    """The page holds smart-link cards from the last publish; the file holds the same links as words."""

    def spec_page(self, marked, phrase):
        old, md = [], []
        for k, (title, note) in enumerate(SPEC_ITEMS):
            url = "https://example.com/spec-%d" % k
            text = note.replace(phrase, marker("R9", phrase), 1) if k == marked else note
            old.append("<li>%s - %s</li>" % (card(url), text))
            md.append("- [%s](%s) - %s" % (title, url, note))
        return ("<p>Related specs:</p><ul>" + "".join(old) + "</ul><p>Next steps follow.</p>",
                "Related specs:\n\n" + "\n".join(md) + "\n\nNext steps follow.\n")

    def test_look_alike_items_with_cards_reattach_in_their_own_item(self):
        page_body, md = self.spec_page(2, "owner to be confirmed")
        out, code = run([comment("c1", ref="R9", selection="owner to be confirmed")],
                        page_body=page_body, markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c1", "text": "owner to be confirmed", "status": "willReattach", "reason": None, "to": None}])
        self.assertEqual(out["willDetach"], 0)

    def test_highlight_spanning_a_card_reattaches_whole(self):
        page_body = ("<p>Intro.</p><p>Read " + marker("R9", "the " + card("https://example.com/doc")
                                                      + " before the review") + " starts.</p>")
        md = "Intro.\n\nRead the [design doc](https://example.com/doc) before the review starts.\n"
        out, code = run([comment("c1", ref="R9", selection="the design doc before the review")],
                        page_body=page_body, markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c1", "text": "the design doc before the review", "status": "willReattach",
             "reason": None, "to": None}])

    def test_plain_links_do_not_shift_the_cards_words(self):
        # The file's first link to this URL is plain (it stays an ordinary link on the page, never a card),
        # so the page's only card for it reads as the second link's words.
        url = "https://example.com/doc"
        page_body = ("<p>See <a href=\"%s\">intro link</a> first.</p><p>Read %s, then go on.</p>"
                     % (url, marker("R9", "the " + card(url) + " now")))
        md = ("See [intro link](%s \"plain\") first.\n\nRead the [design doc](%s) now, then go on.\n"
              % (url, url))
        out, code = run([comment("c1", ref="R9", selection="the design doc now")],
                        page_body=page_body, markdown=md)
        self.assertEqual(code, 0)
        self.assertEqual(out["open"], [
            {"id": "c1", "text": "the design doc now", "status": "willReattach", "reason": None, "to": None}])


if __name__ == "__main__":
    unittest.main()
