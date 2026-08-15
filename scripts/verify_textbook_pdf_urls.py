"""Manually verify real textbook and chapter PDF URLs in the NCERT registry.

This utility is intentionally excluded from the normal test suite because it
performs live network requests. Run it from the repository root with:

    python scripts/verify_textbook_pdf_urls.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services import textbook_registry  # noqa: E402


TIMEOUT = (10, 30)
PDF_SIGNATURE = b"%PDF-"
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1


def is_official_ncert_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname == "ncert.nic.in" or hostname.endswith(".ncert.nic.in")


def verify_pdf_url(url: str) -> dict[str, object]:
    """Verify a configured URL with limited retries for transient NCERT errors."""
    result: dict[str, object] = {
        "ok": False,
        "status": None,
        "mime": "",
        "signature": False,
        "attempts": 0,
        "detail": "not requested",
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result["attempts"] = attempt
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
                result["status"] = response.status_code
                result["mime"] = response.headers.get("content-type", "")
                if not response.ok:
                    result["detail"] = f"HTTP {response.status_code}"
                    return result
                if not is_official_ncert_url(response.url):
                    result["detail"] = "redirected outside an official NCERT host"
                    return result
                signature = bytearray()
                for chunk in response.iter_content(chunk_size=len(PDF_SIGNATURE)):
                    if chunk:
                        signature.extend(chunk)
                    if len(signature) >= len(PDF_SIGNATURE):
                        break
                result["signature"] = bytes(signature[: len(PDF_SIGNATURE)]) == PDF_SIGNATURE
                if not result["signature"]:
                    result["detail"] = "response does not start with the PDF signature"
                    return result
                result["ok"] = True
                result["detail"] = "PDF signature verified"
                return result
        except requests.RequestException as error:
            result["detail"] = type(error).__name__
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
    return result


def invalid_url_result() -> dict[str, object]:
    return {
        "ok": False,
        "status": None,
        "mime": "",
        "signature": False,
        "attempts": 0,
        "detail": "URL is not hosted on an official NCERT host",
    }


def result_fields(result: dict[str, object], url: str) -> str:
    status = result["status"] if result["status"] is not None else "none"
    mime = result["mime"] or "none"
    return (
        f"status={status} mime={mime!r} pdf_signature={result['signature']} "
        f"attempts={result['attempts']} url={url!r} detail={result['detail']!r}"
    )


def configured_real_urls():
    for class_level in textbook_registry.supported_classes():
        for subject in textbook_registry.supported_subjects(class_level):
            textbook = textbook_registry.get_textbook(class_level, subject)
            if not textbook:
                continue
            pdf_url = str(textbook.get("pdf_url") or "").strip()
            if pdf_url.startswith(("http://", "https://")):
                yield class_level, subject, textbook["title"], pdf_url


def configured_chapter_urls():
    """Yield chapter metadata and URL pairs configured in the registry."""
    for class_level in textbook_registry.supported_classes():
        for subject in textbook_registry.supported_subjects(class_level):
            textbook = textbook_registry.get_textbook(class_level, subject)
            if not textbook:
                continue
            for chapter in textbook_registry.list_chapters(class_level, subject):
                pdf_url = str(chapter.get("pdf_url") or "").strip()
                if pdf_url.startswith(("http://", "https://")):
                    yield class_level, subject, textbook["title"], chapter, pdf_url


def main() -> int:
    textbook_entries = list(configured_real_urls())
    chapter_entries = list(configured_chapter_urls())
    if not textbook_entries and not chapter_entries:
        print("No real HTTP(S) textbook PDF URLs are currently configured.")
        return 0

    failures = 0
    for class_level, subject, title, pdf_url in textbook_entries:
        result = verify_pdf_url(pdf_url) if is_official_ncert_url(pdf_url) else invalid_url_result()
        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"{status} textbook class={class_level} subject={subject!r} "
            f"title={title!r} {result_fields(result, pdf_url)}"
        )
        failures += not bool(result["ok"])
    for class_level, subject, textbook_title, chapter, pdf_url in chapter_entries:
        result = verify_pdf_url(pdf_url) if is_official_ncert_url(pdf_url) else invalid_url_result()
        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"{status} chapter class={class_level} subject={subject!r} "
            f"textbook={textbook_title!r} number={chapter['number']} "
            f"title={chapter['title']!r} {result_fields(result, pdf_url)}"
        )
        failures += not bool(result["ok"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
