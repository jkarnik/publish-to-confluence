import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on the path)

import random
import time
import unittest

import matcher
from matcher import Anchor, Result


class ExactMatchTests(unittest.TestCase):
    def test_exact_once(self):
        texts = [
            "The collector restarted at noon.",
            "Alerts stopped syncing since the morning shift started.",
        ]
        got = matcher.find(Anchor("stopped syncing"), texts, allow_move=False)
        start = texts[1].index("stopped syncing")
        self.assertEqual(got, Result("exact", 1, start, start + len("stopped syncing")))
        self.assertEqual(texts[1][got.start:got.end], "stopped syncing")

    def test_exact_twice_no_context(self):
        texts = [
            "The sync job failed overnight and nobody noticed.",
            "Later the sync job failed overnight again.",
        ]
        got = matcher.find(Anchor("sync job failed"), texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="ambiguous"))

    def test_exact_twice_context_picks(self):
        texts = [
            "The agent reports status every minute. The sync job failed overnight. Operators restarted it.",
            "Metrics arrive late on weekends. The sync job failed overnight. Nobody restarted anything.",
        ]
        anchor = Anchor(
            "sync job failed",
            before="late on weekends. The",
            after="overnight. Nobody restarted",
        )
        got = matcher.find(anchor, texts, allow_move=False)
        start = texts[1].index("sync job failed")
        self.assertEqual(got, Result("exact", 1, start, start + len("sync job failed")))

    def test_exact_twice_context_too_close(self):
        note = "Operators note that the sync job failed overnight and was restarted by hand."
        texts = ["Weekly summary for Monday.", note, "Weekly summary for Tuesday.", note]
        anchor = Anchor(
            "sync job failed",
            before="Monday. Operators note that the",
            after="overnight and was restarted by",
        )
        # The old surroundings fit the first one exactly; the second differs by two letters.
        got = matcher.find(anchor, texts, allow_move=False)
        self.assertEqual(got, Result("none", reason="ambiguous"))

    def test_never_crosses_blocks(self):
        texts = ["The agent stopped syncing", "since the morning shift started."]
        for allow_move in (False, True):
            got = matcher.find(Anchor("syncing since"), texts, allow_move=allow_move)
            self.assertEqual(got, Result("none", reason="textGone"))


class ContextOfTests(unittest.TestCase):
    def test_context_of_across_blocks(self):
        texts = [
            "First block ends here.",
            "Second block has the highlighted words in it.",
            "Third block starts here and goes on.",
        ]
        start = texts[1].index("highlighted words")
        end = start + len("highlighted words")
        before, after = matcher.context_of(texts, 1, start, end)
        # Earlier block, one space, then the text before the highlight; last 32 chars.
        self.assertEqual(before, "ends here. Second block has the")
        # The text after the highlight, one space, then the next block; first 32 chars.
        self.assertEqual(after, "in it. Third block starts here")
        self.assertLessEqual(len(before), matcher.CONTEXT)
        self.assertLessEqual(len(after), matcher.CONTEXT)

    def test_context_of_first_and_last_block(self):
        texts = ["Alpha beta gamma.", "Delta epsilon."]
        before, after = matcher.context_of(texts, 0, 6, 10)
        self.assertEqual(before, "Alpha")  # no earlier block, no leading space
        self.assertEqual(after, "gamma. Delta epsilon.")
        before, after = matcher.context_of(texts, 1, 6, 14)
        self.assertEqual(before, "Alpha beta gamma. Delta")
        self.assertEqual(after, "")  # no later block


OLD = "stopped syncing since the morning shift started"
NEW = "stopped syncing since the early shift started"
LEAD = "The collector restarted at noon, then "
TRAIL = " and nobody noticed it until Friday."


def _anchor_for(texts, block, text, **kw):
    """An Anchor for `text` as it sits in texts[block], with context from context_of."""
    start = texts[block].index(text)
    before, after = matcher.context_of(texts, block, start, start + len(text))
    return Anchor(text, before, after, **kw) if kw else Anchor(text, before, after)


def _span_text(texts, got):
    return texts[got.block][got.start:got.end]


class MovedMatchTests(unittest.TestCase):
    def setUp(self):
        self.old_texts = ["Weekly summary.", LEAD + OLD + TRAIL, "Closing remarks."]
        self.anchor = _anchor_for(self.old_texts, 1, OLD)

    def test_moved_reworded(self):
        texts = ["Weekly summary.", LEAD + NEW + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        start = texts[1].index(NEW)
        self.assertEqual(got, Result("moved", 1, start, start + len(NEW)))
        self.assertEqual(_span_text(texts, got), NEW)

    def test_moved_needs_context(self):
        texts = [
            "Something else entirely.",
            "Totally unrelated lead-in words, so " + NEW + " with other trailing remarks.",
            "Nothing like the old page.",
        ]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_moved_without_any_context(self):
        texts = ["Weekly summary.", LEAD + NEW + TRAIL, "Closing remarks."]
        got = matcher.find(Anchor(OLD), texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_no_move_when_not_allowed(self):
        texts = ["Weekly summary.", LEAD + NEW + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=False)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_short_highlight_never_moves(self):
        old = ["Weekly summary.", LEAD + "stopped syncing" + TRAIL, "Closing remarks."]
        anchor = _anchor_for(old, 1, "stopped syncing")
        new = ["Weekly summary.", LEAD + "stopped quietly syncing" + TRAIL, "Closing remarks."]
        got = matcher.find(anchor, new, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_three_word_highlight_can_move(self):
        old = ["Weekly summary.", LEAD + "stopped syncing since" + TRAIL, "Closing remarks."]
        anchor = _anchor_for(old, 1, "stopped syncing since")
        new = ["Weekly summary.", LEAD + "stopped quietly syncing since" + TRAIL, "Closing remarks."]
        got = matcher.find(anchor, new, allow_move=True)
        want = "stopped quietly syncing since"
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(new, got), want)

    def test_under_half_words(self):
        # 3 of the 7 highlight words survive (3/7 is under MIN_WORDS), context is intact.
        texts = ["Weekly summary.", LEAD + "stopped syncing since last week" + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_four_of_seven_words_moves(self):
        # Same as above with one more word kept (4/7 is over MIN_WORDS), so the
        # word threshold is what stopped the test above.
        texts = ["Weekly summary.", LEAD + "stopped syncing since the week" + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(texts, got), "stopped syncing since the")

    def test_exactly_half_words_moves(self):
        old = ["Weekly summary.", LEAD + "stopped syncing since monday" + TRAIL, "Closing remarks."]
        anchor = _anchor_for(old, 1, "stopped syncing since monday")
        text = "stopped overnight monday"  # 2 of 4 words survive: exactly MIN_WORDS
        new = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(anchor, new, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(new, got), text)

    def test_words_out_of_order(self):
        texts = [
            "Weekly summary.",
            LEAD + "started shift morning the since syncing stopped" + TRAIL,
            "Closing remarks.",
        ]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_too_many_extra_words(self):
        # Six of the seven highlight words survive. Seven unrelated words inside the run
        # is allowed (no more extra words than the highlight's seven words); eight is not.
        # The run is 13 or 14 words, within twice the highlight's length either way.
        def run(extra_count):
            filler = " ".join(["quietly", "overnight"][i % 2] for i in range(extra_count))
            text = "stopped syncing since " + filler + " the shift started"
            return ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."], text

        texts, text = run(7)
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(texts, got), text)
        texts, _ = run(8)
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_moved_two_equal_candidates(self):
        block = LEAD + NEW + TRAIL
        texts = ["Weekly summary.", block, "Weekly summary.", block, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="ambiguous"))

    def test_moved_clear_winner_over_weaker_candidate(self):
        weaker = "Totally unrelated lead-in words, so " + NEW + " with other trailing remarks."
        texts = [weaker, "Weekly summary.", LEAD + NEW + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        start = texts[2].index(NEW)
        self.assertEqual(got, Result("moved", 2, start, start + len(NEW)))

    def test_moved_never_crosses_blocks(self):
        # Each block holds under half the highlight's words; together they would hold five of seven.
        texts = ["Weekly summary.", LEAD + "stopped syncing since", "early shift started" + TRAIL]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_moved_words_match_case_insensitively(self):
        text = "Stopped Syncing since the early shift Started"
        texts = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(texts, got), text)


class SpeedTests(unittest.TestCase):
    def test_speed(self):
        rng = random.Random(20261119)
        letters = "abcdefghijklmnoprstuvwz"
        vocab = sorted({
            "".join(rng.choice(letters) for _ in range(rng.randint(3, 7)))
            for _ in range(400)
        })
        texts = [" ".join(rng.choice(vocab) for _ in range(20)) for _ in range(250)]
        self.assertEqual(sum(len(t.split()) for t in texts), 5000)
        anchors = []  # (anchor, block it came from)
        while len(anchors) < 20:
            block = rng.randrange(len(texts))
            words = texts[block].split()
            first = rng.randrange(0, 12)
            span = words[first:first + 6]
            old = " ".join(span)
            if texts[block].count(old) == 1:
                anchors.append((_anchor_for(texts, block, old), block))
                # Reword a middle word to one that is not in the vocabulary.
                span[3] = "zzqx"
                words[first:first + 6] = span
                texts[block] = " ".join(words)
        started = time.perf_counter()
        results = [matcher.find(anchor, texts, allow_move=True) for anchor, _ in anchors]
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        for (anchor, block), got in zip(anchors, results):
            self.assertEqual((got.status, got.block), ("moved", block), anchor)
            self.assertIn("zzqx", texts[block][got.start:got.end])


if __name__ == "__main__":
    unittest.main()
