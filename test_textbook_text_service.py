import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from services import textbook_pdf_service, textbook_registry, textbook_text_service


class TextbookTextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        temporary_root = Path(self.temporary_directory.name)
        self.text_cache_dir = temporary_root / "text-cache"
        self.pdf_cache_dir = temporary_root / "pdf-cache"
        self.pdf_path = temporary_root / "science.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.7\nmock\n")
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "https://ncert.test/class-9/science.pdf",
            "language": "English",
            "version": "latest",
        }

        textbook_text_service._clear_cache_locks_for_tests()
        self.addCleanup(textbook_text_service._clear_cache_locks_for_tests)

        registry_patcher = patch.object(
            textbook_text_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        )
        self.registry_get = registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

        pdf_patcher = patch.object(
            textbook_text_service.textbook_pdf_service,
            "get_textbook_pdf",
            return_value=self.pdf_path,
        )
        self.get_textbook_pdf = pdf_patcher.start()
        self.addCleanup(pdf_patcher.stop)

        self.real_extract_pdf_text_with_timeout = (
            textbook_text_service._extract_pdf_text_with_timeout
        )
        extraction_patcher = patch.object(
            textbook_text_service,
            "_extract_pdf_text_with_timeout",
            return_value=("Extracted textbook text", 1, 1),
        )
        self.extract_pdf_text = extraction_patcher.start()
        self.addCleanup(extraction_patcher.stop)

    def _get_text(self, subject="Science"):
        return textbook_text_service.get_textbook_text(
            9,
            subject,
            text_cache_dir=self.text_cache_dir,
            pdf_cache_dir=self.pdf_cache_dir,
        )

    def _cache_path(self, textbook=None):
        return textbook_text_service.build_textbook_text_cache_path(
            textbook or self.textbook,
            cache_dir=self.text_cache_dir,
        )

    def _temporary_cache_files(self):
        if not self.text_cache_dir.exists():
            return []
        return [
            path for path in self.text_cache_dir.iterdir() if path.suffix == ".tmp"
        ]

    def test_valid_cached_text_is_returned_without_pdf_retrieval_or_extraction(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("Cached textbook text", encoding="utf-8")

        result = self._get_text()

        self.assertEqual(result, "Cached textbook text")
        self.get_textbook_pdf.assert_not_called()
        self.extract_pdf_text.assert_not_called()

    def test_uncached_pdf_text_extracts_successfully(self):
        result = self._get_text()

        self.assertEqual(result, "Extracted textbook text")
        self.assertEqual(self._cache_path().read_text(encoding="utf-8"), result)
        self.get_textbook_pdf.assert_called_once_with(
            9,
            "Science",
            cache_dir=self.pdf_cache_dir,
        )
        self.extract_pdf_text.assert_called_once_with(
            self.pdf_path,
            max_pages=50,
            timeout_seconds=10.0,
        )

    def test_second_call_reuses_text_cache(self):
        first_result = self._get_text()
        second_result = self._get_text()

        self.assertEqual(first_result, second_result)
        self.assertEqual(self.get_textbook_pdf.call_count, 1)
        self.assertEqual(self.extract_pdf_text.call_count, 1)

    def test_missing_textbook_returns_none(self):
        self.registry_get.return_value = None

        result = self._get_text()

        self.assertIsNone(result)
        self.get_textbook_pdf.assert_not_called()
        self.extract_pdf_text.assert_not_called()

    def test_missing_pdf_url_returns_none(self):
        self.registry_get.return_value = {**self.textbook, "pdf_url": ""}

        result = self._get_text()

        self.assertIsNone(result)
        self.get_textbook_pdf.assert_not_called()
        self.extract_pdf_text.assert_not_called()

    def test_pdf_retrieval_failure_returns_none(self):
        self.get_textbook_pdf.return_value = None

        result = self._get_text()

        self.assertIsNone(result)
        self.extract_pdf_text.assert_not_called()
        self.assertFalse(self._cache_path().exists())

    def test_extraction_failure_returns_none(self):
        self.extract_pdf_text.side_effect = RuntimeError("malformed PDF")

        result = self._get_text()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_extraction_timeout_returns_none_without_cache(self):
        self.extract_pdf_text.side_effect = (
            textbook_text_service.TextbookPdfExtractionTimeout("timed out")
        )

        with self.assertLogs("services.textbook_text_service", level="WARNING") as logs:
            result = self._get_text()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())
        self.assertIn("textbook_pdf_extraction_timeout", "\n".join(logs.output))

    def test_page_limit_is_respected_by_pypdf_extractor(self):
        extracted_page_indexes = []

        class FakePage:
            def __init__(self, index):
                self.index = index

            def extract_text(self):
                extracted_page_indexes.append(self.index)
                return f"Page {self.index}"

        fake_reader = SimpleNamespace(pages=[FakePage(index) for index in range(5)])
        with patch.object(textbook_text_service, "PdfReader", return_value=fake_reader):
            text, extracted_pages, total_pages = (
                textbook_text_service._extract_pdf_text_with_pypdf(
                    self.pdf_path,
                    max_pages=2,
                )
            )

        self.assertEqual(text, "Page 0\n\nPage 1")
        self.assertEqual(extracted_pages, 2)
        self.assertEqual(total_pages, 5)
        self.assertEqual(extracted_page_indexes, [0, 1])

    def test_page_limit_reached_is_logged(self):
        self.extract_pdf_text.return_value = ("Limited text", 2, 5)
        with patch.object(textbook_text_service, "TEXTBOOK_PDF_MAX_PAGES", 2):
            with self.assertLogs(
                "services.textbook_text_service",
                level="INFO",
            ) as logs:
                result = self._get_text()

        self.assertEqual(result, "Limited text")
        self.assertIn("textbook_text_page_limit_reached", "\n".join(logs.output))

    def test_empty_extracted_text_is_rejected(self):
        self.extract_pdf_text.return_value = (" \n\t\x00 ", 1, 1)

        result = self._get_text()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_empty_text_cache_is_regenerated(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("  \n", encoding="utf-8")

        result = self._get_text()

        self.assertEqual(result, "Extracted textbook text")
        self.assertEqual(cache_path.read_text(encoding="utf-8"), result)
        self.extract_pdf_text.assert_called_once()

    def test_corrupted_text_cache_is_regenerated(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_bytes(b"\xff\xfe\xfa")

        result = self._get_text()

        self.assertEqual(result, "Extracted textbook text")
        self.assertEqual(cache_path.read_text(encoding="utf-8"), result)
        self.extract_pdf_text.assert_called_once()

    def test_temporary_cache_file_is_cleaned_when_atomic_replace_fails(self):
        with patch.object(
            textbook_text_service.os,
            "replace",
            side_effect=OSError("replace failed"),
        ):
            result = self._get_text()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())
        self.assertEqual(self._temporary_cache_files(), [])

    def test_final_cache_is_created_through_atomic_replace(self):
        real_replace = os.replace
        replace_calls = []

        def checked_replace(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            self.assertTrue(source_path.exists())
            self.assertEqual(source_path.suffix, ".tmp")
            self.assertEqual(destination_path, self._cache_path())
            self.assertFalse(destination_path.exists())
            replace_calls.append((source_path, destination_path))
            real_replace(source_path, destination_path)

        with patch.object(
            textbook_text_service.os,
            "replace",
            side_effect=checked_replace,
        ):
            result = self._get_text()

        self.assertEqual(result, "Extracted textbook text")
        self.assertEqual(len(replace_calls), 1)
        self.assertTrue(self._cache_path().is_file())

    def test_text_cache_path_is_deterministic(self):
        reversed_metadata = dict(reversed(list(self.textbook.items())))

        first_path = self._cache_path()
        second_path = self._cache_path(reversed_metadata)

        self.assertEqual(first_path, second_path)
        self.assertEqual(first_path.suffix, ".txt")

    def test_unsafe_metadata_cannot_escape_text_cache_directory(self):
        unsafe_textbook = {
            **self.textbook,
            "class": "../../outside",
            "subject": "..\\..\\private",
            "title": "C:\\secrets\\textbook",
        }

        cache_path = self._cache_path(unsafe_textbook)
        relative_path = cache_path.relative_to(self.text_cache_dir.resolve())

        self.assertEqual(len(relative_path.parts), 1)
        self.assertNotIn("..", relative_path.parts)
        self.assertNotIn("\\", cache_path.name)
        self.assertNotIn("/", cache_path.name)

    def test_concurrent_same_book_calls_extract_once(self):
        worker_start = threading.Barrier(2)
        extraction_started = threading.Event()
        release_extraction = threading.Event()

        def blocking_extraction(*args, **kwargs):
            extraction_started.set()
            release_extraction.wait(timeout=2)
            return "Concurrent text", 1, 1

        def get_text_from_worker():
            worker_start.wait(timeout=2)
            return self._get_text()

        self.extract_pdf_text.side_effect = blocking_extraction
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(get_text_from_worker) for _ in range(2)]
            self.assertTrue(extraction_started.wait(timeout=2))
            time.sleep(0.05)
            release_extraction.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(results, ["Concurrent text", "Concurrent text"])
        self.assertEqual(self.extract_pdf_text.call_count, 1)
        self.assertEqual(self.get_textbook_pdf.call_count, 1)

    def test_different_books_can_extract_concurrently(self):
        mathematics = {
            **self.textbook,
            "subject": "Mathematics",
            "title": "Mathematics",
            "pdf_url": "https://ncert.test/class-9/mathematics.pdf",
        }
        mathematics_pdf = self.pdf_path.with_name("mathematics.pdf")
        mathematics_pdf.write_bytes(b"%PDF-1.7\nmath\n")
        extraction_barrier = threading.Barrier(2)
        self.registry_get.side_effect = lambda student_class, subject: (
            mathematics if subject == "Mathematics" else self.textbook
        )
        self.get_textbook_pdf.side_effect = lambda student_class, subject, **kwargs: (
            mathematics_pdf if subject == "Mathematics" else self.pdf_path
        )

        def parallel_extraction(pdf_path, **kwargs):
            extraction_barrier.wait(timeout=2)
            return f"Text from {Path(pdf_path).stem}", 1, 1

        self.extract_pdf_text.side_effect = parallel_extraction
        with ThreadPoolExecutor(max_workers=2) as executor:
            science_future = executor.submit(self._get_text, "Science")
            mathematics_future = executor.submit(self._get_text, "Mathematics")
            science_text = science_future.result(timeout=3)
            mathematics_text = mathematics_future.result(timeout=3)

        self.assertEqual(science_text, "Text from science")
        self.assertEqual(mathematics_text, "Text from mathematics")
        self.assertEqual(self.extract_pdf_text.call_count, 2)

    def test_null_bytes_line_endings_and_excess_whitespace_are_cleaned(self):
        raw_text = " A   value\r\n\r\n\r\nSecond\x00\t paragraph\rLast line "

        cleaned_text = textbook_text_service.clean_extracted_text(raw_text)

        self.assertEqual(
            cleaned_text,
            "A value\n\nSecond paragraph\nLast line",
        )

    def test_registry_real_url_entries_pass_official_pdf_url_validation(self):
        registry = textbook_registry._load_registry(textbook_registry.REGISTRY_PATH)
        real_urls = []
        for subjects in registry.values():
            for textbook in subjects.values():
                pdf_url = textbook["pdf_url"]
                if pdf_url.startswith(("http://", "https://")):
                    real_urls.append(pdf_url)

        for pdf_url in real_urls:
            hostname = (urlsplit(pdf_url).hostname or "").lower()
            self.assertTrue(
                hostname == "ncert.nic.in" or hostname.endswith(".ncert.nic.in")
            )
            self.assertIsNone(textbook_pdf_service._url_issue(pdf_url))

    def test_no_gemini_call_occurs(self):
        fake_gemini_service = SimpleNamespace(generate_content=Mock())
        with patch.dict(sys.modules, {"gemini_service": fake_gemini_service}):
            result = self._get_text()

        self.assertEqual(result, "Extracted textbook text")
        fake_gemini_service.generate_content.assert_not_called()

    def test_timeout_controller_terminates_extraction_process(self):
        class FakeConnection:
            def __init__(self, *, poll_result=False):
                self.poll_result = poll_result
                self.closed = False

            def poll(self, timeout):
                self.timeout = timeout
                return self.poll_result

            def recv(self):
                raise AssertionError("recv should not be called on timeout")

            def close(self):
                self.closed = True

        class FakeProcess:
            def __init__(self):
                self.daemon = False
                self.alive = False
                self.terminated = False
                self.closed = False

            def start(self):
                self.alive = True

            def join(self, timeout):
                self.join_timeout = timeout

            def is_alive(self):
                return self.alive

            def terminate(self):
                self.terminated = True
                self.alive = False

            def close(self):
                self.closed = True

        result_connection = FakeConnection()
        worker_connection = FakeConnection()
        fake_process = FakeProcess()
        fake_context = SimpleNamespace(
            Pipe=Mock(return_value=(result_connection, worker_connection)),
            Process=Mock(return_value=fake_process),
        )

        with patch.object(
            textbook_text_service.multiprocessing,
            "get_context",
            return_value=fake_context,
        ) as get_context:
            with self.assertRaises(
                textbook_text_service.TextbookPdfExtractionTimeout
            ):
                self.real_extract_pdf_text_with_timeout(
                    self.pdf_path,
                    max_pages=50,
                    timeout_seconds=0.01,
                )

        get_context.assert_called_once_with("spawn")
        self.assertTrue(fake_process.terminated)
        self.assertTrue(fake_process.closed)
        self.assertTrue(result_connection.closed)
        self.assertTrue(worker_connection.closed)

    def test_process_isolated_extraction_smoke(self):
        from reportlab.pdfgen import canvas

        pdf_path = self.pdf_path.with_name("process-smoke.pdf")
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(72, 720, "Process isolated textbook text")
        pdf.save()

        text, extracted_pages, total_pages = (
            self.real_extract_pdf_text_with_timeout(
                pdf_path,
                max_pages=50,
                timeout_seconds=10,
            )
        )

        self.assertIn("Process isolated textbook text", text)
        self.assertEqual(extracted_pages, 1)
        self.assertEqual(total_pages, 1)


if __name__ == "__main__":
    unittest.main()
