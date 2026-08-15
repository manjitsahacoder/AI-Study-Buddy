"""Offline tests for the isolated NCERT chapter PDF/text foundation."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests

from services import textbook_pdf_service, textbook_registry, textbook_text_service


PDF_BYTES = b"%PDF-1.7\nmock chapter\n%%EOF\n"


class FakeResponse:
    def __init__(
        self,
        chunks=(),
        *,
        status_code=200,
        content_type="application/pdf",
        stream_error=None,
        stream_barrier=None,
        stream_release=None,
    ):
        self.chunks = list(chunks)
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.stream_error = stream_error
        self.stream_barrier = stream_barrier
        self.stream_release = stream_release

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        if self.stream_barrier is not None:
            self.stream_barrier.wait(timeout=2)
        if self.stream_release is not None:
            self.stream_release.wait(timeout=2)
        for chunk in self.chunks:
            yield chunk
        if self.stream_error is not None:
            raise self.stream_error


class ChapterRegistryTests(unittest.TestCase):
    def setUp(self):
        textbook_registry._clear_registry_cache_for_tests()
        self.addCleanup(textbook_registry._clear_registry_cache_for_tests)

    def _textbook(self, chapters):
        return {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "placeholder://ncert/class-9/science",
            "language": "English",
            "version": "latest",
            "chapters": chapters,
        }

    def _chapter(self, number=1, title="Matter in Our Surroundings"):
        return {
            "number": number,
            "title": title,
            "pdf_url": f"https://ncert.nic.in/textbook/pdf/iesc1{number:02d}.pdf",
        }

    def test_lookup_by_number_and_normalized_title_returns_copy(self):
        by_number = textbook_registry.get_chapter(9, "Science", " 1 ")
        by_title = textbook_registry.get_chapter(
            9,
            "science",
            "exploration entering the world of secondary science",
        )

        self.assertEqual(by_number["id"], "chapter-01")
        self.assertEqual(by_number["number"], 1)
        self.assertEqual(by_title["number"], 1)
        by_number["title"] = "Mutated"
        self.assertNotEqual(
            textbook_registry.get_chapter(9, "Science", 1)["title"],
            "Mutated",
        )

    def test_list_chapters_is_numeric_order_and_unsupported_is_graceful(self):
        chapters = textbook_registry.list_chapters(9, "English")

        self.assertEqual([chapter["number"] for chapter in chapters], list(range(1, 9)))
        self.assertEqual(textbook_registry.list_chapters(11, "Science"), [])
        self.assertIsNone(textbook_registry.get_chapter(9, "Science", 99))
        self.assertIsNone(textbook_registry.get_chapter_pdf_url(9, "Science", 99))

    def test_all_registered_class_9_chapters_are_unique_and_official(self):
        expected_counts = {
            "Science": 13,
            "Mathematics": 8,
            "English": 8,
            "Social Science": 9,
        }
        for subject, expected_count in expected_counts.items():
            chapters = textbook_registry.list_chapters(9, subject)
            self.assertEqual(len(chapters), expected_count)
            self.assertEqual([chapter["number"] for chapter in chapters], list(range(1, expected_count + 1)))
            self.assertEqual(len({chapter["id"] for chapter in chapters}), expected_count)
            for chapter in chapters:
                self.assertEqual(chapter["id"], f"chapter-{chapter['number']:02d}")
                parsed = urlsplit(chapter["pdf_url"])
                self.assertEqual(parsed.scheme, "https")
                self.assertEqual(parsed.hostname, "ncert.nic.in")
                self.assertTrue(parsed.path.endswith(".pdf"))

    def test_class_9_science_chapters_use_explicit_official_content_pdf_urls(self):
        textbook = textbook_registry.get_textbook(9, "Science")
        chapters = textbook_registry.list_chapters(9, "Science")

        self.assertEqual(
            [chapter["pdf_url"] for chapter in chapters],
            [
                "https://ncert.nic.in/textbook/pdf/iesc101.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc102.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc103.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc104.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc105.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc106.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc107.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc108.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc109.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc110.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc111.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc112.pdf",
                "https://ncert.nic.in/textbook/pdf/iesc113.pdf",
            ],
        )
        self.assertTrue(all(chapter["pdf_url"] != textbook["pdf_url"] for chapter in chapters))

    def test_registered_chapters_support_number_and_normalized_title_lookups(self):
        chapter = textbook_registry.get_chapter(9, "Science", 10)
        by_title = textbook_registry.get_chapter(
            9,
            "science",
            "sound waves characteristics and applications",
        )

        self.assertEqual(chapter["title"], "Sound Waves: Characteristics and Applications")
        self.assertEqual(by_title["id"], chapter["id"])
        self.assertIsNone(textbook_registry.get_chapter(9, "English", chapter["title"]))

    def test_duplicate_chapter_numbers_are_rejected(self):
        registry = {"9": {"Science": self._textbook([self._chapter(), self._chapter()])}}

        with self.assertRaisesRegex(textbook_registry.TextbookRegistryError, "duplicate chapter"):
            textbook_registry._validate_registry(registry)

    def test_malformed_chapter_metadata_is_rejected(self):
        malformed = {"number": 1, "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc101.pdf"}
        registry = {"9": {"Science": self._textbook([malformed])}}

        with self.assertRaisesRegex(textbook_registry.TextbookRegistryError, "missing title"):
            textbook_registry._validate_registry(registry)

    def test_unsafe_chapter_url_is_rejected(self):
        unsafe = self._chapter()
        unsafe["pdf_url"] = "https://example.test/../../outside.pdf"
        registry = {"9": {"Science": self._textbook([unsafe])}}

        with self.assertRaisesRegex(textbook_registry.TextbookRegistryError, "invalid pdf_url"):
            textbook_registry._validate_registry(registry)

    def test_duplicate_json_chapter_keys_are_rejected_when_loading_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            registry_path = Path(temporary_directory) / "registry.json"
            registry_path.write_text(
                json.dumps({"9": {"Science": self._textbook([])} }),
                encoding="utf-8",
            )
            # The empty chapters value is separately invalid; duplicate keys must be
            # detected before that validation runs.
            registry_path.write_text(
                """
                {"9":{"Science":{"board":"CBSE","class":9,"subject":"Science",
                "title":"Science","pdf_url":"placeholder://ncert/book","language":"English",
                "version":"latest","chapters":[{"number":1,"number":2,"title":"One",
                "pdf_url":"https://ncert.nic.in/textbook/pdf/iesc101.pdf"}]}}}
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(textbook_registry.TextbookRegistryError, "duplicate registry key"):
                textbook_registry._read_registry_json(registry_path)


class ChapterPdfServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.cache_dir = Path(self.temporary_directory.name) / "pdf-cache"
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "placeholder://ncert/class-9/science",
            "language": "English",
            "version": "latest",
        }
        self.chapter = {
            "id": "chapter-01",
            "number": 1,
            "title": "Matter in Our Surroundings",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science-chapter-1.pdf",
        }
        self.second_chapter = {
            "id": "chapter-02",
            "number": 2,
            "title": "Is Matter Around Us Pure",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science-chapter-2.pdf",
        }
        textbook_pdf_service._clear_cache_locks_for_tests()
        self.addCleanup(textbook_pdf_service._clear_cache_locks_for_tests)
        self.get_textbook = patch.object(
            textbook_pdf_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        ).start()
        self.get_chapter = patch.object(
            textbook_pdf_service.textbook_registry,
            "get_chapter",
            return_value=self.chapter,
        ).start()
        self.requests_get = patch.object(textbook_pdf_service.requests, "get").start()
        self.requests_get.side_effect = AssertionError("unexpected network request")
        self.addCleanup(patch.stopall)

    def _get_pdf(self, chapter=1):
        return textbook_pdf_service.get_chapter_pdf(
            9,
            "Science",
            chapter,
            cache_dir=self.cache_dir,
        )

    def _cache_path(self, chapter=None):
        return textbook_pdf_service.build_chapter_cache_path(
            self.textbook,
            chapter or self.chapter,
            cache_dir=self.cache_dir,
        )

    def test_cached_chapter_pdf_is_reused_without_network(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_bytes(PDF_BYTES)

        self.assertEqual(self._get_pdf(), cache_path)
        self.requests_get.assert_not_called()

    def test_uncached_chapter_pdf_downloads_and_uses_shared_timeout(self):
        self.requests_get.side_effect = None
        self.requests_get.return_value = FakeResponse([PDF_BYTES])

        result = self._get_pdf()

        self.assertEqual(result, self._cache_path())
        self.assertEqual(result.read_bytes(), PDF_BYTES)
        self.requests_get.assert_called_once_with(
            self.chapter["pdf_url"],
            stream=True,
            timeout=(10, 30),
            allow_redirects=False,
        )

    def test_chapter_cache_keys_do_not_collide_and_are_traversal_safe(self):
        unsafe_chapter = {
            "id": "chapter-02",
            "number": 2,
            "title": "..\\..\\secrets/second chapter",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science-chapter-2.pdf",
        }
        first_path = self._cache_path()
        second_path = self._cache_path(unsafe_chapter)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(second_path.relative_to(self.cache_dir.resolve()).parts[0], "chapters")
        self.assertNotIn("..", second_path.name)
        self.assertNotIn("\\", second_path.name)
        self.assertNotIn("/", second_path.name)

    def test_missing_or_invalid_chapter_pdf_is_graceful(self):
        self.get_chapter.return_value = {**self.chapter, "pdf_url": ""}
        self.assertIsNone(self._get_pdf())
        self.requests_get.assert_not_called()

        self.get_chapter.return_value = self.chapter
        self.requests_get.side_effect = None
        self.requests_get.return_value = FakeResponse([b"<html>not a PDF</html>"])
        self.assertIsNone(self._get_pdf())
        self.assertFalse(self._cache_path().exists())

    def test_oversized_chapter_pdf_response_is_rejected(self):
        self.requests_get.side_effect = None
        self.requests_get.return_value = FakeResponse([PDF_BYTES])

        with patch.object(
            textbook_pdf_service,
            "TEXTBOOK_PDF_MAX_BYTES",
            len(PDF_BYTES) - 1,
        ):
            self.assertIsNone(self._get_pdf())

        self.assertFalse(self._cache_path().exists())

    def test_chapter_download_failure_and_timeout_are_graceful(self):
        self.requests_get.side_effect = requests.Timeout("mock timeout")

        self.assertIsNone(self._get_pdf())
        self.assertFalse(self._cache_path().exists())

    def test_same_chapter_downloads_once_while_different_chapters_can_download(self):
        worker_start = threading.Barrier(2)
        download_started = threading.Event()
        release_download = threading.Event()

        def blocked_response(*args, **kwargs):
            download_started.set()
            return FakeResponse([PDF_BYTES], stream_release=release_download)

        self.requests_get.side_effect = blocked_response
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(lambda: (worker_start.wait(timeout=2), self._get_pdf())[1])
                for _ in range(2)
            ]
            self.assertTrue(download_started.wait(timeout=2))
            time.sleep(0.05)
            release_download.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(results, [self._cache_path(), self._cache_path()])
        self.assertEqual(self.requests_get.call_count, 1)

        self._cache_path().unlink()
        self.get_chapter.side_effect = lambda class_level, subject, chapter: (
            self.second_chapter if chapter == 2 else self.chapter
        )
        stream_barrier = threading.Barrier(2)
        self.requests_get.side_effect = lambda *args, **kwargs: FakeResponse(
            [PDF_BYTES],
            stream_barrier=stream_barrier,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self._get_pdf, 1)
            second = executor.submit(self._get_pdf, 2)
            self.assertIsNotNone(first.result(timeout=3))
            self.assertIsNotNone(second.result(timeout=3))

        self.assertEqual(self.requests_get.call_count, 3)


class ChapterTextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        temporary_root = Path(self.temporary_directory.name)
        self.text_cache_dir = temporary_root / "text-cache"
        self.pdf_cache_dir = temporary_root / "pdf-cache"
        self.pdf_path = temporary_root / "chapter-1.pdf"
        self.pdf_path.write_bytes(PDF_BYTES)
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "placeholder://ncert/class-9/science",
            "language": "English",
            "version": "latest",
        }
        self.chapter = {
            "id": "chapter-01",
            "number": 1,
            "title": "Matter in Our Surroundings",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science-chapter-1.pdf",
        }
        textbook_text_service._clear_cache_locks_for_tests()
        self.addCleanup(textbook_text_service._clear_cache_locks_for_tests)
        self.get_textbook = patch.object(
            textbook_text_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        ).start()
        self.get_chapter = patch.object(
            textbook_text_service.textbook_registry,
            "get_chapter",
            return_value=self.chapter,
        ).start()
        self.get_chapter_pdf = patch.object(
            textbook_text_service.textbook_pdf_service,
            "get_chapter_pdf",
            return_value=self.pdf_path,
        ).start()
        self.extract = patch.object(
            textbook_text_service,
            "_extract_pdf_text_with_timeout",
            return_value=("Extracted chapter text", 1, 1),
        ).start()
        self.addCleanup(patch.stopall)

    def _get_text(self, chapter=1):
        return textbook_text_service.get_chapter_text(
            9,
            "Science",
            chapter,
            text_cache_dir=self.text_cache_dir,
            pdf_cache_dir=self.pdf_cache_dir,
        )

    def _cache_path(self, chapter=None):
        return textbook_text_service.build_chapter_text_cache_path(
            self.textbook,
            chapter or self.chapter,
            cache_dir=self.text_cache_dir,
        )

    def test_chapter_text_extracts_and_reuses_cache_without_pdf_or_gemini(self):
        fake_gemini_service = SimpleNamespace(generate_content=Mock())
        with patch.dict(__import__("sys").modules, {"gemini_service": fake_gemini_service}):
            first = self._get_text()
            second = self._get_text()

        self.assertEqual(first, "Extracted chapter text")
        self.assertEqual(second, first)
        self.assertEqual(self.get_chapter_pdf.call_count, 1)
        self.assertEqual(self.extract.call_count, 1)
        fake_gemini_service.generate_content.assert_not_called()

    def test_empty_and_corrupt_chapter_text_caches_are_regenerated(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("\n \t", encoding="utf-8")

        self.assertEqual(self._get_text(), "Extracted chapter text")
        cache_path.write_bytes(b"\xff\xfe")
        self.assertEqual(self._get_text(), "Extracted chapter text")
        self.assertEqual(self.extract.call_count, 2)

    def test_empty_text_timeout_and_missing_chapter_are_graceful(self):
        self.extract.return_value = ("\x00  ", 1, 1)
        self.assertIsNone(self._get_text())
        self.assertFalse(self._cache_path().exists())

        self.extract.side_effect = textbook_text_service.TextbookPdfExtractionTimeout("mock timeout")
        self.assertIsNone(self._get_text())
        self.get_chapter.return_value = None
        self.assertIsNone(self._get_text())

    def test_page_cap_and_unsafe_chapter_names_are_supported_safely(self):
        self.extract.return_value = ("Limited chapter text", 2, 7)
        with patch.object(textbook_text_service, "TEXTBOOK_PDF_MAX_PAGES", 2):
            with self.assertLogs("services.textbook_text_service", level="INFO") as logs:
                self.assertEqual(self._get_text(), "Limited chapter text")
        self.assertIn("textbook_chapter_text_page_limit_reached", "\n".join(logs.output))

        unsafe_chapter = {**self.chapter, "title": "..\\..\\private/chapter"}
        unsafe_path = self._cache_path(unsafe_chapter)
        self.assertEqual(unsafe_path.relative_to(self.text_cache_dir.resolve()).parts[0], "chapters")
        self.assertNotIn("..", unsafe_path.name)

    def test_same_chapter_extracts_once_while_different_chapters_extract_independently(self):
        worker_start = threading.Barrier(2)
        extraction_started = threading.Event()
        release_extraction = threading.Event()

        def blocked_extraction(*args, **kwargs):
            extraction_started.set()
            release_extraction.wait(timeout=2)
            return "Concurrent chapter text", 1, 1

        self.extract.side_effect = blocked_extraction
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(lambda: (worker_start.wait(timeout=2), self._get_text())[1])
                for _ in range(2)
            ]
            self.assertTrue(extraction_started.wait(timeout=2))
            time.sleep(0.05)
            release_extraction.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(results, ["Concurrent chapter text", "Concurrent chapter text"])
        self.assertEqual(self.extract.call_count, 1)

        self._cache_path().unlink()
        second_chapter = {
            "id": "chapter-02",
            "number": 2,
            "title": "Second Chapter",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science-chapter-2.pdf",
        }
        second_pdf = self.pdf_path.with_name("chapter-2.pdf")
        second_pdf.write_bytes(PDF_BYTES)
        self.get_chapter.side_effect = lambda class_level, subject, chapter: (
            second_chapter if chapter == 2 else self.chapter
        )
        self.get_chapter_pdf.side_effect = lambda class_level, subject, chapter, **kwargs: (
            second_pdf if chapter == 2 else self.pdf_path
        )
        extraction_barrier = threading.Barrier(2)

        def parallel_extraction(pdf_path, **kwargs):
            extraction_barrier.wait(timeout=2)
            return f"Text {Path(pdf_path).stem}", 1, 1

        self.extract.side_effect = parallel_extraction
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self._get_text, 1)
            second = executor.submit(self._get_text, 2)
            self.assertEqual(first.result(timeout=3), "Text chapter-1")
            self.assertEqual(second.result(timeout=3), "Text chapter-2")


class ChapterPageServiceTests(unittest.TestCase):
    """Offline coverage for page-preserving caches used by Class 9 context."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.page_cache_dir = root / "page-cache"
        self.pdf_cache_dir = root / "pdf-cache"
        self.pdf_path = root / "chapter-1.pdf"
        self.pdf_path.write_bytes(PDF_BYTES)
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Exploration",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc1ps.pdf",
            "language": "English",
            "version": "First Edition, April 2026",
        }
        self.chapter = {
            "id": "chapter-01",
            "number": 1,
            "title": "Exploration: Entering the World of Secondary Science",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc101.pdf",
        }
        self.second_chapter = {
            "id": "chapter-02",
            "number": 2,
            "title": "Cell: The Building Block of Life",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc102.pdf",
        }
        textbook_text_service._clear_cache_locks_for_tests()
        self.addCleanup(textbook_text_service._clear_cache_locks_for_tests)
        self.get_textbook = patch.object(
            textbook_text_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        ).start()
        self.get_chapter = patch.object(
            textbook_text_service.textbook_registry,
            "get_chapter",
            return_value=self.chapter,
        ).start()
        self.get_chapter_pdf = patch.object(
            textbook_text_service.textbook_pdf_service,
            "get_chapter_pdf",
            return_value=self.pdf_path,
        ).start()
        self.extract_pages = patch.object(
            textbook_text_service,
            "extract_pdf_pages_with_timeout",
            return_value=(["First page", "Second page"], 2),
        ).start()
        self.addCleanup(patch.stopall)

    def _get_pages(self, chapter=1, **kwargs):
        options = {
            "page_cache_dir": self.page_cache_dir,
            "pdf_cache_dir": self.pdf_cache_dir,
            "max_pages": 300,
            "timeout_seconds": 30,
        }
        options.update(kwargs)
        return textbook_text_service.get_chapter_pages(
            9,
            "Science",
            chapter,
            **options,
        )

    def _cache_path(self, chapter=None):
        return textbook_text_service.build_chapter_page_cache_path(
            self.textbook,
            chapter or self.chapter,
            max_pages=300,
            cache_dir=self.page_cache_dir,
        )

    def test_page_cache_reuses_requested_chapter_without_pdf_or_reextraction(self):
        first = self._get_pages()
        second = self._get_pages()

        self.assertEqual(first, (["First page", "Second page"], 2))
        self.assertEqual(second, first)
        self.get_chapter_pdf.assert_called_once_with(
            9,
            "Science",
            1,
            cache_dir=self.pdf_cache_dir,
        )
        self.extract_pages.assert_called_once_with(
            self.pdf_path,
            max_pages=300,
            timeout_seconds=30.0,
        )
        payload = json.loads(self._cache_path().read_text(encoding="utf-8"))
        self.assertEqual(payload["page_texts"], ["First page", "Second page"])

    def test_page_loader_requests_only_the_selected_registered_chapter(self):
        self.get_chapter.side_effect = lambda _class, _subject, chapter: (
            self.second_chapter if chapter == 2 else self.chapter
        )

        self.assertEqual(self._get_pages(2), (["First page", "Second page"], 2))
        self.get_chapter_pdf.assert_called_once_with(
            9,
            "Science",
            2,
            cache_dir=self.pdf_cache_dir,
        )

    def test_corrupt_page_cache_is_removed_and_regenerated(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("not-json", encoding="utf-8")

        self.assertEqual(self._get_pages(), (["First page", "Second page"], 2))
        self.assertEqual(self.extract_pages.call_count, 1)
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8"))["total_pages"], 2)

    def test_mismatched_page_cache_source_is_removed_and_regenerated(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text(
            json.dumps(
                {
                    "cache_version": textbook_text_service.PAGE_CACHE_VERSION,
                    "max_pages": 300,
                    "page_texts": ["Wrong source page"],
                    "source_pdf_url": self.second_chapter["pdf_url"],
                    "total_pages": 1,
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(self._get_pages(), (["First page", "Second page"], 2))
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["source_pdf_url"], self.chapter["pdf_url"])

    def test_page_extraction_timeout_corrupt_pdf_and_unavailable_pdf_are_safe(self):
        self.extract_pages.side_effect = textbook_text_service.TextbookPdfExtractionTimeout(
            "mock timeout"
        )
        self.assertIsNone(self._get_pages())

        self.extract_pages.side_effect = RuntimeError("corrupt PDF")
        self.assertIsNone(self._get_pages(max_pages=299))

        self.extract_pages.side_effect = None
        self.get_chapter_pdf.return_value = None
        self.assertIsNone(self._get_pages(max_pages=298))

    def test_page_cache_paths_are_separate_for_registered_chapter_urls(self):
        first_path = self._cache_path()
        second_path = self._cache_path(self.second_chapter)

        self.assertNotEqual(first_path, second_path)
        self.assertIn("chapter_01", first_path.name)
        self.assertIn("chapter_02", second_path.name)


if __name__ == "__main__":
    unittest.main()
