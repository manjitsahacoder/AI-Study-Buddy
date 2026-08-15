import threading
import time
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import requests

from services import textbook_pdf_service


PDF_BYTES = b"%PDF-1.7\nmock textbook\n%%EOF\n"


class FakeResponse:
    def __init__(
        self,
        chunks=(),
        *,
        status_code=200,
        content_type="application/pdf",
        content_length=None,
        stream_error=None,
        stream_barrier=None,
        stream_release=None,
    ):
        self.chunks = list(chunks)
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.stream_error = stream_error
        self.stream_barrier = stream_barrier
        self.stream_release = stream_release
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size):
        if self.stream_barrier is not None:
            self.stream_barrier.wait(timeout=2)
        if self.stream_release is not None:
            self.stream_release.wait(timeout=2)
        for chunk in self.chunks:
            yield chunk
        if self.stream_error is not None:
            raise self.stream_error


class TextbookPdfServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.cache_dir = Path(self.temporary_directory.name) / "textbook-pdfs"
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-science.pdf",
            "language": "English",
            "version": "latest",
        }

        textbook_pdf_service._clear_cache_locks_for_tests()
        self.addCleanup(textbook_pdf_service._clear_cache_locks_for_tests)

        registry_patcher = patch.object(
            textbook_pdf_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        )
        self.registry_get = registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

        network_patcher = patch.object(textbook_pdf_service.requests, "get")
        self.requests_get = network_patcher.start()
        self.requests_get.side_effect = AssertionError("unexpected network request")
        self.addCleanup(network_patcher.stop)

    def _cache_path(self, textbook=None):
        return textbook_pdf_service.build_textbook_cache_path(
            textbook or self.textbook,
            cache_dir=self.cache_dir,
        )

    def _get_pdf(self, subject="Science"):
        return textbook_pdf_service.get_textbook_pdf(
            9,
            subject,
            cache_dir=self.cache_dir,
        )

    def _set_response(self, response):
        self.requests_get.side_effect = None
        self.requests_get.return_value = response

    def _temporary_files(self):
        if not self.cache_dir.exists():
            return []
        return [path for path in self.cache_dir.iterdir() if path.suffix == ".tmp"]

    def test_cached_pdf_is_returned_without_network_request(self):
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True)
        cache_path.write_bytes(PDF_BYTES)

        result = self._get_pdf()

        self.assertEqual(result, cache_path)
        self.requests_get.assert_not_called()

    def test_uncached_valid_pdf_downloads_successfully(self):
        self._set_response(FakeResponse([PDF_BYTES[:8], PDF_BYTES[8:]]))

        result = self._get_pdf()

        self.assertEqual(result, self._cache_path())
        self.assertEqual(result.read_bytes(), PDF_BYTES)
        self.requests_get.assert_called_once_with(
            self.textbook["pdf_url"],
            stream=True,
            timeout=(10, 30),
            allow_redirects=False,
        )

    def test_downloaded_pdf_is_reused_on_second_call(self):
        self._set_response(FakeResponse([PDF_BYTES]))

        first_result = self._get_pdf()
        second_result = self._get_pdf()

        self.assertEqual(first_result, second_result)
        self.assertEqual(self.requests_get.call_count, 1)

    def test_missing_pdf_url_returns_none(self):
        self.registry_get.return_value = {**self.textbook, "pdf_url": ""}

        result = self._get_pdf()

        self.assertIsNone(result)
        self.requests_get.assert_not_called()

    def test_placeholder_pdf_url_returns_none(self):
        self.registry_get.return_value = {
            **self.textbook,
            "pdf_url": "placeholder://ncert/class-9/science",
        }

        result = self._get_pdf()

        self.assertIsNone(result)
        self.requests_get.assert_not_called()

    def test_invalid_pdf_url_returns_none(self):
        self.registry_get.return_value = {
            **self.textbook,
            "pdf_url": "file:///private/textbook.pdf",
        }

        result = self._get_pdf()

        self.assertIsNone(result)
        self.requests_get.assert_not_called()

    def test_unapproved_pdf_url_returns_none_without_network_request(self):
        self.registry_get.return_value = {
            **self.textbook,
            "pdf_url": "https://example.com/textbook.pdf",
        }

        result = self._get_pdf()

        self.assertIsNone(result)
        self.requests_get.assert_not_called()

    def test_http_failure_returns_none(self):
        self._set_response(FakeResponse(status_code=503))

        result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_timeout_returns_none(self):
        self.requests_get.side_effect = requests.Timeout("mock timeout")

        result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_non_pdf_response_is_rejected(self):
        self._set_response(
            FakeResponse(
                [PDF_BYTES],
                content_type="text/html; charset=utf-8",
            )
        )

        result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_oversized_content_length_is_rejected_before_streaming(self):
        self._set_response(
            FakeResponse(
                [PDF_BYTES],
                content_length=len(PDF_BYTES) + 1,
            )
        )

        with patch.object(
            textbook_pdf_service,
            "TEXTBOOK_PDF_MAX_BYTES",
            len(PDF_BYTES),
        ):
            result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_oversized_stream_without_content_length_is_rejected(self):
        self._set_response(FakeResponse([PDF_BYTES]))

        with patch.object(
            textbook_pdf_service,
            "TEXTBOOK_PDF_MAX_BYTES",
            len(PDF_BYTES) - 1,
        ):
            result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())
        self.assertEqual(self._temporary_files(), [])

    def test_empty_response_is_rejected(self):
        self._set_response(FakeResponse([]))

        result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_partial_download_does_not_leave_final_cache_file(self):
        self._set_response(
            FakeResponse(
                [PDF_BYTES[:12]],
                stream_error=requests.ConnectionError("connection lost"),
            )
        )

        result = self._get_pdf()

        self.assertIsNone(result)
        self.assertFalse(self._cache_path().exists())

    def test_temporary_file_is_cleaned_after_download_failure(self):
        self._set_response(
            FakeResponse(
                [PDF_BYTES[:12]],
                stream_error=requests.ConnectionError("connection lost"),
            )
        )

        self._get_pdf()

        self.assertEqual(self._temporary_files(), [])

    def test_cache_path_is_deterministic(self):
        first_path = self._cache_path()
        second_path = self._cache_path(dict(reversed(list(self.textbook.items()))))

        self.assertEqual(first_path, second_path)
        self.assertEqual(first_path.suffix, ".pdf")

    def test_unsafe_metadata_cannot_escape_cache_directory(self):
        unsafe_textbook = {
            **self.textbook,
            "class": "../../outside",
            "subject": "..\\..\\private",
            "title": "C:\\secrets\\textbook",
        }

        cache_path = self._cache_path(unsafe_textbook)
        relative_path = cache_path.relative_to(self.cache_dir.resolve())

        self.assertEqual(len(relative_path.parts), 1)
        self.assertNotIn("..", relative_path.parts)
        self.assertNotIn("\\", cache_path.name)
        self.assertNotIn("/", cache_path.name)

    def test_concurrent_requests_for_same_textbook_download_once(self):
        worker_start = threading.Barrier(2)
        download_started = threading.Event()
        release_download = threading.Event()

        def network_response(*args, **kwargs):
            download_started.set()
            return FakeResponse([PDF_BYTES], stream_release=release_download)

        def get_pdf_from_worker():
            worker_start.wait(timeout=2)
            return self._get_pdf()

        self.requests_get.side_effect = network_response
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(get_pdf_from_worker) for _ in range(2)]
            self.assertTrue(download_started.wait(timeout=2))
            time.sleep(0.05)
            release_download.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(results, [self._cache_path(), self._cache_path()])
        self.assertEqual(self.requests_get.call_count, 1)

    def test_different_textbooks_do_not_share_cache_files(self):
        mathematics = {
            **self.textbook,
            "subject": "Mathematics",
            "title": "Mathematics",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-mathematics.pdf",
        }
        mathematics_pdf = b"%PDF-1.7\nmock mathematics\n%%EOF\n"
        self.registry_get.side_effect = lambda student_class, subject: (
            mathematics if subject == "Mathematics" else self.textbook
        )
        self.requests_get.side_effect = [
            FakeResponse([PDF_BYTES]),
            FakeResponse([mathematics_pdf]),
        ]

        science_path = self._get_pdf("Science")
        mathematics_path = self._get_pdf("Mathematics")

        self.assertNotEqual(science_path, mathematics_path)
        self.assertEqual(science_path.read_bytes(), PDF_BYTES)
        self.assertEqual(mathematics_path.read_bytes(), mathematics_pdf)

    def test_different_textbooks_can_download_concurrently(self):
        mathematics = {
            **self.textbook,
            "subject": "Mathematics",
            "title": "Mathematics",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/test-mathematics.pdf",
        }
        stream_barrier = threading.Barrier(2)
        self.registry_get.side_effect = lambda student_class, subject: (
            mathematics if subject == "Mathematics" else self.textbook
        )
        self.requests_get.side_effect = lambda url, **kwargs: FakeResponse(
            [PDF_BYTES],
            stream_barrier=stream_barrier,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            science_future = executor.submit(self._get_pdf, "Science")
            mathematics_future = executor.submit(self._get_pdf, "Mathematics")
            science_path = science_future.result(timeout=3)
            mathematics_path = mathematics_future.result(timeout=3)

        self.assertIsNotNone(science_path)
        self.assertIsNotNone(mathematics_path)
        self.assertEqual(self.requests_get.call_count, 2)

    def test_log_output_does_not_include_url_query_parameters(self):
        secret = "do-not-log-this-token"
        self.textbook["pdf_url"] = (
            f"https://ncert.nic.in/textbook/pdf/test-science.pdf?token={secret}"
        )
        self.registry_get.return_value = self.textbook
        self._set_response(FakeResponse(status_code=500))

        with self.assertLogs("services.textbook_pdf_service", level="INFO") as logs:
            result = self._get_pdf()

        self.assertIsNone(result)
        self.assertNotIn(secret, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
