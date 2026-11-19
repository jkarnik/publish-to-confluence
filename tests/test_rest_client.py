"""Tests for scripts/rest_client.py. An injected opener records every request and
returns canned replies, so nothing here touches the network."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

import base64  # noqa: E402
import email  # noqa: E402
import http.client  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import socket  # noqa: E402
import unittest  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from unittest import mock  # noqa: E402

import rest_client  # noqa: E402

SITE = "https://example.atlassian.net/wiki"
EMAIL = "tester@example.com"
TOKEN = "tok-SECRET-123"
CREDENTIALS = base64.b64encode((EMAIL + ":" + TOKEN).encode()).decode()


class FakeResponse:
    """What urlopen returns: a context manager with .status and .read()."""

    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body=b"", url=SITE + "/x"):
    return urllib.error.HTTPError(url, code, "status " + str(code), {}, io.BytesIO(body))


class Opener:
    """Replays canned replies in order and records each request.

    A dict or list reply becomes a 200 JSON response, bytes become a 200 raw body,
    a FakeResponse is returned as is, and an exception is raised."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.replies:
            raise AssertionError("unexpected extra request: " + request.full_url)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, FakeResponse):
            return reply
        if isinstance(reply, bytes):
            return FakeResponse(200, reply)
        return FakeResponse(200, json.dumps(reply).encode())

    @property
    def urls(self):
        return [r.full_url for r in self.requests]


def header(request, name):
    """Case-insensitive header lookup (urllib capitalizes names its own way)."""
    for key, value in request.header_items():
        if key.lower() == name.lower():
            return value
    return None


def make(*replies):
    opener = Opener(*replies)
    return rest_client.RestClient(SITE, EMAIL, TOKEN, opener=opener), opener


class RequestBasicsTests(unittest.TestCase):
    def test_auth_header(self):
        client, opener = make({"accountId": "u1"})
        status, payload = client.current_user()
        self.assertEqual((status, payload), (200, {"accountId": "u1"}))
        (request,) = opener.requests
        self.assertEqual(request.full_url, SITE + "/rest/api/user/current")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(header(request, "Authorization"), "Basic " + CREDENTIALS)
        self.assertEqual(header(request, "Accept"), "application/json")
        self.assertEqual(opener.timeouts, [120])

    def test_credentials_are_not_copied_onto_a_redirect(self):
        client, opener = make({}, {"results": [{"title": "a.png", "_links": {"download": "/d"}}]}, b"x")
        client.current_user()
        client.download("7", "a.png")
        self.assertEqual(len(opener.requests), 3)
        handler = urllib.request.HTTPRedirectHandler()
        for request in opener.requests:
            with self.subTest(url=request.full_url):
                self.assertEqual(header(request, "Authorization"), "Basic " + CREDENTIALS)
                self.assertNotIn("Authorization", request.headers)
                self.assertIn("Authorization", request.unredirected_hdrs)
                followed = handler.redirect_request(
                    request, None, 302, "Found", {}, "https://media.example.com/file")
                self.assertIsNone(header(followed, "Authorization"))
                self.assertEqual(header(followed, "Accept"), header(request, "Accept"))

    def test_opener_defaults_to_urlopen(self):
        fake = Opener({"ok": True})
        with mock.patch.object(urllib.request, "urlopen", fake):
            client = rest_client.RestClient(SITE, EMAIL, TOKEN)
            self.assertEqual(client.current_user(), (200, {"ok": True}))
        self.assertEqual(fake.timeouts, [120])

    def test_trailing_slash_on_site_is_ignored(self):
        opener = Opener({})
        client = rest_client.RestClient(SITE + "/", EMAIL, TOKEN, opener=opener)
        client.current_user()
        self.assertEqual(opener.urls, [SITE + "/rest/api/user/current"])

    def test_empty_body_is_an_empty_payload(self):
        client, _ = make(b"")
        self.assertEqual(client.current_user(), (200, {}))

    def test_non_json_success_body_is_a_failure(self):
        client, _ = make(b"<html>sign in</html>")
        status, payload = client.current_user()
        self.assertEqual(status, 0)
        self.assertIn("message", payload)
        self.assertNotIn("sign in", payload["message"])

    def test_repr_hides_the_token(self):
        client, _ = make()
        self.assertNotIn(TOKEN, repr(client))
        self.assertNotIn(CREDENTIALS, repr(client))


class ReadTests(unittest.TestCase):
    def test_read_page_url(self):
        page = helpers.page("<p>x</p>", page_id="7")
        client, opener = make(page)
        self.assertEqual(client.read_page("7"), (200, page))
        self.assertEqual(opener.urls, [SITE + "/rest/api/content/7?expand=body.storage,version"])

    def test_read_page_custom_expand(self):
        client, opener = make({})
        client.read_page("7", "body.view,version")
        self.assertEqual(opener.urls, [SITE + "/rest/api/content/7?expand=body.view,version"])

    def test_page_id_is_quoted(self):
        client, opener = make({})
        client.read_page("7/../x?y=1")
        self.assertEqual(
            opener.urls, [SITE + "/rest/api/content/7%2F..%2Fx%3Fy%3D1?expand=body.storage,version"])

    def test_read_version_url(self):
        client, opener = make(helpers.page("<p>old</p>", version=3, page_id="7"))
        status, payload = client.read_version("7", 3)
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"]["number"], 3)
        self.assertEqual(
            opener.urls,
            [SITE + "/rest/api/content/7?status=historical&version=3&expand=body.storage,version"])


class SaveBodyTests(unittest.TestCase):
    def test_save_body_payload(self):
        page = helpers.page("<p>old</p>", version=5, title="My page", page_id="7")
        saved = helpers.page("<p>new</p>", version=6, title="My page", page_id="7")
        client, opener = make(saved)
        self.assertEqual(client.save_body(page, "<p>new</p>", "Fix wording"), (200, saved))
        (request,) = opener.requests
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.full_url, SITE + "/rest/api/content/7")
        self.assertEqual(header(request, "Content-Type"), "application/json")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "7",
            "type": "page",
            "status": "current",
            "title": "My page",
            "version": {"number": 6, "minorEdit": True, "message": "Fix wording"},
            "body": {"storage": {"value": "<p>new</p>", "representation": "storage"}},
        })

    def test_save_body_keeps_a_non_page_type(self):
        page = helpers.page("<p>old</p>", page_id="7")
        page["type"] = "blogpost"
        client, opener = make({})
        client.save_body(page, "<p>new</p>", "m")
        self.assertEqual(json.loads(opener.requests[0].data.decode("utf-8"))["type"], "blogpost")

    def test_save_body_conflict_comes_back_as_a_message(self):
        page = helpers.page("<p>old</p>", page_id="7")
        client, _ = make(http_error(409, b'{"message": "Version conflict"}'))
        self.assertEqual(client.save_body(page, "<p>new</p>", "m"),
                         (409, {"message": "Version conflict"}))


def parse_multipart(request):
    """Return the parts of a multipart request as a list of email messages."""
    content_type = header(request, "Content-Type")
    raw = b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.data
    message = email.message_from_bytes(raw)
    assert message.is_multipart(), content_type
    return message.get_payload()


class UploadTests(unittest.TestCase):
    def upload(self, name, comment="sha256:abc", data=None, reply=None):
        data = helpers.tiny_png() if data is None else data
        client, opener = make({"results": []} if reply is None else reply)
        with helpers.TempDir() as folder:
            path = os.path.join(folder, "source.png")
            with open(path, "wb") as handle:
                handle.write(data)
            result = client.upload("7", path, name, comment)
        return result, opener.requests[0], data

    def test_upload_multipart(self):
        (status, payload), request, data = self.upload('say "hi".png')
        self.assertEqual((status, payload), (200, {"results": []}))
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.full_url, SITE + "/rest/api/content/7/child/attachment")
        self.assertEqual(header(request, "X-Atlassian-Token"), "no-check")
        self.assertEqual(header(request, "Authorization"), "Basic " + CREDENTIALS)
        self.assertTrue(header(request, "Content-Type").startswith("multipart/form-data; boundary="))
        parts = parse_multipart(request)
        self.assertEqual([p.get_param("name", header="content-disposition") for p in parts],
                         ["minorEdit", "comment", "file"])
        self.assertEqual(parts[0].get_payload(), "true")
        self.assertEqual(parts[1].get_payload(), "sha256:abc")
        self.assertEqual(parts[2].get_payload(decode=True), data)
        self.assertEqual(parts[2].get_content_type(), "image/png")
        self.assertEqual(parts[2].get_filename(), 'say %22hi%22.png')
        self.assertNotIn(b'say "hi"', request.data)

    def test_upload_unknown_type_is_octet_stream(self):
        _, request, _ = self.upload("notes.unknownext", data=b"bytes")
        self.assertEqual(parse_multipart(request)[2].get_content_type(), "application/octet-stream")

    def test_upload_line_breaks_in_name_cannot_break_the_header(self):
        _, request, _ = self.upload("a\r\nb.png")
        parts = parse_multipart(request)
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[2].get_filename(), "a%0D%0Ab.png")

    def test_upload_missing_file_is_a_message_not_a_crash(self):
        client, opener = make()
        status, payload = client.upload("7", os.path.join(os.sep, "no", "such", "file.png"),
                                        "file.png", "sha256:abc")
        self.assertEqual(status, 0)
        self.assertIn("file.png", payload["message"])
        self.assertEqual(opener.requests, [])

    def test_upload_http_error(self):
        client, _ = make(http_error(413, b'{"message": "Too large"}'))
        with helpers.TempDir() as folder:
            path = os.path.join(folder, "a.png")
            with open(path, "wb") as handle:
                handle.write(helpers.tiny_png())
            self.assertEqual(client.upload("7", path, "a.png", "c"), (413, {"message": "Too large"}))


class AttachmentsTests(unittest.TestCase):
    FIRST = {"title": "a.png", "extensions": {"comment": "sha256:1"}}
    SECOND = {"title": "b.png", "metadata": {"comment": "sha256:2"}}

    def test_attachments_paging(self):
        client, opener = make(
            {"results": [self.FIRST],
             "_links": {"next": "/rest/api/content/7/child/attachment?limit=250&start=250"}},
            {"results": [self.SECOND], "_links": {}})
        self.assertEqual(client.attachments("7"), (200, [self.FIRST, self.SECOND]))
        self.assertEqual(opener.urls, [
            SITE + "/rest/api/content/7/child/attachment?limit=250",
            SITE + "/rest/api/content/7/child/attachment?limit=250&start=250",
        ])

    def test_attachments_next_link_with_wiki_prefix(self):
        client, opener = make(
            {"results": [self.FIRST],
             "_links": {"next": "/wiki/rest/api/content/7/child/attachment?limit=250&start=250"}},
            {"results": [self.SECOND]})
        self.assertEqual(client.attachments("7"), (200, [self.FIRST, self.SECOND]))
        self.assertEqual(opener.urls[1],
                         SITE + "/rest/api/content/7/child/attachment?limit=250&start=250")

    def test_attachments_none(self):
        client, _ = make({"results": [], "_links": {}})
        self.assertEqual(client.attachments("7"), (200, []))

    def test_attachments_failure_on_a_later_page_returns_the_failure(self):
        client, _ = make(
            {"results": [self.FIRST], "_links": {"next": "/rest/api/content/7/child/attachment?start=1"}},
            http_error(500, b"oops"))
        self.assertEqual(client.attachments("7"), (500, {"message": "oops"}))

    def test_attachments_not_found(self):
        client, _ = make(http_error(404, b'{"message": "No content found"}'))
        self.assertEqual(client.attachments("7"), (404, {"message": "No content found"}))

    def test_paging_that_loops_stops(self):
        link = "/rest/api/content/7/child/attachment?limit=250&start=1"
        client, opener = make(
            {"results": [self.FIRST], "_links": {"next": link}},
            {"results": [self.SECOND], "_links": {"next": link}})
        status, payload = client.attachments("7")
        self.assertEqual(status, 0)
        self.assertIn("message", payload)
        self.assertEqual(len(opener.requests), 2)

    def test_next_link_to_another_site_is_refused_and_not_followed(self):
        client, opener = make(
            {"results": [self.FIRST], "_links": {"next": "https://evil.example.com/steal"}})
        status, payload = client.attachments("7")
        self.assertEqual(status, 0)
        self.assertIn("message", payload)
        self.assertEqual(len(opener.requests), 1)

    def test_absolute_next_link_on_this_site_is_followed(self):
        client, opener = make(
            {"results": [self.FIRST],
             "_links": {"next": SITE + "/rest/api/content/7/child/attachment?start=1"}},
            {"results": [self.SECOND]})
        self.assertEqual(client.attachments("7"), (200, [self.FIRST, self.SECOND]))
        self.assertEqual(opener.urls[1], SITE + "/rest/api/content/7/child/attachment?start=1")


class InlineCommentsTests(unittest.TestCase):
    def test_inline_comments_paging_and_shape(self):
        client, opener = make(
            {"results": [
                {"id": "11", "resolutionStatus": "open",
                 "properties": {"inlineMarkerRef": "ref-1", "inlineOriginalSelection": "first text"}},
                {"id": "12", "resolutionStatus": "resolved",
                 "properties": {"inline-marker-ref": "ref-2", "inline-original-selection": "second"}},
            ], "_links": {"next": "/wiki/api/v2/pages/7/inline-comments?limit=250&cursor=abc"}},
            {"results": [
                {"id": "13", "resolutionStatus": "dangling"},
                {"id": "14", "resolutionStatus": "open", "properties": None},
            ], "_links": {}})
        self.assertEqual(client.inline_comments("7"), (200, [
            {"id": "11", "status": "open", "ref": "ref-1", "selection": "first text"},
            {"id": "12", "status": "resolved", "ref": "ref-2", "selection": "second"},
            {"id": "13", "status": "dangling", "ref": None, "selection": None},
            {"id": "14", "status": "open", "ref": None, "selection": None},
        ]))
        self.assertEqual(opener.urls, [
            SITE + "/api/v2/pages/7/inline-comments?limit=250",
            SITE + "/api/v2/pages/7/inline-comments?limit=250&cursor=abc",
        ])

    def test_inline_comments_failure(self):
        client, _ = make(http_error(403, b'{"message": "Forbidden"}'))
        self.assertEqual(client.inline_comments("7"), (403, {"message": "Forbidden"}))

    def test_inline_comments_none(self):
        client, _ = make({"results": []})
        self.assertEqual(client.inline_comments("7"), (200, []))


class DownloadTests(unittest.TestCase):
    LISTING = {"results": [
        {"title": "other.png", "_links": {"download": "/download/attachments/7/other.png?version=1"}},
        {"title": "my pic.png",
         "_links": {"download": "/download/attachments/7/my%20pic.png?version=2&api=v2"}},
    ]}

    def test_download(self):
        data = helpers.tiny_png()
        client, opener = make(self.LISTING, data)
        self.assertEqual(client.download("7", "my pic.png"), (200, data))
        self.assertEqual(opener.urls, [
            SITE + "/rest/api/content/7/child/attachment?filename=my%20pic.png",
            SITE + "/download/attachments/7/my%20pic.png?version=2&api=v2",
        ])
        self.assertEqual(header(opener.requests[1], "Authorization"), "Basic " + CREDENTIALS)
        self.assertEqual(opener.timeouts, [120, 120])

    def test_download_quotes_the_filename(self):
        client, opener = make({"results": []})
        client.download("7", "a&b/c d.png")
        self.assertEqual(opener.urls,
                         [SITE + "/rest/api/content/7/child/attachment?filename=a%26b%2Fc%20d.png"])

    def test_download_link_with_wiki_prefix(self):
        listing = {"results": [{"title": "a.png", "_links": {"download": "/wiki/download/attachments/7/a.png"}}]}
        client, opener = make(listing, b"data")
        self.assertEqual(client.download("7", "a.png"), (200, b"data"))
        self.assertEqual(opener.urls[1], SITE + "/download/attachments/7/a.png")

    def test_download_attachment_not_listed(self):
        client, opener = make({"results": [{"title": "other.png", "_links": {"download": "/d"}}]})
        self.assertEqual(client.download("7", "a.png"), (404, b""))
        self.assertEqual(len(opener.requests), 1)

    def test_download_without_a_link(self):
        client, opener = make({"results": [{"title": "a.png"}]})
        self.assertEqual(client.download("7", "a.png"), (404, b""))
        self.assertEqual(len(opener.requests), 1)

    def test_download_listing_fails(self):
        client, _ = make(http_error(401, b'{"message": "bad"}'))
        self.assertEqual(client.download("7", "a.png"), (401, b""))

    def test_download_file_fails(self):
        client, _ = make(self.LISTING, http_error(403, b"nope"))
        self.assertEqual(client.download("7", "my pic.png"), (403, b""))

    def test_download_network_error(self):
        client, _ = make(self.LISTING, urllib.error.URLError("no route"))
        self.assertEqual(client.download("7", "my pic.png"), (0, b""))

    def test_download_listing_network_error(self):
        client, _ = make(urllib.error.URLError("no route"))
        self.assertEqual(client.download("7", "a.png"), (0, b""))

    def test_download_refuses_a_link_to_another_site(self):
        listing = {"results": [{"title": "a.png", "_links": {"download": "https://evil.example.com/a.png"}}]}
        client, opener = make(listing)
        status, data = client.download("7", "a.png")
        self.assertEqual(data, b"")
        self.assertNotEqual(status, 200)
        self.assertEqual(len(opener.requests), 1)


class ErrorTests(unittest.TestCase):
    def test_http_error(self):
        client, _ = make(http_error(401, b'{"message": "Client must be authenticated", "statusCode": 401}'))
        self.assertEqual(client.current_user(), (401, {"message": "Client must be authenticated"}))

    def test_http_error_plain_text_body(self):
        client, _ = make(http_error(502, b"Bad gateway from proxy"))
        self.assertEqual(client.current_user(), (502, {"message": "Bad gateway from proxy"}))

    def test_http_error_json_without_message_keeps_the_text(self):
        body = b'{"errors": [{"title": "Not allowed"}]}'
        client, _ = make(http_error(403, body))
        self.assertEqual(client.current_user(), (403, {"message": body.decode()}))

    def test_http_error_message_is_cut_to_300_characters(self):
        client, _ = make(http_error(500, b"x" * 1000),
                         http_error(500, json.dumps({"message": "y" * 1000}).encode()))
        self.assertEqual(client.current_user(), (500, {"message": "x" * 300}))
        self.assertEqual(client.current_user(), (500, {"message": "y" * 300}))

    def test_http_error_with_an_empty_body_still_says_something(self):
        client, _ = make(http_error(404, b""))
        status, payload = client.current_user()
        self.assertEqual(status, 404)
        self.assertTrue(payload["message"])

    def test_http_error_with_undecodable_body(self):
        client, _ = make(http_error(500, b"\xff\xfe bad"))
        status, payload = client.current_user()
        self.assertEqual(status, 500)
        self.assertIn("bad", payload["message"])

    def test_error_status_returned_without_raising_is_still_an_error(self):
        client, _ = make(FakeResponse(404, b'{"message": "gone"}'))
        self.assertEqual(client.current_user(), (404, {"message": "gone"}))

    def test_network_error(self):
        client, _ = make(urllib.error.URLError("no route to host"))
        status, payload = client.current_user()
        self.assertEqual(status, 0)
        self.assertIn("no route to host", payload["message"])

    def test_other_network_failures_are_status_zero_too(self):
        failures = [socket.timeout("timed out"), ConnectionResetError("reset"),
                    http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"ab"),
                    ValueError("unknown url type")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                client, _ = make(failure)
                status, payload = client.current_user()
                self.assertEqual(status, 0)
                self.assertTrue(payload["message"])


class TokenSafetyTests(unittest.TestCase):
    CALLS = {
        "current_user": lambda c: c.current_user(),
        "read_page": lambda c: c.read_page("7"),
        "read_version": lambda c: c.read_version("7", 2),
        "save_body": lambda c: c.save_body(helpers.page("x", page_id="7"), "y", "m"),
        "attachments": lambda c: c.attachments("7"),
        "inline_comments": lambda c: c.inline_comments("7"),
    }

    def assert_clean(self, result):
        text = repr(result)
        for secret in (TOKEN, CREDENTIALS, "Basic " + CREDENTIALS):
            self.assertNotIn(secret, text)
        self.assertNotIn("Authorization", text)

    def test_token_never_in_messages(self):
        echoes = [
            lambda: http_error(401, ("Bad login for " + TOKEN).encode()),
            lambda: http_error(
                401, json.dumps({"message": "Sent Authorization: Basic " + CREDENTIALS}).encode()),
            lambda: http_error(400, ("echo " + CREDENTIALS).encode()),
            lambda: urllib.error.URLError("proxy refused " + TOKEN),
            lambda: OSError("connection to " + TOKEN + " failed"),
        ]
        for name, call in self.CALLS.items():
            for number, echo in enumerate(echoes):
                with self.subTest(method=name, echo=number):
                    client, _ = make(echo())
                    status, payload = call(client)
                    self.assertIn("message", payload)
                    self.assert_clean((status, payload))

    def test_token_never_in_upload_or_download_failures(self):
        with helpers.TempDir() as folder:
            path = os.path.join(folder, "a.png")
            with open(path, "wb") as handle:
                handle.write(helpers.tiny_png())
            client, _ = make(http_error(500, ("boom " + TOKEN).encode()))
            self.assert_clean(client.upload("7", path, "a.png", "c"))
        client, _ = make(urllib.error.URLError(TOKEN))
        self.assert_clean(client.download("7", "a.png"))
        client, _ = make({"results": [{"title": "a.png", "_links": {"download": "/d"}}]},
                         http_error(500, TOKEN.encode()))
        self.assert_clean(client.download("7", "a.png"))

    def test_a_message_cut_at_300_characters_cannot_leave_part_of_the_token(self):
        body = ("z" * 295 + TOKEN).encode()
        client, _ = make(http_error(500, body))
        _, payload = client.current_user()
        self.assertLessEqual(len(payload["message"]), 300)
        self.assertNotIn(TOKEN[:6], payload["message"])

    def test_token_never_sent_anywhere_but_the_authorization_header(self):
        client, opener = make({}, {"results": []}, {"results": []})
        client.read_page("7")
        client.attachments("7")
        client.inline_comments("7")
        for request in opener.requests:
            self.assertNotIn(TOKEN, request.full_url)
            self.assertEqual([k for k, v in request.header_items() if TOKEN in v], [])


if __name__ == "__main__":
    unittest.main()
