"""Tests for scripts/mode_finish.py: images, comments and cards in one minor edit."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402,F401  (puts scripts/ on sys.path)

import cards  # noqa: E402
import mode_finish  # noqa: E402

PAGE = "100"


def marker(ref, text):
    return '<ac:inline-comment-marker ac:ref="%s">%s</ac:inline-comment-marker>' % (ref, text)


def comment(cid, ref, selection, status="open"):
    return {"id": cid, "status": status, "ref": ref, "selection": selection}


class Setup:
    """A temp folder with the markdown file, plus a FakeClient holding the page."""

    def __init__(self, body, md="", before=None, comments=None, fail=None, version=5, images=None):
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
        self.assertEqual(out["warning"], "couldn't read version 9, so only exact matching ran")
        self.assertEqual(out["comments"]["reattached"], 1)

    def test_before_read_failure_reattaches_exact_only(self):
        s = self.setup(CURRENT, md=MD, comments=[comment("c1", "r1", "brown fox jumps")],
                       fail={"read_version": (500, "boom")})
        out, code = s.run(before=3)
        self.assertEqual(code, 0)
        self.assertIn("couldn't read version 3", out["warning"])
        self.assertEqual(out["comments"]["moved"], [])


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


if __name__ == "__main__":
    unittest.main()
