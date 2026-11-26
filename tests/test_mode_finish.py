"""Tests for scripts/mode_finish.py: images, comments and cards in one minor edit."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402,F401  (puts scripts/ on sys.path)

import cards  # noqa: E402
import mode_finish  # noqa: E402

PAGE = "100"
NO_BEFORE_WARNING = ("couldn't read version %d, so only exact matching ran; open comments that didn't "
                     "match are listed as detached (reason noBefore) because it can't tell whether "
                     "they were attached before")


def marker(ref, text):
    return '<ac:inline-comment-marker ac:ref="%s">%s</ac:inline-comment-marker>' % (ref, text)


def comment(cid, ref, selection, status="open"):
    return {"id": cid, "status": status, "ref": ref, "selection": selection}


class Setup:
    """A temp folder with the markdown file, plus a FakeClient holding the page."""

    def __init__(self, body, md="", before=None, comments=None, fail=None, version=5, images=None,
                 attachments=None):
        self.dir = helpers.TempDir()
        self.folder = self.dir.__enter__()
        for name, data in (images or {}).items():
            with open(os.path.join(self.folder, name), "wb") as handle:
                handle.write(data)
        self.md_path = os.path.join(self.folder, "doc.md")
        with open(self.md_path, "w") as handle:
            handle.write(md)
        versions = {} if before is None else {(PAGE, n): text for n, text in before.items()}
        self.client = helpers.FakeClient(
            pages={PAGE: helpers.page(body, version=version)},
            versions=versions,
            comments={PAGE: comments or []},
            attachments=None if attachments is None else {PAGE: attachments},
            fail=fail,
        )

    def run(self, before=None):
        return mode_finish.run(PAGE, self.md_path, before, self.client)

    def saved_body(self):
        return self.client.saves[-1][1]

    def close(self):
        self.dir.__exit__(None, None, None)


class FinishCase(unittest.TestCase):
    def setup(self, *args, **kwargs):
        made = Setup(*args, **kwargs)
        self.addCleanup(made.close)
        return made


class ImagesAndCardsTests(FinishCase):
    def test_images_and_cards(self):
        s = self.setup(
            '<p><img src="pic.png" alt="Alt" /></p><p>See <a href="https://example.com/docs">docs</a>.</p>',
            md='# T\n\n![Alt](pic.png)\n\nSee [docs](https://example.com/docs "block").\n',
            images={"pic.png": helpers.tiny_png(4, 2)})
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["uploaded"], ["pic.png"])
        self.assertEqual(out["unchanged"], [])
        self.assertEqual(out["embedded"], 1)
        self.assertEqual(out["stripped"], [])
        self.assertEqual(out["cards"], {"made": 1, "tagged": 1, "plain": 0, "keptPlainForComment": 0})
        self.assertEqual(out["pageId"], PAGE)
        self.assertEqual(out["version"], 6)
        body = s.saved_body()
        self.assertIn('ri:filename="pic.png"', body)
        self.assertIn('data-card-appearance="block"', body)
        self.assertEqual(s.client.uploads[0][:2], (PAGE, "pic.png"))

    def test_one_save(self):
        s = self.setup(
            '<p><img src="pic.png" alt="" /></p><p>Go <a href="https://example.com/a">a</a> and '
            '<a href="https://example.com/b">b</a>. The old words stay.</p>',
            md='![](pic.png)\n\nGo [a](https://example.com/a) and [b](https://example.com/b). '
               'The old words stay.\n',
            comments=[comment("c1", "r1", "old words")],
            images={"pic.png": helpers.tiny_png()})
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(len(s.client.saves), 1)
        message = s.client.saves[0][2]
        self.assertTrue(message)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(out["cards"]["made"], 2)
        self.assertEqual(out["embedded"], 1)

    def test_no_save_when_nothing_changes(self):
        s = self.setup('<p>Plain words.</p>', md='Plain words.\n')
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(s.client.saves, [])
        self.assertEqual(out["version"], 5)


OLD = '<p>The quick %s over the lazy dog today.</p><p>Second paragraph here.</p>'
CURRENT = '<p>The quick brown fox leaps over the lazy dog today.</p><p>Second paragraph here.</p>'
MD = "The quick brown fox leaps over the lazy dog today.\n\nSecond paragraph here.\n"


class ReattachTests(FinishCase):
    def test_reattach_exact(self):
        s = self.setup('<p>Intro line.</p><p>The quick brown fox jumps over it.</p>',
                       md="Intro line.\n\nThe quick brown fox jumps over it.\n",
                       comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(out["comments"]["detached"], [])
        self.assertEqual(s.saved_body(),
                         '<p>Intro line.</p><p>The quick %s over it.</p>' % marker("r1", "brown fox jumps"))

    def test_reattach_moved(self):
        before = OLD % marker("r1", "brown fox jumps")
        before = before.replace("</ac:inline-comment-marker> over the", " over</ac:inline-comment-marker> the")
        s = self.setup(CURRENT, md=MD, before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps over")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(out["comments"]["moved"],
                         [{"id": "c1", "from": "brown fox jumps over", "to": "brown fox leaps over"}])
        self.assertIn(marker("r1", "brown fox leaps over"), s.saved_body())
        self.assertNotIn("warning", out)

    def test_without_before_exact_only(self):
        s = self.setup(CURRENT, md=MD, comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["moved"], [])
        self.assertEqual(out["comments"]["detached"], [])
        self.assertEqual(out["comments"]["stillDetached"], [{"id": "c1", "text": "brown fox jumps"}])
        self.assertEqual(s.client.saves, [])

    def test_detached_had_marker(self):
        before = OLD % marker("r1", "brown fox jumps")
        body = '<p>Something else entirely.</p><p>Second paragraph here.</p>'
        s = self.setup(body, md="Something else entirely.\n\nSecond paragraph here.\n",
                       before={3: before}, comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["detached"],
                         [{"id": "c1", "text": "brown fox jumps", "reason": "textGone"}])
        self.assertEqual(out["comments"]["stillDetached"], [])

    def test_still_detached(self):
        # The comment has no marker in version 3 either, so it was already detached.
        before = OLD % "brown fox jumps"
        s = self.setup(CURRENT, md=MD, before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["detached"], [])
        self.assertEqual(out["comments"]["stillDetached"], [{"id": "c1", "text": "brown fox jumps"}])
        self.assertEqual(out["comments"]["moved"], [])

    def test_already_attached(self):
        body = '<p>The quick %s over it.</p>' % marker("r1", "brown fox jumps")
        s = self.setup(body, md="The quick brown fox jumps over it.\n",
                       comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["alreadyAttached"], 1)
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(s.client.saves, [])

    def test_before_read_failure(self):
        s = self.setup(CURRENT, md=MD, comments=[comment("c1", "r1", "brown fox leaps")])
        out, code = s.run(before=9)  # version 9 isn't in the fake, so it reads as 404
        self.assertEqual(code, 0)
        self.assertEqual(out["warning"], NO_BEFORE_WARNING % 9)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(out["comments"]["detached"], [])  # it matched, so nothing is "noBefore"

    def test_before_read_failure_reattaches_exact_only(self):
        # Version 3 holds the comment's marker, so with a good read this would move
        # (test_reattach_moved); the 500 means only exact matching runs.
        before = OLD % marker("r1", "brown fox jumps over")
        s = self.setup(CURRENT, md=MD, before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps over")],
                       fail={"read_version": (500, "boom")})
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["warning"], NO_BEFORE_WARNING % 3)
        self.assertEqual(out["comments"]["moved"], [])
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(out["comments"]["stillDetached"], [])
        self.assertEqual(out["comments"]["detached"],
                         [{"id": "c1", "text": "brown fox jumps over", "reason": "noBefore"}])
        self.assertEqual(s.client.saves, [])

    def test_before_read_failure_resolved_comment_is_not_found(self):
        s = self.setup(CURRENT, md=MD,
                       comments=[comment("c1", "r1", "brown fox jumps over", status="resolved")])
        out, code = s.run(before=9)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["resolved"], {"reattached": 0, "notFound": 1, "skipped": 0})
        self.assertEqual(out["comments"]["detached"], [])
        self.assertEqual(out["comments"]["stillDetached"], [])

    def test_unchanged_comment_reattaches_exactly_with_before(self):
        # The text update only dropped the marker; its words are the same.
        before = ('<p>Intro line.</p><p>The quick %s over it.</p><p>Closing line.</p>'
                  % marker("r1", "brown fox jumps"))
        s = self.setup('<p>Intro line.</p><p>The quick brown fox jumps over it.</p><p>Closing line.</p>',
                       md="Intro line.\n\nThe quick brown fox jumps over it.\n\nClosing line.\n",
                       before={3: before}, comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(out["comments"]["moved"], [])
        self.assertEqual(out["comments"]["detached"], [])
        self.assertNotIn("warning", out)
        self.assertEqual(s.saved_body(), before)

    def test_alignment_is_computed_once_for_every_find(self):
        before = ('<p>Intro line.</p><p>The quick %s over it.</p><p>Middle line.</p>'
                  '<p>The slow %s under it.</p>' % (marker("r1", "brown fox jumps"),
                                                    marker("r2", "grey cat sleeps")))
        current = before.replace(marker("r1", "brown fox jumps"), "brown fox jumps").replace(
            marker("r2", "grey cat sleeps"), "grey cat sleeps")
        s = self.setup(current, md="x\n", before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps"),
                                 comment("c2", "r2", "grey cat sleeps")])
        with mock.patch.object(mode_finish, "align", wraps=mode_finish.align) as spy_align, \
                mock.patch.object(mode_finish, "find", wraps=mode_finish.find) as spy_find:
            out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 2)
        self.assertEqual(spy_align.call_count, 1)
        self.assertEqual(spy_find.call_count, 2)
        old_texts = ["Intro line.", "The quick brown fox jumps over it.", "Middle line.",
                     "The slow grey cat sleeps under it."]
        for call in spy_find.call_args_list:
            self.assertEqual(call.kwargs["old_texts"], old_texts)
            self.assertEqual(call.kwargs["alignment"], [0, 1, 2, 3])


def alert_list(*names):
    """A page with one look-alike list item per name."""
    items = "".join("<li>Alert when packet loss on the %s interface exceeds 5%%.</li>" % name
                    for name in names)
    return "<h2>Alerting requirements</h2><ul>%s</ul><p>Out of scope.</p>" % items


class OwnBlockTests(FinishCase):
    """With version `before`, a comment stays in the block that replaced its own."""

    TAIL = "downlink interface exceeds 5%"

    def before_list(self):
        return alert_list("uplink", "downlink", "backup").replace(self.TAIL, marker("r1", self.TAIL))

    def test_deleted_list_item_detaches(self):
        # The update deleted the commented item; its look-alike siblings stay.
        body = alert_list("uplink", "backup")
        s = self.setup(body, md="Alerting requirements\n", before={3: self.before_list()},
                       comments=[comment("c1", "r1", self.TAIL)])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["detached"],
                         [{"id": "c1", "text": self.TAIL, "reason": "textGone"}])
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(out["comments"]["moved"], [])
        self.assertEqual(s.client.saves, [])
        self.assertNotIn("inline-comment-marker", s.client.pages[PAGE]["body"]["storage"]["value"])


class EmptySelectionTests(FinishCase):
    """A comment with a ref but no selection text is still re-attached or reported."""

    BEFORE = '<p>Intro line.</p><p>The quick %s over it.</p>' % marker("r1", "brown fox jumps")

    def test_already_on_page_is_counted(self):
        s = self.setup(self.BEFORE, md="x\n", comments=[comment("c1", "r1", "")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["alreadyAttached"], 1)
        self.assertEqual(s.client.saves, [])

    def test_reattaches_from_its_marker_in_before(self):
        s = self.setup('<p>Intro line.</p><p>The quick brown fox jumps over it.</p>', md="x\n",
                       before={3: self.BEFORE}, comments=[comment("c1", "r1", "")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(s.saved_body(), self.BEFORE)

    def test_text_gone_is_detached(self):
        s = self.setup('<p>Intro line.</p><p>Nothing like it now.</p>', md="x\n",
                       before={3: self.BEFORE}, comments=[comment("c1", "r1", "")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["detached"],
                         [{"id": "c1", "text": "brown fox jumps", "reason": "textGone"}])
        self.assertEqual(out["comments"]["stillDetached"], [])

    def test_no_marker_in_before_is_still_detached(self):
        before = '<p>Intro line.</p><p>The quick brown fox jumps over it.</p>'
        s = self.setup(before, md="x\n", before={3: before}, comments=[comment("c1", "r1", "")])
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["stillDetached"], [{"id": "c1", "text": ""}])
        self.assertEqual(out["comments"]["detached"], [])

    def test_without_before_is_still_detached(self):
        # A comment with no selection key at all is the same as an empty one.
        s = self.setup('<p>Intro line.</p>', md="x\n",
                       comments=[{"id": "c1", "status": "open", "ref": "r1"}])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["stillDetached"], [{"id": "c1", "text": ""}])
        self.assertEqual(s.client.saves, [])

    def test_unreadable_before_is_no_before(self):
        s = self.setup('<p>Intro line.</p>', md="x\n", comments=[comment("c1", "r1", "")])
        out, code = s.run(before=9)
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["detached"], [{"id": "c1", "text": "", "reason": "noBefore"}])
        self.assertEqual(out["warning"], NO_BEFORE_WARNING % 9)

    def test_without_a_ref_it_is_skipped(self):
        s = self.setup('<p>Intro line.</p>', md="x\n", comments=[comment("c1", "", "Intro line")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(out["comments"]["stillDetached"], [])
        self.assertEqual(s.client.saves, [])


class ResolvedTests(FinishCase):
    def comments(self):
        return [comment("c1", "r1", "brown fox leaps", status="resolved"),
                comment("c2", "r2", "gone words here", status="resolved")]

    def test_resolved(self):
        self.assertTrue(mode_finish.REATTACH_RESOLVED)
        s = self.setup(CURRENT, md=MD, comments=self.comments())
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["resolved"], {"reattached": 1, "notFound": 1, "skipped": 0})
        self.assertEqual(out["comments"]["reattached"], 0)
        self.assertEqual(out["comments"]["stillDetached"], [])
        self.assertIn(marker("r1", "brown fox leaps"), s.saved_body())

    def test_resolved_skipped_when_not_reattached(self):
        original = mode_finish.REATTACH_RESOLVED
        mode_finish.REATTACH_RESOLVED = False
        self.addCleanup(setattr, mode_finish, "REATTACH_RESOLVED", original)
        s = self.setup(CURRENT, md=MD, comments=self.comments())
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["resolved"], {"reattached": 0, "notFound": 0, "skipped": 2})
        self.assertEqual(s.client.saves, [])

    def test_resolved_never_moves(self):
        before = OLD % marker("r1", "brown fox jumps")
        s = self.setup(CURRENT, md=MD, before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps", status="resolved")])
        out, code = s.run(before=3)
        self.assertEqual(out["comments"]["resolved"], {"reattached": 0, "notFound": 1, "skipped": 0})
        self.assertEqual(out["comments"]["moved"], [])
        self.assertEqual(out["comments"]["detached"], [])


class CardsAndCommentsTests(FinishCase):
    def test_comment_on_link_words(self):
        self.assertTrue(cards.CARD_WRAP_OK)
        s = self.setup('<p>Read <a href="https://example.com/guide">the setup guide</a> first.</p>',
                       md='Read [the setup guide](https://example.com/guide "block") first.\n',
                       comments=[comment("c1", "r1", "setup guide")])
        out, code = s.run()
        self.assertEqual(code, 0)
        self.assertEqual(out["comments"]["reattached"], 1)
        self.assertEqual(out["cards"]["made"], 1)
        body = s.saved_body()
        self.assertIn('<ac:inline-comment-marker ac:ref="r1"><a href="https://example.com/guide"'
                      ' data-card-appearance="block">https://example.com/guide</a>'
                      '</ac:inline-comment-marker>', body)
        self.assertEqual(body.count("ac:inline-comment-marker ac:ref"), 1)


class ExitCodeTests(FinishCase):
    def test_detached_alone_is_exit_0(self):
        before = OLD % marker("r1", "brown fox jumps")
        s = self.setup('<p>Other text.</p>', md="Other text.\n", before={3: before},
                       comments=[comment("c1", "r1", "brown fox jumps")])
        out, code = s.run(before=3)
        self.assertEqual(len(out["comments"]["detached"]), 1)
        self.assertEqual(code, 0)

    def test_failed_upload_is_exit_1(self):
        s = self.setup('<p><img src="pic.png" alt="" /></p>', md="![](pic.png)\n",
                       images={"pic.png": helpers.tiny_png()}, fail={"upload": (500, "boom")})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(out["stripped"], ["pic.png"])
        self.assertNotIn("<img", s.saved_body())

    def test_missing_locally_is_exit_1(self):
        s = self.setup('<p><img src="pic.png" alt="" /></p>', md="![](pic.png)\n")
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertEqual(out["missingLocally"], ["pic.png"])

    def test_not_on_page_is_exit_1(self):
        s = self.setup('<p>No placeholder here.</p>', md="![](pic.png)\n\nNo placeholder here.\n",
                       images={"pic.png": helpers.tiny_png()})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertEqual(out["notOnPage"], ["pic.png"])

    def test_read_failure_is_an_error(self):
        s = self.setup('<p>x</p>', md="x\n", fail={"read_page": (503, "down")})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertIn("503", out["error"])
        self.assertEqual(s.client.saves, [])

    def test_save_failure_is_an_error(self):
        s = self.setup('<p>See <a href="https://example.com/a">a</a>.</p>',
                       md="See [a](https://example.com/a).\n", fail={"save_body": (409, "conflict")})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertIn("409", out["error"])

    def test_comment_read_failure_saves_nothing(self):
        s = self.setup('<p>See <a href="https://example.com/a">a</a>.</p>',
                       md="See [a](https://example.com/a).\n", fail={"inline_comments": (500, "boom")})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertIn("500", out["error"])
        self.assertEqual(s.client.saves, [])


class EditedDuringPublishTests(FinishCase):
    """`--before N`: after a text update the page is at N + 1; anything higher is someone's edit."""

    BODY = '<p>Their edit.</p><p><img src="pic.png" alt="Alt" /></p>'
    MD = "Their edit.\n\n![Alt](pic.png)\n"

    def _run(self, version, before=5):
        s = self.setup(self.BODY, md=self.MD, version=version, images={"pic.png": helpers.tiny_png()})
        out, code = s.run(before=before)
        return s, out, code

    def test_page_two_above_before_is_flagged_and_still_saved(self):
        s, out, code = self._run(version=7)
        self.assertEqual(code, 0)
        self.assertIs(out["editedDuringPublish"], True)
        self.assertEqual(len(s.client.saves), 1)
        self.assertIn("<p>Their edit.</p>", s.saved_body())
        self.assertIn('ri:filename="pic.png"', s.saved_body())
        self.assertEqual(out["version"], 8)
        self.assertEqual(out["embedded"], 1)

    def test_page_one_above_before_has_no_key(self):
        s, out, code = self._run(version=6)
        self.assertEqual(code, 0)
        self.assertNotIn("editedDuringPublish", out)
        self.assertEqual(out["version"], 7)

    def test_no_key_without_before(self):
        s, out, code = self._run(version=7, before=None)
        self.assertNotIn("editedDuringPublish", out)

    def test_flag_shows_even_when_nothing_is_saved(self):
        s = self.setup('<p>Their edit.</p>', md="Their edit.\n", version=9)
        out, code = s.run(before=5)
        self.assertIs(out["editedDuringPublish"], True)
        self.assertEqual(s.client.saves, [])
        self.assertEqual(out["version"], 9)


class ConflictMessageTests(FinishCase):
    def test_409_does_not_say_to_run_finish_again(self):
        s = self.setup('<p>See <a href="https://example.com/a">a</a>.</p>',
                       md="See [a](https://example.com/a).\n", fail={"save_body": (409, "conflict")})
        out, code = s.run()
        self.assertEqual(code, 1)
        self.assertEqual(out["error"],
                         "couldn't save the page (HTTP 409); the page changed during the publish, "
                         "so publishing again will show what changed")
        self.assertNotIn("finish", out["error"])

    def test_other_save_failures_have_no_hint(self):
        s = self.setup('<p>See <a href="https://example.com/a">a</a>.</p>',
                       md="See [a](https://example.com/a).\n", fail={"save_body": (500, "boom")})
        out, code = s.run()
        self.assertEqual(out["error"], "couldn't save the page (HTTP 500)")


class CalledOffPublishTests(FinishCase):
    """`--before N` with the page still at N: no text update landed, so put every image back."""

    OLD_PAGE = '<p><img src="old.png" alt="Old one" /></p><p>Text.</p>'

    def test_restores_an_image_the_file_dropped_and_strips_nothing(self):
        s = self.setup(self.OLD_PAGE, md="Text.\n", version=5, attachments={"old.png": "sha256:aaa"})
        out, code = s.run(before=5)
        self.assertEqual(code, 0)
        self.assertEqual(out["stripped"], [])
        self.assertEqual(out["embedded"], 1)
        self.assertNotIn("editedDuringPublish", out)
        body = s.saved_body()
        self.assertNotIn("<img", body)
        self.assertIn('ri:filename="old.png"', body)
        self.assertIn('ac:alt="Old one"', body)
        self.assertIn('ac:align="center"', body)
        self.assertIn("<p>Text.</p>", body)

    def test_a_changed_image_that_fails_to_upload_is_restored_not_stripped(self):
        s = self.setup('<p><img src="pic.png" alt="Alt" /></p>', md="![Alt](pic.png)\n", version=5,
                       images={"pic.png": helpers.tiny_png()}, attachments={"pic.png": "sha256:old"},
                       fail={"upload": (500, "boom")})
        out, code = s.run(before=5)
        self.assertEqual(code, 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(out["stripped"], [])
        self.assertIn('ri:filename="pic.png"', s.saved_body())
        self.assertNotIn("<img", s.saved_body())

    def test_a_file_that_is_gone_locally_is_restored_not_stripped(self):
        s = self.setup('<p><img src="pic.png" alt="Alt" /></p>', md="![Alt](pic.png)\n", version=5,
                       attachments={"pic.png": "sha256:old"})
        out, code = s.run(before=5)
        self.assertEqual(code, 1)
        self.assertEqual(out["missingLocally"], ["pic.png"])
        self.assertEqual(out["stripped"], [])
        self.assertIn('ri:filename="pic.png"', s.saved_body())

    def test_an_image_that_is_not_ours_stays_a_placeholder(self):
        body = '<p><img src="theirs.png" alt="" /></p><p><img src="old.png" alt="" /></p>'
        s = self.setup(body, md="Text.\n", version=5,
                       attachments={"theirs.png": "added by hand", "old.png": "sha256:aaa"})
        out, code = s.run(before=5)
        self.assertIn('<img src="theirs.png" alt="" />', s.saved_body())
        self.assertIn('ri:filename="old.png"', s.saved_body())

    def test_after_a_text_update_leftovers_are_left_alone(self):
        s = self.setup(self.OLD_PAGE, md="Text.\n", version=6, attachments={"old.png": "sha256:aaa"})
        out, code = s.run(before=5)
        self.assertEqual(s.client.saves, [])
        self.assertEqual(out["embedded"], 0)

    def test_without_before_leftovers_are_left_alone(self):
        s = self.setup(self.OLD_PAGE, md="Text.\n", version=5, attachments={"old.png": "sha256:aaa"})
        out, code = s.run()
        self.assertEqual(s.client.saves, [])
        self.assertEqual(out["embedded"], 0)


if __name__ == "__main__":
    unittest.main()
