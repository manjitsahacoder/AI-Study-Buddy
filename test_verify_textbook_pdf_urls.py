"""Offline tests for the manual NCERT PDF URL verification utility."""

from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests


SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "verify_textbook_pdf_urls.py"
SPEC = importlib.util.spec_from_file_location("verify_textbook_pdf_urls", SCRIPT_PATH)
verify_textbook_pdf_urls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_textbook_pdf_urls)


class FakeResponse:
    def __init__(self, *, status_code=206, content_type="application/pdf", chunks=(b"%PDF-",)):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.url = "https://ncert.nic.in/textbook/pdf/iesc101.pdf"
        self.ok = status_code < 400
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def iter_content(self, chunk_size):
        yield from self.chunks


class VerifyTextbookPdfUrlsTests(unittest.TestCase):
    def test_configured_chapter_urls_cover_all_registered_class_9_chapters(self):
        entries = list(verify_textbook_pdf_urls.configured_chapter_urls())

        self.assertEqual(len(entries), 38)
        self.assertEqual(
            {subject: sum(1 for _, entry_subject, *_ in entries if entry_subject == subject) for subject in {entry[1] for entry in entries}},
            {"Science": 13, "Mathematics": 8, "English": 8, "Social Science": 9},
        )

    def test_verify_pdf_url_reports_status_mime_and_signature(self):
        with patch.object(
            verify_textbook_pdf_urls.requests,
            "get",
            return_value=FakeResponse(),
        ):
            result = verify_textbook_pdf_urls.verify_pdf_url(
                "https://ncert.nic.in/textbook/pdf/iesc101.pdf"
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 206)
        self.assertEqual(result["mime"], "application/pdf")
        self.assertTrue(result["signature"])
        self.assertEqual(result["attempts"], 1)

    def test_verify_pdf_url_retries_transient_request_failures(self):
        with patch.object(
            verify_textbook_pdf_urls.requests,
            "get",
            side_effect=requests.ConnectionError("reset"),
        ) as requests_get, patch.object(
            verify_textbook_pdf_urls,
            "MAX_ATTEMPTS",
            2,
        ), patch.object(verify_textbook_pdf_urls.time, "sleep") as sleep:
            result = verify_textbook_pdf_urls.verify_pdf_url(
                "https://ncert.nic.in/textbook/pdf/iesc101.pdf"
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(requests_get.call_count, 2)
        sleep.assert_called_once()

    def test_main_reports_all_requested_chapter_fields_without_live_requests(self):
        chapter = {
            "number": 1,
            "title": "Verified Chapter",
        }
        result = {
            "ok": True,
            "status": 206,
            "mime": "application/pdf",
            "signature": True,
            "attempts": 1,
            "detail": "PDF signature verified",
        }
        output = io.StringIO()
        with patch.object(verify_textbook_pdf_urls, "configured_real_urls", return_value=[]), patch.object(
            verify_textbook_pdf_urls,
            "configured_chapter_urls",
            return_value=[(9, "Science", "Exploration", chapter, "https://ncert.nic.in/textbook/pdf/iesc101.pdf")],
        ), patch.object(verify_textbook_pdf_urls, "verify_pdf_url", return_value=result), redirect_stdout(output):
            self.assertEqual(verify_textbook_pdf_urls.main(), 0)

        report = output.getvalue()
        self.assertIn("class=9", report)
        self.assertIn("subject='Science'", report)
        self.assertIn("textbook='Exploration'", report)
        self.assertIn("number=1", report)
        self.assertIn("title='Verified Chapter'", report)
        self.assertIn("status=206", report)
        self.assertIn("mime='application/pdf'", report)
        self.assertIn("pdf_signature=True", report)
        self.assertIn("url='https://ncert.nic.in/textbook/pdf/iesc101.pdf'", report)


if __name__ == "__main__":
    unittest.main()
