"""Write side of inline-comment markers in a storage body."""
from __future__ import annotations

import html
from typing import List, Set, Tuple

from storage import Token, apply_edits, tokenize
from visible_text import Block, _is_hidden


def _visible_text_tokens(tokens: List[Token]) -> Set[int]:
    """Indexes of text tokens a reader sees (not inside a macro body, code, image and so on)."""
    visible: Set[int] = set()
    hidden_name = ""
    hidden_depth = 0
    for i, token in enumerate(tokens):
        if hidden_name:
            if token.name == hidden_name and token.kind == "start":
                hidden_depth += 1
            elif token.name == hidden_name and token.kind == "end":
                hidden_depth -= 1
                if hidden_depth == 0:
                    hidden_name = ""
        elif token.kind in ("start", "empty") and _is_hidden(token):
            if token.kind == "start":
                hidden_name, hidden_depth = token.name, 1
        elif token.kind == "text":
            visible.add(i)
    return visible


def wrap(body: str, block: Block, start: int, end: int, ref: str) -> str:
    """Wrap visible chars [start, end) of block in markers with ac:ref=ref, in the form P1 recorded:
    one marker per text piece, each inside its innermost element, all with the same ref."""
    while start < end and block.text[start] == " ":  # a collapsed space can map over tag markup
        start += 1
    while end > start and block.text[end - 1] == " ":
        end -= 1
    if start >= end:
        return body
    low = block.starts[start]  # an entity gives each of its chars the whole entity's span,
    high = block.ends[end - 1]  # so these never fall inside one

    tokens = tokenize(body)
    visible = _visible_text_tokens(tokens)
    pieces: List[Tuple[int, int]] = []
    for i, token in enumerate(tokens):
        if token.end <= low:
            continue
        if token.start >= high:
            break
        if i in visible:
            pieces.append((max(token.start, low), min(token.end, high)))
    while pieces and not body[pieces[0][0]:pieces[0][1]].strip():
        pieces.pop(0)
    while pieces and not body[pieces[-1][0]:pieces[-1][1]].strip():
        pieces.pop()
    if not pieces:
        return body

    opening = '<ac:inline-comment-marker ac:ref="%s">' % html.escape(ref, quote=True)
    closing = "</ac:inline-comment-marker>"
    return apply_edits(body, [(a, b, opening + body[a:b] + closing) for a, b in pieces])
