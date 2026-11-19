"""Tests for scripts/local_config.py: SETUP.md and the token file."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib
import io
import unittest

import helpers
import local_config

SITE = "https://example.atlassian.net"
PAGE = SITE + "/wiki/spaces/ABC/pages/123/Some+Title"


def write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


class ParseParentTests(unittest.TestCase):
    def test_page_address(self):
        result = local_config.parse_parent(PAGE)
        self.assertEqual(result, {"setup": "ok", "parent": PAGE, "site": SITE + "/wiki"})

    def test_page_address_without_title(self):
        result = local_config.parse_parent(SITE + "/wiki/spaces/ABC/pages/123")
        self.assertEqual(result["setup"], "ok")

    def test_folder_address(self):
        address = SITE + "/wiki/spaces/ABC/folder/456"
        result = local_config.parse_parent(address)
        self.assertEqual(result, {"setup": "ok", "parent": address, "site": SITE + "/wiki"})

    def test_pair_can_sit_anywhere_after_wiki(self):
        for path in ("/wiki/pages/123", "/wiki/spaces/ABC/folder/456/My+Folder",
                     "/wiki/a/b/c/pages/7/x/y"):
            self.assertEqual(local_config.parse_parent(SITE + path)["setup"], "ok", path)

    def test_query_and_fragment_ignored(self):
        address = SITE + "/wiki/spaces/ABC/pages/123/Some+Title?src=share#heading"
        result = local_config.parse_parent(address)
        self.assertEqual(result["setup"], "ok")
        self.assertEqual(result["parent"], address)
        self.assertEqual(result["site"], SITE + "/wiki")

    def test_digits_only_in_query_do_not_count(self):
        result = local_config.parse_parent(SITE + "/wiki/spaces/ABC/overview?pages/123")
        self.assertEqual(result["setup"], "invalid")

    def test_short_link(self):
        address = SITE + "/wiki/x/AbC1"
        result = local_config.parse_parent(address)
        self.assertEqual(result, {"setup": "short-link", "parent": address, "site": None})

    def test_placeholder_and_empty(self):
        for text in (local_config.PLACEHOLDER, "  " + local_config.PLACEHOLDER + " ",
                     "", "   "):
            result = local_config.parse_parent(text)
            self.assertEqual(result["setup"], "placeholder", repr(text))
            self.assertIsNone(result["parent"])
            self.assertIsNone(result["site"])

    def test_invalid(self):
        bad = [
            "http://example.atlassian.net/wiki/spaces/ABC/pages/123",   # not https
            "https://",                                                 # no host
            "http://",
            SITE + "/spaces/ABC/pages/123",                             # no /wiki/
            SITE + "/wiki",                                             # nothing after wiki
            SITE + "/wiki/spaces/ABC/pages/",                           # no id
            SITE + "/wiki/spaces/ABC/pages/abc/Title",                  # id not digits
            SITE + "/wiki/spaces/ABC/folder/",                          # no id
            SITE + "/wiki/spaces/ABC/overview",                         # not a page or folder
            SITE + "/wiki/spaces/ABC/pages123",                         # no separator
            "not a url",
            "example.atlassian.net/wiki/spaces/ABC/pages/123",          # no scheme
        ]
        for address in bad:
            result = local_config.parse_parent(address)
            self.assertEqual(result["setup"], "invalid", address)
            self.assertEqual(result["parent"], address)
            self.assertIsNone(result["site"])

    def test_text_after_the_address_is_invalid(self):
        result = local_config.parse_parent(PAGE + " and some more words")
        self.assertEqual(result["setup"], "invalid")

    def test_site_only_when_ok(self):
        for address in (SITE + "/wiki/x/AbC1", "http://", local_config.PLACEHOLDER):
            self.assertIsNone(local_config.parse_parent(address)["site"])


class ReadSetupTests(unittest.TestCase):
    def test_read_setup_missing_file(self):
        with helpers.TempDir() as folder:
            result = local_config.read_setup(os.path.join(folder, "SETUP.md"))
        self.assertEqual(result, {"setup": "missing", "parent": None, "site": None})

    def test_read_setup_no_parent_line(self):
        with helpers.TempDir() as folder:
            path = write(folder, "SETUP.md", "# Where your pages go\n\nSome words.\n")
            result = local_config.read_setup(path)
        self.assertEqual(result, {"setup": "placeholder", "parent": None, "site": None})

    def test_read_setup_empty_file(self):
        with helpers.TempDir() as folder:
            result = local_config.read_setup(write(folder, "SETUP.md", ""))
        self.assertEqual(result["setup"], "placeholder")

    def test_read_setup_crlf_and_spaces(self):
        with helpers.TempDir() as folder:
            path = write(folder, "SETUP.md", "# Title\r\n\r\nParent:   " + PAGE + "  \r\n")
            result = local_config.read_setup(path)
            self.assertEqual(result, {"setup": "ok", "parent": PAGE, "site": SITE + "/wiki"})
            path = write(folder, "SETUP.md", "parent:" + PAGE + "\r\n")
            self.assertEqual(local_config.read_setup(path)["setup"], "ok")
            path = write(folder, "SETUP.md", "  PARENT: " + PAGE)
            self.assertEqual(local_config.read_setup(path)["setup"], "ok")

    def test_value_keeps_everything_after_the_first_colon(self):
        with helpers.TempDir() as folder:
            path = write(folder, "SETUP.md", "Parent: http://example.atlassian.net:8080/x\n")
            result = local_config.read_setup(path)
        self.assertEqual(result["setup"], "invalid")
        self.assertEqual(result["parent"], "http://example.atlassian.net:8080/x")

    def test_first_parent_line_wins(self):
        with helpers.TempDir() as folder:
            path = write(folder, "SETUP.md",
                         "Parent: " + SITE + "/wiki/x/AbC1\nParent: " + PAGE + "\n")
            result = local_config.read_setup(path)
        self.assertEqual(result["setup"], "short-link")

    def test_line_that_only_mentions_parent_is_skipped(self):
        with helpers.TempDir() as folder:
            path = write(folder, "SETUP.md",
                         "The Parent: line says where pages go.\nParent: " + PAGE + "\n")
            result = local_config.read_setup(path)
        self.assertEqual(result["setup"], "ok")

    def test_empty_parent_value_is_placeholder(self):
        with helpers.TempDir() as folder:
            result = local_config.read_setup(write(folder, "SETUP.md", "Parent:\n"))
        self.assertEqual(result["setup"], "placeholder")

    def test_committed_template_is_placeholder(self):
        template = os.path.join(local_config.REPO_ROOT, "SETUP.example.md")
        result = local_config.read_setup(template)
        self.assertEqual(result, {"setup": "placeholder", "parent": None, "site": None})

    def test_utf8_byte_order_mark(self):
        with helpers.TempDir() as folder:
            path = os.path.join(folder, "SETUP.md")
            with open(path, "wb") as handle:
                handle.write(b"\xef\xbb\xbfParent: " + PAGE.encode("utf-8") + b"\n")
            result = local_config.read_setup(path)
        self.assertEqual(result["setup"], "ok")

    def test_unreadable_path_counts_as_missing(self):
        with helpers.TempDir() as folder:
            result = local_config.read_setup(folder)  # a folder, not a file
        self.assertEqual(result["setup"], "missing")

    def test_default_path_is_setup_md_in_repo_root(self):
        self.assertEqual(local_config.SETUP_PATH,
                         os.path.join(local_config.REPO_ROOT, "SETUP.md"))
        self.assertEqual(local_config.ENV_PATH,
                         os.path.join(local_config.REPO_ROOT, "atlassian-api.env"))


class ReadCredentialsTests(unittest.TestCase):
    def read(self, text):
        with helpers.TempDir() as folder:
            return local_config.read_credentials(write(folder, "atlassian-api.env", text))

    def test_both_present(self):
        self.assertEqual(
            self.read("ATLASSIAN_EMAIL=me@example.com\nATLASSIAN_API_TOKEN=tok123\n"),
            ("me@example.com", "tok123"))

    def test_credentials_missing_or_empty(self):
        with helpers.TempDir() as folder:
            self.assertIsNone(local_config.read_credentials(os.path.join(folder, "nope.env")))
        self.assertIsNone(self.read(""))
        self.assertIsNone(self.read("ATLASSIAN_EMAIL=\nATLASSIAN_API_TOKEN=\n"))
        self.assertIsNone(self.read("ATLASSIAN_EMAIL=me@example.com\nATLASSIAN_API_TOKEN=\n"))
        self.assertIsNone(self.read("ATLASSIAN_EMAIL=\nATLASSIAN_API_TOKEN=tok\n"))
        self.assertIsNone(self.read("ATLASSIAN_EMAIL=me@example.com\n"))
        self.assertIsNone(self.read("ATLASSIAN_API_TOKEN=tok\n"))
        self.assertIsNone(self.read("ATLASSIAN_EMAIL=   \nATLASSIAN_API_TOKEN=\t\n"))

    def test_committed_template_is_empty(self):
        template = os.path.join(local_config.REPO_ROOT, "atlassian-api.env.example")
        self.assertIsNone(local_config.read_credentials(template))

    def test_token_with_equals(self):
        creds = self.read("ATLASSIAN_EMAIL=me@example.com\nATLASSIAN_API_TOKEN=ab=cd==\n")
        self.assertEqual(creds, ("me@example.com", "ab=cd=="))

    def test_crlf_spaces_comments_and_blank_lines(self):
        text = ("# my token\r\n\r\n  ATLASSIAN_EMAIL = me@example.com  \r\n"
                "ATLASSIAN_API_TOKEN=  tok=1 \r\nOTHER=x\r\n")
        self.assertEqual(self.read(text), ("me@example.com", "tok=1"))

    def test_lines_without_equals_are_skipped(self):
        text = "garbage\nATLASSIAN_EMAIL=me@example.com\nATLASSIAN_API_TOKEN=tok"
        self.assertEqual(self.read(text), ("me@example.com", "tok"))

    def test_prints_nothing(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.read("ATLASSIAN_EMAIL=me@example.com\nATLASSIAN_API_TOKEN=secret-tok\n")
            self.read("ATLASSIAN_EMAIL=\n")
            local_config.read_setup(os.path.join(local_config.REPO_ROOT, "nope.md"))
        self.assertEqual(out.getvalue() + err.getvalue(), "")


class RepoRootTests(unittest.TestCase):
    def test_repo_root(self):
        self.assertTrue(os.path.isdir(os.path.join(local_config.REPO_ROOT, "scripts")))
        self.assertTrue(os.path.isfile(
            os.path.join(local_config.REPO_ROOT, "scripts", "local_config.py")))

    def test_placeholder_matches_the_template(self):
        template = os.path.join(local_config.REPO_ROOT, "SETUP.example.md")
        with open(template, encoding="utf-8") as handle:
            last = [line for line in handle.read().splitlines() if line.strip()][-1]
        self.assertEqual(last, "Parent: " + local_config.PLACEHOLDER)


if __name__ == "__main__":
    unittest.main()
