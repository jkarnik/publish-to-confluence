"""Tests for scripts/merge_files.py: preview a merge by section, apply it with a backup."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import errno
import os.path
import stat
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import helpers
import merge_files

NOW = datetime(2026, 11, 19, 10, 15, 0, tzinfo=timezone.utc)

BASE = (
    "# Network 360\n"
    "\n"
    "## Scope\n"
    "\n"
    "We cover the core flow.\n"
    "\n"
    "## Stages\n"
    "\n"
    "### Ingest\n"
    "\n"
    "Read the flow records.\n"
)


def write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def change(section, kind, before, after):
    return {"section": section, "kind": kind, "before": before, "after": after}


class PreviewTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(merge_files.preview(BASE, BASE), {"identical": True, "changes": []})

    def test_blank_lines_and_line_endings_are_not_changes(self):
        other = BASE.replace("\n\n", "\n\n\n").replace("\n", "\r\n") + "\n\n"
        self.assertEqual(merge_files.preview(BASE, other), {"identical": True, "changes": []})

    def test_changed_sentence(self):
        proposed = BASE.replace("We cover the core flow.", "We cover the core flow and exports.")
        self.assertEqual(merge_files.preview(BASE, proposed), {
            "identical": False,
            "changes": [change("Scope", "changed", "We cover the core flow.",
                               "We cover the core flow and exports.")],
        })

    def test_added_section(self):
        proposed = BASE + "\n## Related work\n\nSee ABC-123 for the plan.\nAlso ABC-124.\n"
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Related work", "added", "", "See ABC-123 for the plan."),
        ])

    def test_added_section_without_body_shows_its_heading(self):
        proposed = BASE + "\n## Risks\n"
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Risks", "added", "", "Risks"),
        ])

    def test_deleted_section(self):
        proposed = BASE.split("## Stages")[0]
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Stages", "deleted", "Stages", ""),
            change("Stages > Ingest", "deleted", "Read the flow records.", ""),
        ])

    def test_deleted_lines(self):
        before = "# Doc\n\n## Goals\n\n- one\n- two\n- three\n- four\n"
        after = "# Doc\n\n## Goals\n\n- one\n- four\n"
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Goals", "deleted", "- two - three", ""),
        ])

    def test_added_lines_in_an_existing_section(self):
        before = "# Doc\n\n## Goals\n\n- one\n"
        after = "# Doc\n\n## Goals\n\n- one\n- two\n"
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Goals", "added", "", "- two"),
        ])

    def test_changes_come_in_document_order(self):
        proposed = (BASE.replace("core flow.", "core flow only.")
                    .replace("Read the flow records.", "Read the flow records fast.")
                    + "\n## Wrap-up\n\nDone.\n")
        sections = [c["section"] for c in merge_files.preview(BASE, proposed)["changes"]]
        self.assertEqual(sections, ["Scope", "Stages > Ingest", "Wrap-up"])

    def test_title_change(self):
        proposed = BASE.replace("# Network 360\n", "# Network 360 scope\n", 1)
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Title", "changed", "Network 360", "Network 360 scope"),
        ])

    def test_nested_path(self):
        proposed = BASE.replace("Read the flow records.", "Read the flow records and logs.")
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Stages > Ingest", "changed", "Read the flow records.",
                   "Read the flow records and logs."),
        ])

    def test_sibling_heading_pops_the_path(self):
        before = "# Doc\n\n## Stages\n\n### Ingest\n\nA.\n\n### Store\n\nB.\n\n## Wrap-up\n\nC.\n"
        after = before.replace("B.", "B2.").replace("C.", "C2.")
        sections = [c["section"] for c in merge_files.preview(before, after)["changes"]]
        self.assertEqual(sections, ["Stages > Store", "Wrap-up"])

    def test_text_before_the_first_heading_is_top(self):
        before = "Intro line.\n\n# Doc\n\n## Scope\n\nBody.\n"
        after = before.replace("Intro line.", "Intro line, longer.")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("(top)", "changed", "Intro line.", "Intro line, longer."),
        ])

    def test_text_added_before_the_first_heading(self):
        before = "# Doc\n\nBody.\n"
        after = "Intro line.\n\n# Doc\n\nBody.\n"
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("(top)", "added", "", "Intro line."),
        ])

    def test_a_later_title_level_heading_starts_a_new_top_level_section(self):
        before = "# Doc\n\n## Scope\n\nA.\n\n# Appendix\n\n## Notes\n\nB.\n"
        after = before.replace("B.", "B2.")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Appendix > Notes", "changed", "B.", "B2."),
        ])

    def test_fence_hash_not_heading(self):
        before = "# Doc\n\n## Setup\n\n```bash\n# install\nrun it\n```\n\n## Next\n\nGo.\n"
        after = before.replace("run it", "run it twice")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Setup", "changed", "run it", "run it twice"),
        ])

    def test_tilde_and_longer_fences(self):
        before = "# Doc\n\n## Setup\n\n~~~\n## not a heading\n~~~\n\n````\n```\n# still code\n````\n\nEnd.\n"
        after = before.replace("End.", "End!")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Setup", "changed", "End.", "End!"),
        ])

    def test_hash_without_a_space_is_not_a_heading(self):
        before = "# Doc\n\n## Tags\n\n#networking\n"
        after = before.replace("#networking", "#networking #flow")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Tags", "changed", "#networking", "#networking #flow"),
        ])

    def test_closing_hashes_are_not_part_of_the_heading(self):
        before = "# Doc ##\n\n## Scope ##\n\nA.\n"
        after = before.replace("A.", "B.")
        self.assertEqual(merge_files.preview(before, after)["changes"], [
            change("Scope", "changed", "A.", "B."),
        ])

    def test_renamed_section_is_paired(self):
        proposed = BASE.replace("## Scope\n", "## Scope and goals\n")
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Scope and goals", "changed", "Scope", "Scope and goals"),
        ])

    def test_renamed_parent_leaves_its_children_quiet(self):
        proposed = BASE.replace("## Stages\n", "## Phases\n")
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Phases", "changed", "Stages", "Phases"),
        ])

    def test_heading_level_change_shows_the_marks(self):
        proposed = BASE.replace("### Ingest", "## Ingest")
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"], [
            change("Ingest", "changed", "### Ingest", "## Ingest"),
        ])

    def test_snippet_cut(self):
        long_line = "word " * 80
        proposed = BASE.replace("We cover the core flow.", long_line.strip())
        result = merge_files.preview(BASE, proposed)["changes"][0]
        self.assertEqual(len(result["after"]), merge_files.SNIPPET)
        self.assertTrue(result["after"].endswith("…"))
        self.assertEqual(result["before"], "We cover the core flow.")

    def test_snippet_of_exactly_the_limit_is_kept(self):
        line = "x" * merge_files.SNIPPET
        proposed = BASE.replace("We cover the core flow.", line)
        self.assertEqual(merge_files.preview(BASE, proposed)["changes"][0]["after"], line)
        proposed = BASE.replace("We cover the core flow.", line + "y")
        after = merge_files.preview(BASE, proposed)["changes"][0]["after"]
        self.assertEqual((len(after), after[-1]), (merge_files.SNIPPET, "…"))

    def test_joined_lines_are_cut_too(self):
        before = "# Doc\n\n## Goals\n\nkeep\n"
        after = "# Doc\n\n## Goals\n\nkeep\n" + "".join("line %d is here\n" % n for n in range(30))
        added = merge_files.preview(before, after)["changes"][0]["after"]
        self.assertEqual(len(added), merge_files.SNIPPET)
        self.assertTrue(added.startswith("line 0 is here line 1 is here"))

    def test_output_is_json_ready(self):
        import json
        json.dumps(merge_files.preview(BASE, BASE.replace("flow.", "flows.")))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.folder = self.tmp.__enter__()
        self.addCleanup(self.tmp.__exit__, None, None, None)
        self.backups = os.path.join(self.folder, "backups")
        self.file = write(self.folder, "notes.md", "old text\n")
        self.proposed = write(self.folder, "notes-proposed.md", "new text\n")

    def test_apply(self):
        result = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        backup = os.path.join(self.backups, "notes-20261119T101500Z.md")
        self.assertEqual(result, {"file": self.file, "backup": backup})
        self.assertEqual(read(backup), "old text\n")
        self.assertEqual(read(self.file), "new text\n")
        self.assertFalse(os.path.exists(self.proposed))

    def test_apply_keeps_the_files_mode(self):
        os.chmod(self.file, 0o640)
        os.chmod(self.proposed, 0o600)
        merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o640)

    def test_apply_same_second(self):
        first = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        write(self.folder, "notes-proposed.md", "newer text\n")
        second = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        write(self.folder, "notes-proposed.md", "newest text\n")
        third = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        self.assertEqual(os.path.basename(first["backup"]), "notes-20261119T101500Z.md")
        self.assertEqual(os.path.basename(second["backup"]), "notes-20261119T101500Z-2.md")
        self.assertEqual(os.path.basename(third["backup"]), "notes-20261119T101500Z-3.md")
        self.assertEqual(read(first["backup"]), "old text\n")
        self.assertEqual(read(second["backup"]), "new text\n")
        self.assertEqual(read(third["backup"]), "newer text\n")
        self.assertEqual(read(self.file), "newest text\n")

    def test_apply_names_the_backup_in_utc(self):
        zone = timezone(timedelta(hours=-5))
        local = datetime(2026, 11, 19, 5, 15, 0, tzinfo=zone)
        result = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=local)
        self.assertEqual(os.path.basename(result["backup"]), "notes-20261119T101500Z.md")

    def test_apply_without_now_uses_the_clock(self):
        result = merge_files.apply(self.file, self.proposed, backup_dir=self.backups)
        name = os.path.basename(result["backup"])
        self.assertRegex(name, r"^notes-\d{8}T\d{6}Z\.md$")

    def test_apply_creates_the_backup_folder(self):
        deep = os.path.join(self.folder, "a", "b")
        merge_files.apply(self.file, self.proposed, backup_dir=deep, now=NOW)
        self.assertTrue(os.path.isfile(os.path.join(deep, "notes-20261119T101500Z.md")))

    def test_apply_keeps_text_byte_for_byte(self):
        original = "café\r\nline\r\n"
        write(self.folder, "notes.md", original)
        write(self.folder, "notes-proposed.md", "naïve\r\n")
        result = merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        self.assertEqual(read(result["backup"]), original)
        self.assertEqual(read(self.file), "naïve\r\n")

    def test_apply_across_drives(self):
        real_replace = os.replace
        calls = []

        def replace(source, target):
            calls.append((source, target))
            if source == self.proposed:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(source, target)

        os.chmod(self.file, 0o640)
        with mock.patch.object(merge_files.os, "replace", side_effect=replace):
            merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        self.assertEqual(read(self.file), "new text\n")
        self.assertFalse(os.path.exists(self.proposed))
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o640)
        self.assertEqual(sorted(os.listdir(self.folder)), ["backups", "notes.md"])

    def test_apply_other_replace_errors_leave_the_file_alone(self):
        with mock.patch.object(merge_files.os, "replace",
                               side_effect=OSError(errno.EACCES, "Permission denied")):
            with self.assertRaises(OSError):
                merge_files.apply(self.file, self.proposed, backup_dir=self.backups, now=NOW)
        self.assertEqual(read(self.file), "old text\n")
        self.assertEqual(read(self.proposed), "new text\n")

    def test_apply_refuses_the_same_file(self):
        with self.assertRaises(ValueError):
            merge_files.apply(self.file, self.file, backup_dir=self.backups, now=NOW)
        self.assertEqual(read(self.file), "old text\n")
        self.assertFalse(os.path.exists(self.backups))

    def test_apply_refuses_a_second_name_for_the_same_file(self):
        link = os.path.join(self.folder, "alias.md")
        os.link(self.file, link)
        with self.assertRaises(ValueError):
            merge_files.apply(self.file, link, backup_dir=self.backups, now=NOW)
        self.assertEqual(read(self.file), "old text\n")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.folder = self.tmp.__enter__()
        self.addCleanup(self.tmp.__exit__, None, None, None)
        self.file = write(self.folder, "notes.md", BASE)
        self.proposed = write(self.folder, "notes-proposed.md",
                              BASE.replace("core flow.", "core flows."))

    def test_run_preview(self):
        out, code = merge_files.run_preview(self.file, self.proposed)
        self.assertEqual(code, 0)
        self.assertEqual(out, {"identical": False, "changes": [
            change("Scope", "changed", "We cover the core flow.", "We cover the core flows.")]})
        self.assertEqual(read(self.file), BASE)

    def test_run_preview_identical(self):
        out, code = merge_files.run_preview(self.file, self.file)
        self.assertEqual((out, code), ({"identical": True, "changes": []}, 0))

    def test_run_preview_reads_utf8(self):
        write(self.folder, "a.md", "# Doc\n\n## Scope\n\ncafé\n")
        write(self.folder, "b.md", "# Doc\n\n## Scope\n\ncafé au lait\n")
        out, _ = merge_files.run_preview(os.path.join(self.folder, "a.md"),
                                         os.path.join(self.folder, "b.md"))
        self.assertEqual(out["changes"][0]["before"], "café")

    def test_run_missing_file(self):
        missing = os.path.join(self.folder, "missing.md")
        for runner in (merge_files.run_preview, merge_files.run_apply):
            for args in ((missing, self.proposed), (self.file, missing)):
                out, code = runner(*args)
                self.assertEqual(code, 1)
                self.assertEqual(list(out), ["error"])
                self.assertIn("missing.md", out["error"])
        self.assertEqual(read(self.file), BASE)
        self.assertTrue(os.path.exists(self.proposed))

    def test_run_unreadable_file(self):
        folder_path = os.path.join(self.folder, "a-folder")
        os.mkdir(folder_path)
        binary = os.path.join(self.folder, "binary.md")
        with open(binary, "wb") as handle:
            handle.write(b"\xff\xfe\x00bad")
        for bad in (folder_path, binary):
            for runner in (merge_files.run_preview, merge_files.run_apply):
                out, code = runner(self.file, bad)
                self.assertEqual(code, 1)
                self.assertEqual(list(out), ["error"])
                self.assertIn(os.path.basename(bad), out["error"])
        self.assertEqual(read(self.file), BASE)

    def test_run_apply(self):
        result = {"file": self.file, "backup": "somewhere/notes-20261119T101500Z.md"}
        with mock.patch.object(merge_files, "apply", return_value=result) as apply:
            out, code = merge_files.run_apply(self.file, self.proposed)
        apply.assert_called_once_with(self.file, self.proposed)
        self.assertEqual((out, code), (result, 0))

    def test_run_apply_same_path(self):
        with mock.patch.object(merge_files, "apply") as apply:
            out, code = merge_files.run_apply(self.file, self.file)
        self.assertEqual(code, 1)
        self.assertEqual(list(out), ["error"])
        apply.assert_not_called()
        self.assertEqual(read(self.file), BASE)

    def test_run_apply_reports_a_write_failure(self):
        with mock.patch.object(merge_files, "apply",
                               side_effect=OSError(errno.EACCES, "Permission denied")):
            out, code = merge_files.run_apply(self.file, self.proposed)
        self.assertEqual(code, 1)
        self.assertEqual(list(out), ["error"])
        self.assertIn("Permission denied", out["error"])


if __name__ == "__main__":
    unittest.main()
