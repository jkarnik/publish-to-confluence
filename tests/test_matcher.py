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
    return Anchor(text, before, after, block=block, **kw)


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
        # Four of the seven highlight words (4/7 is over MIN_WORDS), starting and ending
        # on words that are not stopwords, so the word threshold is the only thing in play.
        text = "stopped syncing since shift"
        texts = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(texts, got), text)

    def test_partial_run_ending_on_stopword_detaches(self):
        # 4 of 7 words, no extra words, surroundings intact: the same strength as the case
        # above, but the run would end on "the", so it must not anchor a comment.
        texts = ["Weekly summary.", LEAD + "stopped syncing since the week" + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))
        # Seven unrelated words before that "the" make it worse, not better.
        filler = " ".join(["quietly", "overnight"][i % 2] for i in range(7))
        text = "stopped syncing since " + filler + " the early shift started"
        texts = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_run_starting_on_stopword_starts_on_next_word(self):
        # The highlight starts with "the"; the new text has "the" too, but the span
        # must begin on the first non-stopword highlight word.
        old = ["Weekly summary.", LEAD + "the agent stopped syncing since monday" + TRAIL, "Closing remarks."]
        anchor = _anchor_for(old, 1, "the agent stopped syncing since monday")
        new = ["Weekly summary.", LEAD + "the agent stopped quietly syncing since monday" + TRAIL, "Closing remarks."]
        got = matcher.find(anchor, new, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(new, got), "agent stopped quietly syncing since monday")

    def test_small_insertion_still_moves(self):
        text = "stopped syncing again since the early morning shift started"  # 2 extra words, n = 7
        texts = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        start = texts[1].index(text)
        self.assertEqual(got, Result("moved", 1, start, start + len(text)))

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
        # Six of seven highlight words survive. With n = 7 a run may hold at most
        # max(2, 7 // 2) = 3 extra words: 3 moves, 4 detaches.
        def run(extra_count):
            filler = " ".join(["quietly", "overnight"][i % 2] for i in range(extra_count))
            text = "stopped syncing since " + filler + " the shift started"
            return ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."], text

        texts, text = run(3)
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(texts, got), text)
        texts, _ = run(4)
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_too_many_extra_words_detaches(self):
        # Every highlight word is still there, but spread over a 14-word run (7 extra words),
        # which used to pass; the run is far looser than the wording it replaces.
        filler = " ".join(["quietly", "overnight"][i % 2] for i in range(7))
        text = "stopped syncing since " + filler + " the morning shift started"
        texts = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="textGone"))

    def test_few_extra_words_allowed_for_short_highlights(self):
        # n = 3 still allows max(2, 3 // 2) = 2 extra words, not 1: the whole new wording is the span.
        old = ["Weekly summary.", LEAD + "stopped syncing since" + TRAIL, "Closing remarks."]
        anchor = _anchor_for(old, 1, "stopped syncing since")
        text = "stopped quietly syncing overnight since"
        new = ["Weekly summary.", LEAD + text + TRAIL, "Closing remarks."]
        got = matcher.find(anchor, new, allow_move=True)
        self.assertEqual(got.status, "moved")
        self.assertEqual(_span_text(new, got), text)

    def test_context_needs_seventy_percent(self):
        self.assertEqual(matcher.MIN_CONTEXT, 0.7)

    def test_moved_two_equal_candidates(self):
        block = LEAD + NEW + TRAIL
        texts = ["Weekly summary.", block, "Weekly summary.", block, "Closing remarks."]
        got = matcher.find(self.anchor, texts, allow_move=True)
        self.assertEqual(got, Result("none", reason="ambiguous"))

    def test_moved_clear_winner_over_weaker_candidate(self):
        # Surroundings that still pass MIN_CONTEXT (about 0.74) but fit worse than the intact ones.
        weaker = "The agent restarted around noon, then " + NEW + " and nobody saw it until Monday."
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


ITEMS = [
    "Alert when packet loss on the uplink interface exceeds 5%.",
    "Alert when packet loss on the downlink interface exceeds 5%.",
    "Alert when packet loss on the backup interface exceeds 5%.",
]
NAMES = ("uplink", "downlink", "backup")
GONE = Result("none", reason="textGone")


def _list_texts(items=ITEMS):
    return ["Alerting requirements"] + list(items) + ["Out of scope"]


class AlignTests(unittest.TestCase):
    def test_align_equal_and_delete(self):
        self.assertEqual(matcher.align(["a", "b"], ["a", "b"]), [0, 1])
        self.assertEqual(matcher.align(["a", "b", "c"], ["a", "c"]), [0, None, 1])
        self.assertEqual(matcher.align(["a", "b", "c"], ["a", "b", "c", "d"]), [0, 1, 2])
        self.assertEqual(matcher.align([], ["a"]), [])
        self.assertEqual(matcher.align(["a"], []), [None])

    def test_align_replace_pairs_by_ratio(self):
        alerts = "Uplink alert pages the on-call engineer."
        report = "Backup job report is emailed to the team."
        old = ["Intro", alerts, report, "End"]
        new = ["Intro", "Backup job report is emailed to the whole team.",
               "Uplink alert pages the on-call engineer now.", "End"]
        self.assertEqual(matcher.align(old, new), [0, 2, 1, 3])

    def test_align_replace_below_threshold_is_none(self):
        old = ["Intro", "Alert when disk is full.", "End"]
        new = ["Intro", "Completely unrelated sentence about billing cycles.", "End"]
        self.assertEqual(matcher.align(old, new), [0, None, 2])

    def test_align_uses_each_new_block_once(self):
        old = ["Intro", "Alert when uplink loss is high.", "Alert when uplink loss is higher.", "End"]
        new = ["Intro", "Alert when uplink loss is high!", "End"]
        got = matcher.align(old, new)
        self.assertEqual(got[0], 0)
        self.assertEqual(got[3], 2)
        self.assertEqual(sorted(g for g in got[1:3] if g is not None), [1])

    def test_align_long_reworded_block_pairs(self):
        # Over 200 characters difflib's default "junk" heuristic would sink this ratio.
        sentence = "The collector restarted after the nightly job and nobody noticed the gap. "
        old = ["Intro", sentence * 5 + "Operators agreed to review it.", "End"]
        new = ["Intro", sentence * 5 + "Operators agreed to look at it.", "End"]
        self.assertEqual(matcher.align(old, new), [0, 1, 2])

    def test_align_huge_replace_pairs_by_position(self):
        old = ["Alert number %03d fires when the disk is full." % i for i in range(101)]
        new = ["Alert number %03d fires when the disk is almost full." % i for i in range(101)]
        started = time.perf_counter()
        got = matcher.align(old, new)  # 101 * 101 pairs is over the 10,000 limit
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(got, list(range(101)))


class AlignedMatchTests(unittest.TestCase):
    """With old_texts the comment stays in the block that replaced its own block."""

    def find(self, anchor, new_texts, old_texts, allow_move=True, **kw):
        return matcher.find(anchor, new_texts, allow_move, old_texts=old_texts, **kw)

    def test_deleted_list_item_does_not_slide(self):
        texts = _list_texts()
        for gone, name in enumerate(NAMES):
            anchor = _anchor_for(texts, 1 + gone, "packet loss on the %s interface exceeds 5%%" % name)
            new_texts = texts[:1 + gone] + texts[2 + gone:]
            self.assertEqual(self.find(anchor, new_texts, texts), GONE, name)

    def test_deleted_list_item_tail_highlight_does_not_slide(self):
        texts = _list_texts()
        for gone, name in enumerate(NAMES):
            anchor = _anchor_for(texts, 1 + gone, "%s interface exceeds 5%%" % name)
            new_texts = texts[:1 + gone] + texts[2 + gone:]
            self.assertEqual(self.find(anchor, new_texts, texts), GONE, name)

    def test_deleted_table_row_does_not_slide(self):
        rows = [
            "%s | Packet loss | Page on-call when loss stays above %d%% for ten minutes" % (name, limit)
            for name, limit in (("uplink", 5), ("downlink", 3), ("backup", 8))
        ]
        texts = ["Interface | Metric | Alert threshold"] + rows
        for gone, limit in enumerate((5, 3, 8)):
            text = "Page on-call when loss stays above %d%% for ten minutes" % limit
            anchor = _anchor_for(texts, 1 + gone, text)
            new_texts = texts[:1 + gone] + texts[2 + gone:]
            self.assertEqual(self.find(anchor, new_texts, texts), GONE, limit)

    def test_repeated_exact_text_in_deleted_item_is_ambiguous(self):
        texts = _list_texts()
        for gone in range(3):
            anchor = _anchor_for(texts, 1 + gone, "interface exceeds 5%")
            new_texts = texts[:1 + gone] + texts[2 + gone:]
            got = self.find(anchor, new_texts, texts)
            self.assertEqual(got, Result("none", reason="ambiguous"), gone)
        # Nothing deleted: the text stays in its own item, even though siblings repeat it.
        for item in range(3):
            anchor = _anchor_for(texts, 1 + item, "interface exceeds 5%")
            got = self.find(anchor, texts, texts, allow_move=False)
            start = texts[1 + item].index("interface exceeds 5%")
            self.assertEqual(got, Result("exact", 1 + item, start, start + len("interface exceeds 5%")))

    def test_moved_paragraph_still_attaches(self):
        old = ["Intro", "Section A", "The collector restarted at noon and nobody noticed.",
               "Section B", "Closing"]
        new = ["Intro", "Section A", "Section B",
               "The collector restarted at noon and nobody noticed.", "Closing"]
        anchor = _anchor_for(old, 2, "restarted at noon")
        got = self.find(anchor, new, old, allow_move=False)
        start = new[3].index("restarted at noon")
        self.assertEqual(got, Result("exact", 3, start, start + len("restarted at noon")))

    def test_moved_paragraph_with_repeated_text_is_ambiguous(self):
        sentence = "The collector restarted at noon and nobody noticed."
        old = ["Intro", sentence, "Section B", "Other notes. " + sentence, "Closing"]
        new = ["Intro", "Section B", "Other notes. " + sentence, sentence, "Closing"]
        anchor = _anchor_for(old, 1, "restarted at noon")
        got = self.find(anchor, new, old, allow_move=False)
        self.assertEqual(got, Result("none", reason="ambiguous"))

    def test_reword_in_lookalike_list_moves(self):
        texts = _list_texts()
        text = "packet loss on the downlink interface exceeds 5%"
        anchor = _anchor_for(texts, 2, text)
        reworded = "packet loss on the downlink interface goes above 5"
        new_texts = list(texts)
        new_texts[2] = texts[2].replace(text, reworded + "%")
        got = self.find(anchor, new_texts, texts)
        start = new_texts[2].index(reworded)  # the span ends on the last word, before "%"
        self.assertEqual(got, Result("moved", 2, start, start + len(reworded)))

    def test_delete_plus_sibling_reword(self):
        texts = _list_texts()
        text_a = "packet loss on the uplink interface exceeds 5%"
        text_b = "packet loss on the downlink interface exceeds 5%"
        anchor_a = _anchor_for(texts, 1, text_a)
        anchor_b = _anchor_for(texts, 2, text_b)
        reworded = "packet loss on the downlink interface goes above 5"
        new_texts = [texts[0], texts[2].replace(text_b, reworded + "%"), texts[3], texts[4]]
        self.assertEqual(self.find(anchor_a, new_texts, texts), GONE)
        got = self.find(anchor_b, new_texts, texts)
        start = new_texts[1].index(reworded)
        self.assertEqual(got, Result("moved", 1, start, start + len(reworded)))

    def test_precomputed_alignment_gives_the_same_answer(self):
        texts = _list_texts()
        anchor = _anchor_for(texts, 2, "packet loss on the downlink interface exceeds 5%")
        new_texts = texts[:2] + texts[3:]
        alignment = matcher.align(texts, new_texts)
        self.assertEqual(alignment, [0, 1, None, 2, 3])
        got = matcher.find(anchor, new_texts, True, old_texts=texts, alignment=alignment)
        self.assertEqual(got, GONE)

    def test_without_old_texts_nothing_changes(self):
        # No old page (or no block index): the original behaviour, which cannot tell
        # look-alike items apart.
        texts = _list_texts()
        anchor = _anchor_for(texts, 1, "packet loss on the uplink interface exceeds 5%")
        new_texts = texts[:1] + texts[2:]
        self.assertEqual(matcher.find(anchor, new_texts, True).status, "moved")
        unknown = Anchor(anchor.text, anchor.before, anchor.after)  # block = -1
        self.assertEqual(matcher.find(unknown, new_texts, True, old_texts=texts).status, "moved")


class SpeedTests(unittest.TestCase):
    def test_speed(self):
        rng = random.Random(20261119)
        letters = "abcdefghijklmnoprstuvwz"
        vocab = sorted({
            "".join(rng.choice(letters) for _ in range(rng.randint(3, 7)))
            for _ in range(400)
        })
        old_texts = [" ".join(rng.choice(vocab) for _ in range(20)) for _ in range(250)]
        self.assertEqual(sum(len(t.split()) for t in old_texts), 5000)
        texts = list(old_texts)
        anchors = []  # (anchor, block it came from)
        for block in rng.sample(range(len(old_texts)), 40):
            if len(anchors) == 20:
                break
            words = old_texts[block].split()
            first = rng.randrange(0, 12)
            span = words[first:first + 6]
            old = " ".join(span)
            if old_texts[block].count(old) != 1:
                continue
            anchors.append((_anchor_for(old_texts, block, old), block))
            # Reword a middle word to one that is not in the vocabulary.
            span[3] = "zzqx"
            words[first:first + 6] = span
            texts[block] = " ".join(words)
        self.assertEqual(len(anchors), 20)
        started = time.perf_counter()
        # Each call lines the old page up with the new one itself: the slowest way to call.
        results = [matcher.find(anchor, texts, allow_move=True, old_texts=old_texts)
                   for anchor, _ in anchors]
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        for (anchor, block), got in zip(anchors, results):
            self.assertEqual((got.status, got.block), ("moved", block), anchor)
            self.assertIn("zzqx", texts[block][got.start:got.end])

    def test_speed_long_highlight(self):
        # A ~30-word highlight on a 5,000-word page of varied made-up sentences
        # (about 30% stopwords, 100 blocks of 50 words), plus planted near-copies of the
        # anchor's block so several blocks pass the word-overlap check.
        rng = random.Random(20261120)
        letters = "abcdefghijklmnoprstuvwz"
        vocab = sorted({
            "".join(rng.choice(letters) for _ in range(rng.randint(4, 9)))
            for _ in range(1500)
        } - set(matcher.STOPWORDS))
        stops = sorted(matcher.STOPWORDS)

        def sentence(count):
            return " ".join(
                rng.choice(stops) if rng.random() < 0.3 else rng.choice(vocab)
                for _ in range(count)
            )

        old_texts = [sentence(50) for _ in range(100)]
        self.assertEqual(sum(len(t.split()) for t in old_texts), 5000)
        texts = list(old_texts)
        anchors = []  # (anchor, block it came from)
        for block in range(0, 100, 10):
            words = old_texts[block].split()
            first = rng.randrange(0, 15)
            span = words[first:first + 30]
            anchors.append((_anchor_for(old_texts, block, " ".join(span)), block))
            for index in (7, 22):  # reword two words in the middle
                span[index] = "zzqx%d" % index
            texts[block] = " ".join(words[:first] + span + words[first + 30:])
        # Near-copies: other blocks become the first anchor's block, lightly changed.
        original = texts[anchors[0][1]].split()
        for other in (3, 33, 63):
            copy = list(original)
            for index in rng.sample(range(len(copy)), 6):
                copy[index] = rng.choice(vocab)
            texts[other] = " ".join(copy)
        started = time.perf_counter()
        results = [matcher.find(anchor, texts, allow_move=True, old_texts=old_texts)
                   for anchor, _ in anchors]
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        for (anchor, block), got in list(zip(anchors, results))[1:]:
            self.assertEqual((got.status, got.block), ("moved", block), anchor)


if __name__ == "__main__":
    unittest.main()
