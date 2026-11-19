"""Text normalization shared by the storage and markdown readers."""
from __future__ import annotations

import re
from html.entities import html5
from typing import Dict, List, Optional, Tuple

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


# A complete entity: &name; or &#123; or &#x1F; (digit counts capped so int() stays cheap).
_ENTITY = re.compile(r"&(?:#([0-9]{1,8})|#[xX]([0-9a-fA-F]{1,8})|([A-Za-z][A-Za-z0-9]{0,31}));")

# NBSP, U+2000-U+200A, narrow NBSP, medium math space, ideographic space -> plain space.
_PLAIN_SPACES = frozenset(
    ["\u00a0", "\u202f", "\u205f", "\u3000"] + [chr(cp) for cp in range(0x2000, 0x200B)]
)
# Zero-width space, non-joiner, joiner, word joiner, byte-order mark -> dropped.
_ZERO_WIDTH = frozenset(["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])


def _decode_entity(s: str, i: int) -> Optional[Tuple[str, int]]:
    """If a complete entity starts at s[i] (which is "&"), return (decoded text, end index)."""
    m = _ENTITY.match(s, i)
    if not m:
        return None
    dec, hexa, name = m.groups()
    if name is not None:
        decoded = html5.get(name + ";")
        return (decoded, m.end()) if decoded is not None else None
    cp = int(dec) if dec is not None else int(hexa, 16)
    if cp == 0 or cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
        return None
    return chr(cp), m.end()


def normalize(s: str) -> str:
    return normalize_map(s)[0]


def normalize_map(s: str) -> Tuple[str, List[int], List[int]]:
    """Entities decoded, curly quotes straight, NBSP/thin spaces plain, zero-width chars dropped,
    whitespace runs -> one space, leading/trailing space dropped; starts[i], ends[i] = raw span of char i."""
    out: List[str] = []
    starts: List[int] = []
    ends: List[int] = []
    pending: Optional[List[int]] = None  # [start, end) of the whitespace run being collapsed
    i = 0
    n = len(s)
    while i < n:
        start = i
        piece = s[i]
        i += 1
        if piece == "&":
            decoded = _decode_entity(s, start)
            if decoded is not None:
                piece, i = decoded
        for ch in piece:  # an entity can decode to more than one char; they share its raw span
            ch = QUOTES.get(ch, ch)
            if ch in _ZERO_WIDTH:
                continue
            if ch in _PLAIN_SPACES or ch.isspace():
                if pending is None:
                    pending = [start, i]
                else:
                    pending[1] = i
                continue
            if pending is not None:
                if out:  # a leading run is dropped
                    out.append(" ")
                    starts.append(pending[0])
                    ends.append(pending[1])
                pending = None
            out.append(ch)
            starts.append(start)
            ends.append(i)
    # a trailing run is dropped
    return "".join(out), starts, ends
