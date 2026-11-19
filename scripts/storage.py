"""Storage XHTML as tokens with offsets into the body string."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Token:
    kind: str  # "start" | "end" | "empty" | "text" | "cdata" | "comment" | "other"
    start: int  # body[start:end] is the token's raw text
    end: int
    name: str = ""  # lowercased tag name with prefix, e.g. "ac:inline-comment-marker"; "" for text
    attrs: Dict[str, str] = field(default_factory=dict)  # entity-decoded values


_NAME = r"[A-Za-z_][\w:.\-]*"
# One attribute with its leading whitespace: name, then optionally = and a
# double-quoted, single-quoted or bare value. A ">" inside quotes is part of the value.
_ATTR = r"""\s+[^\s=/>"'<]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>"']+))?"""

_TOKEN = re.compile(
    r"(?P<cdata><!\[CDATA\[.*?\]\]>)"
    r"|(?P<comment><!--.*?-->)"
    r"|(?P<other><!(?!--|\[CDATA\[)[^>]*>|<\?[^>]*>)"
    r"|(?P<end></(?P<endname>" + _NAME + r")\s*>)"
    r"|(?P<tag><(?P<name>" + _NAME + r")(?P<attrs>(?:" + _ATTR + r")*)\s*(?P<slash>/?)>)"
    r"|(?P<text>[^<]+|<)",  # a "<" that starts nothing above is plain text
    re.DOTALL,
)

_ATTR_PARTS = re.compile(
    r"""\s+(?P<name>[^\s=/>"'<]+)(?:(?P<eq>\s*=\s*)(?P<value>"[^"]*"|'[^']*'|[^\s>"']+))?"""
)

# A whole start or empty tag, for set_attr.
_WHOLE_TAG = re.compile(
    r"<(?P<name>" + _NAME + r")(?P<attrs>(?:" + _ATTR + r")*)\s*/?>",
    re.DOTALL,
)


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def _parse_attrs(text: str, start: int, end: int) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for m in _ATTR_PARTS.finditer(text, start, end):
        key = m.group("name").lower()
        if key not in attrs:  # first one wins, as in HTML
            raw = m.group("value")
            attrs[key] = "" if raw is None else html.unescape(_unquote(raw))
    return attrs


def tokenize(body: str) -> List[Token]:
    """Quoted ">" inside attributes stays in the tag."""
    tokens: List[Token] = []
    for m in _TOKEN.finditer(body):
        if m.group("cdata") is not None:
            tokens.append(Token("cdata", m.start(), m.end()))
        elif m.group("comment") is not None:
            tokens.append(Token("comment", m.start(), m.end()))
        elif m.group("other") is not None:
            tokens.append(Token("other", m.start(), m.end()))
        elif m.group("end") is not None:
            tokens.append(Token("end", m.start(), m.end(), m.group("endname").lower()))
        elif m.group("tag") is not None:
            attrs = _parse_attrs(body, m.start("attrs"), m.end("attrs"))
            kind = "empty" if m.group("slash") else "start"
            tokens.append(Token(kind, m.start(), m.end(), m.group("name").lower(), attrs))
        else:
            if tokens and tokens[-1].kind == "text" and tokens[-1].end == m.start():
                tokens[-1] = Token("text", tokens[-1].start, m.end())
            else:
                tokens.append(Token("text", m.start(), m.end()))
    return tokens


def element_ranges(tokens: List[Token], name: str) -> List[Tuple[int, int]]:
    """(start idx, end idx), nesting-aware; empty tag -> (i, i)."""
    name = name.lower()
    ranges: List[Tuple[int, int]] = []
    stack: List[int] = []
    for i, token in enumerate(tokens):
        if token.name != name:
            continue
        if token.kind == "start":
            stack.append(i)
        elif token.kind == "end":
            if stack:  # an end with nothing open is ignored
                ranges.append((stack.pop(), i))
        elif token.kind == "empty":
            ranges.append((i, i))
    ranges.sort()
    return ranges


def open_elements(tokens: List[Token], index: int) -> List[int]:
    """Start-token indices enclosing tokens[index], outermost first."""
    if not 0 <= index < len(tokens):
        raise IndexError("token index out of range: %r" % (index,))
    stack: List[int] = []
    for i in range(index):
        token = tokens[i]
        if token.kind == "start":
            stack.append(i)
        elif token.kind == "end":
            # Close the nearest open element of this name, and anything left open inside it.
            for depth in range(len(stack) - 1, -1, -1):
                if tokens[stack[depth]].name == token.name:
                    del stack[depth:]
                    break
    return stack


def _escape_attr(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def set_attr(tag: str, name: str, value: Optional[str]) -> str:
    """Return start-tag text with attr set (escaped) or removed (None)."""
    whole = _WHOLE_TAG.fullmatch(tag)
    if whole is None:
        raise ValueError("not a start or empty tag: %r" % (tag,))
    wanted = name.lower()
    found = None
    for m in _ATTR_PARTS.finditer(tag, whole.start("attrs"), whole.end("attrs")):
        if m.group("name").lower() == wanted:
            found = m
            break
    if value is None:
        if found is None:
            return tag
        return tag[:found.start()] + tag[found.end():]
    quoted = '"' + _escape_attr(value) + '"'
    if found is None:
        at = whole.end("attrs")  # after the last attribute, before any space and "/>" or ">"
        return tag[:at] + " " + name + "=" + quoted + tag[at:]
    if found.group("value") is None:
        at = found.end("name")
        return tag[:at] + "=" + quoted + tag[at:]
    first, last = found.span("value")
    return tag[:first] + quoted + tag[last:]


def apply_edits(body: str, edits: List[Tuple[int, int, str]]) -> str:
    """Replace [start, end) spans; ValueError on overlap."""
    ordered = sorted(edits, key=lambda edit: (edit[0], edit[1]))  # stable: same-point inserts keep order
    previous_end = 0
    for start, end, _ in ordered:
        if start < 0 or end < start or end > len(body):
            raise ValueError("edit span out of range: (%d, %d)" % (start, end))
        if start < previous_end:
            raise ValueError("edits overlap at %d" % start)
        previous_end = end
    out = body
    for start, end, text in reversed(ordered):
        out = out[:start] + text + out[end:]
    return out
