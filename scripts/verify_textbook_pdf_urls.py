"""Manually verify real PDF URLs configured in the NCERT textbook registry.

This utility is intentionally excluded from the normal test suite because it
performs live network requests. Run it from the repository root with:

    python scripts/verify_textbook_pdf_urls.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services import textbook_registry  # noqa: E402


TIMEOUT = (10, 30)
PDF_SIGNATURE = b"%PDF-"


def is_official_ncert_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname == "ncert.nic.in" or hostname.endswith(".ncert.nic.in")


def verify_pdf_url(url: str) -> tuple[bool, str]:
    try:
        with requests.get(
            url,
            headers={
                "Range": "bytes=0-4",
                "User-Agent": "AI-Study-Buddy-NCERT-URL-Verifier/1.0",
            },
            stream=True,
            timeout=TIMEOUT,
        ) as response:
            response.raise_for_status()
            final_url = response.url
            if not is_official_ncert_url(final_url):
                return False, "redirected outside an official NCERT host"
            signature = bytearray()
            for chunk in response.iter_content(chunk_size=len(PDF_SIGNATURE)):
                if chunk:
                    signature.extend(chunk)
                if len(signature) >= len(PDF_SIGNATURE):
                    break
            if bytes(signature[: len(PDF_SIGNATURE)]) != PDF_SIGNATURE:
                return False, "response does not start with the PDF signature"
            return True, f"HTTP {response.status_code} PDF signature verified"
    except requests.RequestException as error:
        return False, type(error).__name__


def configured_real_urls():
    for class_level in textbook_registry.supported_classes():
        for subject in textbook_registry.supported_subjects(class_level):
            textbook = textbook_registry.get_textbook(class_level, subject)
            if not textbook:
                continue
            pdf_url = str(textbook.get("pdf_url") or "").strip()
            if pdf_url.startswith(("http://", "https://")):
                yield class_level, subject, textbook["title"], pdf_url


def main() -> int:
    entries = list(configured_real_urls())
    if not entries:
        print("No real HTTP(S) textbook PDF URLs are currently configured.")
        return 0

    failures = 0
    for class_level, subject, title, pdf_url in entries:
        if not is_official_ncert_url(pdf_url):
            is_valid, detail = False, "URL is not hosted on an official NCERT host"
        else:
            is_valid, detail = verify_pdf_url(pdf_url)
        status = "PASS" if is_valid else "FAIL"
        print(f"{status} class={class_level} subject={subject!r} title={title!r}: {detail}")
        failures += not is_valid
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
