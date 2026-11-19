"""Make blocking macros plain.

Confluence refuses a markdown text update while a page holds almost any macro (probes P3, P7, P8);
only `code` and `status` are accepted. Before a republish, `prepare` calls make_plain to turn every
other macro into plain content.
"""
from __future__ import annotations

import html
from typing import Dict, Iterator, List, Optional, Tuple

import cards
import storage

_MACRO = "ac:structured-macro"
_RICH = "ac:rich-text-body"
_PLAIN = "ac:plain-text-body"
_PARAMETER = "ac:parameter"
_KEEP = frozenset({"code", "status"})
# Elements whose children are blocks, so a paragraph can stand in one.
_CONTAINERS = frozenset({"td", "th", "li", "blockquote", "div", "ac:layout-cell", _RICH})
# Siblings that don't make a macro inline. Another macro counts as neutral: it is replaced too.
_BLOCKS = frozenset({"p", "ul", "ol", "table", "div", "blockquote", "pre", "hr", "h1", "h2", "h3",
                     "h4", "h5", "h6", _MACRO})


def _text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _matching_end(tokens: List[storage.Token], index: int, limit: int) -> int:
    """Index of the end tag that closes the start tag at `index`, or `limit` when none does."""
    name = tokens[index].name
    depth = 0
    for i in range(index, limit):
        token = tokens[i]
        if token.name != name:
            continue
        if token.kind == "start":
            depth += 1
        elif token.kind == "end":
            depth -= 1
            if depth == 0:
                return i
    return limit


def _children(tokens: List[storage.Token], first: int, last: int) -> Iterator[Tuple[int, int]]:
    """(start, end) token indexes of what sits directly between tokens `first` and `last`: an
    element as its start and end, any other token as (i, i)."""
    i = first + 1
    while i < last:
        end = _matching_end(tokens, i, last) if tokens[i].kind == "start" else i
        yield i, end
        i = end + 1


def _text_of(body: str, tokens: List[storage.Token], first: int, last: int) -> str:
    """The text between tokens first and last (CDATA unwrapped, entities decoded)."""
    parts = []
    for token in tokens[first + 1:last]:
        raw = body[token.start:token.end]
        if token.kind == "cdata":
            parts.append(raw[len("<![CDATA["):-len("]]>")])
        elif token.kind == "text":
            parts.append(html.unescape(raw))
    return "".join(parts)


class _Macro:
    """The parts of one structured macro that decide how it is made plain."""

    def __init__(self, body: str, tokens: List[storage.Token], first: int, last: int) -> None:
        self.first, self.last = first, last
        self.name = tokens[first].attrs.get("ac:name", "").lower()
        self.params: Dict[str, str] = {}
        self.rich: Optional[str] = None  # inner XHTML of the rich text body
        self.plain: Optional[str] = None  # text of the plain text body
        if last <= first:
            return
        for start, end in _children(tokens, first, last):
            token = tokens[start]
            if token.kind == "empty" and token.name == _RICH:
                self.rich = ""
            elif token.kind != "start":
                continue
            elif token.name == _PARAMETER:
                key = token.attrs.get("ac:name", "").lower()
                self.params.setdefault(key, _text_of(body, tokens, start, end).strip())
            elif token.name == _RICH and self.rich is None:
                self.rich = body[token.end:tokens[end].start] if end < last else ""
            elif token.name == _PLAIN and self.plain is None:
                self.plain = _text_of(body, tokens, start, end)


def _between_blocks(body: str, tokens: List[storage.Token], macro: _Macro) -> bool:
    """True when nothing but whitespace and block elements sits beside the macro, so a paragraph is
    valid where it stands."""
    parents = storage.open_elements(tokens, macro.first)
    if parents:
        parent = parents[-1]
        if tokens[parent].name not in _CONTAINERS:
            return False
        lo, hi = parent, _matching_end(tokens, parent, len(tokens))
    else:
        lo, hi = -1, len(tokens)
    for start, end in _children(tokens, lo, hi):
        if start >= macro.first and end <= max(macro.last, macro.first):
            continue
        token = tokens[start]
        if token.kind == "cdata":
            return False
        if token.kind == "text":
            if html.unescape(body[tokens[start].start:tokens[start].end]).strip():
                return False
        elif token.kind in ("start", "empty") and token.name not in _BLOCKS:
            return False
    return True


def _plain_form(body: str, tokens: List[storage.Token], macro: _Macro) -> Tuple[str, str]:
    """(kind, replacement) for a macro that isn't a Jira issue, `code` or `status`."""
    if macro.name == "jira" and macro.params.get("jqlquery") and not macro.params.get("key"):
        line = "Jira list: " + _text(macro.params["jqlquery"])
        return "jiraList", "<p>%s</p>" % line if _between_blocks(body, tokens, macro) else line
    if macro.rich is not None:
        title = macro.params.get("title", "") if macro.name == "expand" else ""
        heading = "<p><strong>%s</strong></p>" % _text(title) if title else ""
        return macro.name, heading + macro.rich
    if macro.plain is not None:
        return macro.name, "<p>%s</p>" % _text(macro.plain)
    return macro.name, ""


def _one_pass(body: str) -> Tuple[str, Dict[str, int]]:
    """Make every outermost blocking macro plain; macros inside an unwrapped body wait for the next pass."""
    tokens = storage.tokenize(body)
    edits: List[Tuple[int, int, str]] = []
    counts: Dict[str, int] = {}
    covered = -1  # token index; whatever lies inside a macro already seen is left for later
    for first, last in storage.element_ranges(tokens, _MACRO):
        if first <= covered:
            continue
        covered = last
        macro = _Macro(body, tokens, first, last)
        if macro.name in _KEEP or (macro.name == "jira" and macro.params.get("key")):
            continue  # a Jira issue still here has no link in the view; it stays a macro
        kind, replacement = _plain_form(body, tokens, macro)
        edits.append((tokens[first].start, tokens[last].end, replacement))
        counts[kind] = counts.get(kind, 0) + 1
    return storage.apply_edits(body, edits), counts


def make_plain(body: str, view_html: str) -> Tuple[str, Dict[str, int], List[str]]:
    """Return (body, counts by kind, unresolved Jira keys).

    Jira issue macros become links (cards.jira_macros_to_links). Every other macro except `code` and
    `status` is replaced: a Jira list by its query as text, a macro with a rich text body by that
    body (an expand's title first), one with only a plain text body by a paragraph of its text, and
    one with neither by nothing. Comment markers inside an unwrapped body are carried over as they
    were. Counts have `jira` (always), `jiraList`, and the macro name of every other kind made plain.
    """
    body, jira, unresolved = cards.jira_macros_to_links(body, view_html)
    counts: Dict[str, int] = {"jira": jira}
    while True:
        body, made = _one_pass(body)
        if not made:
            break
        for kind, n in made.items():
            counts[kind] = counts.get(kind, 0) + n
    return body, counts, unresolved
