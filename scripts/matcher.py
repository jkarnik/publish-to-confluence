"""Finds a comment's anchor text in the visible blocks of a document."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Tuple

CONTEXT = 32
MIN_WORDS = 0.5
MIN_CONTEXT = 0.7
MARGIN = 0.15
MIN_MOVE_WORDS = 3
# Surroundings that already hold this many of the highlight's own words can't tell
# look-alike passages apart (a deleted list item's sibling slides into its place).
REPEAT_WORDS = 2
# A moved run may not start or end on one of these (they may sit inside it).
STOPWORDS = frozenset(
    "a an the of to in on at by for with and or but is are was were be it its this that as from".split()
)


@dataclass(frozen=True)
class Anchor:
    text: str  # all normalized
    before: str = ""
    after: str = ""


@dataclass(frozen=True)
class Result:
    status: str  # "exact" | "moved" | "none"
    block: int = -1
    start: int = -1
    end: int = -1  # span in blocks[block]
    reason: Optional[str] = None  # "ambiguous" | "textGone" when status == "none"


def context_of(texts: List[str], block: int, start: int, end: int) -> Tuple[str, str]:
    """Up to CONTEXT chars before/after, across blocks joined by one space."""
    before = texts[block][:start]
    i = block - 1
    # Walking back only as far as needed gives the same last CONTEXT chars as joining
    # every earlier block, without copying the whole document per call.
    while i >= 0 and len(before) < CONTEXT:
        before = texts[i] + " " + before
        i -= 1
    after = texts[block][end:]
    j = block + 1
    while j < len(texts) and len(after) < CONTEXT:
        after = after + " " + texts[j]
        j += 1
    return before[-CONTEXT:].strip(" "), after[:CONTEXT].strip(" ")


def _context_score(anchor: Anchor, before: str, after: str) -> float:
    """Mean difflib ratio over the sides the anchor has; 0.0 when it has neither."""
    ratios = []
    if anchor.before:
        ratios.append(difflib.SequenceMatcher(None, anchor.before, before).ratio())
    if anchor.after:
        ratios.append(difflib.SequenceMatcher(None, anchor.after, after).ratio())
    return sum(ratios) / len(ratios) if ratios else 0.0


def _exact_spans(text: str, texts: List[str]) -> List[Tuple[int, int, int]]:
    """Every (block, start, end) where text occurs inside one block, case-sensitive."""
    spans = []
    for block, block_text in enumerate(texts):
        pos = block_text.find(text)
        while pos != -1:
            spans.append((block, pos, pos + len(text)))
            pos = block_text.find(text, pos + 1)
    return spans


def _pick_exact(anchor: Anchor, texts: List[str], spans: List[Tuple[int, int, int]]) -> Result:
    if len(spans) == 1:
        block, start, end = spans[0]
        return Result("exact", block, start, end)
    if not anchor.before and not anchor.after:
        return Result("none", reason="ambiguous")
    scored = []
    for block, start, end in spans:
        before, after = context_of(texts, block, start, end)
        scored.append((_context_score(anchor, before, after), block, start, end))
    ranked = sorted(scored, key=lambda item: -item[0])  # stable: earlier span wins a tie
    if ranked[0][0] - ranked[1][0] >= MARGIN:
        _, block, start, end = ranked[0]
        return Result("exact", block, start, end)
    return Result("none", reason="ambiguous")


_WORD = re.compile(r"\w+")


def _words(text: str) -> List[Tuple[str, int, int]]:
    """(lowercased word, start, end) for each word in text."""
    return [(m.group().lower(), m.start(), m.end()) for m in _WORD.finditer(text)]


def _runs_in_block(words: List[Tuple[str, int, int]], highlight: List[str],
                   edge_words: frozenset) -> List[Tuple[float, int, int]]:
    """(word score, first word index, last word index) for each run that qualifies.

    A run starts and ends on a highlight word that is not a stopword (edge_words), holds
    at most twice the highlight's word count, scores LCS / highlight words >= MIN_WORDS,
    and has at most max(2, n // 2) extra words (run length - LCS).
    """
    n = len(highlight)
    max_extra = max(2, n // 2)
    found = []
    for first, (word, _, _) in enumerate(words):
        if word not in edge_words:
            continue
        # row[j] = LCS(highlight[:j], the run so far), extended one run word at a time,
        # so every end for this start costs one row instead of a fresh table.
        row = [0] * (n + 1)
        for last in range(first, min(len(words), first + 2 * n)):
            run_word = words[last][0]
            diag, row[0] = 0, 0
            for j in range(1, n + 1):
                above = row[j]
                if highlight[j - 1] == run_word:
                    row[j] = diag + 1
                elif row[j - 1] > above:
                    row[j] = row[j - 1]
                diag = above
            lcs = row[n]
            extra = (last - first + 1) - lcs
            if extra > max_extra:
                break  # a longer run never has fewer extra words
            if run_word not in edge_words:
                continue
            score = lcs / n
            if score >= MIN_WORDS:
                found.append((score, first, last))
    return found


def _context_upper_bound(anchor: Anchor, before: str, after: str) -> float:
    """Like _context_score but with difflib's cheap upper bounds, so hopeless runs skip the full ratio."""
    bounds = []
    if anchor.before:
        bounds.append(difflib.SequenceMatcher(None, anchor.before, before).quick_ratio())
    if anchor.after:
        bounds.append(difflib.SequenceMatcher(None, anchor.after, after).quick_ratio())
    return sum(bounds) / len(bounds) if bounds else 0.0


def _find_moved(anchor: Anchor, texts: List[str]) -> Optional[Result]:
    """Match the highlight after its passage was reworded.

    Returns a Result("moved", ...), Result("none", reason="ambiguous"), or None when
    nothing qualifies (the caller reports textGone).
    """
    if not (anchor.before or anchor.after):
        return None
    highlight = [w.lower() for w in _WORD.findall(anchor.text)]
    n = len(highlight)
    if n < MIN_MOVE_WORDS:
        return None
    highlight_set = frozenset(highlight)
    edge_words = highlight_set - STOPWORDS
    around = {w.lower() for w in _WORD.findall(anchor.before + " " + anchor.after)}
    if len(around & edge_words) >= REPEAT_WORDS:
        return None
    highlight_count = Counter(highlight)
    candidates = []  # (score, block, start, end)
    for block, text in enumerate(texts):
        words = _words(text)
        in_block = Counter(w for w, _, _ in words if w in highlight_set)
        shared = sum(min(count, highlight_count[w]) for w, count in in_block.items())
        if shared < MIN_WORDS * n:  # LCS can't exceed the shared words
            continue
        for word_score, first, last in _runs_in_block(words, highlight, edge_words):
            start, end = words[first][1], words[last][2]
            before, after = context_of(texts, block, start, end)
            if _context_upper_bound(anchor, before, after) < MIN_CONTEXT:
                continue
            context_score = _context_score(anchor, before, after)
            if context_score >= MIN_CONTEXT:
                candidates.append((word_score + context_score, block, start, end))
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda c: (-c[0], c[1], c[2], c[3]))
    best_score, block, start, end = ranked[0]
    for score, other_block, other_start, other_end in ranked[1:]:
        overlaps = other_block == block and other_start < end and start < other_end
        if overlaps:
            continue
        if best_score - score < MARGIN:
            return Result("none", reason="ambiguous")
        break
    return Result("moved", block, start, end)


def find(anchor: Anchor, texts: List[str], allow_move: bool) -> Result:
    if not anchor.text:
        return Result("none", reason="textGone")
    spans = _exact_spans(anchor.text, texts)
    if spans:
        return _pick_exact(anchor, texts, spans)
    if allow_move:
        moved = _find_moved(anchor, texts)
        if moved is not None:
            return moved
    return Result("none", reason="textGone")
