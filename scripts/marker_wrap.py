"""Write side of inline-comment markers in a storage body."""
from __future__ import annotations

from visible_text import Block


def wrap(body: str, block: Block, start: int, end: int, ref: str) -> str:
    """Wrap visible chars [start, end) of block in markers with ac:ref=ref, in the form P1 recorded."""
    raise NotImplementedError
