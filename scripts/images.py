"""Images: size, upload when changed, and embed or strip them in a storage body."""
from __future__ import annotations

import hashlib
import html
import math
import os
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from storage import apply_edits, element_ranges, tokenize

if TYPE_CHECKING:
    from markdown_doc import ImageRef
    from storage import Token

OUR_MARK = "sha256:"
MAX_WIDTH = 760

# An ac:image that holds one of these points at another page's attachment, not ours.
_OTHER_PAGE_REFS = {"ri:page", "ri:blog-post", "ri:content-entity"}


SVG_READ_BYTES = 65536
_UTF8_BOM = b"\xef\xbb\xbf"
_SVG_OPEN = re.compile(r"<svg(?=[\s/>])")
# The rest of a start tag: any character, but a quoted value can hold a ">".
_SVG_TAG = re.compile(r"""<svg(?=[\s/>])(?:[^>"']|"[^"]*"|'[^']*')*>""")
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_NUMBER = r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_LENGTH = re.compile(r"(%s)(px|in|cm|mm|Q|pt|pc)?" % _NUMBER)
_VIEWBOX_NUMBER = re.compile(r"[+-]?" + _NUMBER)
_PIXELS_PER_UNIT = {"": 1.0, "px": 1.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4,
                    "Q": 96 / 101.6, "pt": 96 / 72, "pc": 16.0}


def _svg_root_tag(text: str) -> Optional[str]:
    """The first <svg ...> start tag outside XML comments, or None."""
    pos = 0
    while True:
        found = _SVG_OPEN.search(text, pos)
        if not found:
            return None
        comment = text.find("<!--", pos, found.start())
        if comment < 0:
            tag = _SVG_TAG.match(text, found.start())
            return tag.group(0) if tag else None
        end = text.find("-->", comment + 4)
        if end < 0:
            return None
        pos = end + 3


def _svg_pixels(value: Optional[str]) -> Optional[float]:
    """A width or height as pixels, or None when it has no value or a unit we can't convert."""
    found = _LENGTH.fullmatch((value or "").strip())
    return float(found.group(1)) * _PIXELS_PER_UNIT[found.group(2) or ""] if found else None


def _svg_viewbox(value: Optional[str]) -> Optional[Tuple[float, float]]:
    """The width and height of a viewBox of four numbers, or None."""
    parts = re.split(r"[\s,]+", (value or "").strip())
    if len(parts) != 4 or not all(_VIEWBOX_NUMBER.fullmatch(part) for part in parts):
        return None
    width, height = float(parts[2]), float(parts[3])
    return (width, height) if width > 0 and height > 0 else None


def _svg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) in pixels from the start of an SVG file, or None."""
    tag = _svg_root_tag(data.decode("utf-8", "replace"))
    if tag is None:
        return None
    attrs: Dict[str, str] = {}
    for found in _ATTRIBUTE.finditer(tag):
        attrs.setdefault(found.group(1), found.group(2) if found.group(2) is not None else found.group(3))
    width, height = _svg_pixels(attrs.get("width")), _svg_pixels(attrs.get("height"))
    if width is None or height is None:
        box = _svg_viewbox(attrs.get("viewBox"))
        if box is None:
            return None
        if width is not None:
            height = width * box[1] / box[0]
        elif height is not None:
            width = height * box[0] / box[1]
        else:
            width, height = box
    if not (math.isfinite(width) and math.isfinite(height)):
        return None
    result = (round(width), round(height))
    return result if result[0] > 0 and result[1] > 0 else None


def image_size(path: str) -> Optional[Tuple[int, int]]:
    """Return (width, height) of the image file, or None if it can't be read.

    Reads PNG, GIF, JPEG and SVG. An SVG gets its size from the root tag's width and height
    (px or absolute units) or its viewBox; a size in %, em or ex alone gives None."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] == 0x01 or 0xD0 <= marker[1] <= 0xD8:
                        continue  # markers with no length
                    length = int.from_bytes(f.read(2), "big")
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        data = f.read(5)  # precision, height, width
                        if len(data) < 5:
                            return None
                        return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
                    if length < 2:  # a broken length would loop forever
                        return None
                    f.seek(length - 2, 1)
            f.seek(0)
            data = f.read(SVG_READ_BYTES)
            start = data[len(_UTF8_BOM):] if data.startswith(_UTF8_BOM) else data
            if path.lower().endswith(".svg") or start.lstrip().startswith((b"<?xml", b"<svg")):
                return _svg_size(data)
    except OSError:
        return None
    return None


def embed_markup(alt: str, name: str, size: Optional[Tuple[int, int]]) -> str:
    """Return the storage markup that embeds attachment `name`."""
    attrs = 'ac:align="center" ac:layout="center"'
    if size and size[0] > 0 and size[1] > 0:
        width, height = size
        attrs += (' ac:original-height="%d" ac:original-width="%d"'
                  ' ac:custom-width="true" ac:width="%d"' % (height, width, min(width, MAX_WIDTH)))
    return ('<ac:image %s ac:alt="%s"><ri:attachment ri:filename="%s" /></ac:image>'
            % (attrs, html.escape(alt, quote=True), html.escape(name, quote=True)))


def notes(client, page_id: str) -> Dict[str, str]:
    """Attachment title -> comment."""
    status, results = client.attachments(page_id)
    if status != 200 or not isinstance(results, list):
        return {}
    out: Dict[str, str] = {}
    for attachment in results:
        comment = ((attachment.get("extensions") or {}).get("comment")
                   or (attachment.get("metadata") or {}).get("comment") or "")
        out[attachment["title"]] = comment
    return out


def _image_elements(tokens: List[Token]) -> List[Tuple[int, int, Optional[str], str]]:
    """(first token, last token, kind, value) for each ac:image, in order.

    kind is "attachment" (value: the filename, on this page), "url" (value: the address)
    or None for anything else, including another page's attachment. Attributes are read
    by name, so their order and quoting don't matter."""
    found = []
    last = -1
    for first, end in element_ranges(tokens, "ac:image"):
        if first <= last:  # nested inside the previous one
            continue
        last = end
        kind: Optional[str] = None
        value = ""
        inside = tokens[first:end + 1]
        if not any(token.name in _OTHER_PAGE_REFS for token in inside):
            for token in inside:
                if token.kind not in ("empty", "start"):
                    continue
                if token.name == "ri:attachment":
                    kind, value = "attachment", token.attrs.get("ri:filename", "")
                    break
                if token.name == "ri:url":
                    kind, value = "url", token.attrs.get("ri:value", "")
                    break
        found.append((first, end, kind, value))
    return found


def _is_blank(body: str, token: Token) -> bool:
    return token.kind == "text" and not body[token.start:token.end].strip()


def _removal_edits(body: str, tokens: List[Token], spans: List[Tuple[int, int]]) -> List[Tuple[int, int, str]]:
    """Edits that delete each (first, last) token span, and also the <p> around it when
    nothing else is left in that paragraph (with the newline after it)."""
    gone = set()
    for first, last in spans:
        gone.update(range(first, last + 1))
    wanted = set()
    for first, last in spans:
        start, end = tokens[first].start, tokens[last].end
        left = first - 1
        while left >= 0 and (left in gone or _is_blank(body, tokens[left])):
            left -= 1
        right = last + 1
        while right < len(tokens) and (right in gone or _is_blank(body, tokens[right])):
            right += 1
        if (left >= 0 and right < len(tokens)
                and tokens[left].kind == "start" and tokens[left].name == "p"
                and tokens[right].kind == "end" and tokens[right].name == "p"):
            start, end = tokens[left].start, tokens[right].end
            if body.startswith("\n", end):
                end += 1
        wanted.add((start, end))
    return [(start, end, "") for start, end in sorted(wanted)
            if not any(other != (start, end) and other[0] <= start and end <= other[1]
                       for other in wanted)]


def to_placeholders(body: str, names: Set[str]) -> Tuple[str, int]:
    """Replace embeds of the named attachments with placeholders; return (body, count)."""
    tokens = tokenize(body)
    edits = []
    for first, last, kind, value in _image_elements(tokens):
        if kind != "attachment" or value not in names:
            continue
        attrs = tokens[first].attrs
        tag = '<img src="%s"' % html.escape(value, quote=True)
        if "ac:alt" in attrs:
            tag += ' alt="%s"' % html.escape(attrs["ac:alt"], quote=True)
        edits.append((tokens[first].start, tokens[last].end, tag + " />"))
    return apply_edits(body, edits), len(edits)


def remove_embeds(body: str, keep: Set[str]) -> Tuple[str, int]:
    """Remove embeds except those named in `keep`; return (body, count removed)."""
    tokens = tokenize(body)
    spans = [(first, last) for first, last, kind, value in _image_elements(tokens)
             if kind == "attachment" and value not in keep]
    return apply_edits(body, _removal_edits(body, tokens, spans)), len(spans)


def upload_changed(client, page_id: str, images: List[ImageRef], existing: Dict[str, str]) -> Dict:
    """Return {"uploaded", "unchanged", "missingLocally", "failed", "ready": {src: size}}."""
    out: Dict = {"uploaded": [], "unchanged": [], "missingLocally": [], "failed": [], "ready": {}}
    owner: Dict[str, str] = {}  # attachment name -> the file that claimed it
    for image in images:
        if not os.path.isfile(image.path):
            out["missingLocally"].append(image.src)
            continue
        if owner.setdefault(image.name, image.path) != image.path:
            out["failed"].append({"image": image.src,
                                  "error": "another image is also named %s" % image.name})
            continue
        try:
            with open(image.path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        except OSError as err:
            out["failed"].append({"image": image.src,
                                  "error": "cannot read the file: %s" % (err.strerror or err)})
            continue
        if existing.get(image.name) == OUR_MARK + digest:
            out["unchanged"].append(image.name)
        else:
            status, result = client.upload(page_id, image.path, image.name, OUR_MARK + digest)
            if status != 200:
                message = result.get("message") if isinstance(result, dict) else result
                out["failed"].append({"image": image.src,
                                      "error": "upload HTTP %s: %s" % (status, message)})
                continue
            out["uploaded"].append(image.name)
        out["ready"][image.src] = image_size(image.path)
    return out


def embed(body: str, images: List[ImageRef], ready: Dict[str, Optional[Tuple[int, int]]]) -> Tuple[str, Dict]:
    """Counts {"embedded", "alreadyEmbedded", "stripped", "notOnPage"}."""
    tokens = tokenize(body)
    elements = _image_elements(tokens)

    # A placeholder's address is the image's src as written, or just its file name (what
    # prepare leaves). Uploaded images claim their addresses first, so an image that
    # failed to upload never strips the placeholder of a different one with the same name.
    claimed: Dict[str, ImageRef] = {}
    for image in images:
        if image.src in ready:
            for key in (image.src, image.name):
                claimed.setdefault(key, image)
    dropped: Dict[str, ImageRef] = {}
    for image in images:
        if image.src not in ready:
            for key in (image.src, image.name):
                if key not in claimed:
                    dropped.setdefault(key, image)

    inside_embeds = set()
    for first, last, _kind, _value in elements:
        inside_embeds.update(range(first, last + 1))
    placeholders = [(i, i, token.attrs["src"]) for i, token in enumerate(tokens)
                    if token.name == "img" and token.kind in ("empty", "start")
                    and "src" in token.attrs and i not in inside_embeds]
    placeholders += [(first, last, value) for first, last, kind, value in elements if kind == "url"]

    edits: List[Tuple[int, int, str]] = []
    removals: List[Tuple[int, int]] = []
    embedded: Dict[str, int] = {}  # image src -> placeholders swapped
    stripped: Set[str] = set()
    for first, last, key in placeholders:
        image = claimed.get(key)
        if image is not None:
            markup = embed_markup(image.alt, image.name, ready[image.src])
            edits.append((tokens[first].start, tokens[last].end, markup))
            embedded[image.src] = embedded.get(image.src, 0) + 1
        elif key in dropped:
            removals.append((first, last))
            stripped.add(dropped[key].src)
    edits += _removal_edits(body, tokens, removals)

    on_page = {value for _first, _last, kind, value in elements if kind == "attachment"}
    counts: Dict = {"embedded": 0, "alreadyEmbedded": 0, "stripped": [], "notOnPage": []}
    for image in images:
        if image.src in ready:
            if image.src in embedded:
                counts["embedded"] += embedded[image.src]
            elif image.name in on_page:
                counts["alreadyEmbedded"] += 1
            else:
                counts["notOnPage"].append(image.src)
        elif image.src in stripped:
            counts["stripped"].append(image.src)
    return apply_edits(body, edits), counts
