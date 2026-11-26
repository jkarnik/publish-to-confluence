"""Tests for scripts/mode_prepare.py: the `prepare` mode."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unittest

import helpers
import images
import mode_prepare

PAGE = "100"
SITE = "https://example.atlassian.net"
OURS = images.OUR_MARK + "0123abcd"


def embed(name, alt=""):
    return images.embed_markup(alt, name, None)


def placeholder(name, alt=""):
    return '<img src="%s" alt="%s" />' % (name, alt)


def jira_macro(key):
    return ('<ac:structured-macro ac:name="jira" ac:schema-version="1" ac:macro-id="m-%s">'
            '<ac:parameter ac:name="key">%s</ac:parameter></ac:structured-macro>' % (key, key))


def issue_link(key):
    url = "%s/browse/%s" % (SITE, key)
    return '<a href="%s">%s</a>' % (url, url)


def macro(name, params="", body=""):
    return '<ac:structured-macro ac:name="%s" ac:schema-version="1">%s%s</ac:structured-macro>' % (
        name, params, body)


def param(name, value):
    return '<ac:parameter ac:name="%s">%s</ac:parameter>' % (name, value)


def rich(inner):
    return "<ac:rich-text-body>%s</ac:rich-text-body>" % inner


def view_of(*keys):
    return "".join('<p><a href="%s/browse/%s">%s</a></p>' % (SITE, key, key) for key in keys)


def make_client(body, notes=None, view="", version=5, fail=None):
    stored = helpers.page(body, version=version, page_id=PAGE)
    stored["body"]["view"] = {"value": view}
    return helpers.FakeClient(pages={PAGE: stored}, attachments={PAGE: notes or {}}, fail=fail)


def run(client, markdown="Just text.\n", overwrite=False):
    """Run prepare with a markdown file holding `markdown`; return (output, exit code)."""
    with helpers.TempDir() as folder:
        path = os.path.join(folder, "note.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        return mode_prepare.run(PAGE, path, overwrite, client)


class PrepareTests(unittest.TestCase):
    def test_swaps_our_images(self):
        body = "<p>%s</p><p>%s</p>" % (embed("ours.png", "Ours"), embed("hand.png"))
        client = make_client(body, notes={"ours.png": OURS, "hand.png": "added by a person"})
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1],
                         "<p>%s</p><p>%s</p>" % (placeholder("ours.png", "Ours"), embed("hand.png")))
        self.assertEqual(out["unembedded"], 1)
        self.assertEqual(out["removedUnreferenced"], 0)

    def test_swaps_referenced_images(self):
        body = "<p>%s</p>" % embed("shot.png", "A shot")
        client = make_client(body, notes={"shot.png": "added by a person"})
        out, code = run(client, "Text\n\n![A shot](images/shot.png)\n")
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1], "<p>%s</p>" % placeholder("shot.png", "A shot"))
        self.assertEqual(out["unembedded"], 1)

    def test_overwrite_removes_unreferenced(self):
        body = "<p>%s</p><p>%s</p><p>%s</p>" % (
            embed("keep.png"), embed("old.png"), embed("ours.png"))
        notes = {"keep.png": "", "old.png": "added by a person", "ours.png": OURS}
        markdown = "![](keep.png)\n"

        client = make_client(body, notes=notes)
        out, code = run(client, markdown, overwrite=True)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1], "<p>%s</p>" % placeholder("keep.png"))
        self.assertEqual(out["removedUnreferenced"], 2)  # old.png and ours.png
        self.assertEqual(out["unembedded"], 1)
        self.assertEqual(set(client.attachment_notes[PAGE]),
                         {"keep.png", "old.png", "ours.png"})  # the attachments stay

        # Without --overwrite: ours.png is swapped, old.png stays, nothing is removed.
        client = make_client(body, notes=notes)
        out, code = run(client, markdown)
        self.assertEqual(client.saves[0][1], "<p>%s</p><p>%s</p><p>%s</p>" % (
            placeholder("keep.png"), embed("old.png"), placeholder("ours.png")))
        self.assertEqual(out["removedUnreferenced"], 0)
        self.assertEqual(out["unembedded"], 2)

    def test_cards_left_alone(self):
        cards = (
            '<p>See <a href="https://example.com/a" data-card-appearance="inline">'
            'https://example.com/a</a></p>'
            '<p><a href="https://example.com/b" data-card-appearance="block">'
            'https://example.com/b</a></p>'
            '<p><a href="https://example.com/c" data-card-appearance="embed" data-layout="wide">'
            'https://example.com/c</a></p>'
            '<p><a href="%s/browse/ABC-9" data-card-appearance="inline">%s/browse/ABC-9</a></p>'
            '<p><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">Done'
            '</ac:parameter></ac:structured-macro></p>'
            '<p><ac:link><ri:user ri:account-id="user-1" /></ac:link></p>' % (SITE, SITE))
        client = make_client(cards)
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves, [])  # nothing to make plain, so no edit at all
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": []})

        # With something else to fix, the cards still come out exactly as stored.
        client = make_client(cards + jira_macro("ABC-123"), view=view_of("ABC-123"))
        run(client)
        self.assertEqual(client.saves[0][1], cards + issue_link("ABC-123"))

    def test_jira_macro_made_plain(self):
        body = "<p>Bug: %s done.</p>" % jira_macro("ABC-123")
        client = make_client(body, view=view_of("ABC-123"))
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1], "<p>Bug: %s done.</p>" % issue_link("ABC-123"))
        self.assertEqual(out["madePlain"], {"jira": 1, "unresolved": []})
        self.assertEqual(out["unembedded"], 0)

    def test_panels_made_plain(self):
        panel = macro("info", param("title", "Heads up"), rich("<p>Careful here.</p>"))
        toc = macro("toc", param("maxLevel", "3"))
        client = make_client("<p>Intro</p>%s%s<p>End</p>" % (toc, panel))
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1], "<p>Intro</p><p><strong>Heads up</strong></p>"
                                             "<p>Careful here.</p><p>End</p>")
        self.assertEqual(out["madePlain"], {"jira": 0, "info": 1, "toc": 1, "unresolved": []})
        self.assertEqual(out["version"], 6)
        self.assertEqual(client.saves[0][2], "Make 1 info panel and 1 table of contents plain "
                                             "before republishing")

    def test_code_and_status_left(self):
        code_macro = macro("code", param("language", "py"),
                           "<ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body>")
        status = macro("status", param("title", "Done") + param("colour", "Green"))
        body = "<p>a</p>%s<p>%s</p>" % (code_macro, status)
        client = make_client(body)
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves, [])  # nothing blocks, so no edit at all
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": []})

        # With a panel to fix, code and status still come out exactly as stored.
        panel = macro("note", "", rich("<p>n</p>"))
        client = make_client(body + panel)
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves[0][1], body + "<p>n</p>")
        self.assertEqual(out["madePlain"], {"jira": 0, "note": 1, "unresolved": []})

    def test_unresolved_with_panels(self):
        body = macro("tip", "", rich("<p>t</p>")) + "<p>%s</p>" % jira_macro("ABC-2")
        client = make_client(body, view="")
        out, code = run(client)
        self.assertEqual(code, 1)  # the stuck key still gives exit 1
        self.assertEqual(client.saves, [])  # the publish is called off, so the page stays as it is
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": ["ABC-2"]})
        self.assertEqual(out["version"], 5)
        self.assertNotIn("error", out)

    def test_message_for_every_kind(self):
        body = ("<p>%s</p><p>%s</p><p>%s</p>%s%s%s"
                % (embed("a.png"), jira_macro("ABC-123"), jira_macro("ABC-124"),
                   macro("info", "", rich("<p>i</p>")), macro("info", "", rich("<p>j</p>")),
                   macro("expand", "", rich("<p>e</p>"))))
        client = make_client(body, notes={"a.png": OURS}, view=view_of("ABC-123", "ABC-124"))
        run(client)
        self.assertEqual(client.saves[0][2],
                         "Swap 1 image for a placeholder, turn 2 Jira issues into links "
                         "and make 1 expand section and 2 info panels plain before republishing")

    def test_save_failure_reports_no_work(self):
        body = macro("info", "", rich("<p>i</p>"))
        client = make_client(body, fail={"save_body": (409, "conflict")})
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": []})
        self.assertIn("HTTP 409", out["error"])

    def test_view_is_requested(self):
        seen = []
        client = make_client("<p>x</p>")
        original = client.read_page
        client.read_page = lambda page_id, expand="body.storage,version": (
            seen.append(expand) or original(page_id, expand))
        run(client)
        self.assertEqual(seen, ["body.storage,version,body.view"])

    def test_unresolved_blocker(self):
        body = "<p>%s %s %s</p>" % (jira_macro("ABC-1"), jira_macro("ABC-2"), jira_macro("ABC-2"))
        client = make_client(body, view=view_of("ABC-1"))
        out, code = run(client)
        self.assertEqual(code, 1)
        # The key that could be linked is not linked either: the page stays as it is.
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": ["ABC-2"]})
        self.assertNotIn("error", out)
        self.assertEqual(client.saves, [])
        self.assertEqual(out["version"], 5)

    def test_unresolved_only_saves_nothing(self):
        client = make_client("<p>%s</p>" % jira_macro("ABC-2"), view="")
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertEqual(out["madePlain"], {"jira": 0, "unresolved": ["ABC-2"]})
        self.assertEqual(client.saves, [])
        self.assertEqual(out["version"], 5)

    def test_unresolved_changes_nothing_at_all(self):
        # Images, an unreferenced image, a panel, a table of contents and a Jira issue that
        # could be linked all wait: with a stuck key the publish is called off.
        body = ("<p>%s</p><p>%s</p>%s%s<p>%s</p><p>%s</p><p>%s</p>"
                % (embed("ours.png"), embed("old.png"), macro("info", "", rich("<p>i</p>")),
                   macro("toc"), jira_macro("ABC-1"), jira_macro("ABC-2"), jira_macro("ABC-2")))
        client = make_client(body, notes={"ours.png": OURS, "old.png": OURS},
                             view=view_of("ABC-1"), version=9)
        out, code = run(client, "![](ours.png)\n", overwrite=True)
        self.assertEqual(code, 1)
        self.assertEqual(client.saves, [])
        self.assertEqual(client.pages[PAGE]["body"]["storage"]["value"], body)
        self.assertEqual(out, {"pageId": PAGE, "version": 9, "unembedded": 0,
                               "madePlain": {"jira": 0, "unresolved": ["ABC-2"]},
                               "removedUnreferenced": 0})

    def test_markers_kept(self):
        marker1 = '<ac:inline-comment-marker ac:ref="ref-1">the anchor</ac:inline-comment-marker>'
        marker2 = '<ac:inline-comment-marker ac:ref="ref-2">see issue</ac:inline-comment-marker>'
        marker3 = '<ac:inline-comment-marker ac:ref="ref-3">old</ac:inline-comment-marker>'
        body = ("<p>Intro %s %s</p><p>%s %s</p><p>%s %s</p>"
                % (marker1, embed("ours.png"), marker2, jira_macro("ABC-123"),
                   marker3, embed("old.png")))
        client = make_client(body, notes={"ours.png": OURS, "old.png": ""},
                             view=view_of("ABC-123"))
        out, code = run(client, "![](old.png)\n", overwrite=True)
        self.assertEqual(code, 0)
        saved = client.saves[0][1]
        self.assertEqual(saved, "<p>Intro %s </p><p>%s %s</p><p>%s %s</p>"
                         % (marker1, marker2, issue_link("ABC-123"), marker3,
                            placeholder("old.png")))
        for marker in (marker1, marker2, marker3):
            self.assertIn(marker, saved)
        self.assertEqual((out["unembedded"], out["madePlain"]["jira"],
                          out["removedUnreferenced"]), (1, 1, 1))

    def test_one_save(self):
        body = "<p>%s</p><p>%s</p><p>%s</p>" % (
            embed("a.png"), embed("b.png"), jira_macro("ABC-123"))
        client = make_client(body, notes={"a.png": OURS, "b.png": OURS},
                             view=view_of("ABC-123"))
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(len(client.saves), 1)
        page_id, _body, message = client.saves[0]
        self.assertEqual(page_id, PAGE)
        self.assertEqual(message, "Swap 2 images for placeholders and turn 1 Jira issue "
                                  "into a link before republishing")
        self.assertEqual(out["version"], 6)  # the saved version
        self.assertEqual(out, {"pageId": PAGE, "version": 6, "unembedded": 2,
                               "madePlain": {"jira": 1, "unresolved": []},
                               "removedUnreferenced": 0})

    def test_message_names_each_change(self):
        body = "<p>%s</p><p>%s</p>" % (embed("a.png"), embed("old.png"))
        client = make_client(body, notes={"a.png": OURS, "old.png": ""})
        run(client, "![](a.png)\n", overwrite=True)
        self.assertEqual(client.saves[0][2], "Swap 1 image for a placeholder and remove 1 "
                                             "unreferenced image before republishing")

    def test_nothing_to_do_no_save(self):
        client = make_client("<p>Plain text only.</p>", version=7)
        out, code = run(client)
        self.assertEqual(code, 0)
        self.assertEqual(client.saves, [])
        self.assertEqual(out, {"pageId": PAGE, "version": 7, "unembedded": 0,
                               "madePlain": {"jira": 0, "unresolved": []},
                               "removedUnreferenced": 0})

    def test_read_or_save_failure(self):
        body = "<p>%s</p>" % embed("a.png")

        client = make_client(body, notes={"a.png": OURS}, fail={"read_page": (500, "server down")})
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertEqual(out["pageId"], PAGE)
        self.assertIn("HTTP 500", out["error"])
        self.assertEqual(client.saves, [])

        client = make_client(body, notes={"a.png": OURS}, fail={"save_body": (409, "conflict")})
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertEqual(out["pageId"], PAGE)
        self.assertIn("HTTP 409", out["error"])
        self.assertEqual(out["version"], 5)  # the page is unchanged
        self.assertEqual(out["unembedded"], 0)
        self.assertEqual(client.saves, [])

        client = make_client(body, notes={"a.png": OURS}, fail={"read_page": (0, "network error: down")})
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertIn("network error", out["error"])

    def test_attachment_list_failure(self):
        client = make_client("<p>%s</p>" % embed("a.png"), notes={"a.png": OURS},
                             fail={"attachments": (503, "unavailable")})
        out, code = run(client)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 503", out["error"])
        self.assertEqual(client.saves, [])

    def test_missing_markdown_file(self):
        client = make_client("<p>x</p>")
        with helpers.TempDir() as folder:
            out, code = mode_prepare.run(PAGE, os.path.join(folder, "gone.md"), False, client)
        self.assertEqual(code, 1)
        self.assertEqual(out["pageId"], PAGE)
        self.assertIn("gone.md", out["error"])
        self.assertEqual(client.saves, [])


if __name__ == "__main__":
    unittest.main()
