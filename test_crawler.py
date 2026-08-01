import unittest
from unittest.mock import Mock, patch

from crawler import CrawlerError, Page, extract, robots_allows, validate_public_url


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


if __name__ == "__main__":
    unittest.main()
