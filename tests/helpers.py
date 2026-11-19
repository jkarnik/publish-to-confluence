"""Shared helpers for the tests: path setup, a tiny PNG, a page builder, a temp
directory and FakeClient, an in-memory stand-in for scripts/rest_client.RestClient.

Importing this module puts <repo>/scripts first on sys.path. It imports no script
module itself.
"""
import copy
import os
import shutil
import struct
import sys
import tempfile
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")

while SCRIPTS_DIR in sys.path:
    sys.path.remove(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)


def _not_found():
    return 404, {"message": "not found"}


def tiny_png(width=2, height=1):
    """Return the bytes of a valid width x height RGB PNG."""
    def chunk(kind, payload):
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x20\x80\xe0" * width  # filter byte 0, then RGB pixels
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def page(body, version=5, title="Test page", page_id="100"):
    """A dict shaped like a REST page read."""
    return {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {"number": version},
        "body": {"storage": {"value": body}},
    }


class TempDir:
    """Context manager that yields the path of a new temporary directory and
    removes it afterwards."""

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="publish-to-confluence-test-")
        return self.path

    def __exit__(self, exc_type, exc, tb):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


class FakeClient:
    """In-memory stand-in for RestClient. Every method returns (status, payload)
    like the real one.

    pages[id]          page(...) dict, optionally with body.view.value
    versions[(id, n)]  body string of version n
    comments[id]       list of {"id", "status", "ref", "selection"}
    attachments[id]    {file name: comment}
    files[(id, name)]  bytes
    user               what current_user returns
    fail               {"method_name": (status, message)} makes that method fail

    Successful saves and uploads are recorded in self.saves [(page_id, body,
    message)] and self.uploads [(page_id, name, comment)]. A failed call records
    nothing and changes nothing.
    """

    def __init__(self, pages=None, versions=None, comments=None, attachments=None,
                 files=None, user=None, fail=None):
        self.pages = {} if pages is None else pages
        self.versions = {} if versions is None else versions
        self.comments = {} if comments is None else comments
        # Not called "attachments": that is a method, as in RestClient.
        self.attachment_notes = {} if attachments is None else attachments
        self.files = {} if files is None else files
        self.user = {"accountId": "user-1", "displayName": "Test User"} if user is None else user
        self.fail = {} if fail is None else fail
        self.saves = []
        self.uploads = []

    def _failure(self, method):
        if method in self.fail:
            status, message = self.fail[method]
            return status, {"message": message}
        return None

    def current_user(self):
        failure = self._failure("current_user")
        if failure:
            return failure
        return 200, copy.deepcopy(self.user)

    def read_page(self, page_id, expand="body.storage,version"):
        failure = self._failure("read_page")
        if failure:
            return failure
        if page_id not in self.pages:
            return _not_found()
        result = copy.deepcopy(self.pages[page_id])
        wanted = [part.strip() for part in expand.split(",")]
        if "body.view" not in wanted:
            result.get("body", {}).pop("view", None)
        return 200, result

    def read_version(self, page_id, number):
        failure = self._failure("read_version")
        if failure:
            return failure
        if (page_id, number) not in self.versions:
            return _not_found()
        title = self.pages.get(page_id, {}).get("title", "Test page")
        return 200, page(self.versions[(page_id, number)], version=number,
                         title=title, page_id=page_id)

    def save_body(self, page, body, message):
        failure = self._failure("save_body")
        if failure:
            return failure
        page_id = page["id"]
        if page_id not in self.pages:
            return _not_found()
        stored = self.pages[page_id]
        stored["version"]["number"] += 1
        stored["body"]["storage"]["value"] = body
        self.saves.append((page_id, body, message))
        return 200, copy.deepcopy(stored)

    def attachments(self, page_id):
        failure = self._failure("attachments")
        if failure:
            return failure
        if page_id in self.attachment_notes:
            notes = self.attachment_notes[page_id]
        elif page_id in self.pages:
            notes = {}
        else:
            return _not_found()
        return 200, [{"title": name, "extensions": {"comment": comment}}
                     for name, comment in notes.items()]

    def upload(self, page_id, path, name, comment):
        failure = self._failure("upload")
        if failure:
            return failure
        self.uploads.append((page_id, name, comment))
        return 200, {"title": name, "extensions": {"comment": comment}}

    def inline_comments(self, page_id):
        failure = self._failure("inline_comments")
        if failure:
            return failure
        if page_id in self.comments:
            return 200, copy.deepcopy(self.comments[page_id])
        if page_id in self.pages:
            return 200, []
        return _not_found()

    def download(self, page_id, filename):
        failure = self._failure("download")
        if failure:
            return failure
        if (page_id, filename) not in self.files:
            return _not_found()
        return 200, self.files[(page_id, filename)]
