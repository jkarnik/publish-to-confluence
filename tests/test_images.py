"""Tests for scripts/images.py: image size, upload when changed, embeds and placeholders."""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402,F401  (puts scripts/ on sys.path)

import images  # noqa: E402
from markdown_doc import ImageRef  # noqa: E402
from storage import tokenize  # noqa: E402


def write(directory, name, data):
    path = os.path.join(directory, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def ref(directory, src, alt=""):
    """An ImageRef for a file named by src under directory."""
    return ImageRef(alt=alt, src=src, path=os.path.join(directory, src),
                    name=os.path.basename(src))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def jpeg(width, height):
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
    sof = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big")
           + width.to_bytes(2, "big") + b"\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + app0 + sof


def attached(name, extra=""):
    return '<ac:image%s><ri:attachment ri:filename="%s" /></ac:image>' % (extra, name)


class ImageSizeTests(unittest.TestCase):
    def test_image_size_png_gif_jpeg(self):
        with helpers.TempDir() as tmp:
            png = write(tmp, "a.png", helpers.tiny_png(3, 2))
            gif = write(tmp, "a.gif", b"GIF89a" + (7).to_bytes(2, "little")
                        + (5).to_bytes(2, "little") + b"\x00" * 12)
            old_gif = write(tmp, "b.gif", b"GIF87a" + (9).to_bytes(2, "little")
                            + (4).to_bytes(2, "little") + b"\x00" * 12)
            jpg = write(tmp, "a.jpg", jpeg(640, 480))
            self.assertEqual(images.image_size(png), (3, 2))
            self.assertEqual(images.image_size(gif), (7, 5))
            self.assertEqual(images.image_size(old_gif), (9, 4))
            self.assertEqual(images.image_size(jpg), (640, 480))

    def test_image_size_none_for_unknown_or_broken_files(self):
        with helpers.TempDir() as tmp:
            text = write(tmp, "a.txt", b"hello, this is not an image at all")
            no_frame = write(tmp, "b.jpg", b"\xff\xd8\xff\xe0")
            zero_length = write(tmp, "c.jpg", b"\xff\xd8\xff\xe0\x00\x00" * 4)
            cut_short = write(tmp, "d.jpg", b"\xff\xd8\xff\xc0\x00\x11\x08")
            for path in (text, no_frame, zero_length, cut_short, os.path.join(tmp, "gone.png")):
                self.assertIsNone(images.image_size(path), path)


def svg(directory, text, name="a.svg"):
    """Write SVG text (a str) to a file in directory and return its path."""
    return write(directory, name, text.encode("utf-8"))


class SvgSizeTests(unittest.TestCase):
    def test_image_size_svg_width_height(self):
        with helpers.TempDir() as tmp:
            plain = svg(tmp, '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"></svg>')
            rounded = svg(tmp, '<svg width="99.6px" height="10.4px"></svg>', "b.svg")
            single = svg(tmp, "<svg width='300' height='150'></svg>", "c.svg")
            self.assertEqual(images.image_size(plain), (1200, 600))
            self.assertEqual(images.image_size(rounded), (100, 10))
            self.assertEqual(images.image_size(single), (300, 150))

    def test_image_size_svg_width_is_not_read_from_other_attributes(self):
        with helpers.TempDir() as tmp:
            both = svg(tmp, '<svg stroke-width="5" width="300" height="150"></svg>')
            # stroke-width is not the width, so only the height counts and the viewBox scales to it.
            height_only = svg(tmp, '<svg stroke-width="5" height="150" viewBox="0 0 400 200"></svg>', "b.svg")
            no_width = svg(tmp, '<svg stroke-width="5" height="150"></svg>', "c.svg")
            in_a_value = svg(tmp, "<svg data-note='x width=\"5\" height=\"5\"' width=\"300\" height=\"150\"></svg>",
                             "d.svg")
            self.assertEqual(images.image_size(both), (300, 150))
            self.assertEqual(images.image_size(height_only), (300, 150))
            self.assertIsNone(images.image_size(no_width))
            self.assertEqual(images.image_size(in_a_value), (300, 150))

    def test_image_size_svg_absolute_units(self):
        cases = [
            ('width="210mm" height="297mm"', (794, 1123)),
            ('width="2in" height="1in"', (192, 96)),
            ('width="2.54cm" height="1cm"', (96, 38)),
            ('width="72pt" height="36pt"', (96, 48)),
            ('width="10pc" height="5pc"', (160, 80)),
            ('width="101.6Q" height="50.8Q"', (96, 48)),
            ('width="1.2e3" height="6E2px"', (1200, 600)),
            ('width=" 40 " height=".5in"', (40, 48)),
        ]
        with helpers.TempDir() as tmp:
            for attrs, expected in cases:
                path = svg(tmp, "<svg %s></svg>" % attrs)
                self.assertEqual(images.image_size(path), expected, attrs)

    def test_image_size_svg_viewbox(self):
        prolog = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<!-- <svg width="1" height="1"> -->\n'
                  '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                  '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
                  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 250"></svg>')
        split = ('<svg\n   xmlns="http://www.w3.org/2000/svg"\n   width="100%"\n'
                 '   viewBox="0 0 640 320"\n>\n</svg>')
        cases = [
            ("a.svg", '<svg width="100%" height="100%" viewBox="0 0 1200 600"></svg>', (1200, 600)),
            ("b.svg", '<svg viewBox="0,0,400,200"></svg>', (400, 200)),
            ("c.svg", '<svg viewBox=" 0, 0 ,99.6 50.2 "></svg>', (100, 50)),
            ("d.svg", prolog, (500, 250)),
            ("e.svg", split, (640, 320)),
            ("f.svg", '<svg width="50%" height="10em" viewBox="0 0 400 200"></svg>', (400, 200)),
            ("g.svg", '<svg width="3ex" height="1vw" viewBox="-20 -10 400 200"></svg>', (400, 200)),
            ("h.svg", '<svg data-x="a>b" viewBox="0 0 30 20"></svg>', (30, 20)),
            # Not named .svg: the first non-blank text decides.
            ("i.txt", '<svg width="100%" viewBox="0 0 80 40"></svg>', (80, 40)),
            ("j.dat", '\n\n  <?xml version="1.0"?><svg viewBox="0 0 80 40"></svg>', (80, 40)),
            ("k", '<svg>\n</svg>\n', None),
            ("l.SVG", 'not xml first\n<svg viewBox="0 0 70 35"></svg>', (70, 35)),
        ]
        with helpers.TempDir() as tmp:
            for name, text, expected in cases:
                self.assertEqual(images.image_size(svg(tmp, text, name)), expected, name)
            bom = write(tmp, "m.dat", b'\xef\xbb\xbf\n<svg viewBox="0 0 90 45"></svg>')
            self.assertEqual(images.image_size(bom), (90, 45))

    def test_image_size_svg_one_dimension(self):
        cases = [
            ('width="800" viewBox="0 0 400 200"', (800, 400)),
            ('height="100" viewBox="0 0 400 200"', (200, 100)),
            ('width="50%" height="300" viewBox="0 0 400 200"', (600, 300)),
            ('width="4in" height="2em" viewBox="0 0 300 100"', (384, 128)),
            ('width="800" viewBox="10 20 400 200"', (800, 400)),
            ('width="800"', None),
            ('height="800"', None),
            ('width="800" viewBox="0 0 0 0"', None),
            ('width="1" viewBox="0 0 1000 1"', None),  # the height rounds to 0
        ]
        with helpers.TempDir() as tmp:
            for attrs, expected in cases:
                path = svg(tmp, "<svg %s></svg>" % attrs)
                self.assertEqual(images.image_size(path), expected, attrs)

    def test_image_size_svg_unknown(self):
        cases = [
            "<svg></svg>",
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            '<svg viewBox="0 0 0 0"></svg>',
            '<svg viewBox="0 0 100 0"></svg>',
            '<svg viewBox="0 0 -5 10"></svg>',
            '<svg viewBox="0 0 100"></svg>',
            '<svg viewBox="0 0 100 50 7"></svg>',
            '<svg viewBox="0 0 wide high"></svg>',
            '<svg viewBox="0 0 nan inf"></svg>',
            '<svg viewBox=""></svg>',
            '<svg width="0" height="0"></svg>',
            '<svg width="-5" height="10"></svg>',
            '<svg width="1e999" height="10"></svg>',
            '<svg width="50%" height="50%"></svg>',
            "plain text, not an svg at all",
            "",
            '<svg width="10" height="10"',  # the tag never closes
            '<!-- <svg width="10" height="10"></svg>',  # the comment never closes
            "<html><body>hello</body></html>",
        ]
        with helpers.TempDir() as tmp:
            for text in cases:
                self.assertIsNone(images.image_size(svg(tmp, text)), text)
            self.assertIsNone(images.image_size(os.path.join(tmp, "gone.svg")))
            self.assertIsNone(images.image_size(tmp))  # a folder, not a file

    def test_image_size_svg_reads_only_the_first_64k(self):
        late = '<!-- %s -->\n<svg width="10" height="10"></svg>' % ("x" * 70000)
        early = '<!-- %s -->\n<svg width="10" height="10"></svg>' % ("x" * 60000)
        with helpers.TempDir() as tmp:
            self.assertIsNone(images.image_size(svg(tmp, late)))
            self.assertEqual(images.image_size(svg(tmp, early, "b.svg")), (10, 10))

    def test_image_size_png_wins_over_an_svg_name(self):
        with helpers.TempDir() as tmp:
            path = write(tmp, "a.svg", helpers.tiny_png(3, 2))
            self.assertEqual(images.image_size(path), (3, 2))


class EmbedMarkupTests(unittest.TestCase):
    def attrs(self, markup):
        tokens = tokenize(markup)
        return tokens[0].attrs, [t.attrs for t in tokens if t.name == "ri:attachment"][0]

    def test_embed_markup(self):
        image, attachment = self.attrs(images.embed_markup("Diagram", "a.png", (1000, 500)))
        self.assertEqual(image["ac:align"], "center")
        self.assertEqual(image["ac:layout"], "center")
        self.assertEqual(image["ac:width"], "760")
        self.assertEqual(image["ac:custom-width"], "true")
        self.assertEqual(image["ac:original-width"], "1000")
        self.assertEqual(image["ac:original-height"], "500")
        self.assertEqual(image["ac:alt"], "Diagram")
        self.assertEqual(attachment["ri:filename"], "a.png")

    def test_embed_markup_never_upscales(self):
        image, _ = self.attrs(images.embed_markup("", "a.png", (300, 100)))
        self.assertEqual(image["ac:width"], "300")
        image, _ = self.attrs(images.embed_markup("", "a.png", (760, 100)))
        self.assertEqual(image["ac:width"], "760")

    def test_embed_markup_without_a_size_sets_no_width(self):
        image, _ = self.attrs(images.embed_markup("Alt", "a.png", None))
        self.assertEqual(image["ac:align"], "center")
        for key in ("ac:width", "ac:custom-width", "ac:original-width", "ac:original-height"):
            self.assertNotIn(key, image)

    def test_embed_markup_svg_capped(self):
        image, _ = self.attrs(images.embed_markup("Diagram", "a.svg", (1200, 600)))
        self.assertEqual(image["ac:width"], "760")
        self.assertEqual(image["ac:original-width"], "1200")
        self.assertEqual(image["ac:original-height"], "600")

    def test_embed_markup_zero_size(self):
        for size in ((0, 0), (0, 5), (5, 0), (-1, 5), (5, -1)):
            image, _ = self.attrs(images.embed_markup("Alt", "a.svg", size))
            self.assertEqual(image["ac:align"], "center", size)
            for key in ("ac:width", "ac:custom-width", "ac:original-width", "ac:original-height"):
                self.assertNotIn(key, image, size)

    def test_embed_markup_escapes_alt_and_filename(self):
        markup = images.embed_markup('A "quoted" <b> & more', 'my "pic" & <x>.png', (10, 10))
        self.assertIn('ac:alt="A &quot;quoted&quot; &lt;b&gt; &amp; more"', markup)
        self.assertIn('ri:filename="my &quot;pic&quot; &amp; &lt;x&gt;.png"', markup)
        image, attachment = self.attrs(markup)
        self.assertEqual(image["ac:alt"], 'A "quoted" <b> & more')
        self.assertEqual(attachment["ri:filename"], 'my "pic" & <x>.png')


class NotesTests(unittest.TestCase):
    def test_notes(self):
        client = helpers.FakeClient(attachments={"100": {"a.png": "sha256:abc", "b.png": ""}})
        self.assertEqual(images.notes(client, "100"), {"a.png": "sha256:abc", "b.png": ""})

    def test_notes_reads_metadata_comment_too(self):
        class Client:
            def attachments(self, page_id):
                return 200, [{"title": "m.png", "metadata": {"comment": "sha256:m"}},
                             {"title": "e.png", "extensions": {"comment": "sha256:e"},
                              "metadata": {"comment": "ignored"}},
                             {"title": "n.png"},
                             {"title": "x.png", "extensions": None, "metadata": None}]
        self.assertEqual(images.notes(Client(), "100"),
                         {"m.png": "sha256:m", "e.png": "sha256:e", "n.png": "", "x.png": ""})

    def test_notes_is_empty_when_the_read_fails(self):
        client = helpers.FakeClient(attachments={"100": {"a.png": "x"}},
                                    fail={"attachments": (500, "boom")})
        self.assertEqual(images.notes(client, "100"), {})
        self.assertEqual(images.notes(helpers.FakeClient(), "999"), {})  # 404


class ToPlaceholdersTests(unittest.TestCase):
    def test_to_placeholders(self):
        body = ('<p>Text</p>\n<p>' + attached("a.png", ' ac:alt="Alt &amp; one" ac:width="300"')
                + '</p>\n<p>' + attached("b.png", ' ac:alt="Keep"') + '</p>')
        out, count = images.to_placeholders(body, {"a.png"})
        self.assertEqual(count, 1)
        self.assertEqual(out, '<p>Text</p>\n<p><img src="a.png" alt="Alt &amp; one" /></p>\n<p>'
                         + attached("b.png", ' ac:alt="Keep"') + '</p>')

    def test_to_placeholders_without_alt_and_with_reordered_attributes(self):
        body = ('<ac:image ac:width="10" ac:align="center"><ri:attachment ri:version-at-save="2"'
                ' ri:filename="a.png" /></ac:image>'
                '<ac:image ac:align="center" ac:alt="Second"><ri:attachment ri:filename="a.png">'
                '</ri:attachment></ac:image>')
        out, count = images.to_placeholders(body, {"a.png"})
        self.assertEqual(count, 2)
        self.assertEqual(out, '<img src="a.png" /><img src="a.png" alt="Second" />')

    def test_to_placeholders_escapes_and_matches_decoded_names(self):
        body = attached("a&amp;b.png", ' ac:alt="x"')
        out, count = images.to_placeholders(body, {"a&b.png"})
        self.assertEqual((out, count), ('<img src="a&amp;b.png" alt="x" />', 1))

    def test_to_placeholders_leaves_everything_else(self):
        body = ('<p><ac:image><ri:url ri:value="https://example.com/a.png" /></ac:image></p>'
                '<p><ac:image><ri:attachment ri:filename="other.png" /></ac:image></p>'
                '<p><img src="a.png" /></p>')
        self.assertEqual(images.to_placeholders(body, {"a.png"}), (body, 0))
        self.assertEqual(images.to_placeholders(body, set()), (body, 0))

    def test_to_placeholders_leaves_attachments_of_other_pages(self):
        body = ('<ac:image><ri:attachment ri:filename="a.png"><ri:page ri:content-title="Other" />'
                '</ri:attachment></ac:image>')
        self.assertEqual(images.to_placeholders(body, {"a.png"}), (body, 0))


class RemoveEmbedsTests(unittest.TestCase):
    def test_remove_embeds(self):
        url = '<p><ac:image><ri:url ri:value="https://example.com/x.png" /></ac:image></p>'
        body = ('<p>Intro</p>\n<p>' + attached("keep.png") + '</p>\n'
                '<p> ' + attached("old.png", ' ac:width="5" ac:align="center"') + ' </p>\n'
                '<p>text ' + attached("old2.png") + ' more</p>' + url)
        out, count = images.remove_embeds(body, {"keep.png"})
        self.assertEqual(count, 2)
        self.assertEqual(out, '<p>Intro</p>\n<p>' + attached("keep.png") + '</p>\n'
                         '<p>text  more</p>' + url)

    def test_remove_embeds_two_in_one_paragraph_removes_the_paragraph(self):
        body = '<p>Before</p><p>' + attached("a.png") + ' ' + attached("b.png") + '</p><p>After</p>'
        self.assertEqual(images.remove_embeds(body, set()), ('<p>Before</p><p>After</p>', 2))
        out, count = images.remove_embeds(body, {"a.png"})
        self.assertEqual(count, 1)
        self.assertEqual(out, '<p>Before</p><p>' + attached("a.png") + ' </p><p>After</p>')

    def test_remove_embeds_embed_outside_a_paragraph(self):
        body = '<div>' + attached("a.png") + '</div>'
        self.assertEqual(images.remove_embeds(body, set()), ('<div></div>', 1))

    def test_remove_embeds_never_touches_url_images_or_other_pages(self):
        body = ('<p><ac:image><ri:url ri:value="https://example.com/a.png" /></ac:image></p>'
                '<p><ac:image><ri:attachment ri:filename="a.png"><ri:page ri:content-title="X" />'
                '</ri:attachment></ac:image></p>'
                '<p><img src="a.png" /></p>')
        self.assertEqual(images.remove_embeds(body, set()), (body, 0))

    def test_remove_embeds_nothing_to_remove(self):
        body = '<p>' + attached("a.png") + '</p>'
        self.assertEqual(images.remove_embeds(body, {"a.png"}), (body, 0))


class UploadChangedTests(unittest.TestCase):
    def setUp(self):
        self.pages = {"100": helpers.page("<p>x</p>")}

    def test_upload_changed(self):
        with helpers.TempDir() as tmp:
            a, b, c = helpers.tiny_png(3, 2), helpers.tiny_png(4, 1), helpers.tiny_png(5, 5)
            write(tmp, "img/a.png", a)
            write(tmp, "b.png", b)
            write(tmp, "c.png", c)
            client = helpers.FakeClient(pages=self.pages)
            existing = {"a.png": "sha256:" + digest(a),  # same bytes: skipped
                        "b.png": "sha256:" + digest(b"old bytes"),  # changed
                        "c.png": ""}  # added by hand: replaced
            out = images.upload_changed(client, "100", [
                ref(tmp, "img/a.png"), ref(tmp, "b.png"), ref(tmp, "c.png"), ref(tmp, "gone.png")],
                existing)
            self.assertEqual(out["unchanged"], ["a.png"])
            self.assertEqual(out["uploaded"], ["b.png", "c.png"])
            self.assertEqual(out["missingLocally"], ["gone.png"])
            self.assertEqual(out["failed"], [])
            self.assertEqual(out["ready"], {"img/a.png": (3, 2), "b.png": (4, 1), "c.png": (5, 5)})
            self.assertEqual(client.uploads, [("100", "b.png", "sha256:" + digest(b)),
                                              ("100", "c.png", "sha256:" + digest(c))])
            self.assertEqual(set(out), {"uploaded", "unchanged", "missingLocally", "failed", "ready"})

    def test_upload_changed_two_images_with_one_filename(self):
        with helpers.TempDir() as tmp:
            write(tmp, "one/x.png", helpers.tiny_png(1, 1))
            write(tmp, "two/x.png", helpers.tiny_png(2, 2))
            client = helpers.FakeClient(pages=self.pages)
            out = images.upload_changed(client, "100", [ref(tmp, "one/x.png"), ref(tmp, "two/x.png")], {})
            self.assertEqual(out["uploaded"], ["x.png"])
            self.assertEqual(out["failed"], [{"image": "two/x.png",
                                              "error": "another image is also named x.png"}])
            self.assertEqual(out["ready"], {"one/x.png": (1, 1)})
            self.assertEqual(len(client.uploads), 1)

    def test_upload_changed_upload_failure(self):
        with helpers.TempDir() as tmp:
            write(tmp, "a.png", helpers.tiny_png(1, 1))
            client = helpers.FakeClient(pages=self.pages, fail={"upload": (403, "no permission")})
            out = images.upload_changed(client, "100", [ref(tmp, "a.png")], {})
            self.assertEqual(out["uploaded"], [])
            self.assertEqual(out["ready"], {})
            self.assertEqual(len(out["failed"]), 1)
            self.assertEqual(out["failed"][0]["image"], "a.png")
            self.assertTrue(out["failed"][0]["error"].startswith("upload HTTP 403"), out["failed"][0])
            self.assertIn("no permission", out["failed"][0]["error"])

    def test_upload_changed_unreadable_file_fails_without_crashing(self):
        with helpers.TempDir() as tmp:
            path = write(tmp, "a.png", helpers.tiny_png(1, 1))
            os.chmod(path, 0)
            try:
                if os.access(path, os.R_OK):
                    self.skipTest("this account can read files with no permissions")
                client = helpers.FakeClient(pages=self.pages)
                out = images.upload_changed(client, "100", [ref(tmp, "a.png")], {})
            finally:
                os.chmod(path, 0o600)
            self.assertEqual(client.uploads, [])
            self.assertEqual(out["ready"], {})
            self.assertEqual([item["image"] for item in out["failed"]], ["a.png"])

    def test_upload_changed_unknown_format_is_ready_without_a_size(self):
        with helpers.TempDir() as tmp:
            write(tmp, "a.webp", b"RIFF....WEBPVP8 ")
            out = images.upload_changed(helpers.FakeClient(pages=self.pages), "100",
                                        [ref(tmp, "a.webp")], {})
            self.assertEqual(out["uploaded"], ["a.webp"])
            self.assertEqual(out["ready"], {"a.webp": None})


class EmbedTests(unittest.TestCase):
    def setUp(self):
        self.refs = {
            "a": ImageRef("Alpha", "docs/a.png", "/x/docs/a.png", "a.png"),
            "b": ImageRef("Beta", "docs/b.png", "/x/docs/b.png", "b.png"),
            "c": ImageRef("Gamma", "docs/c.png", "/x/docs/c.png", "c.png"),
            "d": ImageRef("Delta", "docs/d.png", "/x/docs/d.png", "d.png"),
            "e": ImageRef("Eps", "docs/e.png", "/x/docs/e.png", "e.png"),
            "f": ImageRef("Phi", "docs/f.png", "/x/docs/f.png", "f.png"),
        }

    def test_embed(self):
        r = self.refs
        body = ('<p>Intro</p>\n'
                '<p><img src="docs/a.png" alt="" /></p>\n'
                '<p><ac:image><ri:url ri:value="docs/b.png" /></ac:image></p>\n'
                '<p><ac:image ac:width="10" ac:alt="Gamma"><ri:attachment ri:version-at-save="1"'
                ' ri:filename="c.png" /></ac:image></p>\n'
                '<p><img src="docs/d.png" alt="Delta" /></p>\n'
                '<p><img src="f.png" /></p>\n'
                '<p>End</p>')
        ready = {r["a"].src: (1000, 400), r["b"].src: (300, 200), r["c"].src: (50, 50),
                 r["e"].src: (10, 10), r["f"].src: None}
        out, counts = images.embed(body, [r[k] for k in "abcdef"], ready)
        self.assertEqual(counts, {"embedded": 3, "alreadyEmbedded": 1,
                                  "stripped": ["docs/d.png"], "notOnPage": ["docs/e.png"]})
        self.assertEqual(out, (
            '<p>Intro</p>\n'
            '<p>' + images.embed_markup("Alpha", "a.png", (1000, 400)) + '</p>\n'
            '<p>' + images.embed_markup("Beta", "b.png", (300, 200)) + '</p>\n'
            '<p><ac:image ac:width="10" ac:alt="Gamma"><ri:attachment ri:version-at-save="1"'
            ' ri:filename="c.png" /></ac:image></p>\n'
            '<p>' + images.embed_markup("Phi", "f.png", None) + '</p>\n'
            '<p>End</p>'))
        self.assertIn('ac:width="760"', out)
        self.assertIn('ac:width="300"', out)

    def test_embed_changes_nothing_when_there_is_nothing_to_do(self):
        r = self.refs
        body = '<p>' + attached("a.png") + '</p>'
        out, counts = images.embed(body, [r["a"]], {r["a"].src: (5, 5)})
        self.assertEqual(out, body)
        self.assertEqual(counts, {"embedded": 0, "alreadyEmbedded": 1, "stripped": [], "notOnPage": []})
        out, counts = images.embed("", [], {})
        self.assertEqual((out, counts), ("", {"embedded": 0, "alreadyEmbedded": 0,
                                              "stripped": [], "notOnPage": []}))

    def test_embed_counts_every_placeholder_of_an_image(self):
        r = self.refs
        body = '<p><img src="docs/a.png" /></p><p><img src="a.png" alt="again" /></p>'
        out, counts = images.embed(body, [r["a"]], {r["a"].src: (5, 5)})
        self.assertEqual(counts["embedded"], 2)
        self.assertEqual(out.count("<ac:image "), 2)
        self.assertNotIn("<img", out)

    def test_embed_strips_a_failed_image_but_not_a_ready_one_with_the_same_name(self):
        ready_one = ImageRef("One", "x.png", "/x/x.png", "x.png")
        failed_one = ImageRef("Two", "other/x.png", "/x/other/x.png", "x.png")
        body = '<p><img src="x.png" /></p>\n<p><img src="other/x.png" /></p>\n<p>End</p>'
        for order in ([ready_one, failed_one], [failed_one, ready_one]):
            out, counts = images.embed(body, order, {"x.png": (5, 5)})
            self.assertEqual(out, '<p>' + images.embed_markup("One", "x.png", (5, 5))
                             + '</p>\n<p>End</p>')
            self.assertEqual(counts, {"embedded": 1, "alreadyEmbedded": 0,
                                      "stripped": ["other/x.png"], "notOnPage": []})

    def test_embed_strips_a_failed_images_placeholder_that_has_text_around_it(self):
        r = self.refs
        body = '<p>See <img src="docs/d.png" alt="Delta" /> below</p>'
        out, counts = images.embed(body, [r["d"]], {})
        self.assertEqual(out, "<p>See  below</p>")
        self.assertEqual(counts["stripped"], ["docs/d.png"])

    def test_embed_escaped_names_and_alt(self):
        image = ImageRef('He said "hi" & left', "my pic&1.png", "/x/my pic&1.png", "my pic&1.png")
        body = '<p><img src="my pic&amp;1.png" alt="x" /></p>'
        out, counts = images.embed(body, [image], {image.src: (20, 10)})
        self.assertEqual(counts["embedded"], 1)
        self.assertEqual(out, "<p>" + images.embed_markup(image.alt, image.name, (20, 10)) + "</p>")

    def test_embed_leaves_attachment_embeds_of_unlisted_names_and_url_images(self):
        r = self.refs
        body = ('<p>' + attached("zzz.png") + '</p>'
                '<p><ac:image><ri:url ri:value="https://example.com/q.png" /></ac:image></p>')
        out, counts = images.embed(body, [r["d"]], {})
        self.assertEqual(out, body)
        self.assertEqual(counts["stripped"], [])

    def test_embed_then_to_placeholders_round_trip(self):
        r = self.refs
        body = '<p><img src="docs/a.png" alt="Alpha" /></p>'
        embedded, _ = images.embed(body, [r["a"]], {r["a"].src: (100, 50)})
        placeholders, count = images.to_placeholders(embedded, {"a.png"})
        self.assertEqual((placeholders, count), ('<p><img src="a.png" alt="Alpha" /></p>', 1))
        again, counts = images.embed(placeholders, [r["a"]], {r["a"].src: (100, 50)})
        self.assertEqual(again, embedded)


if __name__ == "__main__":
    unittest.main()
