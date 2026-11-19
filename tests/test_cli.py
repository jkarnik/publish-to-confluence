"""Tests for the entry point scripts/confluence_rest.py."""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

# Works for both "python3 -m unittest discover -s tests" and
# "python3 -m unittest tests.test_cli" from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

import confluence_rest  # noqa: E402
import local_config  # noqa: E402
import merge_files  # noqa: E402
import mode_check  # noqa: E402
import mode_comments  # noqa: E402
import mode_download  # noqa: E402
import mode_finish  # noqa: E402
import mode_prepare  # noqa: E402
import rest_client  # noqa: E402

SETUP_OK = {"setup": "ok", "parent": "123", "site": "https://example.atlassian.net/wiki"}
CREDENTIALS = ("me@example.com", "secret-token-value")


def run_main(argv):
    """Call main(argv); return (exit code, parsed stdout JSON, raw stdout)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = confluence_rest.main(argv)
    raw = out.getvalue()
    return code, json.loads(raw), raw


class UsageTests(unittest.TestCase):
    def test_no_args_prints_usage_exit_1(self):
        code, out, _ = run_main([])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("usage"))

    def test_unknown_mode_exit_1(self):
        code, out, _ = run_main(["frobnicate"])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("usage"))

    def test_wrong_argument_count_exit_1(self):
        for argv in (["check", "extra"], ["comments", "123"], ["prepare"],
                     ["finish", "123"], ["preview-merge", "a.md"],
                     ["apply-merge", "a.md", "b.md", "c.md"],
                     ["download", "123", "pic.png"]):
            with self.subTest(argv=argv):
                code, out, _ = run_main(argv)
                self.assertEqual(code, 1)
                self.assertTrue(out["error"].startswith("usage"))

    def test_page_id_must_be_digits(self):
        for page_id in ("abc", "12a", "", "../etc", "1 2"):
            with self.subTest(page_id=page_id):
                code, out, _ = run_main(["comments", page_id, "a.md"])
                self.assertEqual(code, 1)
                self.assertTrue(out["error"].startswith("usage"))

    def test_unknown_option_exit_1(self):
        code, out, _ = run_main(["prepare", "123", "a.md", "--force"])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("usage"))

    def test_before_must_be_a_whole_number(self):
        for argv in (["finish", "123", "a.md", "--before", "x"],
                     ["finish", "123", "a.md", "--before"],
                     ["finish", "123", "a.md", "--before", "-3"]):
            with self.subTest(argv=argv):
                code, out, _ = run_main(argv)
                self.assertEqual(code, 1)
                self.assertTrue(out["error"].startswith("usage"))


class CheckTests(unittest.TestCase):
    def test_check_calls_mode_check(self):
        with mock.patch.object(mode_check, "run", return_value=({"setup": "ok"}, 0)) as run:
            code, out, _ = run_main(["check"])
        self.assertEqual(code, 0)
        self.assertEqual(out, {"setup": "ok"})
        run.assert_called_once_with(local_config.SETUP_PATH, local_config.ENV_PATH)

    def test_check_returns_the_mode_exit_code(self):
        with mock.patch.object(mode_check, "run", return_value=({"setup": "missing"}, 2)):
            code, out, _ = run_main(["check"])
        self.assertEqual(code, 2)
        self.assertEqual(out, {"setup": "missing"})


class ClientModeTests(unittest.TestCase):
    def patch_config(self, setup=None, credentials=CREDENTIALS):
        setup = SETUP_OK if setup is None else setup
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(local_config, "read_setup", return_value=setup))
        stack.enter_context(mock.patch.object(local_config, "read_credentials", return_value=credentials))
        self.client_class = stack.enter_context(mock.patch.object(rest_client, "RestClient"))
        self.addCleanup(stack.close)

    def test_comments_without_token_exit_2(self):
        with mock.patch.object(local_config, "read_setup", return_value=SETUP_OK), \
                mock.patch.object(local_config, "read_credentials", return_value=None), \
                mock.patch.object(mode_comments, "run") as run:
            code, out, _ = run_main(["comments", "123", "a.md"])
        self.assertEqual(code, 2)
        self.assertEqual(out, {"error": "token", "token": "missing"})
        run.assert_not_called()

    def test_setup_missing_exit_2(self):
        with mock.patch.object(local_config, "read_setup",
                               return_value={"setup": "missing", "parent": None, "site": None}), \
                mock.patch.object(local_config, "read_credentials", return_value=CREDENTIALS), \
                mock.patch.object(mode_comments, "run") as run:
            code, out, _ = run_main(["comments", "123", "a.md"])
        self.assertEqual(code, 2)
        self.assertEqual(out, {"error": "setup", "setup": "missing"})
        run.assert_not_called()

    def test_every_client_mode_needs_setup_and_token(self):
        argvs = (["comments", "123", "a.md"], ["prepare", "123", "a.md"],
                 ["finish", "123", "a.md"], ["download", "123", "pic.png", "out.png"])
        for argv in argvs:
            with self.subTest(argv=argv):
                with mock.patch.object(local_config, "read_setup",
                                       return_value={"setup": "placeholder", "parent": None, "site": None}), \
                        mock.patch.object(local_config, "read_credentials", return_value=CREDENTIALS):
                    code, out, _ = run_main(argv)
                self.assertEqual((code, out), (2, {"error": "setup", "setup": "placeholder"}))
                with mock.patch.object(local_config, "read_setup", return_value=SETUP_OK), \
                        mock.patch.object(local_config, "read_credentials", return_value=None):
                    code, out, _ = run_main(argv)
                self.assertEqual((code, out), (2, {"error": "token", "token": "missing"}))

    def test_comments_wiring(self):
        self.patch_config()
        with mock.patch.object(mode_comments, "run", return_value=({"pageId": "123"}, 0)) as run:
            code, out, _ = run_main(["comments", "123", "notes.md"])
        self.assertEqual((code, out), (0, {"pageId": "123"}))
        self.client_class.assert_called_once_with("https://example.atlassian.net/wiki", *CREDENTIALS)
        run.assert_called_once_with("123", os.path.abspath("notes.md"), self.client_class.return_value)

    def test_finish_passes_before_as_int(self):
        self.patch_config()
        with mock.patch.object(mode_finish, "run", return_value=({"version": 8}, 0)) as run:
            code, out, _ = run_main(["finish", "123", "notes.md", "--before", "7"])
        self.assertEqual((code, out), (0, {"version": 8}))
        run.assert_called_once_with("123", os.path.abspath("notes.md"), 7, self.client_class.return_value)

    def test_finish_before_defaults_to_none(self):
        self.patch_config()
        with mock.patch.object(mode_finish, "run", return_value=({}, 0)) as run:
            run_main(["finish", "123", "notes.md"])
        self.assertIsNone(run.call_args[0][2])

    def test_prepare_overwrite_flag(self):
        self.patch_config()
        with mock.patch.object(mode_prepare, "run", return_value=({"version": 6}, 1)) as run:
            code, _, _ = run_main(["prepare", "123", "notes.md", "--overwrite"])
            self.assertEqual(code, 1)
            self.assertIs(run.call_args[0][2], True)
            run_main(["prepare", "123", "notes.md"])
            self.assertIs(run.call_args[0][2], False)
            run_main(["prepare", "--overwrite", "123", "notes.md"])
            self.assertEqual(run.call_args[0][:2], ("123", os.path.abspath("notes.md")))
            self.assertIs(run.call_args[0][2], True)

    def test_download_wiring(self):
        self.patch_config()
        with mock.patch.object(mode_download, "run", return_value=({"saved": "x"}, 0)) as run:
            code, out, _ = run_main(["download", "123", "pic.png", "out/pic.png"])
        self.assertEqual((code, out), (0, {"saved": "x"}))
        self.client_class.assert_called_once_with("https://example.atlassian.net/wiki", *CREDENTIALS)
        run.assert_called_once_with("123", "pic.png", os.path.abspath("out/pic.png"),
                                    self.client_class.return_value)

    def test_unexpected_error_prints_json_exit_1_without_token(self):
        self.patch_config()
        boom = RuntimeError("failed with " + CREDENTIALS[1])
        with mock.patch.object(mode_comments, "run", side_effect=boom):
            code, out, raw = run_main(["comments", "123", "a.md"])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("RuntimeError: failed with"))
        self.assertNotIn(CREDENTIALS[1], raw)

    def test_not_implemented_error_is_not_caught(self):
        self.patch_config()
        with mock.patch.object(mode_comments, "run", side_effect=NotImplementedError):
            with self.assertRaises(NotImplementedError):
                run_main(["comments", "123", "a.md"])


class MergeModeTests(unittest.TestCase):
    def test_merge_modes_need_no_token(self):
        with mock.patch.object(local_config, "read_setup", side_effect=AssertionError("setup read")), \
                mock.patch.object(local_config, "read_credentials", side_effect=AssertionError("token read")), \
                mock.patch.object(merge_files, "run_preview", return_value=({"identical": True}, 0)) as preview, \
                mock.patch.object(merge_files, "run_apply", return_value=({"file": "f", "backup": "b"}, 0)) as apply:
            code, out, _ = run_main(["preview-merge", "notes.md", "proposed.md"])
            self.assertEqual((code, out), (0, {"identical": True}))
            preview.assert_called_once_with(os.path.abspath("notes.md"), os.path.abspath("proposed.md"))
            code, out, _ = run_main(["apply-merge", "notes.md", "proposed.md"])
            self.assertEqual((code, out), (0, {"file": "f", "backup": "b"}))
            apply.assert_called_once_with(os.path.abspath("notes.md"), os.path.abspath("proposed.md"))

    def test_output_is_indented_json_with_unicode_kept(self):
        with mock.patch.object(merge_files, "run_preview", return_value=({"note": "café"}, 0)):
            _, _, raw = run_main(["preview-merge", "a.md", "b.md"])
        self.assertIn("café", raw)
        self.assertIn('\n  "note"', raw)


class WholeProgramTests(unittest.TestCase):
    def test_all_modules_import(self):
        names = sorted(f[:-3] for f in os.listdir(helpers.SCRIPTS_DIR) if f.endswith(".py"))
        self.assertIn("confluence_rest", names)
        for name in names:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_runs_under_dash_I(self):
        script = os.path.join(helpers.SCRIPTS_DIR, "confluence_rest.py")
        result = subprocess.run([sys.executable, "-I", script], cwd=helpers.REPO_ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(json.loads(result.stdout)["error"].startswith("usage"))


if __name__ == "__main__":
    unittest.main()
