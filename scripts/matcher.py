"""Finds a comment's anchor text in the visible blocks of a document."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple

CONTEXT = 32
MIN_WORDS = 0.5
MIN_CONTEXT = 0.7
MARGIN = 0.15
MIN_MOVE_WORDS = 3
# A moved run may not start or end on one of these (they may sit inside it).
STOPWORDS = frozenset(
    "a an the of to in on at by for with and or but is are was were be it its this that as from".split()
)


@dataclass(frozen=True)
class Anchor:
    text: str  # all normalized
    before: str = ""
    after: str = ""
    block: int = -1  # index of the anchor's block in the OLD page's blocks; -1 = unknown


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


def _find_moved(anchor: Anchor, texts: List[str], only_block: Optional[int] = None) -> Optional[Result]:
    """Match the highlight after its passage was reworded, in only_block if given.

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
    highlight_count = Counter(highlight)
    candidates = []  # (score, block, start, end)
    blocks = range(len(texts)) if only_block is None else [only_block]
    for block in blocks:
        words = _words(texts[block])
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


_MAX_REPLACE_PAIRS = 10000
_MIN_PAIR_RATIO = 0.5
_CHAR_PRODUCT_LIMIT = 5000  # len(old) * len(new) up to this: compare characters


@lru_cache(maxsize=4096)
def _tokens(text: str) -> Tuple[str, ...]:
    return tuple(w.lower() for w in _WORD.findall(text))


def _pair_ratio(old: str, new: str) -> float:
    """difflib ratio of two blocks, or 0.0 when a cheap upper bound already rules out the pair.

    Short blocks are compared character by character. Long ones are compared word by
    word: character ratios cost about a millisecond per 300-character pair, which adds up
    to seconds over a big replaced region. autojunk is off because, with it on, difflib
    treats common characters as junk once a block passes 200 characters and the ratio of
    a lightly reworded paragraph collapses.
    """
    first, second = old, new
    if len(old) * len(new) > _CHAR_PRODUCT_LIMIT:
        words_old, words_new = _tokens(old), _tokens(new)
        if words_old and words_new:
            first, second = words_old, words_new
    sequence = difflib.SequenceMatcher(None, first, second, autojunk=False)
    if sequence.real_quick_ratio() < _MIN_PAIR_RATIO or sequence.quick_ratio() < _MIN_PAIR_RATIO:
        return 0.0
    return sequence.ratio()


def align(old_texts: List[str], texts: List[str]) -> List[Optional[int]]:
    """For each old block, the index of the new block that replaced it, or None.

    Unchanged blocks line up through difflib's opcodes. Inside a replaced region, old and
    new blocks pair greedily by descending difflib ratio (each new block once, a pair
    only at ratio >= 0.5). A region over 10,000 pairs pairs by position instead, still
    only at ratio >= 0.5. Deleted and unpaired old blocks map to None.
    """
    mapping: List[Optional[int]] = [None] * len(old_texts)
    opcodes = difflib.SequenceMatcher(None, old_texts, texts, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
        elif tag == "replace":
            if (i2 - i1) * (j2 - j1) > _MAX_REPLACE_PAIRS:
                pairs = [(_pair_ratio(old_texts[i1 + k], texts[j1 + k]), i1 + k, j1 + k)
                         for k in range(min(i2 - i1, j2 - j1))]
            else:
                pairs = [(_pair_ratio(old_texts[i], texts[j]), i, j)
                         for i in range(i1, i2) for j in range(j1, j2)]
            pairs = [pair for pair in pairs if pair[0] >= _MIN_PAIR_RATIO]
            pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2]))
            used = set()
            for _, i, j in pairs:
                if mapping[i] is None and j not in used:
                    mapping[i] = j
                    used.add(j)
    return mapping


def _pick_exact_aligned(anchor: Anchor, texts: List[str], old_texts: List[str],
                        spans: List[Tuple[int, int, int]], target: Optional[int]) -> Result:
    """Exact matches when the old page is known: stay in the block that replaced the anchor's own."""
    in_target = [span for span in spans if span[0] == target]
    if in_target:
        return _pick_exact(anchor, texts, in_target)
    # Not in its own block: only a passage that is unique both before and after has moved.
    if len(spans) == 1 and len(_exact_spans(anchor.text, old_texts)) == 1:
        block, start, end = spans[0]
        return Result("exact", block, start, end)
    return Result("none", reason="ambiguous")


def find(anchor: Anchor, texts: List[str], allow_move: bool,
         old_texts: Optional[List[str]] = None,
         alignment: Optional[List[Optional[int]]] = None) -> Result:
    """Find the anchor in texts.

    Given old_texts (the page the comment was made on) and anchor.block >= 0, matches stay
    inside the block that replaced the anchor's own block, so a comment can't slide onto a
    look-alike sibling when its own passage is deleted. alignment (from align) is computed
    from old_texts when not passed. Without old_texts or a block, every block is searched.
    """
    if not anchor.text:
        return Result("none", reason="textGone")
    aligned = old_texts is not None and anchor.block >= 0
    target: Optional[int] = None
    if aligned:
        if alignment is None:
            alignment = align(old_texts, texts)
        if anchor.block < len(alignment):
            target = alignment[anchor.block]
    spans = _exact_spans(anchor.text, texts)
    if spans:
        if aligned:
            return _pick_exact_aligned(anchor, texts, old_texts, spans, target)
        return _pick_exact(anchor, texts, spans)
    if allow_move and (target is not None or not aligned):
        moved = _find_moved(anchor, texts, target)
        if moved is not None:
            return moved
    return Result("none", reason="textGone")
