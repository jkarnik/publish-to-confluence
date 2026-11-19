"""Finds a comment's anchor text in the visible blocks of a document."""
from __future__ import annotations

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
    raise NotImplementedError


def find(anchor: Anchor, texts: List[str], allow_move: bool) -> Result:
    raise NotImplementedError
