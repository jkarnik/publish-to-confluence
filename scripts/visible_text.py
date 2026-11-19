"""Visible text of a storage body, split into blocks with offsets back into the body."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List


@dataclass
class Block:
    text: str  # normalized visible text of one block
    starts: List[int] = field(default_factory=list)  # storage offset where char i starts ([] for markdown blocks)
    ends: List[int] = field(default_factory=list)  # storage offset where char i ends


BLOCK_TAGS: FrozenSet[str] = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "pre",
    "div", "tr", "table", "ul", "ol", "caption", "ac:task-body", "ac:layout-cell",
})


def blocks(body: str) -> List[Block]:
    """Skipped (not visible): ac:structured-macro (all), ac:plain-text-body, ac:parameter, pre, ac:image,
    ri:*, ac:task-id, ac:task-status, time, and <a data-card-appearance=...> cards. Markers are transparent."""
    raise NotImplementedError
