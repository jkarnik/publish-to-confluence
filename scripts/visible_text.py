"""Visible text of a storage body, split into blocks with offsets back into the body."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List

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


def _is_hidden(token: Token) -> bool:
    if token.name in HIDDEN_TAGS or token.name.startswith("ri:"):
        return True
    return token.name == "a" and "data-card-appearance" in token.attrs  # a smart-link card


def blocks(body: str) -> List[Block]:
    """Skipped (not visible): ac:structured-macro (all), ac:plain-text-body, ac:parameter, pre, ac:image,
    ri:*, ac:task-id, ac:task-status, time, and <a data-card-appearance=...> cards. Markers are transparent."""
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

    for token in tokenize(body):
        if hidden_name:  # inside a hidden element: only look for its matching end
            if token.name == hidden_name and token.kind == "start":
                hidden_depth += 1
            elif token.name == hidden_name and token.kind == "end":
                hidden_depth -= 1
                if hidden_depth == 0:
                    hidden_name = ""
            continue
        if token.kind in ("start", "end", "empty") and token.name in BLOCK_TAGS:
            close()  # <pre> is a block tag too, so it ends the block before it is skipped below
        if token.kind in ("start", "empty") and _is_hidden(token):
            if token.kind == "start":
                hidden_name, hidden_depth = token.name, 1
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
