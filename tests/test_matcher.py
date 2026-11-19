import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on the path)

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


if __name__ == "__main__":
    unittest.main()
