# Simple web page extractor

This command accepts one public URL and returns JSON containing the page title, description, headings, links, images, tables, and readable text. It uses `requests` and Beautiful Soup by default and can optionally render JavaScript with Playwright.

## Setup

Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Usage

Print JSON:

```bash
python crawler.py "https://example.com"
```

Save it to a file:

```bash
python crawler.py "https://example.com" --output page.json
```

For classwork, give each extraction a descriptive name. The crawler creates the
`outputs` folder when needed, makes the filename safe, and prints the full saved
location:

```bash
python crawler.py "https://example.com/chapter-7" --name "PHL 218 - Chapter 7"
```

This produces `outputs/PHL_218_-_Chapter_7.json`. Choose another folder with
`--output-dir`, and use `--overwrite` only when you intentionally want to replace
an existing named extraction:

```bash
python crawler.py "https://example.com/chapter-7" --name "PHL 218 - Chapter 7" --output-dir study-data --overwrite
```

Useful controls:

```bash
python crawler.py "https://example.com" --timeout 20 --max-bytes 3000000 --delay 1
```

## JavaScript-heavy pages

`requests` only receives the server's original HTML. If the content appears after JavaScript runs, install the optional renderer:

```bash
python -m pip install -r requirements-playwright.txt
playwright install chromium
python crawler.py "https://example.com" --playwright --output page.json
```

Playwright is slower and consumes more resources. Its browser may load third-party subresources, so only use it with sites you trust. It does not bypass CAPTCHAs, paywalls, or access controls.

If a site requires a human-verification step, open a visible browser and ask the
crawler to wait. Complete the check yourself, return to the terminal, and press
Enter only after the real page has loaded:

```bash
python crawler.py "https://example.com/chapter" --playwright --headed --wait-for-user --name "Course - Chapter"
```

The crawler detects common CAPTCHA and human-verification pages and refuses to
save them as successful study outputs. Manual mode does not bypass security; it
only lets the authorized user complete the site's normal check.

## Responsible-use limits

- The tool checks `robots.txt` and refuses disallowed pages. Missing or unsupported responses (HTTP 404, 405, or 410) permit fetching, while access-denied and server-error responses remain conservative. Also follow the site's terms of service and applicable law.
- It does not log in, submit forms, retain cookies, or bypass authentication. Use an official API or obtain permission for protected data.
- It extracts one page per run; it does not recursively follow links. For batches, add a delay and respect published rate limits. HTTP 429 means slow down and honor `Retry-After`.
- Only public HTTP(S) destinations are accepted. Localhost, private/link-local IPs, embedded URL credentials, excessive redirects, large responses, and non-HTML responses are rejected.
- Site markup varies, so the generic JSON may need site-specific selectors. Images and links are listed, but binary files are not downloaded.
- DNS rebinding and browser subrequests are difficult to secure perfectly. Do not expose this script directly as a public web service without stronger network-level egress controls, request queues, quotas, and audit logging.
