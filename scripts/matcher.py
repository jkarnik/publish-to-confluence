"""Finds a comment's anchor text in the visible blocks of a document."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import List, Optional, Tuple

CONTEXT = 32
MIN_WORDS = 0.5
MIN_CONTEXT = 0.6
MARGIN = 0.15
MIN_MOVE_WORDS = 3


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


def _find_moved(anchor: Anchor, texts: List[str]) -> Optional[Result]:
    """K7b: match the highlight after the text was reworded. Not written yet.

    Returns a Result("moved", ...), Result("none", reason="ambiguous"), or None when
    nothing qualifies. Until K7b fills this in it always returns None.
    """
    return None


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
