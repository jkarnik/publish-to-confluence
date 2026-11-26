"""Merge a proposed markdown file into the local file: preview, then apply with a backup."""
from __future__ import annotations

import errno
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, Iterator, List, Optional, Tuple

BACKUP_DIR = os.path.expanduser("~/.claude/publish-to-confluence/backups")
SNIPPET = 100

TOP = "(top)"
TITLE = "Title"
PATH_JOINER = " > "

_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(\S.*?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")

# One line of a section as (raw, shown): raw is compared, shown goes in a snippet.
Item = Tuple[str, str]


class _Section:
    """A heading (None for the text before the first one) and its non-blank lines."""

    def __init__(self, path: str, heading: Optional[Item] = None) -> None:
        self.path = path
        self.heading = heading
        self.body: List[str] = []

    def items(self) -> List[Item]:
        items = [self.heading] if self.heading else []
        items.extend((line, line.strip()) for line in self.body)
        return items

    def first_line(self) -> str:
        if self.body:
            return self.body[0].strip()
        return self.heading[1] if self.heading else ""


def _sections(text: str) -> List[_Section]:
    """Split markdown into sections by ATX headings that are outside code fences."""
    sections = [_Section(TOP)]
    stack: List[Tuple[int, str]] = []  # (level, text) of the open headings below the title
    seen_title = False
    fence: Optional[Tuple[str, int]] = None  # (character, length) of the open fence
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        fenced = _FENCE.match(line)
        if fence:
            if fenced and fenced.group(1)[0] == fence[0] and len(fenced.group(1)) >= fence[1] \
                    and not fenced.group(2).strip():
                fence = None
        elif fenced and not (fenced.group(1)[0] == "`" and "`" in fenced.group(2)):
            fence = (fenced.group(1)[0], len(fenced.group(1)))
        else:
            heading = _HEADING.match(line)
            if heading:
                level, shown = len(heading.group(1)), heading.group(2)
                if level == 1 and not seen_title:
                    seen_title = True
                    stack = []
                    path = TITLE
                else:
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    stack.append((level, shown))
                    path = PATH_JOINER.join(name for _, name in stack)
                sections.append(_Section(path, ("#" * level + " " + shown, shown)))
                continue
        if line:
            sections[-1].body.append(line)
    return sections


def _snippet(text: str) -> str:
    if len(text) <= SNIPPET:
        return text
    return text[:SNIPPET - 1] + "…"


def _paired(old: List[_Section], new: List[_Section]) -> Iterator[Tuple[Optional[_Section], Optional[_Section]]]:
    """Pair sections by path; sections that were renamed pair up in order."""
    matcher = SequenceMatcher(None, [s.path for s in old], [s.path for s in new], autojunk=False)
    for _, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        count = min(old_end - old_start, new_end - new_start)
        for offset in range(count):
            yield old[old_start + offset], new[new_start + offset]
        for section in old[old_start + count:old_end]:
            yield section, None
        for section in new[new_start + count:new_end]:
            yield None, section


def _section_changes(old: _Section, new: _Section) -> List[Dict]:
    old_items, new_items = old.items(), new.items()
    matcher = SequenceMatcher(None, [raw for raw, _ in old_items], [raw for raw, _ in new_items],
                              autojunk=False)
    changes = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        before, after = old_items[old_start:old_end], new_items[new_start:new_end]
        before_text = " ".join(shown for _, shown in before)
        after_text = " ".join(shown for _, shown in after)
        if before_text == after_text:  # for example a heading that moved a level
            before_text = " ".join(raw for raw, _ in before)
            after_text = " ".join(raw for raw, _ in after)
        kind = "changed" if before and after else "deleted" if before else "added"
        changes.append({"section": new.path, "kind": kind,
                        "before": _snippet(before_text), "after": _snippet(after_text)})
    return changes


def preview(file_text: str, proposed_text: str) -> Dict:
    """Describe what applying the proposed text would change, without writing."""
    changes: List[Dict] = []
    for old, new in _paired(_sections(file_text), _sections(proposed_text)):
        if old is None:
            changes.append({"section": new.path, "kind": "added",
                            "before": "", "after": _snippet(new.first_line())})
        elif new is None:
            changes.append({"section": old.path, "kind": "deleted",
                            "before": _snippet(old.first_line()), "after": ""})
        else:
            changes.extend(_section_changes(old, new))
    return {"identical": not changes, "changes": changes}


def _same_file(first: str, second: str) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return os.path.realpath(first) == os.path.realpath(second)


def _utc(moment: Optional[datetime]) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _free_backup_path(backup_dir: str, stem: str, stamp: str) -> str:
    name = "%s-%s" % (stem, stamp)
    path = os.path.join(backup_dir, name + ".md")
    number = 2
    while os.path.lexists(path):
        path = os.path.join(backup_dir, "%s-%d.md" % (name, number))
        number += 1
    return path


def _move_over(source: str, target: str) -> None:
    """Replace target with source. Across drives, copy first so target is never half written."""
    try:
        os.replace(source, target)
        return
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
    handle, temp = tempfile.mkstemp(dir=os.path.dirname(target) or ".", prefix=".merge-", suffix=".tmp")
    os.close(handle)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, target)
    except BaseException:
        if os.path.lexists(temp):
            os.unlink(temp)
        raise
    try:
        os.unlink(source)
    except OSError:
        pass  # the merge is in place; a leftover proposal does no harm


def apply(file_path: str, proposed_path: str, backup_dir: str = BACKUP_DIR, now: Optional[datetime] = None) -> Dict:
    """Back up the file, then write the merged result."""
    if _same_file(file_path, proposed_path):
        raise ValueError("the file and the proposed merge are the same file")
    mode = stat.S_IMODE(os.stat(file_path).st_mode)
    os.stat(proposed_path)  # fail before the backup if the proposal is missing
    stem = os.path.splitext(os.path.basename(file_path))[0]
    os.makedirs(backup_dir, exist_ok=True)
    backup = _free_backup_path(backup_dir, stem, _utc(now).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(file_path, backup)
    _move_over(proposed_path, file_path)
    os.chmod(file_path, mode)
    return {"file": file_path, "backup": backup}


def _read(path: str) -> Tuple[str, Optional[str]]:
    """Return (text, None), or ("", plain reason) when the file can't be read as UTF-8."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read(), None
    except FileNotFoundError:
        return "", "file not found: %s" % path
    except UnicodeDecodeError:
        return "", "not UTF-8 text: %s" % path
    except OSError as error:
        return "", "cannot read %s: %s" % (path, error.strerror or error)


def run_preview(file_path: str, proposed_path: str) -> Tuple[Dict, int]:
    """Return (output dict, exit code) for the preview mode."""
    file_text, problem = _read(file_path)
    if problem:
        return {"error": problem}, 1
    proposed_text, problem = _read(proposed_path)
    if problem:
        return {"error": problem}, 1
    return preview(file_text, proposed_text), 0


def run_apply(file_path: str, proposed_path: str) -> Tuple[Dict, int]:
    """Return (output dict, exit code) for the apply mode."""
    for path in (file_path, proposed_path):
        problem = _read(path)[1]
        if problem:
            return {"error": problem}, 1
    if _same_file(file_path, proposed_path):
        return {"error": "the file and the proposed merge are the same file: %s" % file_path}, 1
    try:
        return apply(file_path, proposed_path), 0
    except (OSError, ValueError) as error:
        reason = (error.strerror or error) if isinstance(error, OSError) else error
        return {"error": "could not apply the merge: %s" % reason}, 1
