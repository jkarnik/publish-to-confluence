"""Confluence REST client. Every call returns (status, payload); status 0 = network error,
payload {"message": ...}."""
from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, List, Optional, Tuple

TIMEOUT = 120  # seconds, for every request
MAX_MESSAGE = 300  # characters kept from an error reply
PAGE_SIZE = 250

# What a credential header or value looks like, in case a server echoes one back.
_AUTH_HEADER = re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:basic\s+)?\S+")
_BASIC_VALUE = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=_-]{8,}")


def _quote(value: object) -> str:
    return urllib.parse.quote(str(value), safe="")


def _error_body(err: urllib.error.HTTPError) -> bytes:
    try:
        return err.read()
    except (OSError, http.client.HTTPException, AttributeError, ValueError):
        return b""
    finally:
        try:
            err.close()
        except (OSError, AttributeError, ValueError):
            pass


class RestClient:
    def __init__(self, site: str, email: str, token: str, opener: Optional[Callable] = None):
        """site is the wiki address and ends in /wiki. opener(request, timeout=120) returns a
        response the way urllib.request.urlopen does, and defaults to it."""
        self.site = site.rstrip("/")
        pair = base64.b64encode((email + ":" + token).encode("utf-8")).decode("ascii")
        self._auth = "Basic " + pair
        self._secrets = [secret for secret in (token, pair) if secret]
        self._opener = opener if opener is not None else urllib.request.urlopen

    def __repr__(self) -> str:
        return "RestClient(site=%r)" % self.site

    # ---- requests ----------------------------------------------------------------

    def _scrub(self, text: str) -> str:
        """Remove the token, the encoded credentials and any auth header from a message."""
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        text = _AUTH_HEADER.sub("[redacted]", text)
        return _BASIC_VALUE.sub("[redacted]", text)

    def _message(self, raw: bytes) -> str:
        """A short, safe message from an error reply: its JSON "message" if it has one."""
        text = raw.decode("utf-8", "replace").strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("message"):
            text = str(parsed["message"])
        return self._scrub(text)[:MAX_MESSAGE]

    def _send(self, method: str, path: str, data: Optional[bytes] = None,
              headers: Optional[dict] = None, accept: str = "application/json"):
        """One request. Returns (status, body, None) on success, or (status, b"", message) on
        any failure, where status 0 means no usable reply came back."""
        request = urllib.request.Request(
            self.site + path, data=data, method=method,
            headers={"Accept": accept, **(headers or {})})
        # Unredirected, so urllib does not copy the credentials onto a redirect to another host.
        request.add_unredirected_header("Authorization", self._auth)
        try:
            with self._opener(request, timeout=TIMEOUT) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, b"", self._message(_error_body(err)) or "HTTP %d" % err.code
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as err:
            reason = getattr(err, "reason", None) or err
            return 0, b"", self._scrub("network error: %s" % (reason,))[:MAX_MESSAGE]
        if status >= 300:
            return status, b"", self._message(body) or "HTTP %d" % status
        return status, body, None

    def _call(self, method: str, path: str, data: Optional[bytes] = None,
              headers: Optional[dict] = None) -> Tuple[int, dict]:
        """A request whose reply is a JSON object."""
        status, body, message = self._send(method, path, data, headers)
        if message is not None:
            return status, {"message": message}
        try:
            payload = json.loads(body.decode("utf-8")) if body.strip() else {}
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return 0, {"message": "unexpected reply (not a JSON object)"}
        return status, payload

    def _local_path(self, link: str) -> Optional[str]:
        """A "next" or "download" link as a path under site, or None if it points elsewhere
        (the credentials must go to this site only). Links come back as /rest/... or
        /wiki/...; site already ends in /wiki."""
        if link.startswith(self.site + "/"):
            link = link[len(self.site):]
        if link.startswith("/wiki/"):
            link = link[len("/wiki"):]
        if not link.startswith("/") or link.startswith("//"):
            return None
        return link

    def _all_results(self, path: Optional[str]) -> Tuple[int, object]:
        """Follow _links.next from path: (200, every result), or the first failure."""
        results: List[dict] = []
        seen = set()
        while path:
            if path in seen:
                return 0, {"message": "paging did not advance"}
            seen.add(path)
            status, payload = self._call("GET", path)
            if status != 200:
                return status, payload
            results.extend(item for item in (payload.get("results") or []) if isinstance(item, dict))
            links = payload.get("_links")
            link = links.get("next") if isinstance(links, dict) else None
            path = None
            if link:
                path = self._local_path(str(link))
                if path is None:
                    return 0, {"message": "paging link points outside the site"}
        return 200, results

    # ---- pages -------------------------------------------------------------------

    def current_user(self) -> Tuple[int, dict]:
        return self._call("GET", "/rest/api/user/current")

    def read_page(self, page_id: str, expand: str = "body.storage,version") -> Tuple[int, dict]:
        return self._call("GET", "/rest/api/content/%s?expand=%s" % (
            _quote(page_id), urllib.parse.quote(expand, safe=",.")))

    def read_version(self, page_id: str, number: int) -> Tuple[int, dict]:
        """Historical body.storage."""
        return self._call("GET", "/rest/api/content/%s?status=historical&version=%d"
                          "&expand=body.storage,version" % (_quote(page_id), int(number)))

    def save_body(self, page: dict, body: str, message: str) -> Tuple[int, dict]:
        """Save the body as version + 1, asking for a minor edit (minorEdit is sent as true).

        Confluence still records these saves as normal versions, so don't rely on the flag.
        """
        page_id = str(page["id"])
        payload = {
            "id": page_id,
            "type": page.get("type", "page"),
            "status": "current",
            "title": page["title"],
            "version": {"number": page["version"]["number"] + 1, "minorEdit": True,
                        "message": message},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        return self._call("PUT", "/rest/api/content/%s" % _quote(page_id),
                          json.dumps(payload).encode("utf-8"),
                          {"Content-Type": "application/json"})

    # ---- attachments -------------------------------------------------------------

    def attachments(self, page_id: str) -> Tuple[int, List[dict]]:
        """All pages of results."""
        return self._all_results(
            "/rest/api/content/%s/child/attachment?limit=%d" % (_quote(page_id), PAGE_SIZE))

    def upload(self, page_id: str, path: str, name: str, comment: str) -> Tuple[int, dict]:
        try:
            with open(path, "rb") as handle:
                content = handle.read()
        except OSError as err:
            return 0, {"message": "cannot read %s: %s" % (name, err.strerror or err)}
        boundary = uuid.uuid4().hex
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"

        def field(key: str, value: str) -> bytes:
            return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                    % (boundary, key, value)).encode("utf-8")

        safe_name = name.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
        body = (field("minorEdit", "true") + field("comment", comment)
                + ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                   "Content-Type: %s\r\n\r\n" % (boundary, safe_name, kind)).encode("utf-8")
                + content + ("\r\n--%s--\r\n" % boundary).encode("ascii"))
        return self._call("PUT", "/rest/api/content/%s/child/attachment" % _quote(page_id), body, {
            "X-Atlassian-Token": "no-check",
            "Content-Type": "multipart/form-data; boundary=" + boundary})

    def download(self, page_id: str, filename: str) -> Tuple[int, bytes]:
        """(200, the file's bytes), or (status, b"") where the status says why: the HTTP status,
        0 for a network error, 404 if the page has no attachment with that name."""
        status, listing = self._call("GET", "/rest/api/content/%s/child/attachment?filename=%s"
                                     % (_quote(page_id), _quote(filename)))
        if status != 200:
            return status, b""
        link = None
        for item in listing.get("results") or []:
            if isinstance(item, dict) and item.get("title") == filename:
                links = item.get("_links")
                link = links.get("download") if isinstance(links, dict) else None
                break
        if not link:
            return 404, b""
        path = self._local_path(str(link))
        if path is None:
            return 0, b""
        status, body, message = self._send("GET", path, accept="*/*")
        if message is not None:
            return status, b""
        return status, body

    # ---- inline comments ---------------------------------------------------------

    def inline_comments(self, page_id: str) -> Tuple[int, List[dict]]:
        """[{"id", "status", "ref", "selection"}]."""
        status, results = self._all_results(
            "/api/v2/pages/%s/inline-comments?limit=%d" % (_quote(page_id), PAGE_SIZE))
        if status != 200:
            return status, results
        comments = []
        for item in results:
            props = item.get("properties") or {}
            comments.append({
                "id": item.get("id"),
                "status": item.get("resolutionStatus"),
                "ref": props.get("inlineMarkerRef") or props.get("inline-marker-ref"),
                "selection": props.get("inlineOriginalSelection")
                or props.get("inline-original-selection"),
            })
        return 200, comments
