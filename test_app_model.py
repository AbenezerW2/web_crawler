import unittest

from app_model import AppValidationError, ExtractionOptions, build_crawler_command


class AppModelTests(unittest.TestCase):
    def test_builds_whole_book_command(self):
        options = ExtractionOptions(
            url="https://books.example/title/",
            name="Book Name",
            output_dir="outputs/book-name",
            start_chapter=5,
            end_chapter=8,
        )

        command = build_crawler_command(options, "python", "crawler.py")

        self.assertEqual(command[:3], ["python", "crawler.py", "https://books.example/title/"])
        self.assertIn("--wait-for-user", command)
        self.assertEqual(command[command.index("--start-chapter") + 1], "5")
        self.assertEqual(command[command.index("--batch-chapters") + 1], "8")
        self.assertEqual(command[command.index("--name") + 1], "Book Name - Chapter")
        self.assertEqual(options.expected_outputs, 4)

    def test_builds_single_page_requests_command(self):
        options = ExtractionOptions(
            url="https://example.com/chapter",
            name="Chapter notes",
            output_dir="outputs",
            whole_book=False,
            playwright=False,
            headed=False,
            wait_for_user=False,
            delay=0,
        )

        command = build_crawler_command(options, "python", "crawler.py")

        self.assertNotIn("--playwright", command)
        self.assertNotIn("--batch-chapters", command)
        self.assertEqual(command[command.index("--name") + 1], "Chapter notes")
        self.assertEqual(options.expected_outputs, 1)

    def test_rejects_invalid_url(self):
        with self.assertRaises(AppValidationError):
            ExtractionOptions("file:///notes", "Book", "outputs").validated()

    def test_rejects_backwards_chapter_range(self):
        with self.assertRaises(AppValidationError):
            ExtractionOptions(
                "https://books.example/title/",
                "Book",
                "outputs",
                start_chapter=8,
                end_chapter=5,
            ).validated()

    def test_manual_verification_requires_visible_playwright(self):
        with self.assertRaises(AppValidationError):
            ExtractionOptions(
                "https://example.com",
                "Page",
                "outputs",
                whole_book=False,
                playwright=True,
                headed=False,
                wait_for_user=True,
            ).validated()


if __name__ == "__main__":
    unittest.main()
