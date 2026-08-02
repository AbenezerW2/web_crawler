#!/usr/bin/env python3
"""Safe, single-page web extractor with an optional Playwright renderer."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


USER_AGENT = "SimplePageExtractor/1.0 (+local educational tool)"
MAX_REDIRECTS = 5


class CrawlerError(RuntimeError):
    pass


@dataclass
class Page:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    html: str


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CrawlerError("URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise CrawlerError("Credentials embedded in URLs are not allowed")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CrawlerError(f"Could not resolve host: {parsed.hostname}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise CrawlerError(f"Refusing non-public destination: {ip}")


def robots_allows(url: str, timeout: float) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        validate_public_url(robots_url)
        response = requests.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=False,
        )
        # RFC 9309 treats most 4xx responses as "unavailable", meaning a
        # crawler may proceed. Keep authentication/authorization failures
        # conservative, but allow common missing/unsupported responses.
        if response.status_code in {404, 405, 410}:
            return True
        if response.status_code in {401, 403}:
            return False
        if response.status_code >= 400:
            raise CrawlerError(f"Could not verify robots.txt (HTTP {response.status_code})")
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except requests.RequestException as exc:
        raise CrawlerError(f"Could not verify robots.txt: {exc}") from exc


def fetch_requests(url: str, timeout: float, max_bytes: int) -> Page:
    validate_public_url(url)
    if not robots_allows(url, timeout):
        raise CrawlerError("robots.txt does not allow this URL for this crawler")

    current = url
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for _ in range(MAX_REDIRECTS + 1):
        validate_public_url(current)
        try:
            response = session.get(current, timeout=timeout, stream=True, allow_redirects=False)
        except requests.RequestException as exc:
            raise CrawlerError(f"Request failed: {exc}") from exc

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise CrawlerError("Redirect response did not include a Location")
            current = urljoin(current, location)
            continue

        try:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "html" not in content_type and "xml" not in content_type:
                raise CrawlerError(f"Expected HTML/XML, received {content_type or 'unknown content type'}")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise CrawlerError(f"Response exceeded the {max_bytes:,}-byte limit")
                chunks.append(chunk)
            response.encoding = response.encoding or response.apparent_encoding
            html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            return Page(url, response.url, response.status_code, content_type, html)
        finally:
            response.close()
    raise CrawlerError(f"Too many redirects (maximum {MAX_REDIRECTS})")


def looks_like_verification_page(page: Page) -> bool:
    soup = BeautifulSoup(page.html, "html.parser")
    title = clean_text(soup.title.get_text()) if soup.title else ""
    text = clean_text(soup.get_text(" ", strip=True))[:5000]
    combined = f"{title} {text}".lower()
    signals = (
        "human verification",
        "confirm you are human",
        "verify you are human",
        "security check before continuing",
        "checking your browser",
        "captcha",
    )
    # In manual Playwright mode, ``status_code`` belongs to the initial
    # navigation response. It can remain 405 even after the user completes a
    # challenge and the browser navigates to the real page, so detection must
    # be based on the current rendered content rather than that stale status.
    return any(signal in combined for signal in signals)


def fetch_playwright(
    url: str,
    timeout: float,
    max_bytes: int,
    headed: bool = False,
    wait_for_user: bool = False,
) -> Page:
    validate_public_url(url)
    if not robots_allows(url, timeout):
        raise CrawlerError("robots.txt does not allow this URL for this crawler")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlerError("Playwright is not installed; see README.md") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            if wait_for_user:
                print(
                    "Complete any verification in the browser window, then return here and press Enter...",
                    file=sys.stderr,
                )
                input()
                page.wait_for_timeout(1000)
            final_url = page.url
            validate_public_url(final_url)
            html = page.content()
            if len(html.encode("utf-8")) > max_bytes:
                raise CrawlerError(f"Rendered page exceeded the {max_bytes:,}-byte limit")
            rendered = Page(url, final_url, response.status if response else 0, "text/html (rendered)", html)
            if looks_like_verification_page(rendered):
                hint = " Try --playwright --headed --wait-for-user to complete it manually." if not wait_for_user else " The verification was still present after the manual wait."
                raise CrawlerError("The site returned a human-verification page instead of the requested content." + hint)
            return rendered
        finally:
            browser.close()


def clean_text(value: str) -> str:
    return " ".join(value.split())


def named_output_path(name: str, output_dir: str, output_format: str = "json") -> Path:
    """Return a filesystem-safe JSON path for a user-friendly study name."""
    filename = re.sub(r"[^\w.-]+", "_", name.strip(), flags=re.UNICODE).strip("._")
    if not filename:
        raise CrawlerError("Output name must contain at least one letter or number")
    extensions = {"json": ".json", "markdown": ".md", "text": ".txt"}
    extension = extensions[output_format]
    for known_extension in extensions.values():
        if filename.lower().endswith(known_extension):
            filename = filename[: -len(known_extension)]
            break
    filename += extension
    return Path(output_dir).expanduser() / filename


def extract(page: Page) -> dict[str, Any]:
    soup = BeautifulSoup(page.html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    description = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    headings = [
        {"level": int(tag.name[1]), "text": clean_text(tag.get_text(" ", strip=True))}
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    ]
    links = [
        {"text": clean_text(tag.get_text(" ", strip=True)), "url": urljoin(page.final_url, tag["href"])}
        for tag in soup.find_all("a", href=True)
    ]
    images = [
        {"alt": tag.get("alt", ""), "url": urljoin(page.final_url, tag["src"])}
        for tag in soup.find_all("img", src=True)
    ]
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        tables.append(rows)

    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    content_blocks = []
    block_names = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre"]
    for tag in content_root.find_all(block_names):
        if tag.find_parent(["nav", "header", "footer", "aside"]):
            continue
        if tag.name == "p" and tag.find_parent(["li", "blockquote"]):
            continue
        value = clean_text(tag.get_text(" ", strip=True))
        if not value:
            continue
        if tag.name.startswith("h"):
            content_blocks.append({"type": "heading", "level": int(tag.name[1]), "text": value})
        elif tag.name == "li":
            content_blocks.append({"type": "list_item", "text": value})
        elif tag.name == "blockquote":
            content_blocks.append({"type": "quote", "text": value})
        elif tag.name == "pre":
            content_blocks.append({"type": "preformatted", "text": tag.get_text("\n", strip=True)})
        else:
            content_blocks.append({"type": "paragraph", "text": value})

    return {
        "requested_url": page.requested_url,
        "final_url": page.final_url,
        "status_code": page.status_code,
        "content_type": page.content_type,
        "title": clean_text(soup.title.get_text()) if soup.title else None,
        "description": description.get("content") if description else None,
        "canonical_url": urljoin(page.final_url, canonical["href"]) if canonical and canonical.get("href") else None,
        "headings": headings,
        "links": links,
        "images": images,
        "tables": tables,
        "content_blocks": content_blocks,
        "text": clean_text(soup.get_text(" ", strip=True)),
    }


def render_markdown(data: dict[str, Any]) -> str:
    lines = [f"# {data.get('title') or 'Extracted page'}", "", f"Source: {data['final_url']}", ""]
    blocks = data.get("content_blocks", [])
    if not blocks:
        lines.extend([data.get("text", ""), ""])
    for block in blocks:
        kind, value = block["type"], block["text"]
        if kind == "heading":
            lines.extend([f"{'#' * min(block['level'] + 1, 6)} {value}", ""])
        elif kind == "list_item":
            lines.append(f"- {value}")
        elif kind == "quote":
            lines.extend([f"> {value}", ""])
        elif kind == "preformatted":
            lines.extend(["```", value, "```", ""])
        else:
            lines.extend([value, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_text(data: dict[str, Any]) -> str:
    lines = [data.get("title") or "Extracted page", f"Source: {data['final_url']}", ""]
    blocks = data.get("content_blocks", [])
    if not blocks:
        lines.append(data.get("text", ""))
    for block in blocks:
        value = block["text"]
        if block["type"] == "heading":
            lines.extend([value.upper(), ""])
        elif block["type"] == "list_item":
            lines.append(f"- {value}")
        else:
            lines.extend([value, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_output(data: dict[str, Any], output_format: str) -> str:
    if output_format == "markdown":
        return render_markdown(data)
    if output_format == "text":
        return render_text(data)
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def chapter_urls(book_url: str, start: int, end: int) -> list[str]:
    if start < 1 or end < start:
        raise CrawlerError("Chapter range must start at 1 or later and end at or after the start")
    parsed = urlparse(book_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CrawlerError("Book URL must be an absolute http:// or https:// URL")
    base = book_url.split("#", 1)[0]
    if base.endswith(".xhtml"):
        base = base.rsplit("/", 1)[0] + "/"
    else:
        base = base.rstrip("/") + "/"
    return [urljoin(base, f"ch{number}.xhtml") for number in range(start, end + 1)]


def fetch_playwright_batch(
    urls: list[str],
    timeout: float,
    max_bytes: int,
    headed: bool,
    wait_for_user: bool,
    delay: float,
) -> Iterator[Page]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlerError("Playwright is not installed; see README.md") from exc

    for url in urls:
        validate_public_url(url)
        if not robots_allows(url, timeout):
            raise CrawlerError(f"robots.txt does not allow this URL: {url}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = browser.new_context(user_agent=USER_AGENT)
        browser_page = context.new_page()
        try:
            for index, url in enumerate(urls):
                response = browser_page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
                if index == 0 and wait_for_user:
                    print(
                        "Complete any verification in the browser window, wait for the real chapter, "
                        "then return here and press Enter...",
                        file=sys.stderr,
                    )
                    input()
                    browser_page.wait_for_timeout(1000)
                final_url = browser_page.url
                validate_public_url(final_url)
                html = browser_page.content()
                if len(html.encode("utf-8")) > max_bytes:
                    raise CrawlerError(f"Rendered page exceeded the {max_bytes:,}-byte limit: {url}")
                rendered = Page(url, final_url, response.status if response else 0, "text/html (rendered)", html)
                if looks_like_verification_page(rendered):
                    raise CrawlerError(
                        f"The page returned a human-verification screen: {url}. "
                        "Complete the check before pressing Enter."
                    )
                if response and response.status >= 400 and not (
                    index == 0 and wait_for_user and response.status == 405
                ):
                    raise CrawlerError(f"Chapter request returned HTTP {response.status}: {url}")
                yield rendered
                if delay and index < len(urls) - 1:
                    time.sleep(delay)
        finally:
            browser.close()


def save_named_output(
    data: dict[str, Any],
    name: str,
    output_dir: str,
    output_format: str,
    overwrite: bool,
) -> Path:
    output_path = named_output_path(name, output_dir, output_format)
    if output_path.exists() and not overwrite:
        raise CrawlerError(f"Output already exists: {output_path} (use --overwrite to replace it)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_output(data, output_format), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured data from one public web page.")
    parser.add_argument("url")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("-o", "--output", help="Write the selected format to this exact file path")
    destination.add_argument("-n", "--name", help="Name this study output; saves it in --output-dir")
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "text"),
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument("--output-dir", default="outputs", help="Folder for --name outputs (default: outputs)")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing named output")
    parser.add_argument("--playwright", action="store_true", help="Render JavaScript before extraction")
    parser.add_argument("--headed", action="store_true", help="Show the Playwright browser window")
    parser.add_argument(
        "--wait-for-user",
        action="store_true",
        help="Wait for Enter after you manually complete browser verification",
    )
    parser.add_argument("--timeout", type=float, default=15, help="Timeout in seconds (default: 15)")
    parser.add_argument("--max-bytes", type=int, default=5_000_000, help="Maximum HTML size")
    parser.add_argument("--delay", type=float, default=0, help="Wait before fetching; useful in batch scripts")
    parser.add_argument(
        "--batch-chapters",
        type=int,
        metavar="END",
        help="Extract chapter URLs from --start-chapter through END in one browser session",
    )
    parser.add_argument("--start-chapter", type=int, default=1, help="First chapter in batch mode (default: 1)")
    args = parser.parse_args()
    if args.timeout <= 0 or args.max_bytes <= 0 or args.delay < 0:
        parser.error("timeout and max-bytes must be positive; delay cannot be negative")
    if (args.headed or args.wait_for_user) and not args.playwright:
        parser.error("--headed and --wait-for-user require --playwright")
    if args.wait_for_user and not args.headed:
        parser.error("--wait-for-user requires --headed so you can see the verification page")
    if args.batch_chapters is not None and not args.playwright:
        parser.error("--batch-chapters requires --playwright")
    if args.batch_chapters is not None and args.output:
        parser.error("--output cannot represent multiple files; use --name and/or --output-dir in batch mode")

    try:
        if args.batch_chapters is not None:
            urls = chapter_urls(args.url, args.start_chapter, args.batch_chapters)
            pages = fetch_playwright_batch(
                urls, args.timeout, args.max_bytes, args.headed, args.wait_for_user, args.delay
            )
            prefix = args.name.strip() if args.name else "Chapter"
            completed = 0
            for chapter_number, page in zip(range(args.start_chapter, args.batch_chapters + 1), pages):
                data = extract(page)
                path = save_named_output(
                    data,
                    f"{prefix} {chapter_number:02d}",
                    args.output_dir,
                    args.format,
                    args.overwrite,
                )
                print(f"saved: {path.resolve()}")
                completed += 1
            print(f"completed: {completed} chapters")
            return 0
        time.sleep(args.delay)
        if args.playwright:
            page = fetch_playwright(args.url, args.timeout, args.max_bytes, args.headed, args.wait_for_user)
        else:
            page = fetch_requests(args.url, args.timeout, args.max_bytes)
        data = extract(page)
        result = render_output(data, args.format)
        output_path = named_output_path(args.name, args.output_dir, args.format) if args.name else Path(args.output).expanduser() if args.output else None
        if output_path:
            if args.name and output_path.exists() and not args.overwrite:
                raise CrawlerError(f"Output already exists: {output_path} (use --overwrite to replace it)")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as handle:
                handle.write(result)
            print(f"saved: {output_path.resolve()}")
        else:
            print(result, end="")
        return 0
    except (CrawlerError, OSError, requests.RequestException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
