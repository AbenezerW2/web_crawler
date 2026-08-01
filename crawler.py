#!/usr/bin/env python3
"""Safe, single-page web extractor with an optional Playwright renderer."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any
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


def fetch_playwright(url: str, timeout: float, max_bytes: int) -> Page:
    validate_public_url(url)
    if not robots_allows(url, timeout):
        raise CrawlerError("robots.txt does not allow this URL for this crawler")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlerError("Playwright is not installed; see README.md") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            final_url = page.url
            validate_public_url(final_url)
            html = page.content()
            if len(html.encode("utf-8")) > max_bytes:
                raise CrawlerError(f"Rendered page exceeded the {max_bytes:,}-byte limit")
            return Page(url, final_url, response.status if response else 0, "text/html (rendered)", html)
        finally:
            browser.close()


def clean_text(value: str) -> str:
    return " ".join(value.split())


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
        "text": clean_text(soup.get_text(" ", strip=True)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured data from one public web page.")
    parser.add_argument("url")
    parser.add_argument("-o", "--output", help="Write JSON to this file (default: stdout)")
    parser.add_argument("--playwright", action="store_true", help="Render JavaScript before extraction")
    parser.add_argument("--timeout", type=float, default=15, help="Timeout in seconds (default: 15)")
    parser.add_argument("--max-bytes", type=int, default=5_000_000, help="Maximum HTML size")
    parser.add_argument("--delay", type=float, default=0, help="Wait before fetching; useful in batch scripts")
    args = parser.parse_args()
    if args.timeout <= 0 or args.max_bytes <= 0 or args.delay < 0:
        parser.error("timeout and max-bytes must be positive; delay cannot be negative")

    try:
        time.sleep(args.delay)
        page = (fetch_playwright if args.playwright else fetch_requests)(args.url, args.timeout, args.max_bytes)
        result = json.dumps(extract(page), ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(result + "\n")
        else:
            print(result)
        return 0
    except CrawlerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
