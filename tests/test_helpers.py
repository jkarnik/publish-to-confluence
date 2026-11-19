"""Tests for the shared test helpers in tests/helpers.py."""
import inspect
import os
import struct
import subprocess
import sys
import unittest
import zlib

# Works for both "python3 -m unittest discover -s tests" and
# "python3 -m unittest tests.test_helpers" from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_chunks(test, data):
    """Split PNG bytes into (type, payload) chunks, checking every CRC."""
    test.assertEqual(data[:8], PNG_SIGNATURE)
    pos = 8
    chunks = []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        test.assertEqual(crc, zlib.crc32(kind + payload) & 0xFFFFFFFF)
        chunks.append((kind, payload))
        pos += 12 + length
    test.assertEqual(pos, len(data))
    return chunks


class PathSetupTests(unittest.TestCase):
    def test_scripts_dir_is_in_sys_path(self):
        self.assertIn(helpers.SCRIPTS_DIR, sys.path)
        self.assertEqual(os.path.basename(helpers.SCRIPTS_DIR), "scripts")
        self.assertEqual(
            os.path.dirname(helpers.SCRIPTS_DIR),
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
        )

    def test_importing_helpers_puts_scripts_first(self):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        code = (
            "import sys; sys.path.insert(0, %r); import helpers; "
            "print(sys.path[0] == helpers.SCRIPTS_DIR)" % tests_dir
        )
        out = subprocess.run(
            [sys.executable, "-I", "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "True")


class TinyPngTests(unittest.TestCase):
    def test_signature_and_size(self):
        data = helpers.tiny_png(3, 2)
        self.assertTrue(data.startswith(PNG_SIGNATURE))
        self.assertEqual(data[12:16], b"IHDR")
        self.assertEqual(struct.unpack(">II", data[16:24]), (3, 2))

    def test_default_size_is_two_by_one(self):
        data = helpers.tiny_png()
        self.assertEqual(struct.unpack(">II", data[16:24]), (2, 1))

    def test_chunks_are_valid_and_pixels_decode(self):
        data = helpers.tiny_png(3, 2)
        chunks = read_chunks(self, data)
        self.assertEqual([kind for kind, _ in chunks], [b"IHDR", b"IDAT", b"IEND"])
        ihdr = chunks[0][1]
        self.assertEqual(ihdr[8], 8)   # bit depth
        self.assertEqual(ihdr[9], 2)   # colour type: RGB, 3 bytes per pixel
        raw = zlib.decompress(chunks[1][1])
        self.assertEqual(len(raw), 2 * (1 + 3 * 3))  # 2 rows: filter byte + 3 pixels

    def test_different_sizes_give_different_bytes(self):
        self.assertNotEqual(helpers.tiny_png(2, 1), helpers.tiny_png(3, 2))

    def test_same_size_gives_same_bytes(self):
        self.assertEqual(helpers.tiny_png(4, 4), helpers.tiny_png(4, 4))


class PageTests(unittest.TestCase):
    def test_default_shape(self):
        p = helpers.page("<p>Hi</p>")
        self.assertEqual(p["id"], "100")
        self.assertEqual(p["type"], "page")
        self.assertEqual(p["title"], "Test page")
        self.assertEqual(p["version"]["number"], 5)
        self.assertEqual(p["body"]["storage"]["value"], "<p>Hi</p>")

    def test_custom_values(self):
        p = helpers.page("x", version=9, title="Other", page_id="42")
        self.assertEqual(
            (p["id"], p["title"], p["version"]["number"]), ("42", "Other", 9)
        )

    def test_pages_do_not_share_nested_dicts(self):
        a = helpers.page("a")
        b = helpers.page("b")
        a["version"]["number"] = 99
        self.assertEqual(b["version"]["number"], 5)


class TempDirTests(unittest.TestCase):
    def test_yields_a_real_directory_and_removes_it(self):
        with helpers.TempDir() as path:
            self.assertIsInstance(path, str)
            self.assertTrue(os.path.isdir(path))
            with open(os.path.join(path, "a.txt"), "w") as f:
                f.write("x")
        self.assertFalse(os.path.exists(path))

    def test_removed_after_an_error(self):
        seen = []
        with self.assertRaises(RuntimeError):
            with helpers.TempDir() as path:
                seen.append(path)
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(seen[0]))

    def test_each_use_gets_a_new_directory(self):
        with helpers.TempDir() as one:
            with helpers.TempDir() as two:
                self.assertNotEqual(one, two)


def make_client(**overrides):
    kwargs = dict(
        pages={"100": helpers.page("<p>Body</p>", version=5)},
        versions={("100", 3): "<p>Old body</p>"},
        comments={"100": [{"id": "c1", "status": "current", "ref": "r1", "selection": "Body"}]},
        attachments={"100": {"a.png": "sha256:abc", "b.png": "hand-made"}},
        files={("100", "a.png"): helpers.tiny_png()},
        user={"accountId": "u-1", "displayName": "Test User"},
    )
    kwargs.update(overrides)
    return helpers.FakeClient(**kwargs)


class FakeClientReadTests(unittest.TestCase):
    def test_current_user(self):
        self.assertEqual(
            make_client().current_user(),
            (200, {"accountId": "u-1", "displayName": "Test User"}),
        )

    def test_current_user_has_a_default(self):
        status, payload = helpers.FakeClient().current_user()
        self.assertEqual(status, 200)
        self.assertIn("displayName", payload)

    def test_read_page(self):
        status, payload = make_client().read_page("100")
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"]["number"], 5)
        self.assertEqual(payload["body"]["storage"]["value"], "<p>Body</p>")

    def test_read_page_returns_a_copy(self):
        client = make_client()
        _, payload = client.read_page("100")
        payload["body"]["storage"]["value"] = "changed"
        payload["version"]["number"] = 99
        _, again = client.read_page("100")
        self.assertEqual(again["body"]["storage"]["value"], "<p>Body</p>")
        self.assertEqual(again["version"]["number"], 5)

    def test_read_page_view_only_when_asked_for(self):
        p = helpers.page("<p>Body</p>")
        p["body"]["view"] = {"value": "<p>Rendered</p>"}
        client = helpers.FakeClient(pages={"100": p})
        _, plain = client.read_page("100")
        self.assertNotIn("view", plain["body"])
        _, with_view = client.read_page("100", expand="body.storage,body.view,version")
        self.assertEqual(with_view["body"]["view"]["value"], "<p>Rendered</p>")
        self.assertEqual(with_view["body"]["storage"]["value"], "<p>Body</p>")

    def test_read_page_view_asked_for_but_missing(self):
        status, payload = make_client().read_page("100", expand="body.view")
        self.assertEqual(status, 200)
        self.assertNotIn("view", payload["body"])

    def test_read_version(self):
        status, payload = make_client().read_version("100", 3)
        self.assertEqual(status, 200)
        self.assertEqual(payload["body"]["storage"]["value"], "<p>Old body</p>")
        self.assertEqual(payload["version"]["number"], 3)
        self.assertEqual(payload["id"], "100")

    def test_inline_comments(self):
        status, payload = make_client().inline_comments("100")
        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            [{"id": "c1", "status": "current", "ref": "r1", "selection": "Body"}],
        )

    def test_attachments(self):
        status, payload = make_client().attachments("100")
        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            [
                {"title": "a.png", "extensions": {"comment": "sha256:abc"}},
                {"title": "b.png", "extensions": {"comment": "hand-made"}},
            ],
        )

    def test_download(self):
        status, payload = make_client().download("100", "a.png")
        self.assertEqual(status, 200)
        self.assertEqual(payload, helpers.tiny_png())

    def test_known_page_with_no_comments_or_attachments_gives_empty_lists(self):
        client = helpers.FakeClient(pages={"100": helpers.page("x")})
        self.assertEqual(client.inline_comments("100"), (200, []))
        self.assertEqual(client.attachments("100"), (200, []))

    def test_unknown_ids_give_404(self):
        client = make_client()
        not_found = (404, {"message": "not found"})
        self.assertEqual(client.read_page("999"), not_found)
        self.assertEqual(client.read_version("100", 4), not_found)
        self.assertEqual(client.read_version("999", 3), not_found)
        self.assertEqual(client.attachments("999"), not_found)
        self.assertEqual(client.inline_comments("999"), not_found)
        self.assertEqual(client.download("100", "missing.png"), not_found)
        self.assertEqual(client.download("999", "a.png"), not_found)
        self.assertEqual(client.save_body(helpers.page("x", page_id="999"), "y", "m"), not_found)
        self.assertEqual(client.saves, [])


class FakeClientWriteTests(unittest.TestCase):
    def test_save_body_bumps_version_and_records_the_save(self):
        client = make_client()
        _, page = client.read_page("100")
        status, payload = client.save_body(page, "<p>New</p>", "first save")
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"]["number"], 6)
        self.assertEqual(client.saves, [("100", "<p>New</p>", "first save")])
        _, again = client.read_page("100")
        self.assertEqual(again["version"]["number"], 6)
        self.assertEqual(again["body"]["storage"]["value"], "<p>New</p>")

    def test_second_save_bumps_again_and_records_both(self):
        client = make_client()
        _, page = client.read_page("100")
        client.save_body(page, "<p>One</p>", "m1")
        _, page = client.read_page("100")
        _, payload = client.save_body(page, "<p>Two</p>", "m2")
        self.assertEqual(payload["version"]["number"], 7)
        self.assertEqual([s[1:] for s in client.saves], [("<p>One</p>", "m1"), ("<p>Two</p>", "m2")])

    def test_save_updates_the_dict_passed_to_the_constructor(self):
        p = helpers.page("<p>Body</p>", version=5)
        client = helpers.FakeClient(pages={"100": p})
        _, page = client.read_page("100")
        client.save_body(page, "<p>New</p>", "m")
        self.assertEqual(p["version"]["number"], 6)
        self.assertEqual(p["body"]["storage"]["value"], "<p>New</p>")

    def test_upload_records_the_upload(self):
        client = make_client()
        status, payload = client.upload("100", "/some/dir/c.png", "c.png", "sha256:def")
        self.assertEqual(status, 200)
        self.assertEqual(payload["title"], "c.png")
        self.assertEqual(client.uploads, [("100", "c.png", "sha256:def")])

    def test_nothing_recorded_to_start_with(self):
        client = helpers.FakeClient()
        self.assertEqual((client.saves, client.uploads), ([], []))


class FakeClientFailTests(unittest.TestCase):
    CALLS = {
        "current_user": lambda c: c.current_user(),
        "read_page": lambda c: c.read_page("100"),
        "read_version": lambda c: c.read_version("100", 3),
        "save_body": lambda c: c.save_body(helpers.page("x"), "<p>New</p>", "m"),
        "attachments": lambda c: c.attachments("100"),
        "upload": lambda c: c.upload("100", "/x/c.png", "c.png", "note"),
        "inline_comments": lambda c: c.inline_comments("100"),
        "download": lambda c: c.download("100", "a.png"),
    }

    def test_each_method_can_be_made_to_fail(self):
        for name, call in self.CALLS.items():
            with self.subTest(method=name):
                client = make_client(fail={name: (503, "down for %s" % name)})
                self.assertEqual(call(client), (503, {"message": "down for %s" % name}))

    def test_only_the_named_method_fails(self):
        client = make_client(fail={"read_page": (401, "no")})
        self.assertEqual(client.read_page("100"), (401, {"message": "no"}))
        self.assertEqual(client.inline_comments("100")[0], 200)
        self.assertEqual(client.attachments("100")[0], 200)

    def test_failed_calls_record_nothing_and_change_nothing(self):
        client = make_client(fail={"save_body": (409, "conflict"), "upload": (500, "boom")})
        _, page = client.read_page("100")
        self.assertEqual(client.save_body(page, "<p>New</p>", "m"), (409, {"message": "conflict"}))
        self.assertEqual(client.upload("100", "/x/c.png", "c.png", "n"), (500, {"message": "boom"}))
        self.assertEqual((client.saves, client.uploads), ([], []))
        _, again = client.read_page("100")
        self.assertEqual(again["version"]["number"], 5)
        self.assertEqual(again["body"]["storage"]["value"], "<p>Body</p>")

    def test_status_zero_is_a_network_error(self):
        client = make_client(fail={"read_page": (0, "network error")})
        self.assertEqual(client.read_page("100"), (0, {"message": "network error"}))


class FakeClientMatchesRestClientTests(unittest.TestCase):
    METHODS = (
        "current_user", "read_page", "read_version", "save_body",
        "attachments", "upload", "inline_comments", "download",
    )

    def test_method_names_exist(self):
        for name in self.METHODS:
            self.assertTrue(callable(getattr(helpers.FakeClient, name, None)), name)

    def test_parameters_and_defaults_match_rest_client(self):
        try:
            import rest_client
        except ModuleNotFoundError:
            self.skipTest("scripts/rest_client.py is not in this checkout yet")

        def shape(func):
            return [(p.name, p.default) for p in inspect.signature(func).parameters.values()]

        for name in self.METHODS:
            with self.subTest(method=name):
                self.assertEqual(
                    shape(getattr(helpers.FakeClient, name)),
                    shape(getattr(rest_client.RestClient, name)),
                )


if __name__ == "__main__":
    unittest.main()
