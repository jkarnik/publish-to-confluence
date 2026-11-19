"""Tests for scripts/flatten.py: macros that block a text update become plain content."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  (puts scripts/ on sys.path)

import flatten

URL = "https://example.atlassian.net/browse/ABC-123"
VIEW = '<p>Tracked in <a href="%s" class="jira-issue-key">ABC-123</a></p>' % URL


def macro(name, params="", body=""):
    return ('<ac:structured-macro ac:name="%s" ac:schema-version="1" ac:macro-id="m-%s">%s%s'
            '</ac:structured-macro>' % (name, name, params, body))


def param(name, value):
    return '<ac:parameter ac:name="%s">%s</ac:parameter>' % (name, value)


def rich(inner):
    return "<ac:rich-text-body>" + inner + "</ac:rich-text-body>"


def plain(text):
    return "<ac:plain-text-body><![CDATA[%s]]></ac:plain-text-body>" % text


def jira_issue(key):
    return macro("jira", param("key", key) + param("server", "System JIRA"))


def jira_list(jql):
    return macro("jira", param("jqlQuery", jql) + param("columns", "key,summary"))


def run(body, view=VIEW):
    return flatten.make_plain(body, view)


class KeepTests(unittest.TestCase):
    def test_keeps_code_and_status(self):
        code = macro("code", param("language", "py"), plain("print('<b>')"))
        status = macro("status", param("title", "Done") + param("colour", "Green"))
        body = "<p>a</p>%s<p>b %s</p>" % (code, status)
        self.assertEqual(run(body), (body, {"jira": 0}, []))

    def test_keeps_code_inside_an_unwrapped_macro(self):
        code = macro("code", "", plain("x = 1"))
        out, counts, _ = run(macro("info", "", rich("<p>t</p>" + code)))
        self.assertEqual(out, "<p>t</p>" + code)
        self.assertEqual(counts, {"jira": 0, "info": 1})

    def test_no_macros_unchanged(self):
        body = "<h1>T</h1><p>Plain <strong>text</strong></p>"
        self.assertEqual(run(body), (body, {"jira": 0}, []))


class JiraTests(unittest.TestCase):
    def test_jira_issue_to_link(self):
        body = "<p>See %s now.</p>" % jira_issue("ABC-123")
        out, counts, unresolved = run(body)
        self.assertEqual(out, '<p>See <a href="%s">%s</a> now.</p>' % (URL, URL))
        self.assertEqual(counts, {"jira": 1})
        self.assertEqual(unresolved, [])

    def test_unresolved_issue_left_and_listed(self):
        body = "<p>%s</p>" % jira_issue("ABC-999")
        out, counts, unresolved = run(body)
        self.assertEqual(out, body)
        self.assertEqual(counts, {"jira": 0})
        self.assertEqual(unresolved, ["ABC-999"])

    def test_jira_list_to_text(self):
        body = "<p>Before</p>%s<p>After</p>" % jira_list("project = ABC AND status = \"Open\" & x < 3")
        out, counts, unresolved = run(body)
        self.assertEqual(
            out, "<p>Before</p><p>Jira list: project = ABC AND status = \"Open\" &amp; x &lt; 3</p>"
                 "<p>After</p>")
        self.assertEqual(counts, {"jira": 0, "jiraList": 1})
        self.assertEqual(unresolved, [])

    def test_jira_list_alone_in_table_cell_is_a_paragraph(self):
        body = "<table><tbody><tr><td>%s</td></tr></tbody></table>" % jira_list("project = ABC")
        out, _, _ = run(body)
        self.assertEqual(out, "<table><tbody><tr><td><p>Jira list: project = ABC</p></td></tr></tbody></table>")

    def test_jira_list_alone_in_list_item_is_a_paragraph(self):
        out, _, _ = run("<ul><li>\n%s\n</li></ul>" % jira_list("project = ABC"))
        self.assertEqual(out, "<ul><li>\n<p>Jira list: project = ABC</p>\n</li></ul>")

    def test_jira_list_after_a_block_in_a_cell_is_a_paragraph(self):
        out, _, _ = run("<table><tbody><tr><td><p>x</p>%s</td></tr></tbody></table>" % jira_list("a = b"))
        self.assertIn("<td><p>x</p><p>Jira list: a = b</p></td>", out)

    def test_jira_list_inline_is_plain_text(self):
        out, counts, _ = run("<p>Open: %s today</p>" % jira_list("project = ABC"))
        self.assertEqual(out, "<p>Open: Jira list: project = ABC today</p>")
        self.assertEqual(counts["jiraList"], 1)

    def test_jira_list_in_cell_with_text_is_inline(self):
        out, _, _ = run("<table><tbody><tr><td>Open: %s</td></tr></tbody></table>" % jira_list("a = b"))
        self.assertIn("<td>Open: Jira list: a = b</td>", out)

    def test_jira_list_in_cell_with_inline_element_is_inline(self):
        out, _, _ = run("<ul><li><strong>Open</strong> %s</li></ul>" % jira_list("a = b"))
        self.assertEqual(out, "<ul><li><strong>Open</strong> Jira list: a = b</li></ul>")

    def test_jira_list_with_xml_escaped_jql(self):
        out, _, _ = run(jira_list("summary ~ &quot;a&quot; AND x &gt; 1"))
        self.assertEqual(out, '<p>Jira list: summary ~ "a" AND x &gt; 1</p>')


class UnwrapTests(unittest.TestCase):
    def test_info_panel_unwrapped(self):
        body = ("<p>a</p>%s%s%s%s<p>z</p>"
                % (macro("info", param("title", "Heads up"), rich("<p>Info text</p>")),
                   macro("note", "", rich("<p>Note text</p>")),
                   macro("panel", param("bgColor", "#eee"), rich("<p>Panel <em>text</em></p>")),
                   macro("excerpt", "", rich("<p>Excerpt text</p>"))))
        out, counts, _ = run(body)
        self.assertEqual(out, "<p>a</p><p>Info text</p><p>Note text</p><p>Panel <em>text</em></p>"
                              "<p>Excerpt text</p><p>z</p>")
        self.assertEqual(counts, {"jira": 0, "info": 1, "note": 1, "panel": 1, "excerpt": 1})

    def test_any_other_macro_with_rich_body_is_unwrapped(self):
        out, counts, _ = run(macro("tip", "", rich("<p>Tip</p>")) + macro("warning", "", rich("<p>W</p>")))
        self.assertEqual(out, "<p>Tip</p><p>W</p>")
        self.assertEqual(counts, {"jira": 0, "tip": 1, "warning": 1})

    def test_expand_keeps_title_and_body(self):
        body = macro("expand", param("title", "More &amp; &lt;more&gt;"),
                     rich("<p>Hidden</p><ul><li>one</li></ul>"))
        out, counts, _ = run(body)
        self.assertEqual(out, "<p><strong>More &amp; &lt;more&gt;</strong></p><p>Hidden</p><ul><li>one</li></ul>")
        self.assertEqual(counts, {"jira": 0, "expand": 1})

    def test_expand_without_title_has_no_title_paragraph(self):
        out, _, _ = run(macro("expand", "", rich("<p>Hidden</p>")))
        self.assertEqual(out, "<p>Hidden</p>")

    def test_only_expand_gets_a_title_paragraph(self):
        out, _, _ = run(macro("panel", param("title", "Box"), rich("<p>x</p>")))
        self.assertEqual(out, "<p>x</p>")

    def test_empty_rich_body(self):
        out, counts, _ = run("<p>a</p>" + macro("info", "", "<ac:rich-text-body></ac:rich-text-body>"))
        self.assertEqual(out, "<p>a</p>")
        self.assertEqual(counts["info"], 1)

    def test_toc_removed(self):
        body = "<p>a</p>%s<p>b</p>%s<p>c</p>" % (
            macro("toc", param("maxLevel", "3")),
            '<ac:structured-macro ac:name="children" ac:schema-version="2" />')
        out, counts, _ = run(body)
        self.assertEqual(out, "<p>a</p><p>b</p><p>c</p>")
        self.assertEqual(counts, {"jira": 0, "toc": 1, "children": 1})

    def test_noformat_to_paragraph(self):
        out, counts, _ = run(macro("noformat", "", plain("a < b && c\nsecond line")))
        self.assertEqual(out, "<p>a &lt; b &amp;&amp; c\nsecond line</p>")
        self.assertEqual(counts, {"jira": 0, "noformat": 1})

    def test_other_macro_with_plain_body_only(self):
        out, counts, _ = run(macro("widget", "", plain("hello")))
        self.assertEqual(out, "<p>hello</p>")
        self.assertEqual(counts["widget"], 1)


class NestedTests(unittest.TestCase):
    def test_nested_macros(self):
        inner = macro("panel", "", rich("<p>deep</p>" + macro("toc") + jira_issue("ABC-123")))
        body = "<p>a</p>" + macro("expand", param("title", "Outer"), rich("<p>mid</p>" + inner)) + "<p>z</p>"
        out, counts, unresolved = run(body)
        self.assertEqual(out, "<p>a</p><p><strong>Outer</strong></p><p>mid</p><p>deep</p>"
                              '<a href="%s">%s</a><p>z</p>' % (URL, URL))
        self.assertEqual(counts, {"jira": 1, "expand": 1, "panel": 1, "toc": 1})
        self.assertEqual(unresolved, [])

    def test_nested_jira_list_sees_its_final_position(self):
        body = ("<table><tbody><tr><td>%s</td></tr></tbody></table>"
                % macro("info", "", rich(jira_list("a = b"))))
        out, _, _ = run(body)
        self.assertEqual(out, "<table><tbody><tr><td><p>Jira list: a = b</p></td></tr></tbody></table>")

    def test_three_levels_deep(self):
        body = macro("info", "", rich(macro("note", "", rich(macro("tip", "", rich("<p>x</p>"))))))
        out, counts, _ = run(body)
        self.assertEqual(out, "<p>x</p>")
        self.assertEqual(counts, {"jira": 0, "info": 1, "note": 1, "tip": 1})

    def test_unresolved_jira_inside_unwrapped_body_stays(self):
        stuck = jira_issue("ABC-999")
        out, counts, unresolved = run(macro("info", "", rich("<p>%s</p>" % stuck)))
        self.assertEqual(out, "<p>%s</p>" % stuck)
        self.assertEqual(counts, {"jira": 0, "info": 1})
        self.assertEqual(unresolved, ["ABC-999"])


class MarkerTests(unittest.TestCase):
    def test_markers_kept_inside_unwrapped_body(self):
        marker = '<ac:inline-comment-marker ac:ref="r-1">this part</ac:inline-comment-marker>'
        body = "<p>a</p>" + macro("info", "", rich("<p>See %s of it.</p>" % marker)) + "<p>z</p>"
        out, _, _ = run(body)
        self.assertEqual(out, "<p>a</p><p>See %s of it.</p><p>z</p>" % marker)

    def test_marker_around_a_removed_macro_text_stays(self):
        marker = '<ac:inline-comment-marker ac:ref="r-2">%s</ac:inline-comment-marker>'
        body = "<p>%s</p>" % (marker % ("Open: " + jira_list("a = b")))
        out, _, _ = run(body)
        self.assertEqual(out, "<p>%s</p>" % (marker % "Open: Jira list: a = b"))


class CountsTests(unittest.TestCase):
    def test_counts(self):
        body = ("<p>%s</p>%s%s%s%s%s%s%s" % (
            jira_issue("ABC-123") + jira_issue("ABC-123") + jira_issue("ABC-999"),
            jira_list("a = b"), jira_list("c = d"),
            macro("info", "", rich("<p>1</p>")), macro("info", "", rich("<p>2</p>")),
            macro("toc"), macro("noformat", "", plain("n")),
            macro("code", "", plain("keep"))))
        out, counts, unresolved = run(body)
        self.assertEqual(counts, {"jira": 2, "jiraList": 2, "info": 2, "toc": 1, "noformat": 1})
        self.assertEqual(unresolved, ["ABC-999"])
        self.assertIn(macro("code", "", plain("keep")), out)

    def test_second_run_changes_nothing(self):
        body = "<p>a</p>" + macro("info", "", rich(macro("toc") + "<p>x</p>" + jira_issue("ABC-123")))
        once = run(body)[0]
        out, counts, unresolved = run(once)
        self.assertEqual((out, counts, unresolved), (once, {"jira": 0}, []))

    def test_view_html_may_be_empty(self):
        out, counts, unresolved = run("<p>%s</p>" % jira_issue("ABC-1"), "")
        self.assertEqual(counts, {"jira": 0})
        self.assertEqual(unresolved, ["ABC-1"])


if __name__ == "__main__":
    unittest.main()
