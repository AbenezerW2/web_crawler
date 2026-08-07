import unittest

from app import DesktopBridge


class DesktopBridgeTests(unittest.TestCase):
    def test_builds_whole_book_options_from_frontend_payload(self):
        options = DesktopBridge._options_from_payload(
            {
                "mode": "book",
                "url": "https://books.example/title/",
                "name": "Book Name",
                "output_dir": "outputs/book-name",
                "output_format": "markdown",
                "start_chapter": 5,
                "end_chapter": 8,
                "delay": 1,
                "headed": True,
                "wait_for_user": True,
            }
        )

        self.assertTrue(options.whole_book)
        self.assertTrue(options.playwright)
        self.assertEqual(options.expected_outputs, 4)

    def test_builds_requests_page_options_from_frontend_payload(self):
        options = DesktopBridge._options_from_payload(
            {
                "mode": "page",
                "url": "https://example.com/article",
                "name": "Article notes",
                "output_dir": "outputs/pages",
                "output_format": "text",
                "playwright": False,
                "headed": False,
                "wait_for_user": False,
            }
        )

        self.assertFalse(options.whole_book)
        self.assertFalse(options.playwright)
        self.assertEqual(options.expected_outputs, 1)

    def test_status_returns_only_events_after_cursor(self):
        bridge = DesktopBridge()
        bridge._append_event("output", text="first")
        bridge._append_event("saved", path="output.md")

        status = bridge.get_status(1)

        self.assertEqual(status["cursor"], 2)
        self.assertEqual(status["events"], [{"type": "saved", "path": "output.md"}])
        self.assertFalse(status["running"])


if __name__ == "__main__":
    unittest.main()
