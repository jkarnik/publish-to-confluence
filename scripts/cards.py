"""Link cards: turn web links in a storage body into Confluence smart-link cards, and Jira issue
macros into plain links.

Confluence accepts cards on a text update but refuses the Jira issue macro (probe P3), so cards are
never unmade; `prepare` calls jira_macros_to_links instead.
"""
from __future__ import annotations

import html
import re
from collections import deque
from typing import TYPE_CHECKING, Deque, Dict, List, Optional, Tuple

import storage

if TYPE_CHECKING:
    from markdown_doc import LinkRef

CARD_ATTRS = ("data-card-appearance", "data-layout", "data-width")

# Probe P4: Confluence keeps <ac:inline-comment-marker><a ... data-card-appearance>...</a>
# </ac:inline-comment-marker> as written, so a comment on a link's words survives as a card.
CARD_WRAP_OK = True

_WEB = re.compile(r"https?://", re.IGNORECASE)
# What the converter leaves in `title` for a tag in the markdown file (probe P5); same words as the tags.
_TAG_WORD = re.compile(r"(?:plain|block|embed(?: [\w-]+)?)")
_MARKER = "ac:inline-comment-marker"
_MARKER_END = "</" + _MARKER + ">"
_CODE_ELEMENTS = frozenset({"code", "pre", "ac:plain-text-body"})
_CODE_MACROS = frozenset({"code", "noformat"})
_IMAGE_ELEMENTS = frozenset({"img", "ac:image"})


def _same_url(url: str) -> str:
    return url.strip().rstrip("/")


def _text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(value: str) -> str:
    return _text(value).replace('"', "&quot;")


def _is_tag_word(title: Optional[str]) -> bool:
    return title is not None and _TAG_WORD.fullmatch(" ".join(title.lower().split())) is not None


def _in_code(tokens: List[storage.Token], index: int) -> bool:
    for i in storage.open_elements(tokens, index):
        token = tokens[i]
        if token.name in _CODE_ELEMENTS:
            return True
        if token.name == "ac:structured-macro" and token.attrs.get("ac:name", "").lower() in _CODE_MACROS:
            return True
    return False


def _marker_tags(body: str, tokens: List[storage.Token], first: int, last: int) -> Optional[List[str]]:
    """Start tags of the comment markers inside tokens (first, last), one per distinct ref, outermost
    first. None when a marker opens inside and closes outside (or the reverse)."""
    depth = 0
    refs: List[str] = []
    tags: List[str] = []
    for token in tokens[first + 1:last]:
        if token.name != _MARKER:
            continue
        if token.kind == "start":
            depth += 1
            ref = token.attrs.get("ac:ref")
            if ref is not None and ref not in refs:
                refs.append(ref)
                tags.append(body[token.start:token.end])
        elif token.kind == "end":
            depth -= 1
            if depth < 0:
                return None
    return tags if depth == 0 else None


def make_cards(body: str, links: List[LinkRef]) -> Tuple[str, Dict[str, int]]:
    """Counts {"made", "tagged", "plain", "keptPlainForComment"}.

    "made" is every card written; "tagged" is the part of those that are block or embed.
    """
    counts = {"made": 0, "tagged": 0, "plain": 0, "keptPlainForComment": 0}
    pending: Dict[str, Deque[LinkRef]] = {}
    for link in links:
        pending.setdefault(_same_url(link.url), deque()).append(link)

    tokens = storage.tokenize(body)
    edits: List[Tuple[int, int, str]] = []
    done_until = -1  # token index; a link nested inside one already handled is left alone
    for first, last in storage.element_ranges(tokens, "a"):
        if last <= first or first <= done_until:
            continue
        start = tokens[first]
        href = start.attrs.get("href", "").strip()
        if not _WEB.match(href) or CARD_ATTRS[0] in start.attrs:
            continue
        if any(token.name in _IMAGE_ELEMENTS for token in tokens[first + 1:last]):
            continue
        if _in_code(tokens, first):
            continue
        markers = _marker_tags(body, tokens, first, last)
        if markers is None:
            continue
        done_until = last

        queue = pending.get(_same_url(href))
        tag = queue.popleft().tag if queue else None
        raw = body[start.start:start.end]
        opening = storage.set_attr(raw, "title", None) if _is_tag_word(start.attrs.get("title")) else raw

        if tag == "plain" or (markers and not CARD_WRAP_OK):
            counts["plain" if tag == "plain" else "keptPlainForComment"] += 1
            if opening != raw:
                edits.append((start.start, start.end, opening))
            continue

        words = (tag or "inline").split()
        opening = storage.set_attr(opening, CARD_ATTRS[0], words[0])
        if len(words) > 1:
            opening = storage.set_attr(opening, CARD_ATTRS[1], words[1])
        made = opening + _text(href) + "</a>"
        for marker in reversed(markers):
            made = marker + made + _MARKER_END
        edits.append((start.start, tokens[last].end, made))
        counts["made"] += 1
        if tag:
            counts["tagged"] += 1
    return storage.apply_edits(body, edits), counts


def _macro_key(body: str, tokens: List[storage.Token], first: int, last: int) -> str:
    """The text of the macro's `key` parameter, or "" when it has none."""
    for i in range(first + 1, last):
        token = tokens[i]
        if (token.kind == "start" and token.name == "ac:parameter"
                and token.attrs.get("ac:name", "").lower() == "key"):
            parts = []
            for inner in tokens[i + 1:last]:
                if inner.kind == "end" and inner.name == "ac:parameter":
                    break
                if inner.kind == "text":
                    parts.append(body[inner.start:inner.end])
            return html.unescape("".join(parts)).strip()
    return ""


def _issue_url(key: str, view_html: str) -> Optional[str]:
    found = re.search(r"""href\s*=\s*(["'])(https://[^"'/\s]+/browse/%s)\1""" % re.escape(key), view_html)
    return html.unescape(found.group(2)) if found else None


def jira_macros_to_links(body: str, view_html: str) -> Tuple[str, int, List[str]]:
    """Return (body, made plain, unresolved keys).

    Each Jira issue macro that has a `key` parameter becomes a link to the issue, found in the page's
    rendered view. A key the view doesn't link stays a macro and is listed once. Jira list macros
    (no key) and every other macro are left as they are.
    """
    view_html = view_html or ""
    tokens = storage.tokenize(body)
    edits: List[Tuple[int, int, str]] = []
    unresolved: List[str] = []
    for first, last in storage.element_ranges(tokens, "ac:structured-macro"):
        if last <= first or tokens[first].attrs.get("ac:name", "").lower() != "jira":
            continue
        key = _macro_key(body, tokens, first, last)
        if not key:
            continue
        url = _issue_url(key, view_html)
        if url is None:
            if key not in unresolved:
                unresolved.append(key)
            continue
        edits.append((tokens[first].start, tokens[last].end, '<a href="%s">%s</a>' % (_attr(url), _text(url))))
    return storage.apply_edits(body, edits), len(edits), unresolved
