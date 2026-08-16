"""Offline tests for the isolated Class 10 Science chapter-context service."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.pdfgen import canvas

from services import textbook_chapter_context_service as chapter_context_service


class TextbookChapterContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.context_cache_dir = root / "chapter-context"
        self.pdf_cache_dir = root / "pdf-cache"
        self.pdf_path = root / "class-10-science.pdf"
        self.textbook = {
            "board": "CBSE",
            "class": 10,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/jesc1ps.pdf",
            "language": "English",
            "version": "latest",
        }
        self.fixture_pages = [
            [
                "CONTENTS",
                "Chapter 1",
                "Chemical Reactions and Equations",
                "Chapter 2",
                "Acids, Bases and Salts",
            ],
            [
                "SCIENCE",
                "Chapter 1",
                "Chemical Reactions and Equations",
                "Chapter one opening content explains chemical changes.",
                "1",
            ],
            [
                "SCIENCE",
                "Chapter one continuation discusses balanced equations.",
                "2",
            ],
            [
                "SCIENCE",
                "Chapter 2",
                "Acids, Bases and Salts",
                "Acid chapter content must not appear in chapter one context.",
                "3",
            ],
            [
                "SCIENCE",
                "Chapter 8",
                "Heredity",
                "Heredity chapter content.",
                "4",
            ],
            [
                "SCIENCE",
                "Chapter 9",
                "Light - Reflection and Refraction",
                "Light chapter content.",
                "5",
            ],
            [
                "SCIENCE",
                "Chapter 13",
                "Our Environment",
                "Final chapter environment content.",
                "6",
            ],
        ]
        self._write_pdf(self.fixture_pages)
        chapter_context_service._clear_cache_locks_for_tests()
        self.addCleanup(chapter_context_service._clear_cache_locks_for_tests)

        self.registry_get = patch.object(
            chapter_context_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        ).start()
        self.pdf_get = patch.object(
            chapter_context_service.textbook_pdf_service,
            "get_textbook_pdf",
            return_value=self.pdf_path,
        ).start()
        self.addCleanup(patch.stopall)

    def _write_pdf(self, pages):
        pdf = canvas.Canvas(str(self.pdf_path))
        for page_lines in pages:
            y_position = 760
            for line in page_lines:
                pdf.drawString(72, y_position, line)
                y_position -= 24
            pdf.showPage()
        pdf.save()

    def _get_context(self, chapter=1, **kwargs):
        return chapter_context_service.get_chapter_context(
            10,
            "Science",
            chapter,
            cache_dir=self.context_cache_dir,
            pdf_cache_dir=self.pdf_cache_dir,
            **kwargs,
        )

    def _definition(self, number):
        return next(
            item
            for item in chapter_context_service.CLASS_10_SCIENCE_CHAPTERS
            if item.number == number
        )

    def test_extracts_a_real_local_pdf_chapter_and_rejects_contents_match(self):
        context = self._get_context(1)

        self.assertIsNotNone(context)
        self.assertEqual(context["textbook_id"], "cbse-10-science-science-english-latest")
        self.assertEqual(context["chapter_id"], "chapter-01")
        self.assertEqual(context["matched_chapter_title"], "Chemical Reactions and Equations")
        self.assertEqual(context["start_page_index"], 1)
        self.assertEqual(context["end_page_index"], 2)
        self.assertEqual(context["match"]["confidence"], "high")
        self.assertIn("Chapter one opening content", context["text"])
        self.assertIn("Chapter one continuation", context["text"])
        self.assertNotIn("Acid chapter content", context["text"])
        self.assertEqual([page["page_index"] for page in context["page_texts"]], [1, 2])

    def test_normalized_and_alias_chapter_lookup(self):
        normalized = self._get_context("Chapter 1: Chemical Reactions & Equations")
        alias = self._get_context("Heredity and Evolution")

        self.assertEqual(normalized["chapter_id"], "chapter-01")
        self.assertEqual(normalized["requested_chapter"], "Chapter 1: Chemical Reactions & Equations")
        self.assertEqual(alias["chapter_id"], "chapter-08")
        self.assertEqual(alias["matched_chapter_title"], "Heredity")
        self.assertEqual(alias["start_page_index"], 4)
        self.assertEqual(alias["end_page_index"], 4)

    def test_next_validated_heading_defines_the_end_boundary(self):
        context = self._get_context("Chemical Reactions and Equations")

        self.assertEqual(context["match"]["next_heading_page_index"], 3)
        self.assertEqual(context["end_page_index"], 2)
        self.assertNotIn("Acids, Bases and Salts", context["text"])

    def test_final_chapter_uses_end_of_book_as_boundary(self):
        context = self._get_context(13)

        self.assertEqual(context["start_page_index"], 6)
        self.assertEqual(context["end_page_index"], 6)
        self.assertIsNone(context["match"]["next_heading_page_index"])
        self.assertIn("Final chapter environment content", context["text"])

    def test_missing_next_heading_returns_none_instead_of_the_whole_book(self):
        pages_without_chapter_two = self.fixture_pages[:3]
        self._write_pdf(pages_without_chapter_two)

        self.assertIsNone(self._get_context(1))

    def test_missing_requested_heading_returns_none(self):
        self._write_pdf(
            [
                ["CONTENTS", "Chapter 1", "Chemical Reactions and Equations"],
                ["SCIENCE", "Only ordinary textbook content appears here.", "1"],
                [
                    "SCIENCE",
                    "Chapter 2",
                    "Acids, Bases and Salts",
                    "Chapter two content.",
                    "2",
                ],
            ]
        )

        self.assertIsNone(self._get_context(1))

    def test_in_body_chapter_reference_is_not_treated_as_a_heading(self):
        self._write_pdf(
            [
                ["CONTENTS", "Chapter 3", "Metals and Non-metals"],
                [
                    "SCIENCE",
                    "This page refers readers to Chapter 3 Metals and Non-metals.",
                    "The reference is not a chapter heading.",
                    "1",
                ],
                [
                    "SCIENCE",
                    "Chapter 4",
                    "Carbon and its Compounds",
                    "Chapter four content.",
                    "2",
                ],
            ]
        )

        self.assertIsNone(self._get_context(3))

    def test_unsupported_textbook_and_invalid_chapter_return_none_without_pdf_lookup(self):
        self.registry_get.return_value = None
        self.assertIsNone(self._get_context(1))
        self.pdf_get.assert_not_called()

        self.registry_get.return_value = self.textbook
        self.assertIsNone(self._get_context("Unknown chapter"))
        self.pdf_get.assert_not_called()

    def test_unavailable_pdf_returns_none(self):
        self.pdf_get.return_value = None

        self.assertIsNone(self._get_context(1))

    def test_context_truncates_at_a_safe_boundary_and_records_the_state(self):
        context = self._get_context(1, max_chars=110)

        self.assertTrue(context["truncated"])
        self.assertLessEqual(len(context["text"]), 110)
        self.assertEqual(context["max_chars"], 110)
        self.assertFalse(context["text"].endswith(" "))

    def test_chapter_cache_reuse_avoids_repeat_pdf_lookup_and_page_extraction(self):
        with patch.object(
            chapter_context_service.textbook_text_service,
            "extract_pdf_pages_with_timeout",
            wraps=chapter_context_service.textbook_text_service.extract_pdf_pages_with_timeout,
        ) as extract_pages:
            first_context = self._get_context(1)
            second_context = self._get_context(1)

        self.assertEqual(first_context["text"], second_context["text"])
        self.assertEqual(self.pdf_get.call_count, 1)
        self.assertEqual(extract_pages.call_count, 1)

    def test_corrupt_context_cache_is_recovered(self):
        definition = self._definition(1)
        cache_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            definition,
            character_limit=chapter_context_service.TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS,
            cache_dir=self.context_cache_dir,
        )
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("not-json", encoding="utf-8")

        context = self._get_context(1)

        self.assertIsNotNone(context)
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8"))["chapter_id"], "chapter-01")
        self.assertEqual(self.pdf_get.call_count, 1)

    def test_cache_key_includes_chapter_identity_parser_version_and_context_limit(self):
        chapter_one_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(1),
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )
        chapter_two_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(2),
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )
        different_limit_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(1),
            character_limit=600,
            cache_dir=self.context_cache_dir,
        )

        self.assertNotEqual(chapter_one_path, chapter_two_path)
        self.assertNotEqual(chapter_one_path, different_limit_path)
        self.assertEqual(chapter_one_path.parent, self.context_cache_dir.resolve())


class Class9ExplorationChapterContextServiceTests(unittest.TestCase):
    """Offline fixtures for the verified Class 9 Exploration contents list."""

    CHAPTER_TITLES = (
        "Exploration: Entering the World of Secondary Science",
        "Cell: The Building Block of Life",
        "Tissues in Action",
        "Describing Motion Around Us",
        "Exploring Mixtures and their Separation",
        "How Forces Affect Motion",
        "Work, Energy, and Simple Machines",
        "Journey Inside the Atom",
        "Atomic Foundations of Matter",
        "Sound Waves: Characteristics and Applications",
        "Reproduction: How Life Continues",
        "Patterns in Life: Diversity and Classification",
        "Earth as a System: Energy, Matter, and Life",
    )
    CHAPTER_URLS = (
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
    )

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.context_cache_dir = root / "chapter-context"
        self.pdf_cache_dir = root / "pdf-cache"
        self.page_cache_dir = root / "page-cache"
        self.pdf_path = root / "class-9-exploration.pdf"
        self.textbook = {
            "board": "CBSE",
            "class": 9,
            "subject": "Science",
            "title": "Exploration",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc1ps.pdf",
            "language": "English",
            "version": "First Edition, April 2026",
        }
        self.fixture_pages = [
            [
                "CONTENTS",
                "Chapter 1",
                self.CHAPTER_TITLES[0],
                "Chapter 2",
                self.CHAPTER_TITLES[1],
                "Chapter 3",
                self.CHAPTER_TITLES[2],
            ],
            *[
                [
                    "EXPLORATION",
                    f"Chapter {number}",
                    title,
                    f"Verified Class 9 chapter {number} teaching text.",
                    str(number),
                ]
                for number, title in enumerate(self.CHAPTER_TITLES, start=1)
            ],
        ]
        self._write_pdf(self.fixture_pages)
        chapter_context_service._clear_cache_locks_for_tests()
        self.addCleanup(chapter_context_service._clear_cache_locks_for_tests)

        self.registry_get = patch.object(
            chapter_context_service.textbook_registry,
            "get_textbook",
            return_value=self.textbook,
        ).start()
        self.registry_chapter = patch.object(
            chapter_context_service.textbook_registry,
            "get_chapter",
            side_effect=lambda _class, _subject, chapter: self._chapter_for_number(chapter),
        ).start()
        self.chapter_pages = patch.object(
            chapter_context_service.textbook_text_service,
            "get_chapter_pages",
            side_effect=lambda _class, _subject, chapter, **_kwargs: (
                ["\n".join(self._individual_chapter_page(chapter))],
                1,
            ),
        ).start()
        self.pdf_get = patch.object(
            chapter_context_service.textbook_pdf_service,
            "get_textbook_pdf",
            side_effect=AssertionError("Class 9 must not use the preliminary PDF"),
        ).start()
        self.addCleanup(patch.stopall)

    def _write_pdf(self, pages):
        pdf = canvas.Canvas(str(self.pdf_path))
        for page_lines in pages:
            y_position = 760
            for line in page_lines:
                pdf.drawString(72, y_position, line)
                y_position -= 24
            pdf.showPage()
        pdf.save()

    def _get_context(self, chapter=1, **kwargs):
        return chapter_context_service.get_chapter_context(
            9,
            "Science",
            chapter,
            cache_dir=self.context_cache_dir,
            pdf_cache_dir=self.pdf_cache_dir,
            page_cache_dir=self.page_cache_dir,
            **kwargs,
        )

    def _definition(self, number):
        return next(
            definition
            for definition in chapter_context_service.CLASS_9_SCIENCE_CHAPTERS
            if definition.number == number
        )

    def _chapter_for_number(self, chapter):
        number = int(chapter)
        definition = self._definition(number)
        return {
            "id": definition.identifier,
            "number": number,
            "title": definition.title,
            "pdf_url": self.CHAPTER_URLS[number - 1],
        }

    def _individual_chapter_page(self, chapter, *, number=None, title=None):
        definition = self._definition(int(chapter))
        return [
            "EXPLORATION",
            "Chapter",
            str(number if number is not None else definition.number),
            title if title is not None else definition.title,
            f"Verified Class 9 chapter {definition.number} teaching text.",
        ]

    def test_all_official_class_9_titles_are_configured_in_contents_order(self):
        self.assertEqual(
            tuple(item.title for item in chapter_context_service.CLASS_9_SCIENCE_CHAPTERS),
            self.CHAPTER_TITLES,
        )
        self.assertEqual(
            tuple(item.number for item in chapter_context_service.CLASS_9_SCIENCE_CHAPTERS),
            tuple(range(1, 14)),
        )

    def test_all_class_9_chapter_headings_are_identified_from_local_fixture(self):
        for definition in chapter_context_service.CLASS_9_SCIENCE_CONFIGURATION.chapters:
            with self.subTest(chapter=definition.number):
                boundary = chapter_context_service._locate_individual_chapter_pdf_boundary(
                    ["\n".join(self._individual_chapter_page(definition.number))],
                    definition,
                )
                self.assertIsNotNone(boundary)
                self.assertEqual(boundary[0], 0)
                self.assertEqual(boundary[1], 0)

    def test_extracts_class_9_first_and_final_chapters_with_expected_boundaries(self):
        first_context = self._get_context(1)
        final_context = self._get_context(13)

        self.assertEqual(first_context["cache_version"], "class9-exploration-chapter-pdf-v2")
        self.assertEqual(first_context["textbook_id"], "cbse-9-science-exploration-english-first-edition-april-2026")
        self.assertEqual(first_context["pdf_url"], "https://ncert.nic.in/textbook/pdf/iesc101.pdf")
        self.assertEqual(first_context["source_strategy"], "individual_chapter_pdf")
        self.assertEqual(first_context["start_page_index"], 0)
        self.assertEqual(first_context["end_page_index"], 0)
        self.assertIn("Verified Class 9 chapter 1", first_context["text"])
        self.assertEqual(final_context["pdf_url"], "https://ncert.nic.in/textbook/pdf/iesc113.pdf")
        self.assertEqual(final_context["start_page_index"], 0)
        self.assertEqual(final_context["end_page_index"], 0)
        self.assertIsNone(final_context["match"]["next_heading_page_index"])
        self.assertIn("Verified Class 9 chapter 13", final_context["text"])

    def test_class_9_contents_page_false_match_is_rejected(self):
        self.chapter_pages.side_effect = None
        self.chapter_pages.return_value = (
            [
                "\n".join(
                    [
                        "CONTENTS",
                        "Chapter 1",
                        self.CHAPTER_TITLES[0],
                        "Chapter 2",
                        self.CHAPTER_TITLES[1],
                        "Chapter 3",
                        self.CHAPTER_TITLES[2],
                    ]
                )
            ],
            1,
        )

        self.assertIsNone(self._get_context(1))

    def test_class_9_normalized_and_alias_lookup(self):
        normalized = self._get_context(
            "Chapter 1: Exploration - Entering the World of Secondary Science"
        )
        alias = self._get_context("Entering the World of Secondary Science")

        self.assertEqual(normalized["chapter_id"], "chapter-01")
        self.assertEqual(alias["chapter_id"], "chapter-01")
        self.assertEqual(
            alias["matched_chapter_title"],
            "Exploration: Entering the World of Secondary Science",
        )

    def test_class_9_cache_reuse_avoids_repeat_pdf_lookup_and_page_extraction(self):
        first_context = self._get_context(2)
        second_context = self._get_context(2)

        self.assertEqual(first_context["text"], second_context["text"])
        self.chapter_pages.assert_called_once()
        self.pdf_get.assert_not_called()

    def test_class_9_only_requests_the_registered_selected_chapter_pdf(self):
        context = self._get_context(7)

        self.assertIsNotNone(context)
        self.registry_chapter.assert_called_once_with(9, "Science", 7)
        self.chapter_pages.assert_called_once()
        args, kwargs = self.chapter_pages.call_args
        self.assertEqual(args[:3], (9, "Science", 7))
        self.assertEqual(kwargs["pdf_cache_dir"], self.pdf_cache_dir)
        self.pdf_get.assert_not_called()
        self.assertNotEqual(context["pdf_url"], self.textbook["pdf_url"])

    def test_class_9_mismatched_chapter_number_or_title_is_rejected(self):
        self.chapter_pages.side_effect = None
        self.chapter_pages.return_value = (
            ["\n".join(self._individual_chapter_page(1, number=2))],
            1,
        )
        self.assertIsNone(self._get_context(1))

        self.chapter_pages.reset_mock()
        self.chapter_pages.return_value = (
            ["\n".join(self._individual_chapter_page(1, title="Wrong chapter title"))],
            1,
        )
        self.assertIsNone(self._get_context(1, max_chars=999))

    def test_class_9_unavailable_chapter_pdf_returns_none_without_preliminary_fallback(self):
        self.chapter_pages.side_effect = None
        self.chapter_pages.return_value = None

        self.assertIsNone(self._get_context(3))
        self.pdf_get.assert_not_called()

    def test_class_9_corrupt_context_cache_is_removed_and_regenerated(self):
        chapter = self._chapter_for_number(4)
        cache_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(4),
            source_pdf_url=chapter["pdf_url"],
            character_limit=chapter_context_service.TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS,
            cache_dir=self.context_cache_dir,
        )
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("not-json", encoding="utf-8")

        context = self._get_context(4)

        self.assertIsNotNone(context)
        self.assertEqual(context["pdf_url"], chapter["pdf_url"])
        self.assertEqual(self.chapter_pages.call_count, 1)
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8"))["chapter_id"], "chapter-04")

    def test_class_9_semantically_invalid_context_cache_is_regenerated(self):
        original_context = self._get_context(5)
        chapter = self._chapter_for_number(5)
        cache_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(5),
            source_pdf_url=chapter["pdf_url"],
            character_limit=chapter_context_service.TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS,
            cache_dir=self.context_cache_dir,
        )
        invalid_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        invalid_payload["textbook_id"] = "cbse-10-science-science-english-latest"
        invalid_payload["max_chars"] += 1
        invalid_payload["page_texts"] = [
            {"page_index": True, "text": "Wrong cached chapter content."}
        ]
        cache_path.write_text(json.dumps(invalid_payload), encoding="utf-8")

        regenerated_context = self._get_context(5)

        self.assertEqual(self.chapter_pages.call_count, 2)
        self.assertEqual(regenerated_context["text"], original_context["text"])
        self.assertNotIn("Wrong cached chapter content.", regenerated_context["text"])
        cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cached_payload["textbook_id"], original_context["textbook_id"])
        self.assertEqual(
            cached_payload["max_chars"],
            chapter_context_service.TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS,
        )

    def test_class_9_and_class_10_cache_paths_cannot_collide(self):
        class_9_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(1),
            source_pdf_url=self._chapter_for_number(1)["pdf_url"],
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )
        class_10_textbook = {
            "board": "CBSE",
            "class": 10,
            "subject": "Science",
            "title": "Science",
            "pdf_url": "https://ncert.nic.in/textbook/pdf/jesc1ps.pdf",
            "language": "English",
            "version": "latest",
        }
        class_10_path = chapter_context_service.build_chapter_context_cache_path(
            class_10_textbook,
            chapter_context_service.CLASS_10_SCIENCE_CHAPTERS[0],
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )

        self.assertNotEqual(class_9_path, class_10_path)
        self.assertIn("class_9_science_exploration", class_9_path.name)
        self.assertIn("class_10_science", class_10_path.name)

    def test_class_9_context_cache_keys_differ_across_chapter_urls(self):
        first_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(1),
            source_pdf_url=self._chapter_for_number(1)["pdf_url"],
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )
        second_path = chapter_context_service.build_chapter_context_cache_path(
            self.textbook,
            self._definition(2),
            source_pdf_url=self._chapter_for_number(2)["pdf_url"],
            character_limit=500,
            cache_dir=self.context_cache_dir,
        )

        self.assertNotEqual(first_path, second_path)


if __name__ == "__main__":
    unittest.main()
