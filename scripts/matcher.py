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
# Without the old page, surroundings that already hold this many of the highlight's own
# words can't tell look-alike passages apart (a deleted list item's sibling slides in).
REPEAT_WORDS = 2
# Pairing old and new blocks left unmatched, by similarity (see align).
MAX_PAIRS = 10000  # more unmatched old x new pairs than this: none of them is paired
PAIR_MARGIN = 0.05  # a pair must beat every rival sharing a block with it by this much
MIN_PAIR_RATIO = 0.5
CHAR_RATIO_LIMIT = 150  # blocks up to this many characters each compare by character
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


def _find_moved(anchor: Anchor, texts: List[str], only_block: Optional[int] = None,
                repeat_guard: bool = True) -> Optional[Result]:
    """Match the highlight after its passage was reworded, in only_block if given.

    repeat_guard refuses the move when the anchor's old surroundings hold REPEAT_WORDS of
    the highlight's own non-stopword words; find turns it off when the old page is known.

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
    if repeat_guard:
        around = {w.lower() for w in _WORD.findall(anchor.before + " " + anchor.after)}
        if len(around & edge_words) >= REPEAT_WORDS:
            return None
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


@lru_cache(maxsize=4096)
def _tokens(text: str) -> Tuple[str, ...]:
    return tuple(w.lower() for w in _WORD.findall(text))


def _pair_sequences(old: str, new: str):
    """What two blocks are compared as: their characters, or their words when either is long.

    Blocks up to CHAR_RATIO_LIMIT characters each are compared character by character;
    longer ones word by word, because a character ratio costs about a millisecond per
    300-character pair and adds up to seconds over a big replaced region.
    """
    if len(old) > CHAR_RATIO_LIMIT or len(new) > CHAR_RATIO_LIMIT:
        words_old, words_new = _tokens(old), _tokens(new)
        if words_old and words_new:
            return words_old, words_new
    return old, new


@lru_cache(maxsize=4096)
def _counts(sequence) -> Counter:
    return Counter(sequence)


def _ratio_bound(old: str, new: str) -> float:
    """difflib's quick_ratio for the pair (an upper bound on its ratio), from cached counts."""
    first, second = _pair_sequences(old, new)
    total = len(first) + len(second)
    if not total:
        return 1.0
    small, large = sorted((_counts(first), _counts(second)), key=len)
    return 2.0 * sum(min(count, large[item]) for item, count in small.items()) / total


def _pair_ratio(old: str, new: str, floor: float = MIN_PAIR_RATIO) -> float:
    """difflib ratio of two blocks, or 0.0 when a cheap upper bound is already under floor.

    See _pair_sequences for characters or words. autojunk is off because, with it on,
    difflib treats common characters as junk once a block passes 200 characters and the
    ratio of a lightly reworded paragraph collapses.
    """
    first, second = _pair_sequences(old, new)
    sequence = difflib.SequenceMatcher(None, first, second, autojunk=False)
    if sequence.real_quick_ratio() < floor or sequence.quick_ratio() < floor:
        return 0.0
    return sequence.ratio()


def _pair_identical(old_texts: List[str], texts: List[str], mapping: List[Optional[int]],
                    taken: set) -> None:
    """Pair unmatched old and new blocks with identical text that is unique on both sides."""
    old_at: dict = {}
    for i, text in enumerate(old_texts):
        if mapping[i] is None:
            old_at.setdefault(text, []).append(i)
    new_at: dict = {}
    for j, text in enumerate(texts):
        if j not in taken:
            new_at.setdefault(text, []).append(j)
    for text, olds in old_at.items():
        news = new_at.get(text, [])
        if len(olds) == 1 and len(news) == 1:
            mapping[olds[0]] = news[0]
            taken.add(news[0])


def _best_other(top: List[Tuple[float, int]], other: int) -> float:
    """The highest ratio in top (a block's two best pairs) that is not with block other."""
    return max((ratio for ratio, block in top if block != other), default=0.0)


def _pair_by_ratio(old_texts: List[str], texts: List[str], mapping: List[Optional[int]],
                   taken: set, region_of_old: dict, region_of_new: dict) -> None:
    """Pair still-unmatched old and new blocks by difflib ratio, inside one replaced region.

    Every unmatched old block on the page is a rival for every unmatched new block, whether
    difflib put it in the same replaced region, another one, or a deleted or inserted run.
    But a pair is only made when both blocks sit in the same replaced region (the region_of
    maps): a block deleted in one place and a look-alike added in another can't be told
    apart from one block moved and edited, so neither pairs and their comments detach.
    """
    olds = [i for i, new_block in enumerate(mapping) if new_block is None]
    news = [j for j in range(len(texts)) if j not in taken]
    if not olds or not news or len(olds) * len(news) > MAX_PAIRS:
        return  # too many pairs to score: they all stay unpaired
    # A pair is accepted at MIN_PAIR_RATIO or more, so only rivals within PAIR_MARGIN of
    # that can stop one; anything lower counts as no rival.
    floor = MIN_PAIR_RATIO - PAIR_MARGIN
    bounds = []
    for i in olds:
        for j in news:
            bound = _ratio_bound(old_texts[i], texts[j])
            if bound >= floor:
                bounds.append((bound, i, j))
    # Exact ratios cost far more than bounds, so they are worked out highest bound first,
    # and only for pairs that matter. A pair whose bound is PAIR_MARGIN or more below the
    # best exact ratio already found for its old block, and for its new block, can neither
    # pair nor stop the pairing of anything, so skipping it changes no result.
    bounds.sort(key=lambda item: -item[0])
    top_of_old: dict = {}  # block -> its two best (ratio, other block) so far, best first
    top_of_new: dict = {}
    ratios = {}
    for bound, i, j in bounds:
        top_old, top_new = top_of_old.setdefault(i, []), top_of_new.setdefault(j, [])
        if (top_old and top_old[0][0] - bound >= PAIR_MARGIN
                and top_new and top_new[0][0] - bound >= PAIR_MARGIN):
            continue
        ratio = _pair_ratio(old_texts[i], texts[j], floor)
        if ratio < floor:
            continue
        ratios[(i, j)] = ratio
        for top, other in ((top_old, j), (top_new, i)):
            top.append((ratio, other))
            top.sort(reverse=True)
            del top[2:]
    for (i, j), ratio in ratios.items():
        region = region_of_old.get(i)
        if ratio < MIN_PAIR_RATIO or region is None or region != region_of_new.get(j):
            continue
        rival = max(_best_other(top_of_old[i], j), _best_other(top_of_new[j], i))
        # Ties and near-ties stay unpaired. A pair that beats all its rivals by the margin
        # is the only accepted pair for both of its blocks.
        if ratio - rival >= PAIR_MARGIN:
            mapping[i] = j
            taken.add(j)


def align(old_texts: List[str], texts: List[str]) -> List[Optional[int]]:
    """For each old block, the index of the new block that replaced it, or None.

    Unchanged blocks line up through difflib's opcodes. Among the rest, blocks whose text
    is identical and unique on both sides pair first. Then every still-unmatched old block
    is compared with every still-unmatched new block on the page: a pair needs ratio >= 0.5,
    has to beat every other pair sharing its old or its new block by PAIR_MARGIN (so ties
    and near-ties stay unpaired), and both blocks must sit in the same replaced region.
    With more than MAX_PAIRS such pairs, none is scored and none is paired. Deleted and
    unpaired old blocks map to None.
    """
    mapping: List[Optional[int]] = [None] * len(old_texts)
    taken: set = set()
    region_of_old: dict = {}  # block -> number of the replaced region (opcode) it sits in
    region_of_new: dict = {}
    opcodes = difflib.SequenceMatcher(None, old_texts, texts, autojunk=False).get_opcodes()
    for region, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
                taken.add(j1 + offset)
        elif tag == "replace":
            region_of_old.update((i, region) for i in range(i1, i2))
            region_of_new.update((j, region) for j in range(j1, j2))
    _pair_identical(old_texts, texts, mapping, taken)
    _pair_by_ratio(old_texts, texts, mapping, taken, region_of_old, region_of_new)
    return mapping


def _claimed_by_other_block(anchor: Anchor, texts: List[str], old_texts: List[str],
                            alignment: List[Optional[int]], block: int) -> bool:
    """True when texts[block] stands in for a different old block than the anchor's own.

    That is the block's aligned old block, or an unpaired old block it resembles (ratio
    >= 0.5), which align left unpaired only because it could not tell two candidates apart.
    """
    for old_block, new_block in enumerate(alignment):
        if old_block == anchor.block:
            continue
        if new_block == block:
            return True
        if new_block is None and _pair_ratio(old_texts[old_block], texts[block]) >= MIN_PAIR_RATIO:
            return True
    return False


def _pick_exact_aligned(anchor: Anchor, texts: List[str], old_texts: List[str],
                        spans: List[Tuple[int, int, int]], target: Optional[int],
                        alignment: List[Optional[int]]) -> Result:
    """Exact matches when the old page is known: stay in the block that replaced the anchor's own."""
    in_target = [span for span in spans if span[0] == target]
    if in_target:
        return _pick_exact(anchor, texts, in_target)
    # Not in its own block: a passage that is unique before and after may have moved, but
    # not into a block that replaced some other old block.
    if len(spans) == 1 and len(_exact_spans(anchor.text, old_texts)) == 1:
        block, start, end = spans[0]
        if not _claimed_by_other_block(anchor, texts, old_texts, alignment, block):
            return Result("exact", block, start, end)
    return Result("none", reason="ambiguous")


def find(anchor: Anchor, texts: List[str], allow_move: bool,
         old_texts: Optional[List[str]] = None,
         alignment: Optional[List[Optional[int]]] = None) -> Result:
    """Find the anchor in texts.

    Given old_texts (the page the comment was made on) and anchor.block >= 0, matches stay
    inside the block that replaced the anchor's own block, so a comment can't slide onto a
    look-alike sibling when its own passage is deleted. alignment (from align) is computed
    from old_texts when not passed; passing it without old_texts is an error. Without
    old_texts or a block, every block is searched and moves are refused when the old
    surroundings repeat the highlight's words.
    """
    if alignment is not None and old_texts is None:
        raise ValueError("alignment needs old_texts")
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
            return _pick_exact_aligned(anchor, texts, old_texts, spans, target, alignment)
        return _pick_exact(anchor, texts, spans)
    if allow_move and (target is not None or not aligned):
        moved = _find_moved(anchor, texts, target, repeat_guard=not aligned)
        if moved is not None:
            return moved
    return Result("none", reason="textGone")
