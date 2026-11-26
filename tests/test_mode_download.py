"""Tests for scripts/mode_download.py: the `download` mode."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unittest

import helpers
import mode_download

PAGE = "100"
NAME = "diagram.png"


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


class DownloadTests(unittest.TestCase):
    def test_saves_file(self):
        png = helpers.tiny_png(3, 2)
        client = helpers.FakeClient(files={(PAGE, NAME): png})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, "new", "images", NAME)  # parents don't exist yet
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 0)
            self.assertEqual(out, {"pageId": PAGE, "filename": NAME,
                                   "saved": os.path.abspath(dest), "bytes": len(png)})
            self.assertTrue(os.path.isabs(out["saved"]))
            self.assertEqual(read(dest), png)
            self.assertEqual(os.listdir(os.path.dirname(dest)), [NAME])  # no temp file left

    def test_refuses_existing_dest(self):
        client = helpers.FakeClient(files={(PAGE, NAME): helpers.tiny_png()})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, NAME)
            with open(dest, "wb") as handle:
                handle.write(b"mine")
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 1)
            self.assertEqual(set(out), {"pageId", "filename", "error"})
            self.assertEqual((out["pageId"], out["filename"]), (PAGE, NAME))
            self.assertIn("exists", out["error"])
            self.assertEqual(read(dest), b"mine")
            self.assertEqual(os.listdir(folder), [NAME])

    def test_existing_dest_is_not_downloaded(self):
        client = helpers.FakeClient(fail={"download": (500, "should not be called")})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, NAME)
            with open(dest, "wb") as handle:
                handle.write(b"mine")
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 1)
            self.assertIn("exists", out["error"])  # not the 500

    def test_missing_attachment(self):
        client = helpers.FakeClient()
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, "sub", NAME)
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 1)
            self.assertEqual(set(out), {"pageId", "filename", "error"})
            self.assertIn("404", out["error"])
            self.assertFalse(os.path.exists(dest))

    def test_server_error_names_the_status(self):
        client = helpers.FakeClient(fail={"download": (503, "unavailable")})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, NAME)
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 1)
            self.assertIn("503", out["error"])
            self.assertEqual(os.listdir(folder), [])

    def test_empty_file_is_an_error_and_leaves_nothing(self):
        client = helpers.FakeClient(files={(PAGE, NAME): b""})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, "sub", NAME)
            out, code = mode_download.run(PAGE, NAME, dest, client)
            self.assertEqual(code, 1)
            self.assertEqual(set(out), {"pageId", "filename", "error"})
            self.assertIn("empty", out["error"])
            self.assertFalse(os.path.exists(dest))

    def test_failed_write_leaves_no_partial_file(self):
        client = helpers.FakeClient(files={(PAGE, NAME): helpers.tiny_png()})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, NAME)
            real_replace = os.replace

            def broken(src, dst):
                raise OSError("disk full")

            os.replace = broken
            try:
                out, code = mode_download.run(PAGE, NAME, dest, client)
            finally:
                os.replace = real_replace
            self.assertEqual(code, 1)
            self.assertIn("disk full", out["error"])
            self.assertEqual(os.listdir(folder), [])

    def test_saved_file_has_normal_permissions(self):
        client = helpers.FakeClient(files={(PAGE, NAME): helpers.tiny_png()})
        with helpers.TempDir() as folder:
            dest = os.path.join(folder, NAME)
            old = os.umask(0o022)
            try:
                out, code = mode_download.run(PAGE, NAME, dest, client)
            finally:
                os.umask(old)
            self.assertEqual(code, 0)
            self.assertEqual(os.stat(dest).st_mode & 0o777, 0o644)

    def test_relative_dest_is_reported_as_absolute(self):
        png = helpers.tiny_png()
        client = helpers.FakeClient(files={(PAGE, NAME): png})
        with helpers.TempDir() as folder:
            here = os.getcwd()
            os.chdir(folder)
            try:
                out, code = mode_download.run(PAGE, NAME, os.path.join("rel", NAME), client)
            finally:
                os.chdir(here)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isabs(out["saved"]))
            self.assertEqual(read(out["saved"]), png)


if __name__ == "__main__":
    unittest.main()
