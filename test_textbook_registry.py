import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import textbook_registry


class TextbookRegistryTests(unittest.TestCase):
    def setUp(self):
        textbook_registry._clear_registry_cache_for_tests()
        self.addCleanup(textbook_registry._clear_registry_cache_for_tests)

    def test_get_textbook_returns_metadata_for_valid_lookup(self):
        textbook = textbook_registry.get_textbook("9", "Science")

        self.assertIsNotNone(textbook)
        self.assertEqual(textbook["board"], "CBSE")
        self.assertEqual(textbook["class"], 9)
        self.assertEqual(textbook["subject"], "Science")
        self.assertEqual(textbook["title"], "Exploration")
        self.assertEqual(textbook["language"], "English")
        self.assertEqual(textbook["version"], "latest")

    def test_get_textbook_normalizes_subject_and_class_whitespace(self):
        textbook = textbook_registry.get_textbook(" 9 ", "  SCIENCE ")

        self.assertIsNotNone(textbook)
        self.assertEqual(textbook["title"], "Exploration")

    def test_get_textbook_returns_copy_of_metadata(self):
        textbook = textbook_registry.get_textbook(9, "Science")
        textbook["title"] = "Mutated"

        self.assertEqual(
            textbook_registry.get_textbook(9, "Science")["title"],
            "Exploration",
        )

    def test_get_textbook_returns_none_for_invalid_class(self):
        with self.assertLogs("services.textbook_registry", level="INFO") as logs:
            textbook = textbook_registry.get_textbook("11", "Science")

        self.assertIsNone(textbook)
        self.assertIn("unsupported NCERT textbook request", "\n".join(logs.output))

    def test_get_textbook_returns_none_for_invalid_subject(self):
        with self.assertLogs("services.textbook_registry", level="INFO") as logs:
            textbook = textbook_registry.get_textbook("9", "Hindi")

        self.assertIsNone(textbook)
        self.assertIn("unsupported NCERT textbook request", "\n".join(logs.output))

    def test_has_textbook_reports_registry_support(self):
        self.assertTrue(textbook_registry.has_textbook(10, "mathematics"))
        self.assertFalse(textbook_registry.has_textbook(10, "Hindi"))

    def test_supported_classes_are_loaded_from_registry(self):
        self.assertEqual(textbook_registry.supported_classes(), [6, 7, 8, 9, 10])

    def test_supported_subjects_returns_subjects_for_class(self):
        self.assertEqual(
            textbook_registry.supported_subjects("6"),
            ["English", "Mathematics", "Science", "Social Science"],
        )

    def test_registry_loads_once(self):
        with patch(
            "services.textbook_registry._read_registry_json",
            wraps=textbook_registry._read_registry_json,
        ) as read_registry_json:
            self.assertTrue(textbook_registry.has_textbook(8, "English"))
            self.assertTrue(textbook_registry.has_textbook(8, "Science"))

        self.assertEqual(read_registry_json.call_count, 1)

    def test_malformed_registry_returns_empty_registry_and_logs_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            registry_path = Path(temporary_directory) / "ncert_textbooks.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "9": {
                            "Science": {
                                "board": "CBSE",
                                "class": 9,
                                "subject": "Science",
                                "title": "Science",
                                "language": "English",
                                "version": "latest",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(textbook_registry, "REGISTRY_PATH", registry_path):
                textbook_registry._clear_registry_cache_for_tests()
                with self.assertLogs("services.textbook_registry", level="ERROR") as logs:
                    textbook = textbook_registry.get_textbook(9, "Science")

        self.assertIsNone(textbook)
        self.assertIn("invalid NCERT textbook registry", "\n".join(logs.output))

    def test_duplicate_registry_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            registry_path = Path(temporary_directory) / "ncert_textbooks.json"
            registry_path.write_text(
                """
                {
                  "9": {
                    "Science": {
                      "board": "CBSE",
                      "class": 9,
                      "subject": "Science",
                      "title": "Science",
                      "pdf_url": "placeholder://ncert/cbse/class-9/science/science",
                      "language": "English",
                      "version": "latest"
                    },
                    "Science": {
                      "board": "CBSE",
                      "class": 9,
                      "subject": "Science",
                      "title": "Science Duplicate",
                      "pdf_url": "placeholder://ncert/cbse/class-9/science/duplicate",
                      "language": "English",
                      "version": "latest"
                    }
                  }
                }
                """,
                encoding="utf-8",
            )

            with patch.object(textbook_registry, "REGISTRY_PATH", registry_path):
                textbook_registry._clear_registry_cache_for_tests()
                with self.assertLogs("services.textbook_registry", level="ERROR") as logs:
                    textbook = textbook_registry.get_textbook(9, "Science")

        self.assertIsNone(textbook)
        self.assertIn("duplicate registry key", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
