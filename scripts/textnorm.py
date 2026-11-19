"""Text normalization shared by the storage and markdown readers."""
from __future__ import annotations

from typing import Dict, List, Tuple

# Curly single quotes -> ', curly double quotes -> ".
QUOTES: Dict[str, str] = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
}


def normalize(s: str) -> str:
    raise NotImplementedError


def normalize_map(s: str) -> Tuple[str, List[int], List[int]]:
    """Entities decoded, curly quotes straight, NBSP/thin spaces plain, zero-width chars dropped,
    whitespace runs -> one space, leading/trailing space dropped; starts[i], ends[i] = raw span of char i."""
    raise NotImplementedError
