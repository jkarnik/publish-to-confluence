"""Read side of inline-comment markers in a storage body."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from matcher import Anchor, context_of
from storage import Token, element_ranges, tokenize
from textnorm import normalize
from visible_text import blocks

MARKER = "ac:inline-comment-marker"


def refs(body: str) -> Set[str]:
    found: Set[str] = set()
    for token in tokenize(body):
        if token.name == MARKER and token.kind in ("start", "empty") and "ac:ref" in token.attrs:
            found.add(token.attrs["ac:ref"])
    return found


def _pieces(tokens: List[Token], ref: str) -> List[Tuple[int, int, int, int]]:
    """(outer start, inner start, inner end, outer end) of each marker piece with this ref, in order."""
    closed = element_ranges(tokens, MARKER)
    closed_starts = {first for first, _ in closed}
    spans = list(closed)
    # A start tag nothing closes still marks a spot; treat it as an empty piece.
    spans += [(i, i) for i, t in enumerate(tokens)
              if t.name == MARKER and t.kind == "start" and i not in closed_starts]
    pieces = []
    for first, last in sorted(spans):
        if tokens[first].attrs.get("ac:ref") != ref:
            continue
        if first == last:  # an empty tag, or a start tag nothing closes
            pieces.append((tokens[first].start, tokens[first].end, tokens[first].end, tokens[first].end))
        else:
            pieces.append((tokens[first].start, tokens[first].end, tokens[last].start, tokens[last].end))
    return pieces


def _cursor(starts_by_block: List[List[int]], offset: int) -> Tuple[int, int]:
    """(block, index) of the first visible char starting at or after offset; the end of the last block if none."""
    for b, starts in enumerate(starts_by_block):
        for i, start in enumerate(starts):
            if start >= offset:
                return b, i
    last = len(starts_by_block) - 1
    return last, len(starts_by_block[last])


def anchor_for(body: str, ref: str, selection: str,
               link_words: Optional[Dict[str, List[str]]] = None) -> Optional[Anchor]:
    """None if no marker with ref; text = visible text inside its pieces, or selection when that is empty.
    block = index in blocks(body) of the block holding the first visible char; -1 when there is none.
    link_words is passed to blocks(): cards then read as the file's link words (see visible_text.blocks).
    Inside one block, a gap of only spaces between two chosen chars (a line break, or a space between
    two formatted pieces) reads as one space, since a Confluence highlight is contiguous."""
    tokens = tokenize(body)
    pieces = _pieces(tokens, ref)
    if not pieces:
        return None
    doc = blocks(body, link_words)
    texts = [block.text for block in doc]
    inner = [(low, high) for _, low, high, _ in pieces]
    chars = [(b, i) for b, block in enumerate(doc) for i, start in enumerate(block.starts)
             if any(low <= start < high for low, high in inner)]
    while chars and texts[chars[0][0]][chars[0][1]] == " ":
        chars.pop(0)
    while chars and texts[chars[-1][0]][chars[-1][1]] == " ":
        chars.pop()
    if chars:
        parts: List[str] = []
        for n, (b, i) in enumerate(chars):
            if n and b != chars[n - 1][0]:
                parts.append(" ")  # pieces in different blocks meet at one space
            elif n and i > chars[n - 1][1] + 1 and not texts[b][chars[n - 1][1] + 1:i].strip(" "):
                parts.append(" ")  # only spaces were skipped, so the highlight ran on through them
            parts.append(texts[b][i])
        first_block, first_index = chars[0]
        last_block, last_index = chars[-1]
        before = context_of(texts, first_block, first_index, first_index + 1)[0]
        after = context_of(texts, last_block, last_index, last_index + 1)[1]
        return Anchor(normalize("".join(parts)), before, after, first_block)
    if not doc:
        return Anchor(normalize(selection))
    starts_by_block = [block.starts for block in doc]
    block, index = _cursor(starts_by_block, pieces[0][0])
    before = context_of(texts, block, index, index)[0]
    block, index = _cursor(starts_by_block, pieces[-1][3])
    after = context_of(texts, block, index, index)[1]
    return Anchor(normalize(selection), before, after)
