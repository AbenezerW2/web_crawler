from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


OUTPUT_FORMATS = ("markdown", "json", "text")


class AppValidationError(ValueError):
    """Raised when desktop-app form values cannot produce a safe command."""


@dataclass(frozen=True)
class ExtractionOptions:
    url: str
    name: str
    output_dir: str
    output_format: str = "markdown"
    whole_book: bool = True
    start_chapter: int = 1
    end_chapter: int = 1
    playwright: bool = True
    headed: bool = True
    wait_for_user: bool = True
    delay: float = 1
    overwrite: bool = False

    def validated(self) -> "ExtractionOptions":
        url = self.url.strip()
        name = self.name.strip()
        output_dir = self.output_dir.strip()
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AppValidationError("Enter a complete public http:// or https:// URL.")
        if not name:
            raise AppValidationError("Enter a book name or output name.")
        if not output_dir:
            raise AppValidationError("Choose an output folder.")
        if self.output_format not in OUTPUT_FORMATS:
            raise AppValidationError("Choose Markdown, JSON, or text output.")
        if self.delay < 0:
            raise AppValidationError("Delay cannot be negative.")
        if self.wait_for_user and not (self.playwright and self.headed):
            raise AppValidationError("Manual verification requires Playwright and a visible browser.")
        if self.headed and not self.playwright:
            raise AppValidationError("A visible browser requires Playwright.")
        if self.whole_book:
            if not self.playwright:
                raise AppValidationError("Whole-book extraction requires Playwright.")
            if self.start_chapter < 1 or self.end_chapter < self.start_chapter:
                raise AppValidationError("The ending chapter must be at or after the starting chapter.")

        return ExtractionOptions(
            url=url,
            name=name,
            output_dir=output_dir,
            output_format=self.output_format,
            whole_book=self.whole_book,
            start_chapter=self.start_chapter,
            end_chapter=self.end_chapter,
            playwright=self.playwright,
            headed=self.headed,
            wait_for_user=self.wait_for_user,
            delay=self.delay,
            overwrite=self.overwrite,
        )

    @property
    def expected_outputs(self) -> int:
        if self.whole_book:
            return self.end_chapter - self.start_chapter + 1
        return 1


def build_crawler_command(
    options: ExtractionOptions,
    python_executable: str,
    crawler_path: str | Path,
) -> list[str]:
    options = options.validated()
    command = [python_executable, str(crawler_path), options.url]

    if options.playwright:
        command.append("--playwright")
    if options.headed:
        command.append("--headed")
    if options.wait_for_user:
        command.append("--wait-for-user")
    if options.whole_book:
        command.extend(
            [
                "--start-chapter",
                str(options.start_chapter),
                "--batch-chapters",
                str(options.end_chapter),
                "--name",
                f"{options.name} - Chapter",
            ]
        )
    else:
        command.extend(["--name", options.name])

    command.extend(
        [
            "--format",
            options.output_format,
            "--output-dir",
            options.output_dir,
            "--delay",
            f"{options.delay:g}",
        ]
    )
    if options.overwrite:
        command.append("--overwrite")
    return command
