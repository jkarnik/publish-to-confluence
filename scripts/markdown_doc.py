"""Reads a markdown document: title, local images, web links and visible text blocks."""
from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from textnorm import normalize
from visible_text import Block


@dataclass(frozen=True)
class ImageRef:
    alt: str
    src: str
    path: str
    name: str  # attachment filename (basename of src)


@dataclass(frozen=True)
class LinkRef:
    url: str
    text: str
    tag: Optional[str]  # None | "block" | "embed" | "embed <layout>" | "plain"


# ---------------------------------------------------------------- lines and fences

_LINE = re.compile(r"[^\n]*\n|[^\n]+")
_QUOTE_PREFIX = re.compile(r"^(?: {0,3}>[ ]?)+")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_TITLE = re.compile(r"^ {0,3}#[ \t]+(\S.*?)[ \t]*$")
_CLOSING_HASHES = re.compile(r"[ \t]+#+$")


def _lines(md: str) -> List[str]:
    """Lines with their line endings kept, so "".join(_lines(md)) == md."""
    return _LINE.findall(md)


def _unquote(line: str) -> str:
    """The line without its leading "> " quote markers."""
    return _QUOTE_PREFIX.sub("", line)


def _fence_open(line: str) -> Optional[Tuple[str, int]]:
    """(fence character, run length) if the line opens a code fence."""
    m = _FENCE.match(_unquote(line.rstrip("\r\n")))
    if not m:
        return None
    run, rest = m.groups()
    if run[0] == "`" and "`" in rest:
        return None  # ```code``` on one line is an inline code span
    return run[0], len(run)


def _fence_closes(line: str, char: str, size: int) -> bool:
    stripped = _unquote(line.rstrip("\r\n")).strip()
    return len(stripped) >= size and stripped.strip(char) == "" and stripped.startswith(char * size)


def _code_flags(lines: List[str]) -> List[bool]:
    """True for each line that is a fence line or sits inside a fence (an unclosed one runs to the end)."""
    flags: List[bool] = []
    fence: Optional[Tuple[str, int]] = None
    for line in lines:
        if fence is None:
            fence = _fence_open(line)
            flags.append(fence is not None)
        else:
            flags.append(True)
            if _fence_closes(line, fence[0], fence[1]):
                fence = None
    return flags


_CODE_SPAN = re.compile(r"(?<![\\`])(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.DOTALL)


def _blank_out(text: str) -> str:
    """Same length, every character except line breaks replaced by a space."""
    return re.sub(r"[^\n]", " ", text)


def _mask_code(md: str) -> str:
    """md with fenced code and inline code spans blanked out (same offsets, same line breaks)."""
    lines = _lines(md)
    kept = [_blank_out(line) if code else line for line, code in zip(lines, _code_flags(lines))]
    return _CODE_SPAN.sub(lambda m: _blank_out(m.group()), "".join(kept))


# ---------------------------------------------------------------- title

def split_title(md: str) -> Tuple[Optional[str], str]:
    """First "# " line outside code fences."""
    lines = _lines(md)
    for i, (line, code) in enumerate(zip(lines, _code_flags(lines))):
        if code:
            continue
        m = _TITLE.match(line.rstrip("\r\n"))
        if m:
            title = _CLOSING_HASHES.sub("", m.group(1)).strip()
            if title:
                return title, "".join(lines[:i] + lines[i + 1:])
    return None, md


# ---------------------------------------------------------------- links and images

_ESCAPABLE = r"""!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~"""
_UNESCAPE = re.compile(r"\\([" + _ESCAPABLE + r"])")
_WEB = re.compile(r"https?://", re.IGNORECASE)
_SKIP_SCHEMES = re.compile(r"(?i)(https?|data):")
_AUTOLINK = re.compile(r"<(https?://[^\s<>]+)>", re.IGNORECASE)
_BARE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_TAG_TITLE = re.compile(r"^(?:plain|block|embed(?: [\w-]+)?)$")
_TRAILING_PUNCT = ".,;:!?*_~\"'’”"


def _match_bracket(s: str, i: int) -> int:
    """Index of the "]" matching the "[" at s[i], or -1."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _parse_dest(s: str, i: int) -> Optional[Tuple[str, Optional[str], int]]:
    """Parse `url "title")` starting at s[i] (just after the "("). Returns (url, title, index after ")")."""
    n = len(s)
    while i < n and s[i] in " \t\n":
        i += 1
    if i < n and s[i] == "<":
        j = s.find(">", i + 1)
        if j < 0 or "\n" in s[i + 1:j]:
            return None
        url, i = s[i + 1:j], j + 1
    else:
        depth = 0
        j = i
        while j < n:
            c = s[j]
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c in " \t\n":
                break
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        if depth != 0:
            return None
        url, i = s[i:j], j
    k = i
    while k < n and s[k] in " \t\n":
        k += 1
    title = None
    if k > i and k < n and s[k] in "\"'":
        quote = s[k]
        j = k + 1
        while j < n and s[j] != quote:
            j += 2 if s[j] == "\\" else 1
        if j >= n:
            return None
        title = s[k + 1:j]
        k = j + 1
        while k < n and s[k] in " \t\n":
            k += 1
    if k < n and s[k] == ")":
        return _UNESCAPE.sub(r"\1", url), title, k + 1
    return None


def _tag_of(title: Optional[str]) -> Optional[str]:
    if title is None:
        return None
    tag = " ".join(title.lower().split())
    return tag if _TAG_TITLE.match(tag) else None


def _escaped(s: str, i: int) -> bool:
    """True when s[i] is preceded by an odd number of backslashes."""
    count = 0
    while i - 1 - count >= 0 and s[i - 1 - count] == "\\":
        count += 1
    return count % 2 == 1


def _trim_url(candidate: str) -> str:
    """Cut a bare URL where prose takes over: an unbalanced ")" or "]", then trailing punctuation."""
    depth = {")": 0, "]": 0}
    for j, c in enumerate(candidate):
        if c in "([":
            depth[")" if c == "(" else "]"] += 1
        elif c in depth:
            if depth[c] == 0:
                candidate = candidate[:j]
                break
            depth[c] -= 1
    while candidate and candidate[-1] in _TRAILING_PUNCT:
        candidate = candidate[:-1]
    return candidate


def _bare_url_at(s: str, i: int) -> str:
    m = _BARE.match(s, i)
    if not m:
        return ""
    url = _trim_url(m.group())
    scheme = _WEB.match(url)
    return url if scheme and len(url) > scheme.end() else ""


def _images(s: str, original: str) -> Iterator[Tuple[str, str]]:
    """(alt, src) of every ![alt](src) in s (md with code blanked), links around them or not.
    The alt text is read from original, which has the same offsets."""
    pos = 0
    while True:
        i = s.find("![", pos)
        if i < 0:
            return
        pos = i + 2
        if _escaped(s, i):
            continue
        close = _match_bracket(s, i + 1)
        if close < 0 or close + 1 >= len(s) or s[close + 1] != "(":
            continue
        parsed = _parse_dest(s, close + 2)
        if parsed is None:
            continue
        yield original[i + 2:close], parsed[0]
        pos = parsed[2]


def local_images(md: str, md_dir: str) -> List[ImageRef]:
    """Unique by src, not http(s)/data:."""
    out: List[ImageRef] = []
    seen = set()
    for alt, src in _images(_mask_code(md), md):
        if not src or src in seen or _SKIP_SCHEMES.match(src):
            continue
        seen.add(src)
        rel = urllib.parse.unquote(src)
        out.append(ImageRef(alt, src, os.path.normpath(os.path.join(md_dir, rel)), os.path.basename(rel)))
    return out


_LINK_START = re.compile(r"!?\[|<https?://|(?<![A-Za-z0-9])https?://", re.IGNORECASE)


def web_links(md: str) -> List[LinkRef]:
    """Inline links, <autolinks>, bare URLs; document order; not in code, not images,
    not links wrapping an image."""
    s = _mask_code(md)  # same offsets as md, so link text can be read from md
    out: List[LinkRef] = []
    pos = 0
    while True:
        m = _LINK_START.search(s, pos)
        if not m:
            return out
        i, token = m.start(), m.group().lower()
        pos = m.end()
        if token in ("[", "!["):
            bracket = i + len(token) - 1
            if _escaped(s, bracket):
                continue
            close = _match_bracket(s, bracket)
            if close < 0 or close + 1 >= len(s) or s[close + 1] != "(":
                continue
            parsed = _parse_dest(s, close + 2)
            if parsed is None:
                continue
            url, title, end = parsed
            pos = end
            inner = s[bracket + 1:close]
            if token == "![" or "![" in inner or not _WEB.match(url):
                continue
            out.append(LinkRef(url, normalize(_inline(md[bracket + 1:close])), _tag_of(title)))
        elif token == "<https://" or token == "<http://":
            pos = i + 1  # if this is not an autolink, a bare URL may still start right after "<"
            auto = _AUTOLINK.match(s, i)
            if auto:
                out.append(LinkRef(auto.group(1), auto.group(1), None))
                pos = auto.end()
        else:
            url = _bare_url_at(s, i)
            if url:
                out.append(LinkRef(url, url, None))
                pos = i + len(url)


# ---------------------------------------------------------------- visible text

_PUA = 0xE000  # escaped characters are parked at U+E000 + their code while other syntax is stripped
_HOLD = re.compile(r"\x00(\d+)\x00")
_ESCAPE_PARKED = re.compile("[-]")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_ANGLE_AUTOLINK = re.compile(r"<((?:https?|mailto):[^\s<>]+)>", re.IGNORECASE)
_REF_LINK = re.compile(r"\[([^\[\]]+)\]\[[^\[\]]*\]")
_EMPHASIS = [
    re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"),
    re.compile(r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])"),
    re.compile(r"\*(?=\S)(.+?)(?<=\S)\*"),
    re.compile(r"(?<![A-Za-z0-9_])_(?=\S)(.+?)(?<=\S)_(?![A-Za-z0-9_])"),
    re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"),
]


_BRACKET_START = re.compile(r"!?\[")
_BARE_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])https?://[^\s<>\"]+", re.IGNORECASE)


def _replace_links(s: str) -> str:
    """Images dropped; [text](url) becomes text."""
    out: List[str] = []
    pos = 0
    while True:
        m = _BRACKET_START.search(s, pos)
        if not m:
            out.append(s[pos:])
            return "".join(out)
        bracket = m.end() - 1
        close = _match_bracket(s, bracket)
        parsed = None
        if close >= 0 and close + 1 < len(s) and s[close + 1] == "(":
            parsed = _parse_dest(s, close + 2)
        if parsed is None:
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        out.append(s[pos:m.start()])
        if not m.group().startswith("!"):
            out.append(_replace_links(s[bracket + 1:close]))
        pos = parsed[2]


def _inline(raw: str) -> str:
    """Markdown syntax stripped from one block of text; not yet normalized."""
    held: List[str] = []

    def hold(text: str) -> str:
        held.append(text)
        return "\x00%d\x00" % (len(held) - 1)

    s = raw.replace("\x00", "")
    s = _CODE_SPAN.sub(lambda m: hold(m.group(2)), s)
    s = _UNESCAPE.sub(lambda m: chr(_PUA + ord(m.group(1))), s)
    s = _HTML_COMMENT.sub("", s)
    s = _ANGLE_AUTOLINK.sub(lambda m: m.group(1), s)
    s = _HTML_BREAK.sub(" ", s)
    s = _HTML_TAG.sub("", s)
    s = _replace_links(s)
    s = _REF_LINK.sub(r"\1", s)
    # Park bare URLs so a "_" or "*" inside one is not read as emphasis.
    pieces: List[str] = []
    pos = 0
    for m in _BARE_IN_TEXT.finditer(s):
        if m.start() < pos:
            continue
        url = _bare_url_at(s, m.start())
        if url:
            pieces.append(s[pos:m.start()])
            pieces.append(hold(url))
            pos = m.start() + len(url)
    pieces.append(s[pos:])
    s = "".join(pieces)
    for pattern in _EMPHASIS:
        s = pattern.sub(r"\1", s)
    s = _ESCAPE_PARKED.sub(lambda m: chr(ord(m.group()) - _PUA), s)
    return _HOLD.sub(lambda m: held[int(m.group(1))], s)


_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}=+[ \t]*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])(?:[ \t]+(.*))?$")
_TASK = re.compile(r"^\[[ xX]\][ \t]+")
_REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*\S")  # [label]: url, but not a [^1]: footnote
_HARD_BREAK = re.compile(r"(?<!\\)\\$")


def _is_separator(line: str) -> bool:
    """A table separator row such as |---|:---:|."""
    return "|" in line and "-" in line and not line.strip(" \t|:-")


def _cells(line: str) -> List[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return re.split(r"(?<!\\)\|", row)


def visible_blocks(md: str) -> List[Block]:
    """Body without title; markdown syntax stripped; normalized."""
    lines = _lines(split_title(md)[1])
    flags = _code_flags(lines)
    blocks: List[Block] = []
    current: List[str] = []  # raw pieces of the paragraph or list item being collected

    def emit(raw: str) -> None:
        text = normalize(_inline(raw))
        if text:
            blocks.append(Block(text))

    def flush() -> None:
        if current:
            emit(" ".join(current))
            del current[:]

    in_comment = False
    in_table = False
    for index, line in enumerate(lines):
        if flags[index]:
            flush()
            in_table = False
            continue
        raw_text = _unquote(line.rstrip("\r\n"))
        text = raw_text
        # HTML comments, which can span lines.
        if in_comment:
            end = text.find("-->")
            if end < 0:
                continue
            text, in_comment = text[end + 3:], False
        text = _HTML_COMMENT.sub("", text)
        start = text.find("<!--")
        if start >= 0:
            text, in_comment = text[:start], True
        if not text.strip():
            if not raw_text.strip():  # a real blank line, not one that only held a comment
                flush()
                in_table = False
            continue

        if _RULE.match(text) or _SETEXT.match(text) or _REF_DEF.match(text):
            flush()
            in_table = False
            continue
        heading = _HEADING.match(text)
        if heading:
            flush()
            in_table = False
            emit(_CLOSING_HASHES.sub("", heading.group(1) or ""))
            continue

        if not in_table and "|" in text and not _is_separator(text) and index + 1 < len(lines):
            in_table = (not flags[index + 1]) and _is_separator(_unquote(lines[index + 1].rstrip("\r\n")))
            if in_table:
                flush()
        if in_table and "|" in text:
            if not _is_separator(text):
                for cell in _cells(text):
                    emit(cell)
            continue
        in_table = False
        if _is_separator(text):
            flush()
            continue

        item = _LIST_ITEM.match(text)
        if item:
            flush()
            current.append(_TASK.sub("", item.group(1) or ""))
            continue
        current.append(_HARD_BREAK.sub("", text.rstrip()))
    flush()
    return blocks
