import unittest
from unittest.mock import Mock, patch

from crawler import (
    CrawlerError,
    Page,
    extract,
    looks_like_verification_page,
    named_output_path,
    render_markdown,
    render_text,
    robots_allows,
    validate_public_url,
)


class ExtractTests(unittest.TestCase):
    def test_extracts_common_content(self):
        html = """<html><head><title> Demo </title><meta name="description" content="Example"></head>
        <body><h1>Hello world</h1><a href="/about">About</a>
        <img src="photo.jpg" alt="Photo"><table><tr><th>A</th></tr><tr><td>1</td></tr></table>
        <script>secret()</script></body></html>"""
        data = extract(Page("https://example.com", "https://example.com/path", 200, "text/html", html))
        self.assertEqual(data["title"], "Demo")
        self.assertEqual(data["headings"], [{"level": 1, "text": "Hello world"}])
        self.assertEqual(data["links"][0]["url"], "https://example.com/about")
        self.assertEqual(data["images"][0]["url"], "https://example.com/photo.jpg")
        self.assertEqual(data["tables"], [[['A'], ['1']]])
        self.assertNotIn("secret", data["text"])

    def test_rejects_non_http_and_credentials(self):
        for url in ("file:///etc/passwd", "https://user:pass@example.com"):
            with self.assertRaises(CrawlerError):
                validate_public_url(url)

    @patch("crawler.validate_public_url")
    @patch("crawler.requests.get")
    def test_robots_405_allows_fetch(self, mock_get, _mock_validate):
        mock_get.return_value = Mock(status_code=405)
        self.assertTrue(robots_allows("https://example.com/page", 5))

    @patch("crawler.validate_public_url")
    @patch("crawler.requests.get")
    def test_robots_403_remains_blocked(self, mock_get, _mock_validate):
        mock_get.return_value = Mock(status_code=403)
        self.assertFalse(robots_allows("https://example.com/page", 5))

    def test_builds_safe_named_output_path(self):
        path = named_output_path("PHL 218 / Chapter 7", "outputs")
        self.assertEqual(str(path), "outputs/PHL_218_Chapter_7.json")

    def test_named_output_accepts_json_extension(self):
        path = named_output_path("week-1.json", "study")
        self.assertEqual(str(path), "study/week-1.json")

    def test_named_output_uses_format_extension(self):
        self.assertEqual(
            str(named_output_path("PHL 218 - Chapter 7.json", "outputs", "markdown")),
            "outputs/PHL_218_-_Chapter_7.md",
        )

    def test_rejects_empty_named_output(self):
        with self.assertRaises(CrawlerError):
            named_output_path("...", "outputs")

    def test_detects_human_verification_page(self):
        page = Page(
            "https://example.com",
            "https://example.com",
            405,
            "text/html",
            "<title>Human Verification</title><h1>Let's confirm you are human</h1>",
        )
        self.assertTrue(looks_like_verification_page(page))

    def test_accepts_normal_rendered_page(self):
        page = Page(
            "https://example.com",
            "https://example.com",
            200,
            "text/html",
            "<title>Chapter 7</title><h1>Ethics and care</h1>",
        )
        self.assertFalse(looks_like_verification_page(page))

    def test_accepts_real_page_after_initial_405(self):
        page = Page(
            "https://example.com",
            "https://example.com/chapter",
            405,
            "text/html (rendered)",
            "<title>Chapter 7</title><h1>Ethics and care</h1><p>Study content</p>",
        )
        self.assertFalse(looks_like_verification_page(page))

    def test_renders_study_formats(self):
        data = {
            "title": "Chapter 7",
            "final_url": "https://example.com/ch7",
            "content_blocks": [
                {"type": "heading", "level": 2, "text": "Key Terms"},
                {"type": "paragraph", "text": "A useful definition."},
                {"type": "list_item", "text": "First consideration"},
            ],
        }
        markdown = render_markdown(data)
        text = render_text(data)
        self.assertIn("### Key Terms", markdown)
        self.assertIn("- First consideration", markdown)
        self.assertIn("KEY TERMS", text)
        self.assertIn("A useful definition.", text)


if __name__ == "__main__":
    unittest.main()
