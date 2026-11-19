"""Mode `download`: save one attachment from a page to a local path."""
from __future__ import annotations

import os
import uuid
from typing import Dict, Tuple


def _fail(page_id: str, filename: str, reason: str) -> Tuple[Dict, int]:
    return {"pageId": page_id, "filename": filename, "error": reason}, 1


def run(page_id: str, filename: str, dest: str, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    dest = os.path.abspath(dest)
    if os.path.lexists(dest):
        return _fail(page_id, filename, "%s already exists; not overwriting it" % dest)

    status, data = client.download(page_id, filename)
    if status != 200 or not isinstance(data, (bytes, bytearray)):
        reason = "HTTP %d" % status if status else "network error"
        return _fail(page_id, filename, "could not download %s from the page (%s)"
                     % (filename, reason))
    if not data:
        return _fail(page_id, filename, "the attachment %s is empty (HTTP %d); nothing saved"
                     % (filename, status))

    folder = os.path.dirname(dest)
    temp_path = None
    try:
        os.makedirs(folder, exist_ok=True)
        # Same folder as dest, so os.replace stays on one filesystem and is atomic.
        # os.open (not mkstemp) so the file gets normal permissions under the user's umask.
        temp_path = os.path.join(folder, ".download-%s.part" % uuid.uuid4().hex)
        handle = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp_path, dest)
        temp_path = None
    except OSError as error:
        return _fail(page_id, filename, "could not save %s: %s" % (dest, error))
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return {"pageId": page_id, "filename": filename, "saved": dest, "bytes": len(data)}, 0
