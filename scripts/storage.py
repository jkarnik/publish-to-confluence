"""Storage XHTML as tokens with offsets into the body string."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Token:
    kind: str  # "start" | "end" | "empty" | "text" | "cdata" | "comment" | "other"
    start: int  # body[start:end] is the token's raw text
    end: int
    name: str = ""  # lowercased tag name with prefix, e.g. "ac:inline-comment-marker"; "" for text
    attrs: Dict[str, str] = field(default_factory=dict)  # entity-decoded values


def tokenize(body: str) -> List[Token]:
    """Quoted ">" inside attributes stays in the tag."""
    raise NotImplementedError


def element_ranges(tokens: List[Token], name: str) -> List[Tuple[int, int]]:
    """(start idx, end idx), nesting-aware; empty tag -> (i, i)."""
    raise NotImplementedError


def open_elements(tokens: List[Token], index: int) -> List[int]:
    """Start-token indices enclosing tokens[index], outermost first."""
    raise NotImplementedError


def set_attr(tag: str, name: str, value: Optional[str]) -> str:
    """Return start-tag text with attr set (escaped) or removed (None)."""
    raise NotImplementedError


def apply_edits(body: str, edits: List[Tuple[int, int, str]]) -> str:
    """Replace [start, end) spans; ValueError on overlap."""
    raise NotImplementedError
