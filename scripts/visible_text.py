"""Visible text of a storage body, split into blocks with offsets back into the body."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

from storage import Token, tokenize
from textnorm import normalize_map


@dataclass
class Block:
    text: str  # normalized visible text of one block
    starts: List[int] = field(default_factory=list)  # storage offset where char i starts ([] for markdown blocks)
    ends: List[int] = field(default_factory=list)  # storage offset where char i ends


BLOCK_TAGS: FrozenSet[str] = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "pre",
    "div", "tr", "table", "ul", "ol", "caption", "ac:task-body", "ac:layout-cell",
})


# Elements a reader never sees as text: everything from the start tag to its matching end tag is skipped.
HIDDEN_TAGS: FrozenSet[str] = frozenset({
    "ac:structured-macro", "ac:plain-text-body", "ac:parameter", "pre", "ac:image",
    "ac:task-id", "ac:task-status", "time", "ac:emoticon",
})


def _is_card(token: Token) -> bool:
    return token.name == "a" and "data-card-appearance" in token.attrs  # a smart-link card


def _is_hidden(token: Token) -> bool:
    return token.name in HIDDEN_TAGS or token.name.startswith("ri:") or _is_card(token)


def _count_cards(tokens: List[Token]) -> Dict[str, int]:
    """Cards per URL that blocks() meets: the same walk, so a card inside a skipped element is not counted."""
    counts: Dict[str, int] = {}
    hidden_name = ""
    hidden_depth = 0
    for token in tokens:
        if hidden_name:
            if token.name == hidden_name and token.kind == "start":
                hidden_depth += 1
            elif token.name == hidden_name and token.kind == "end":
                hidden_depth -= 1
                if hidden_depth == 0:
                    hidden_name = ""
            continue
        if token.kind in ("start", "empty") and _is_hidden(token):
            if _is_card(token):
                url = token.attrs.get("href", "")
                counts[url] = counts.get(url, 0) + 1
            if token.kind == "start":
                hidden_name, hidden_depth = token.name, 1
    return counts


def blocks(body: str, link_words: Optional[Dict[str, List[str]]] = None) -> List[Block]:
    """Skipped (not visible): ac:structured-macro (all), ac:plain-text-body, ac:parameter, pre, ac:image,
    ri:*, ac:task-id, ac:task-status, time, and <a data-card-appearance=...> cards. Markers are transparent.

    link_words maps a URL to the markdown file's link texts for it, in the file's order. When it is given, the
    k-th card with that URL (k counts from 0, in body order) shows as the k-th text instead of being hidden,
    but only when the body has exactly as many cards to that URL as link_words has texts for it; when the
    counts differ, no card to that URL can be matched to a link, so all of them stay hidden. Cards inside
    skipped elements are in neither count. Each shown char maps to the whole card element, so nothing can be
    wrapped inside a card. With link_words=None every card is hidden."""
    tokens = tokenize(body)
    card_counts = _count_cards(tokens) if link_words is not None else {}  # cards per URL (first pass)
    result: List[Block] = []
    raw: List[str] = []  # the current block's raw characters ...
    raw_starts: List[int] = []  # ... and, for each, the body offset where it starts
    raw_ends: List[int] = []  # ... and where it ends

    def close() -> None:
        if raw:
            text, starts, ends = normalize_map("".join(raw))
            if text:
                result.append(Block(
                    text,
                    [raw_starts[s] for s in starts],
                    [raw_ends[e - 1] for e in ends],
                ))
        del raw[:], raw_starts[:], raw_ends[:]

    hidden_name = ""  # name of the hidden element being skipped ("" when none)
    hidden_depth = 0  # how many of that name are open
    cards_seen: Dict[str, int] = {}  # cards met so far, by URL (only counted when link_words is given)
    card_words = ""  # the words to show for the card being skipped ("" when none)
    card_start = 0  # body offset where that card starts

    def show_card(token: Token) -> str:
        """The file's words for this card, or "" when there are none, the counts differ (or no link_words)."""
        if link_words is None:
            return ""
        url = token.attrs.get("href", "")
        k = cards_seen.get(url, 0)
        cards_seen[url] = k + 1
        texts = link_words.get(url, [])
        return texts[k] if len(texts) == card_counts.get(url, 0) else ""

    def put_card_words(words: str, start: int, end: int) -> None:
        for ch in words:
            raw.append(ch)
            raw_starts.append(start)
            raw_ends.append(end)

    for token in tokens:
        if hidden_name:  # inside a hidden element: only look for its matching end
            if token.name == hidden_name and token.kind == "start":
                hidden_depth += 1
            elif token.name == hidden_name and token.kind == "end":
                hidden_depth -= 1
                if hidden_depth == 0:
                    hidden_name = ""
                    if card_words:  # the card's words stand where its element is
                        put_card_words(card_words, card_start, token.end)
                        card_words = ""
            continue
        if token.kind in ("start", "end", "empty") and token.name in BLOCK_TAGS:
            close()  # <pre> is a block tag too, so it ends the block before it is skipped below
        if token.kind in ("start", "empty") and _is_hidden(token):
            words = show_card(token) if _is_card(token) else ""
            if token.kind == "start":
                hidden_name, hidden_depth = token.name, 1
                card_words, card_start = words, token.start
            elif words:
                put_card_words(words, token.start, token.end)
        elif token.kind in ("start", "empty") and token.name == "br":
            raw.append(" ")  # one synthetic space that stands for the whole tag
            raw_starts.append(token.start)
            raw_ends.append(token.end)
        elif token.kind == "text":
            for offset, ch in enumerate(body[token.start:token.end], token.start):
                raw.append(ch)
                raw_starts.append(offset)
                raw_ends.append(offset + 1)
    close()
    return result
