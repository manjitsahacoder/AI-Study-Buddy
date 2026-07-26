import os
import json
import base64
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(TEST_DB_FD)
os.environ["QUIZ_HISTORY_DB"] = TEST_DB_PATH
os.environ.setdefault("DIAGRAM_AI_REVIEW_ENABLED", "0")

import app as app_module
from database import db
from gemini_service import classify_gemini_exception
from models import (
    Chapter,
    DownloadedFile,
    DiagramLibrary,
    FavouriteNote,
    Flashcard,
    FlashcardSet,
    ImportantQuestionSet,
    LearningHistory,
    LearningSession,
    MemoryChallenge,
    MemoryChallengeSession,
    MindMap,
    QuizHistory,
    RevisionSheet,
    StudyPlanProgress,
    Textbook,
    TutorLesson,
    TutorMessage,
    User,
)
from textbook_catalog import CBSE_TEXTBOOKS, seed_cbse_textbook_catalog
from diagram_library.metadata import DiagramCandidate, reusable_license
from diagram_library.lookup import (
    build_search_queries,
    candidate_language_category,
    candidate_relevance_score,
    rank_diagram_candidates,
    relevant_diagram_candidates,
    subject_mismatch_terms,
)
from diagram_library.providers import NcertProvider, ProviderRegistry
from diagram_library.ai_review import (
    DiagramReviewDecision,
    clear_review_cache,
    review_diagram_candidates,
)
from diagram_library.service import get_or_create_diagram
from diagram_library.storage import download_and_store, repair_cached_image_extension, valid_cached_image


class MockResponse:
    def __init__(self, text):
        self.text = text


class MockModel:
    def __init__(self, response):
        self.response = response

    def generate_content(self, prompt):
        return self.response


class RouteTests(unittest.TestCase):
    TEST_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    TEST_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        with app_module.app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            app_module.clear_smart_search_cache()
        app_module.latest_report = {}
        self.client = app_module.app.test_client()
        self.questions = [
            "What is question one?",
            "What is question two?",
            "What is question three?",
            "What is question four?",
            "What is question five?",
        ]

    def quiz_payload(self):
        payload = {
            "name": "Asha",
            "student_class": "8",
            "subject": "Biology",
            "topic": "Plants",
        }
        payload.update(
            {
                f"question{index}": question
                for index, question in enumerate(self.questions, start=1)
            }
        )
        return payload

    def tearDown(self):
        with app_module.app.app_context():
            db.session.remove()
            db.drop_all()

    def write_test_diagram(self, filename="test-diagram.png"):
        cache_dir = os.path.join(app_module.app.static_folder, "diagram_cache")
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, filename)
        with open(path, "wb") as image_file:
            image_file.write(self.make_image_bytes("PNG"))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return f"diagram_cache/{filename}"

    def write_ncert_diagram(self, subject_area="biology", filename="mitochondria.png"):
        diagram_dir = Path(app_module.app.static_folder) / "textbook_diagrams" / subject_area
        diagram_dir.mkdir(parents=True, exist_ok=True)
        path = diagram_dir / filename
        path.write_bytes(self.make_image_bytes("PNG"))
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def make_image_bytes(self, image_format):
        from io import BytesIO
        from PIL import Image

        buffer = BytesIO()
        image = Image.new("RGB", (2, 2), color=(80, 120, 200))
        image.save(buffer, format=image_format)
        return buffer.getvalue()

    def seed_cached_diagram(
        self,
        lesson_id=None,
        subject="Biology",
        topic="Photosynthesis",
        filename="test-diagram.png",
        author="Diagram Author",
        license_text="CC BY-SA 4.0",
    ):
        image_path = self.write_test_diagram(filename)
        with app_module.app.app_context():
            diagram = DiagramLibrary(
                lesson_id=lesson_id,
                subject=subject,
                topic=topic,
                image_path=image_path,
                provider="Wikimedia Commons",
                source_url="https://commons.wikimedia.org/wiki/File:Test_diagram.png",
                author=author,
                license=license_text,
                attribution=f"{topic} by {author}, {license_text}",
                verified=True,
            )
            db.session.add(diagram)
            db.session.commit()
            return diagram.id

    def answer_payload(self):
        payload = self.quiz_payload()
        payload.update(
            {
                f"answer{index}": f"Answer {index}"
                for index in range(1, 6)
            }
        )
        return payload

    def register_user(
        self,
        username="asha",
        email="asha@example.com",
        password="password123",
        full_name="Asha Student",
        extra_data=None,
    ):
        data = {
            "full_name": full_name,
            "username": username,
            "email": email,
            "student_class": "8",
            "password": password,
            "confirm_password": password,
        }
        if extra_data:
            data.update(extra_data)
        return self.client.post(
            "/register",
            data=data,
        )

    def login_user(self, identifier="asha", password="password123"):
        return self.client.post(
            "/login",
            data={
                "identifier": identifier,
                "password": password,
            },
        )

    def grant_role(self, username, role):
        with app_module.app.app_context():
            user = User.query.filter_by(username=username).first()
            user.role = role
            db.session.commit()

    def test_supported_classes_are_limited_to_6_through_10(self):
        self.assertEqual(app_module.class_options(), ["6", "7", "8", "9", "10"])

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Classes 6-10", page)
        self.assertIn("Future versions will include dedicated support for Classes 11-12", page)
        self.assertIn('value="10"', page)
        self.assertNotIn('value="11"', page)
        self.assertNotIn('value="12"', page)
        self.assertNotIn(">Class 11<", page)
        self.assertNotIn(">Class 12<", page)

    def test_seed_cbse_textbook_catalog_creates_current_english_books(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

            class_six = Textbook.query.filter_by(
                board="CBSE",
                subject="English",
                class_level=6,
                name="Poorvi",
            ).first()
            kaveri = Textbook.query.filter_by(
                board="CBSE",
                subject="English",
                class_level=9,
                name="Kaveri",
            ).first()
            first_flight = Textbook.query.filter_by(
                board="CBSE",
                subject="English",
                class_level=10,
                name="First Flight",
            ).first()

            self.assertIsNotNone(class_six)
            self.assertIsNotNone(kaveri)
            self.assertIsNotNone(first_flight)
            self.assertEqual(Chapter.query.filter_by(textbook_id=kaveri.id).count(), 16)
            self.assertIsNotNone(
                Chapter.query.filter_by(
                    textbook_id=first_flight.id,
                    title="A Letter to God",
                ).first()
            )

    def test_seed_cbse_textbook_catalog_covers_classes_6_to_10_for_core_subjects(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

            expected_pairs = {
                (class_level, subject)
                for class_level in range(6, 11)
                for subject in ("English", "Mathematics", "Science", "Social Science")
            }
            actual_pairs = {
                (textbook.class_level, textbook.subject)
                for textbook in Textbook.query.filter_by(board="CBSE", is_active=True).all()
            }

            self.assertTrue(expected_pairs.issubset(actual_pairs))
            self.assertEqual(Textbook.query.count(), len(CBSE_TEXTBOOKS))
            self.assertEqual(
                Chapter.query.count(),
                sum(len(textbook["chapters"]) for textbook in CBSE_TEXTBOOKS),
            )
            self.assertIsNotNone(
                Chapter.query.join(Textbook).filter(
                    Textbook.class_level == 10,
                    Textbook.subject == "Mathematics",
                    Chapter.title == "Quadratic Equations",
                ).first()
            )
            self.assertIsNotNone(
                Chapter.query.join(Textbook).filter(
                    Textbook.class_level == 8,
                    Textbook.subject == "Science",
                    Chapter.title == "Cell — Structure and Functions",
                ).first()
            )
            self.assertIsNotNone(
                Chapter.query.join(Textbook).filter(
                    Textbook.class_level == 9,
                    Textbook.subject == "Social Science",
                    Textbook.name == "Understanding Society: India and Beyond",
                    Chapter.title == "Understanding Social Science",
                ).first()
            )

    def test_seed_cbse_textbook_catalog_uses_latest_class_9_social_science_book_only(self):
        expected_chapters = [
            "Understanding Social Science",
            "Shaping of the Earth's Surface",
            "Atmosphere and Climate",
            "Early Humans and Beginning of Civilisation",
            "State and Society up to 1000 CE",
            "Democracy",
            "Elections",
            "Building Blocks in Economics: The Problem of Choice",
            "The Price Puzzle: What Drives the Market",
        ]

        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            seed_cbse_textbook_catalog(db.session)

            active_books = Textbook.query.filter_by(
                board="CBSE",
                subject="Social Science",
                class_level=9,
                is_active=True,
            ).all()

            self.assertEqual(len(active_books), 1)
            self.assertEqual(active_books[0].name, "Understanding Society: India and Beyond")
            chapters = Chapter.query.filter_by(
                textbook_id=active_books[0].id,
            ).order_by(Chapter.chapter_number.asc()).all()
            self.assertEqual([chapter.title for chapter in chapters], expected_chapters)
            self.assertEqual(Textbook.query.count(), len(CBSE_TEXTBOOKS))
            self.assertEqual(
                Chapter.query.count(),
                sum(len(textbook["chapters"]) for textbook in CBSE_TEXTBOOKS),
            )

    def test_smart_textbook_search_examples_work_for_every_core_subject(self):
        examples = [
            ("10", "English", "Flight", "First Flight", "letter", "A Letter to God"),
            ("10", "Mathematics", "Math", "Mathematics", "quad", "Quadratic Equations"),
            ("8", "Science", "Science", "Science", "cell", "Cell — Structure and Functions"),
            ("9", "Social Science", "India", "Understanding Society: India and Beyond", "democracy", "Democracy"),
        ]
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        for class_level, subject, book_query, expected_book, chapter_query, expected_chapter in examples:
            with self.subTest(subject=subject):
                textbook_response = self.client.get(
                    f"/api/textbooks/search?q={book_query}&class={class_level}&subject={subject}"
                )
                self.assertEqual(textbook_response.status_code, 200)
                textbook_payload = textbook_response.get_json()
                textbook = next(
                    item for item in textbook_payload if item["name"] == expected_book
                )

                chapter_response = self.client.get(
                    f"/api/chapters/search?textbook_id={textbook['id']}&q={chapter_query}"
                )
                self.assertEqual(chapter_response.status_code, 200)
                chapter_titles = [item["title"] for item in chapter_response.get_json()]
                self.assertIn(expected_chapter, chapter_titles)

    def test_textbook_search_accepts_maths_alias_for_mathematics_catalog(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        response = self.client.get("/api/textbooks/search?q=math&class=10&subject=Maths")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["name"], "Mathematics")

    def test_textbook_search_api_filters_and_ranks_matches(self):
        with app_module.app.app_context():
            db.session.add_all(
                [
                    Textbook(
                        board="CBSE",
                        subject="English",
                        class_level=9,
                        name="My Beehive Reader",
                        normalized_name="my beehive reader",
                        is_active=True,
                    ),
                    Textbook(
                        board="CBSE",
                        subject="English",
                        class_level=9,
                        name="Beehive",
                        normalized_name="beehive",
                        is_active=True,
                    ),
                    Textbook(
                        board="CBSE",
                        subject="English",
                        class_level=9,
                        name="Beehive Workbook",
                        normalized_name="beehive workbook",
                        is_active=True,
                    ),
                ]
            )
            db.session.commit()

        response = self.client.get("/api/textbooks/search?q=beehive&class=9&subject=English")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            [item["name"] for item in payload[:3]],
            ["Beehive", "Beehive Workbook", "My Beehive Reader"],
        )
        self.assertEqual(payload[0]["board"], "CBSE")
        self.assertEqual(payload[0]["class"], 9)

    def test_textbook_info_endpoint_returns_metadata(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            textbook_id = textbook.id
            chapter_count = Chapter.query.filter_by(textbook_id=textbook_id).count()

        response = self.client.get(f"/api/textbooks/{textbook_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["id"], textbook_id)
        self.assertEqual(payload["name"], "First Flight")
        self.assertEqual(payload["board"], "CBSE")
        self.assertEqual(payload["class"], 10)
        self.assertEqual(payload["subject"], "English")
        self.assertEqual(payload["chapter_count"], chapter_count)
        self.assertTrue(payload["available"])

    def test_textbook_info_endpoint_returns_404_for_missing_textbook(self):
        response = self.client.get("/api/textbooks/9999")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["available"])

    def test_textbook_search_database_hit_skips_gemini(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get("/api/textbooks/search?q=Kaveri&class=9&subject=English")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["name"], "Kaveri")
        self.assertFalse(payload[0].get("ai_suggestion", False))
        gemini_request.assert_not_called()

    def test_textbook_search_by_latest_class_9_social_science_keyword_skips_gemini(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get("/api/textbooks/search?q=monsoon&class=9&subject=Social%20Science")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["name"], "Understanding Society: India and Beyond")
        self.assertFalse(payload[0].get("ai_suggestion", False))
        gemini_request.assert_not_called()

    def test_textbook_search_database_miss_calls_gemini_for_spelling_correction(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            gemini_request.return_value = MockResponse(
                json.dumps(
                    {
                        "suggestions": [
                            {"name": "First Flight", "confidence": 0.96},
                        ]
                    }
                )
            )
            response = self.client.get("/api/textbooks/search?q=First%20Flite&class=10&subject=English")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["name"], "First Flight")
        self.assertTrue(payload[0]["ai_suggestion"])
        self.assertFalse(payload[0]["unavailable"])
        gemini_request.assert_called_once()

    def test_textbook_search_gemini_unavailable_returns_empty_suggestions(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request", side_effect=Exception("Gemini unavailable")) as gemini_request:
            response = self.client.get("/api/textbooks/search?q=Nopebook&class=10&subject=English")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        gemini_request.assert_called_once()

    def test_textbook_search_malformed_gemini_json_returns_empty_suggestions(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            gemini_request.return_value = MockResponse("First Flight")
            response = self.client.get("/api/textbooks/search?q=Furst%20Flyt&class=10&subject=English")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        gemini_request.assert_called_once()

    def test_textbook_search_reuses_gemini_cache_for_identical_miss(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            gemini_request.return_value = MockResponse(
                json.dumps(
                    {
                        "suggestions": [
                            {"name": "Poorvi", "confidence": 0.97},
                        ]
                    }
                )
            )
            first_response = self.client.get("/api/textbooks/search?q=Poorvee&class=6&subject=English")
            second_response = self.client.get("/api/textbooks/search?q=Poorvee&class=6&subject=English")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.get_json(), second_response.get_json())
        self.assertEqual(first_response.get_json()[0]["name"], "Poorvi")
        gemini_request.assert_called_once()

    def test_textbook_search_ai_suggestion_not_in_database_is_unavailable(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)

        with patch("app.gemini_request") as gemini_request:
            gemini_request.return_value = MockResponse(
                json.dumps(
                    {
                        "suggestions": [
                            {"name": "Imaginary Reader", "confidence": 0.95},
                        ]
                    }
                )
            )
            response = self.client.get("/api/textbooks/search?q=Imaginary&class=10&subject=English")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["name"], "Imaginary Reader")
        self.assertTrue(payload[0]["ai_suggestion"])
        self.assertTrue(payload[0]["unavailable"])

    def test_chapter_search_api_returns_case_insensitive_suggestions(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(
                board="CBSE",
                subject="English",
                class_level=10,
                name="First Flight",
            ).first()
            textbook_id = textbook.id

        response = self.client.get(f"/api/chapters/search?textbook_id={textbook_id}&q=god")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertLessEqual(len(payload), 10)
        self.assertEqual(payload[0]["title"], "A Letter to God")
        self.assertEqual(payload[0]["textbook_id"], textbook_id)

    def test_empty_chapter_search_returns_popular_chapters_without_gemini(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            textbook_id = textbook.id

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get(f"/api/chapters/search?textbook_id={textbook_id}&q=")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertLessEqual(len(payload), 12)
        self.assertEqual(payload[0]["title"], "A Letter to God")
        self.assertEqual(payload[0]["chapter_number"], 1)
        gemini_request.assert_not_called()

    def test_chapter_search_database_hit_skips_gemini(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            textbook_id = textbook.id

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get(f"/api/chapters/search?textbook_id={textbook_id}&q=letter")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["title"], "A Letter to God")
        gemini_request.assert_not_called()

    def test_latest_class_9_social_science_keyword_search_skips_gemini(self):
        examples = [
            ("monsoon", "Atmosphere and Climate"),
            ("weather", "Atmosphere and Climate"),
            ("democracy", "Democracy"),
            ("voting", "Elections"),
            ("opportunity cost", "Building Blocks in Economics: The Problem of Choice"),
            ("demand", "The Price Puzzle: What Drives the Market"),
        ]
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(
                board="CBSE",
                subject="Social Science",
                class_level=9,
                name="Understanding Society: India and Beyond",
            ).first()
            textbook_id = textbook.id

        for query_text, expected_chapter in examples:
            with self.subTest(query=query_text), patch("app.gemini_request") as gemini_request:
                response = self.client.get(
                    f"/api/chapters/search?textbook_id={textbook_id}&q={query_text}"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()[0]["title"], expected_chapter)
                gemini_request.assert_not_called()

    def test_chapter_search_database_miss_calls_gemini_for_spelling_correction(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            textbook_id = textbook.id

        with patch("app.gemini_request") as gemini_request:
            gemini_request.return_value = MockResponse(
                json.dumps(
                    {
                        "suggestions": [
                            {"title": "A Letter to God", "confidence": 0.96},
                        ]
                    }
                )
            )
            response = self.client.get(f"/api/chapters/search?textbook_id={textbook_id}&q=letrr")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["title"], "A Letter to God")
        self.assertTrue(payload[0]["ai_suggestion"])
        self.assertFalse(payload[0]["unavailable"])
        gemini_request.assert_called_once()

    def test_home_renders_ai_suggestion_badge_and_unavailable_message(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Suggestion", page)
        self.assertIn("This textbook is not yet available.", page)

    def test_home_renders_textbook_and_chapter_information_components(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("data-textbook-info-card", page)
        self.assertIn("data-chapter-info-card", page)
        self.assertIn("data-popular-chapters-panel", page)
        self.assertIn("Popular Chapters", page)
        self.assertIn("Ready to Generate", page)

    def test_home_script_supports_chapter_filtering_selection_and_clear(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("function isSmartTextbookSubject()", page)
        self.assertIn('"mathematics"', page)
        self.assertIn('"science"', page)
        self.assertIn('"social science"', page)
        self.assertIn("function renderPopularChapters(items, filterText)", page)
        self.assertIn("chapterSearchText(item).includes(normalizedFilter)", page)
        self.assertIn("selectChapter(item)", page)
        self.assertIn("hideTextbookInfoCard()", page)
        self.assertIn("hidePopularChapters()", page)

    def test_home_script_toggles_generate_button_state(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("data-start-learning-button", page)
        self.assertIn("function setStartButtonState()", page)
        self.assertIn("startButton.disabled = Boolean(locked)", page)
        self.assertIn('startButton.setAttribute("aria-disabled"', page)

    def test_styles_include_responsive_selection_card_rendering(self):
        css_path = Path(app_module.app.static_folder) / "style.css"
        styles = css_path.read_text(encoding="utf-8")

        self.assertIn(".selection-info-card", styles)
        self.assertIn(".popular-chapter-button", styles)
        self.assertIn("@media (max-width: 560px)", styles)
        self.assertIn(".dark-mode .selection-info-card", styles)

    def test_registration_rejects_unsupported_class(self):
        response = self.register_user(extra_data={"student_class": "11"})

        self.assertEqual(response.status_code, 400)
        page = response.get_data(as_text=True)
        self.assertIn(app_module.SUPPORTED_CLASS_MESSAGE, page)
        self.assertNotIn('value="11"', page)
        with app_module.app.app_context():
            self.assertEqual(User.query.count(), 0)

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_unsupported_class_before_ai_generation(self, generate_content):
        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "12",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(app_module.SUPPORTED_CLASS_MESSAGE, response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_invalid_selected_textbook_before_ai_generation(self, generate_content):
        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "9",
                "subject": "English",
                "book_name": "Kaveri",
                "topic": "How I Taught My Grandmother to Read",
                "textbook_id": "9999",
                "chapter_id": "1",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Selected textbook was not found.", response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_chapter_from_different_textbook_before_ai_generation(self, generate_content):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            kaveri = Textbook.query.filter_by(class_level=9, name="Kaveri").first()
            first_flight = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            first_flight_chapter = Chapter.query.filter_by(textbook_id=first_flight.id).first()
            kaveri_id = kaveri.id
            first_flight_chapter_id = first_flight_chapter.id

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "9",
                "subject": "English",
                "book_name": "Kaveri",
                "topic": "A Letter to God",
                "textbook_id": str(kaveri_id),
                "chapter_id": str(first_flight_chapter_id),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Selected chapter does not belong", response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_validation_accepts_maths_alias_for_mathematics_textbook(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Quadratic Equations
Quadratic equations have degree two.

## Quick Revision
- Standard form is ax^2 + bx + c = 0.

## Visualization Decision JSON
{"visualization_required": false, "reason": "Formula lesson."}

## Diagram JSON
{"template":"generic","title":"Quadratic Equations","elements":{},"labels":[],"type":"none","nodes":[],"connections":[],"reason":"Text lesson.","confidence":0.1}

## Questions
Q1. What is the standard form?

Q2. What is the degree?

Q3. Name one solving method.

Q4. What is the discriminant?

Q5. When are roots equal?
"""
        )
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(
                class_level=10,
                subject="Mathematics",
                name="Mathematics",
            ).first()
            chapter = Chapter.query.filter_by(
                textbook_id=textbook.id,
                title="Quadratic Equations",
            ).first()
            textbook_id = textbook.id
            chapter_id = chapter.id

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "10",
                "subject": "Maths",
                "book_name": "Mathematics",
                "topic": "Quadratic Equations",
                "textbook_id": str(textbook_id),
                "chapter_id": str(chapter_id),
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Textbook: Mathematics", prompt)
        self.assertIn("Chapter: Quadratic Equations", prompt)

    def test_textbook_pdf_paths_prioritize_selected_chapter_candidate(self):
        pdf_paths = [
            Path(f"iebe10{index}.pdf")
            for index in range(1, 9)
        ] + [
            Path("iebe1a1.pdf"),
            Path("iebe1ps.pdf"),
        ]

        ordered_paths = app_module.order_textbook_pdf_paths_for_chapter(
            pdf_paths,
            chapter_number=16,
            chapter_count=16,
        )

        self.assertEqual(ordered_paths[0], Path("iebe108.pdf"))
        self.assertEqual(ordered_paths[-2:], [Path("iebe1a1.pdf"), Path("iebe1ps.pdf")])
        self.assertCountEqual(ordered_paths, pdf_paths)

    def test_understanding_society_registered_and_extracts_local_context(self):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(
                class_level=9,
                subject="Social Science",
                name="Understanding Society: India and Beyond",
                is_active=True,
            ).first()
            chapter = Chapter.query.filter_by(
                textbook_id=textbook.id,
                title="Atmosphere and Climate",
            ).first()
            chapter_count = Chapter.query.filter_by(textbook_id=textbook.id).count()

        context = app_module.local_textbook_context_section(
            "9",
            "Social Science",
            textbook.name,
            chapter.title,
            chapter_number=chapter.chapter_number,
            chapter_count=chapter_count,
        )

        self.assertIn("Local Textbook PDF Context:", context)
        self.assertIn("Matched PDF:", context)
        self.assertIn("Atmosphere and Climate", context)
        self.assertGreater(len(context), 500)

    def test_extract_pdf_text_uses_persistent_cache_between_lru_misses(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            pdf_path = Path(temporary_directory) / "chapter.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            cache_dir = Path(temporary_directory) / "text-cache"
            reader_calls = []

            class FakePage:
                def extract_text(self):
                    return "Cached chapter text"

            class FakePdfReader:
                def __init__(self, path, **kwargs):
                    reader_calls.append(path)
                    self.pages = [FakePage()]

            fake_pypdf = type("FakePypdf", (), {"PdfReader": FakePdfReader})

            with patch.object(app_module, "LEARN_TEXTBOOK_TEXT_CACHE_DIR", cache_dir):
                with patch.dict("sys.modules", {"pypdf": fake_pypdf}):
                    app_module.extract_pdf_text.cache_clear()
                    first_text = app_module.extract_pdf_text(str(pdf_path), 100)
                    app_module.extract_pdf_text.cache_clear()
                    second_text = app_module.extract_pdf_text(str(pdf_path), 100)
                    app_module.extract_pdf_text.cache_clear()

        self.assertEqual(first_text, "Cached chapter text")
        self.assertEqual(second_text, "Cached chapter text")
        self.assertEqual(len(reader_calls), 1)

    def test_textbook_context_returns_empty_when_pdf_extraction_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            textbook_dir = Path(temporary_directory) / "broken_book"
            textbook_dir.mkdir()
            (textbook_dir / "broken.pdf").write_bytes(b"%PDF malformed")
            registry_key = ("8", "science", "broken book")

            with patch.dict(app_module.TEXTBOOK_REGISTRY, {registry_key: textbook_dir}):
                with patch.object(
                    app_module,
                    "_extract_pdf_text_with_timeout",
                    side_effect=TimeoutError("pypdf extraction timed out"),
                ):
                    app_module.extract_pdf_text.cache_clear()
                    with self.assertLogs(app_module.app.logger.name, level="WARNING") as logs:
                        context = app_module.local_textbook_context_section(
                            "8",
                            "Science",
                            "Broken Book",
                            "Plants",
                        )
                    app_module.extract_pdf_text.cache_clear()

        self.assertEqual(context, "")
        log_output = "\n".join(logs.output)
        self.assertIn("textbook_pdf_extraction_failed", log_output)
        self.assertIn("context_load_failed", log_output)

    def test_local_textbook_context_logs_missing_registry_diagnostic(self):
        with self.assertLogs(app_module.app.logger.name, level="WARNING") as logs:
            context = app_module.local_textbook_context_section(
                "10",
                "English",
                "First Flight",
                "A Letter to God",
            )

        self.assertEqual(context, "")
        diagnostic = "\n".join(logs.output)
        self.assertIn("status=registry_missing", diagnostic)
        self.assertIn("First Flight", diagnostic)
        self.assertIn("A Letter to God", diagnostic)
        self.assertIn("('10', 'english', 'first flight')", diagnostic)

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_selected_textbook_from_different_subject(self, generate_content):
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(
                class_level=10,
                subject="Mathematics",
                name="Mathematics",
            ).first()
            chapter = Chapter.query.filter_by(
                textbook_id=textbook.id,
                title="Quadratic Equations",
            ).first()
            textbook_id = textbook.id
            chapter_id = chapter.id

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "10",
                "subject": "Science",
                "book_name": "Mathematics",
                "topic": "Quadratic Equations",
                "textbook_id": str(textbook_id),
                "chapter_id": str(chapter_id),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Selected textbook does not match the selected subject.", response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_selected_textbook_from_different_board(self, generate_content):
        with app_module.app.app_context():
            textbook = Textbook(
                board="ICSE",
                subject="Science",
                class_level=8,
                name="Science",
                normalized_name="science",
                is_active=True,
            )
            db.session.add(textbook)
            db.session.flush()
            chapter = Chapter(
                textbook_id=textbook.id,
                chapter_number=1,
                title="Cells",
                normalized_title="cells",
            )
            db.session.add(chapter)
            db.session.commit()
            textbook_id = textbook.id
            chapter_id = chapter.id

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Science",
                "book_name": "Science",
                "topic": "Cells",
                "textbook_id": str(textbook_id),
                "chapter_id": str(chapter_id),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Selected textbook does not match the selected board.", response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_prompt_and_history_include_selected_textbook_context(self, generate_content):
        self.register_user(extra_data={"student_class": "10"})
        self.login_user()
        generate_content.return_value = MockResponse(
            """# A Letter to God
Lencho writes a letter to God.

## Quick Revision
- Lencho hopes for help.

## Visualization Decision JSON
{"visualization_required": false, "reason": "This lesson is primarily text based."}

## Diagram JSON
{"template":"generic","title":"A Letter to God","elements":{},"labels":[],"type":"none","nodes":[],"connections":[],"reason":"Text lesson.","confidence":0.1}

## Questions
Q1. What does Lencho hope for?

Q2. Why does Lencho write a letter?

Q3. Who reads the letter?

Q4. What is Lencho's reaction?

Q5. What is the main theme?
"""
        )
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            chapter = Chapter.query.filter_by(textbook_id=textbook.id, title="A Letter to God").first()
            textbook_id = textbook.id
            chapter_id = chapter.id

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "10",
                "subject": "English",
                "book_name": "First Flight",
                "topic": "A Letter to God",
                "textbook_id": str(textbook_id),
                "chapter_id": str(chapter_id),
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Class: 10", prompt)
        self.assertIn("Board: CBSE", prompt)
        self.assertIn("Subject: English", prompt)
        self.assertIn("Textbook: First Flight", prompt)
        self.assertIn("Chapter: A Letter to God", prompt)
        self.assertIn("Treat the selected textbook as authoritative.", prompt)
        self.assertIn("Do not mix content from books with similar chapter names.", prompt)
        self.assertIn("Follow NCERT/CBSE terminology.", prompt)
        self.assertIn("Story summary", prompt)
        self.assertIn("Main characters", prompt)
        self.assertIn("Literary devices", prompt)
        self.assertIn("Difficult vocabulary with meanings", prompt)
        self.assertIn("Teach this topic like an experienced CBSE teacher.", prompt)
        self.assertIn("Assume the student has no prior knowledge of the topic.", prompt)
        self.assertIn("## Introduction", prompt)
        self.assertIn("## Main Explanation", prompt)
        self.assertIn("## Important Concepts", prompt)
        self.assertIn("## Real-Life Examples", prompt)
        self.assertIn("## Applications", prompt)
        self.assertIn("## Key Facts", prompt)
        self.assertIn("## Common Mistakes / Misconceptions", prompt)
        self.assertIn("## Conclusion", prompt)
        self.assertIn("Use paragraphs for explanation and bullet points only where they improve clarity.", prompt)
        self.assertIn("Create exactly 5 teacher-style quiz questions from the selected chapter", prompt)
        with app_module.app.app_context():
            lesson = LearningHistory.query.first()
            self.assertEqual(lesson.board, "CBSE")
            self.assertEqual(lesson.subject, "English")
            self.assertEqual(lesson.book_name, "First Flight")
            self.assertEqual(lesson.topic, "A Letter to God")
            self.assertEqual(lesson.textbook_id, textbook_id)
            self.assertEqual(lesson.chapter_id, chapter_id)

    @patch.object(app_module.model, "generate_content")
    def test_learn_generates_quiz_questions_when_lesson_omits_questions_section(self, generate_content):
        self.register_user(extra_data={"student_class": "8"})
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Photosynthesis
Plants make food using sunlight.

## Quick Revision
- Leaves use sunlight.

## Visualization Decision JSON
{"visualization_required": false, "reason": "This lesson is primarily text based."}

## Diagram JSON
{"template":"generic","title":"Photosynthesis","elements":{},"labels":[],"type":"none","nodes":[],"connections":[],"reason":"Text lesson.","confidence":0.1}
"""
        )

        with self.assertLogs(app_module.app.logger.name, level="INFO") as logs:
            response = self.client.post(
                "/learn",
                data={
                    "name": "Asha",
                    "student_class": "8",
                    "subject": "Science",
                    "book_name": "NCERT",
                    "topic": "Photosynthesis",
                },
            )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Plants make food using sunlight.", page)
        self.assertIn("What does the lesson explain about sunlight?", page)
        self.assertEqual(generate_content.call_count, 1)
        lesson_prompt = generate_content.call_args.args[0]
        self.assertIn("## Questions", lesson_prompt)
        log_output = "\n".join(logs.output)
        self.assertIn("gemini_request_start feature=Notes", log_output)
        self.assertIn("gemini_request_complete feature=Notes", log_output)
        self.assertIn("event=textbook_lookup_complete", log_output)
        self.assertIn("event=lesson_generation_complete", log_output)
        self.assertIn("event=gemini_response", log_output)
        self.assertIn("duration_ms=", log_output)
        self.assertIn("event=quiz_generation_complete", log_output)
        self.assertIn("source=local_fallback", log_output)
        self.assertIn("event=complete", log_output)
        self.assertIn("total_request_time_seconds=", log_output)

        with app_module.app.app_context():
            lesson = LearningHistory.query.first()
            saved_questions = json.loads(lesson.quiz_questions)

        self.assertEqual(
            saved_questions[0],
            "In your own words, explain the main idea of Photosynthesis from the lesson.",
        )
        self.assertEqual(saved_questions[2], "What does the lesson explain about sunlight?")
        self.assertEqual(len(saved_questions), 5)

    @patch.object(app_module.model, "generate_content")
    def test_learn_continues_when_textbook_pdf_extraction_fails(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Plants
Plants need sunlight and water.

## Quick Revision
- Plants are living things.

## Questions
Q1. What do plants need?

Q2. Why is sunlight useful for plants?

Q3. Name one thing plants need to grow.

Q4. What are plants?

Q5. Write one important point about plants.
"""
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            textbook_dir = Path(temporary_directory) / "broken_book"
            textbook_dir.mkdir()
            (textbook_dir / "broken.pdf").write_bytes(b"%PDF malformed")
            registry_key = ("8", "science", "broken book")

            with patch.dict(app_module.TEXTBOOK_REGISTRY, {registry_key: textbook_dir}):
                with patch.object(
                    app_module,
                    "_extract_pdf_text_with_timeout",
                    side_effect=TimeoutError("pypdf extraction timed out"),
                ):
                    app_module.extract_pdf_text.cache_clear()
                    with self.assertLogs(app_module.app.logger.name, level="WARNING") as logs:
                        response = self.client.post(
                            "/learn",
                            data={
                                "name": "Asha",
                                "student_class": "8",
                                "subject": "Science",
                                "book_name": "Broken Book",
                                "topic": "Plants",
                            },
                        )
                    app_module.extract_pdf_text.cache_clear()

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Plants need sunlight and water.", page)
        self.assertIn("What do plants need?", page)
        self.assertEqual(generate_content.call_count, 1)
        log_output = "\n".join(logs.output)
        self.assertIn("textbook_pdf_extraction_failed", log_output)
        self.assertIn("context_load_failed", log_output)

    def test_legacy_lesson_prompt_context_falls_back_without_textbook_ids(self):
        legacy_lesson = {
            "subject": "Science",
            "book_name": "",
            "topic": "Photosynthesis",
            "notes": "Plants make food.",
        }

        prompt_context = app_module.lesson_textbook_context_for_prompt(legacy_lesson, "8")

        self.assertIn("Board: CBSE", prompt_context)
        self.assertIn("Subject: Science", prompt_context)
        self.assertIn("Textbook: N/A", prompt_context)
        self.assertIn("Chapter: Photosynthesis", prompt_context)

    def test_selected_textbook_context_flows_to_history_tutor_pdf_diagram_and_quiz_for_all_subjects(self):
        from io import BytesIO
        from types import SimpleNamespace

        from pypdf import PdfReader

        examples = [
            ("10", "English", "First Flight", "A Letter to God"),
            ("10", "Mathematics", "Mathematics", "Quadratic Equations"),
            ("8", "Science", "Science", "Cell — Structure and Functions"),
            ("9", "Social Science", "Understanding Society: India and Beyond", "Democracy"),
        ]

        with app_module.app.app_context():
            app_module.create_user(
                "Asha Student",
                "asha_context",
                "asha_context@example.com",
                "10",
                "password123",
            )
            seed_cbse_textbook_catalog(db.session)

            for student_class, subject, book_name, chapter_title in examples:
                with self.subTest(subject=subject):
                    textbook = Textbook.query.filter_by(
                        board="CBSE",
                        class_level=int(student_class),
                        subject=subject,
                        name=book_name,
                    ).first()
                    chapter = Chapter.query.filter_by(
                        textbook_id=textbook.id,
                        title=chapter_title,
                    ).first()
                    lesson_id = app_module.save_learning_history(
                        1,
                        subject,
                        textbook.name,
                        chapter.title,
                        f"# {chapter.title}\nOfficial chapter notes.",
                        {"available": False, "title": chapter.title},
                        self.questions,
                        board=textbook.board,
                        textbook_id=textbook.id,
                        chapter_id=chapter.id,
                    )
                    lesson = db.session.get(LearningHistory, lesson_id)

                    self.assertEqual(lesson.board, "CBSE")
                    self.assertEqual(lesson.subject, subject)
                    self.assertEqual(lesson.book_name, book_name)
                    self.assertEqual(lesson.topic, chapter_title)
                    self.assertEqual(lesson.textbook_id, textbook.id)
                    self.assertEqual(lesson.chapter_id, chapter.id)

                    lesson_context = app_module.lesson_textbook_context_for_prompt(lesson, student_class)
                    self.assertIn(f"Subject: {subject}", lesson_context)
                    self.assertIn(f"Textbook: {book_name}", lesson_context)
                    self.assertIn(f"Chapter: {chapter_title}", lesson_context)

                    tutor_prompt = app_module.build_tutor_prompt(
                        SimpleNamespace(
                            name="Asha",
                            student_class=student_class,
                            subject=subject,
                            book_name=book_name,
                            chapter=chapter_title,
                            learning_history=lesson,
                        ),
                        lesson.notes,
                        [],
                        "Explain this chapter.",
                    )
                    self.assertIn(f"- Subject: {subject}", tutor_prompt)
                    self.assertIn(f"- Textbook: {book_name}", tutor_prompt)
                    self.assertIn(f"- Chapter: {chapter_title}", tutor_prompt)

                    diagram_prompt = app_module.build_diagram_explanation_prompt(
                        lesson,
                        {"title": chapter_title, "labels": ["Key idea"]},
                        {},
                        student_class,
                    )
                    self.assertIn(f"Subject: {subject}", diagram_prompt)
                    self.assertIn(f"Textbook: {book_name}", diagram_prompt)
                    self.assertIn(f"Chapter: {chapter_title}", diagram_prompt)

                    quiz_prompt = app_module.build_adaptive_quiz_prompt_section(
                        subject,
                        chapter_title,
                        book_name,
                        student_class,
                    )
                    self.assertIn("Adaptive Quiz Engine:", quiz_prompt)

                    pdf_file = app_module.create_learning_history_pdf(
                        lesson,
                        {"available": False},
                        self.questions,
                    )
                    pdf_text = "\n".join(
                        page.extract_text() or ""
                        for page in PdfReader(BytesIO(pdf_file.getvalue())).pages
                    )
                    normalized_pdf_text = " ".join(pdf_text.split())
                    self.assertIn("Board: CBSE", normalized_pdf_text)
                    self.assertIn(f"Textbook: {book_name}", normalized_pdf_text)
                    self.assertIn(f"Chapter: {chapter_title}", normalized_pdf_text)

    @patch.object(app_module.model, "generate_content")
    def test_saved_ai_tools_reject_legacy_unsupported_account_class(self, generate_content):
        with app_module.app.app_context():
            app_module.create_user(
                "Legacy Student",
                "legacy",
                "legacy@example.com",
                "11",
                "password123",
            )
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "",
                "Photosynthesis",
                "Plants make food.",
                {"available": False},
                ["What do plants make?"],
            )

        self.login_user(identifier="legacy", password="password123")
        response = self.client.get(f"/flashcards/{lesson_id}")

        self.assertEqual(response.status_code, 400)
        self.assertIn(app_module.SUPPORTED_CLASS_MESSAGE, response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_displays_notes_and_carries_five_questions(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Quick Revision
- Plants need light.

## Diagram Data
D1: Seed
D2: Roots grow
D3: Leaves make food

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Subject: Biology", prompt)
        self.assertIn("Topic: Plants", prompt)
        self.assertIn("Adaptive Quiz Engine", prompt)
        self.assertIn("Automatically classified educational category: Science", prompt)
        self.assertIn("## Diagram JSON", prompt)
        page = response.get_data(as_text=True)
        self.assertIn("Plant Notes", page)
        self.assertIn("<strong>Subject</strong> Biology", page)
        self.assertIn("Educational Diagram", page)
        self.assertIn("No suitable educational diagram found.", page)
        self.assertNotIn("ai-visualization-svg", page)
        self.assertNotIn('<img class="diagram-library-image"', page)
        self.assertNotIn("D1: Seed", page)
        self.assertNotIn('action="/download_diagram"', page)
        self.assertNotIn('name="diagram_json"', page)
        self.assertNotIn("Download Diagram", page)
        self.assertNotIn("Full Screen", page)
        self.assertIn('action="/download_notes"', page)
        self.assertIn('name="notes"', page)
        self.assertIn('name="diagram_image"', page)
        self.assertIn('action="/quiz"', page)
        self.assertNotIn('name="answer1"', page)
        for index, question in enumerate(self.questions, start=1):
            self.assertIn(f'name="question{index}"', page)
            self.assertIn(question, page)

    def test_adaptive_quiz_classifies_requested_subjects(self):
        cases = [
            ("English", "Grammar", "", "English Grammar"),
            ("English", "Tenses", "", "English Grammar"),
            ("English", "Articles", "", "English Grammar"),
            ("English", "Active Passive Voice", "", "English Grammar"),
            ("English", "Narration", "", "English Grammar"),
            ("Mathematics", "Linear Equations", "", "Mathematics"),
            ("Science", "Force and Motion", "", "Science"),
            ("History", "Indian Freedom Movement", "", "History"),
        ]

        for subject, topic, book_name, expected_category in cases:
            with self.subTest(subject=subject, topic=topic):
                self.assertEqual(
                    app_module.classify_lesson_category(subject, topic, book_name),
                    expected_category,
                )

    def test_adaptive_quiz_prompt_makes_grammar_practice_oriented(self):
        grammar_topics = ["Tenses", "Articles", "Active Passive Voice", "Narration"]

        for topic in grammar_topics:
            with self.subTest(topic=topic):
                prompt = app_module.build_adaptive_quiz_prompt_section(
                    "English",
                    topic,
                    "",
                    "8",
                )

                self.assertIn("Automatically classified educational category: English Grammar", prompt)
                self.assertIn("practice-oriented grammar questions", prompt)
                self.assertIn("fill in the blanks", prompt)
                self.assertIn("error correction", prompt)
                self.assertIn("sentence transformation", prompt)
                self.assertIn("Avoid definition-only questions", prompt)
                self.assertIn("Make the student apply the grammar rule", prompt)
                self.assertIn("Do not ask questions like", prompt)
                self.assertIn("A question may span multiple lines", prompt)
                self.assertIn("She ____ (go) to school every day.", prompt)
                self.assertIn("insert one blank line before the first sub-part", prompt)
                self.assertIn("①", prompt)
                self.assertIn("Never place multiple sub-parts on the same line", prompt)
                self.assertIn("Do NOT separate sub-parts using spaces", prompt)
                self.assertIn("Always use newline characters between sub-parts", prompt)
                self.assertFalse(
                    any("a)" in line and "b)" in line for line in prompt.splitlines())
                )

    @patch.object(app_module.model, "generate_content")
    def test_learn_preserves_multiline_grammar_question_body_through_storage(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Tenses
Tenses show the time of an action.

## Quick Revision
- Use the simple present for habits.

## Questions
Q1. Fill in the blank with the correct form of the verb given in the brackets:
She ____ (go) to school every day.

Q2. Correct the error in the sentence:
He go to market yesterday.

Q3. Rearrange the words to make a meaningful sentence:
school / goes / she / to / every day

Q4. Rewrite the sentence in the past tense:
I eat breakfast.

Q5. Identify the tense:
They are playing football.
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "English",
                "topic": "Tenses",
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Q1. Fill in the blanks with the correct form of the verb.", prompt)
        self.assertIn(
            "Q1. Fill in the blanks with the correct form of the verb.\n\n"
            "  ① My brother ____ (visit) London next month.",
            prompt,
        )
        self.assertIn("\n\n  ② She ____ (write) a letter to her friend yesterday.", prompt)
        self.assertIn("\n\n  ③ They ____ (play) football since morning.", prompt)
        self.assertIn("Do NOT separate sub-parts using spaces", prompt)
        self.assertIn("Always use newline characters between sub-parts", prompt)
        self.assertFalse(
            any("a)" in line and "b)" in line for line in prompt.splitlines())
        )
        page = response.get_data(as_text=True)
        self.assertIn("Fill in the blank with the correct form of the verb", page)
        self.assertIn("She ____ (go) to school every day.", page)

        with app_module.app.app_context():
            lesson = LearningHistory.query.first()
            saved_questions = json.loads(lesson.quiz_questions)

        self.assertEqual(
            saved_questions[0],
            "Fill in the blank with the correct form of the verb given in the brackets:\n"
            "She ____ (go) to school every day.",
        )
        self.assertIn("He go to market yesterday.", saved_questions[1])
        self.assertIn("school / goes / she / to / every day", saved_questions[2])

    def test_split_learning_content_preserves_grammar_question_blocks(self):
        _, _, _, questions = app_module.split_learning_content(
            """# Tenses
Tenses show time.

## Questions
Q1. Fill in the blank with the correct form of the verb given in the brackets:
She ____ (go) to school every day.

Q2. Correct the error in the sentence:
He go to market yesterday.

Q3. Rearrange the words to make a meaningful sentence:
school / goes / she / to / every day

Q4. Change into passive voice:
The teacher praised the student.

Q5. Rewrite as indirect speech:
She said, "I am tired."
"""
        )

        self.assertEqual(
            questions[0],
            "Fill in the blank with the correct form of the verb given in the brackets:\n"
            "She ____ (go) to school every day.",
        )
        self.assertEqual(
            questions[1],
            "Correct the error in the sentence:\nHe go to market yesterday.",
        )
        self.assertEqual(
            questions[2],
            "Rearrange the words to make a meaningful sentence:\n"
            "school / goes / she / to / every day",
        )

    def test_split_learning_content_allows_missing_questions_section(self):
        notes, raw_decision, raw_diagram, questions = app_module.split_learning_content(
            """# Photosynthesis
Plants make food using sunlight.

## Quick Revision
- Leaves use sunlight.

## Visualization Decision JSON
{"visualization_required": true, "visualization_type": "biology_process", "confidence": 0.91}

## Diagram JSON
{"template":"photosynthesis","title":"Photosynthesis","labels":["Sunlight"],"type":"scientific_process"}
"""
        )

        self.assertIn("Plants make food using sunlight.", notes)
        self.assertEqual(raw_decision["visualization_type"], "biology_process")
        self.assertEqual(raw_diagram["template"], "photosynthesis")
        self.assertEqual(questions, [])

    def test_split_learning_content_keeps_existing_subject_quizzes_unchanged(self):
        cases = {
            "Science": [
                "Why do leaves look green?",
                "How do roots help a plant?",
                "What happens during photosynthesis?",
                "Why is sunlight important for plants?",
                "Name one product made during photosynthesis.",
            ],
            "Math": [
                "Solve 2x + 3 = 9.",
                "Find the area of a rectangle with length 8 cm and breadth 5 cm.",
                "What is the value of 7 squared?",
                "Simplify 3a + 2a.",
                "Convert 0.75 into a fraction.",
            ],
            "History": [
                "Why was the Salt March important?",
                "Name one leader of the Indian freedom movement.",
                "What was the main cause of the French Revolution?",
                "How did newspapers help nationalist movements?",
                "What does chronology mean in history?",
            ],
        }

        for subject, expected_questions in cases.items():
            with self.subTest(subject=subject):
                response_text = "# Notes\nUseful notes.\n\n## Questions\n" + "\n\n".join(
                    f"Q{index}. {question}"
                    for index, question in enumerate(expected_questions, start=1)
                )

                _, _, _, questions = app_module.split_learning_content(response_text)

                self.assertEqual(questions, expected_questions)

    def test_adaptive_quiz_prompt_uses_subject_specific_question_styles(self):
        cases = [
            ("Mathematics", "Algebra", "Numerical problems", "Do not ask \"What is Algebra?\""),
            ("Science", "Photosynthesis", "cause/effect", "how a process works"),
            ("History", "French Revolution", "chronology", "historical significance"),
        ]

        for subject, topic, expected_phrase, second_phrase in cases:
            with self.subTest(subject=subject, topic=topic):
                prompt = app_module.build_adaptive_quiz_prompt_section(
                    subject,
                    topic,
                    "",
                    "10",
                )

                self.assertIn(expected_phrase, prompt)
                self.assertIn(second_phrase, prompt)
                self.assertIn("For Class 10, include more application-based", prompt)
                self.assertIn("Avoid repeating the same question format", prompt)

    def test_download_notes_returns_all_notes_as_attachment(self):
        response = self.client.post(
            "/download_notes",
            data={
                "name": "Asha",
                "student_class": "8",
                "board": "CBSE",
                "subject": "Biology",
                "book_name": "NCERT",
                "topic": "Plant Life",
                "notes": "# Plant Notes\nPlants use sunlight.\n\n## Quick Revision\n- Plants need light.",
                "diagram_image": "data:image/png;base64,abc",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        self.assertIn(
            "attachment; filename=Plant_Life_notes.html",
            response.headers["Content-Disposition"],
        )
        notes = response.get_data(as_text=True)
        self.assertIn("Student: Asha", notes)
        self.assertIn("Class: 8", notes)
        self.assertIn("Board: CBSE", notes)
        self.assertIn("Subject: Biology", notes)
        self.assertIn("Textbook: NCERT", notes)
        self.assertIn("Chapter: Plant Life", notes)
        self.assertIn("<h1>Plant Notes</h1>", notes)
        self.assertIn("<h2>Quick Revision</h2>", notes)
        self.assertIn("<li>Plants need light.</li>", notes)
        self.assertIn("<h2>Diagram</h2>", notes)
        self.assertIn('src="data:image/png;base64,abc"', notes)

    def test_legacy_download_diagram_route_is_removed(self):
        diagram_payload = app_module.build_diagram_payload(
            "Science",
            "Photosynthesis",
            {
                "diagram_type": "process",
                "title": "Photosynthesis",
                "labels": ["Sunlight", "Water", "Carbon dioxide", "Leaf", "Oxygen"],
            },
        )

        response = self.client.post(
            "/download_diagram",
            data={
                "topic": "Photosynthesis",
                "diagram_json": json.dumps(diagram_payload),
            },
        )

        self.assertEqual(response.status_code, 410)
        self.assertIn("Diagram Library image download", response.get_data(as_text=True))

    def test_diagram_library_license_filter_accepts_only_reusable_licenses(self):
        self.assertTrue(reusable_license("CC BY-SA 4.0"))
        self.assertTrue(reusable_license("Public domain"))
        self.assertFalse(reusable_license("Fair use"))
        self.assertFalse(reusable_license("CC BY-NC 4.0 non-commercial"))

    def test_diagram_library_uses_cache_without_provider_call(self):
        self.seed_cached_diagram(subject="Biology", topic="Photosynthesis", filename="cached-only.png")

        class FailingRegistry:
            def search(self, queries, limit_per_query=8):
                raise AssertionError("Provider should not be called when cache exists.")

        with app_module.app.app_context():
            diagram = get_or_create_diagram(
                lesson_id=1,
                subject="Biology",
                topic="Photosynthesis",
                static_folder=app_module.app.static_folder,
                provider_registry=FailingRegistry(),
            )
            provider = diagram.provider if diagram else ""

        self.assertIsNotNone(diagram)
        self.assertEqual(provider, "Wikimedia Commons")

    def test_diagram_library_downloads_once_and_stores_metadata(self):
        stored_relative = self.write_test_diagram("provider-download.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative

        class FakeRegistry:
            def __init__(self):
                self.calls = 0

            def search(self, queries, limit_per_query=8):
                self.calls += 1
                return [
                    DiagramCandidate(
                        provider="Wikimedia Commons",
                        title="Photosynthesis educational diagram",
                        image_url="https://upload.wikimedia.org/test.png",
                        source_url="https://commons.wikimedia.org/wiki/File:Photosynthesis_test.png",
                        author="Commons Author",
                        license="CC BY 4.0",
                        attribution="Photosynthesis educational diagram by Commons Author, CC BY 4.0",
                        mime_type="image/png",
                    )
                ]

        registry = FakeRegistry()
        with patch("diagram_library.service.download_and_store", return_value=stored_path):
            with app_module.app.app_context():
                first = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Photosynthesis",
                    static_folder=app_module.app.static_folder,
                    provider_registry=registry,
                )
                self.assertTrue((Path(app_module.app.static_folder) / first.image_path).exists())
                second_registry = type(
                    "FailingRegistry",
                    (),
                    {
                        "search": lambda self, queries, limit_per_query=8: (_ for _ in ()).throw(
                            AssertionError("Provider should not be called after the first download.")
                        )
                    },
                )()
                second = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Photosynthesis",
                    static_folder=app_module.app.static_folder,
                    provider_registry=second_registry,
                )
                count = DiagramLibrary.query.count()
                first_id = first.id
                second_id = second.id
                author = first.author
                license_text = first.license
                attribution = first.attribution

        self.assertEqual(registry.calls, 1)
        self.assertEqual(count, 1)
        self.assertEqual(first_id, second_id)
        self.assertEqual(author, "Commons Author")
        self.assertEqual(license_text, "CC BY 4.0")
        self.assertIn("Commons Author", attribution)

    def test_diagram_library_default_registry_prioritizes_ncert_before_wikimedia(self):
        from diagram_library.service import default_registry

        registry = default_registry(static_folder=app_module.app.static_folder)

        self.assertIsInstance(registry.providers[0], NcertProvider)
        self.assertEqual(registry.providers[1].name, "wikimedia")

    def test_diagram_library_tries_ncert_before_wikimedia(self):
        stored_relative = self.write_test_diagram("fallback-provider-order.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        calls = []

        class EmptyNcertProvider:
            name = "ncert"

            def find(self, queries, *, topic="", subject="", limit_per_query=8):
                calls.append(self.name)
                return []

        class FakeWikimediaProvider:
            name = "wikimedia"

            def find(self, queries, *, topic="", subject="", limit_per_query=8):
                calls.append(self.name)
                return [
                    DiagramCandidate(
                        provider="Wikimedia Commons",
                        title="Unknown topic educational diagram",
                        image_url="https://upload.wikimedia.org/test-fallback-order.png",
                        source_url="https://commons.wikimedia.org/wiki/File:Fallback_order.png",
                        author="Commons Author",
                        license="CC BY 4.0",
                        attribution="Unknown topic diagram by Commons Author, CC BY 4.0",
                        mime_type="image/png",
                    )
                ]

            def fetch(self, candidate, cache_dir, topic):
                return stored_path

        registry = ProviderRegistry([EmptyNcertProvider(), FakeWikimediaProvider()])
        with app_module.app.app_context():
            diagram = get_or_create_diagram(
                lesson_id=1,
                subject="Biology",
                topic="Unknown Topic",
                static_folder=app_module.app.static_folder,
                provider_registry=registry,
            )
            provider = diagram.provider if diagram else ""

        self.assertIsNotNone(diagram)
        self.assertEqual(calls, ["ncert", "wikimedia"])
        self.assertEqual(provider, "Wikimedia Commons")

    def test_diagram_library_ncert_result_skips_wikimedia(self):
        self.write_ncert_diagram("biology", "mitochondria.png")

        class FailingWikimediaProvider:
            name = "wikimedia"

            def find(self, queries, *, topic="", subject="", limit_per_query=8):
                raise AssertionError("Wikimedia should not be called when NCERT finds a diagram.")

        registry = ProviderRegistry(
            [
                NcertProvider(static_folder=app_module.app.static_folder),
                FailingWikimediaProvider(),
            ]
        )
        with app_module.app.app_context():
            diagram = get_or_create_diagram(
                lesson_id=1,
                subject="Biology",
                topic="mitochondrion",
                static_folder=app_module.app.static_folder,
                provider_registry=registry,
            )
            provider = diagram.provider if diagram else ""
            cached_image_exists = bool(diagram and (Path(app_module.app.static_folder) / diagram.image_path).exists())
            diagram_count = DiagramLibrary.query.count()

        self.assertIsNotNone(diagram)
        self.assertEqual(provider, "NCERT Textbook Diagrams")
        self.assertEqual(diagram_count, 1)
        self.assertTrue(cached_image_exists)

    def test_diagram_library_unknown_topic_falls_back_to_wikimedia(self):
        stored_relative = self.write_test_diagram("fallback-wikimedia.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        wikimedia_calls = []

        class FakeWikimediaProvider:
            name = "wikimedia"

            def find(self, queries, *, topic="", subject="", limit_per_query=8):
                wikimedia_calls.append(topic)
                return [
                    DiagramCandidate(
                        provider="Wikimedia Commons",
                        title="Refraction educational diagram",
                        image_url="https://upload.wikimedia.org/test-refraction.png",
                        source_url="https://commons.wikimedia.org/wiki/File:Refraction.png",
                        author="Commons Author",
                        license="CC BY 4.0",
                        attribution="Refraction educational diagram by Commons Author, CC BY 4.0",
                        mime_type="image/png",
                    )
                ]

            def fetch(self, candidate, cache_dir, topic):
                return stored_path

        registry = ProviderRegistry(
            [
                NcertProvider(static_folder=app_module.app.static_folder),
                FakeWikimediaProvider(),
            ]
        )
        with app_module.app.app_context():
            diagram = get_or_create_diagram(
                lesson_id=1,
                subject="Physics",
                topic="Refraction",
                static_folder=app_module.app.static_folder,
                provider_registry=registry,
            )
            provider = diagram.provider if diagram else ""

        self.assertIsNotNone(diagram)
        self.assertEqual(wikimedia_calls, ["Refraction"])
        self.assertEqual(provider, "Wikimedia Commons")

    def test_diagram_library_ncert_cache_reuse_prevents_duplicate_entries(self):
        self.write_ncert_diagram("biology", "photosynthesis.png")
        registry = ProviderRegistry([NcertProvider(static_folder=app_module.app.static_folder)])

        class FailingRegistry:
            def search(self, queries, limit_per_query=8):
                raise AssertionError("Provider should not be called after NCERT result is cached.")

        with app_module.app.app_context():
            first = get_or_create_diagram(
                lesson_id=1,
                subject="Biology",
                topic="Photosynthesis",
                static_folder=app_module.app.static_folder,
                provider_registry=registry,
            )
            second = get_or_create_diagram(
                lesson_id=1,
                subject="Biology",
                topic="Photosynthesis",
                static_folder=app_module.app.static_folder,
                provider_registry=FailingRegistry(),
            )
            diagram_count = DiagramLibrary.query.count()
            first_id = first.id if first else None
            second_id = second.id if second else None

        self.assertIsNotNone(first)
        self.assertEqual(first_id, second_id)
        self.assertEqual(diagram_count, 1)

    def diagram_candidate(
        self,
        title,
        mime_type="image/svg+xml",
        width=1200,
        height=900,
        description="",
        categories=(),
        commons_metadata=None,
    ):
        return DiagramCandidate(
            provider="Wikimedia Commons",
            title=title,
            image_url=f"https://upload.wikimedia.org/wikipedia/commons/{title.replace(' ', '_')}",
            source_url=f"https://commons.wikimedia.org/wiki/File:{title.replace(' ', '_')}",
            author="Commons Author",
            license="CC BY-SA 4.0",
            attribution=f"{title} by Commons Author, CC BY-SA 4.0",
            mime_type=mime_type,
            width=width,
            height=height,
            description=description,
            categories=categories,
            commons_metadata=commons_metadata or {},
        )

    def test_diagram_search_queries_expand_science_motion_with_class_context(self):
        queries = build_search_queries(subject="Science", topic="Motion", student_class="9")

        normalized_queries = [query.lower() for query in queries]
        self.assertTrue(any("science" in query and "class 9" in query for query in normalized_queries))
        self.assertIn("physics motion diagram", normalized_queries)
        self.assertIn("distance displacement velocity diagram", normalized_queries)
        self.assertIn("class 9 motion physics", normalized_queries)

    def test_diagram_relevance_motion_prefers_physics_over_plate_motion(self):
        plate_motion = self.diagram_candidate(
            "Tectonic plate motion diagram English.svg",
            width=2200,
            height=1500,
            description="Geology diagram showing continental drift, subduction, volcanoes, and earthquake zones.",
            categories=("Plate tectonics", "Geology diagrams", "Earth science"),
            commons_metadata={"ImageDescription": "Tectonic plate motion and mantle convection."},
        )
        physics_motion = self.diagram_candidate(
            "Distance displacement velocity motion diagram English.svg",
            width=900,
            height=650,
            description="Class 9 physics educational diagram comparing distance, displacement, speed, velocity, and acceleration.",
            categories=("Physics education", "Mechanics diagrams", "Motion graphs"),
            commons_metadata={"ImageDescription": "School physics motion diagram with distance-time graph."},
        )

        relevant = relevant_diagram_candidates(
            [plate_motion, physics_motion],
            topic="Motion",
            subject="Science",
            student_class="9",
        )
        ranked = rank_diagram_candidates(relevant, topic="Motion", subject="Science")

        self.assertEqual([candidate.title for candidate in ranked], [physics_motion.title])
        self.assertIn("tectonic", subject_mismatch_terms(plate_motion, topic="Motion", subject="Science"))
        self.assertGreater(candidate_relevance_score(physics_motion, "Motion", "Science", "9"), 58)

    def test_diagram_relevance_cell_prefers_biology_over_non_biology_cell(self):
        phone_cell = self.diagram_candidate(
            "Cellular network cell tower diagram English.svg",
            description="Telecommunication diagram showing mobile phone cells and radio network coverage.",
            categories=("Cellular networks", "Telecommunication diagrams"),
            commons_metadata={"ImageDescription": "Mobile phone cellular network diagram."},
        )
        biology_cell = self.diagram_candidate(
            "Animal cell structure labelled biology diagram English.svg",
            description="Biology educational diagram showing cell membrane, nucleus, cytoplasm, and mitochondria.",
            categories=("Cell biology", "Biology education", "Cell diagrams"),
            commons_metadata={"ImageDescription": "Class 8 biology cell organelles labelled diagram."},
        )

        relevant = relevant_diagram_candidates([phone_cell, biology_cell], topic="Cell", subject="Science")
        ranked = rank_diagram_candidates(relevant, topic="Cell", subject="Science")

        self.assertEqual([candidate.title for candidate in ranked], [biology_cell.title])
        self.assertIn("cellular network", subject_mismatch_terms(phone_cell, topic="Cell", subject="Science"))

    def test_diagram_relevance_french_revolution_prefers_history_illustration(self):
        chemistry = self.diagram_candidate(
            "Chemical revolution laboratory diagram English.svg",
            description="Chemistry illustration about changes in laboratory science.",
            categories=("Chemistry history", "Scientific revolution"),
        )
        history = self.diagram_candidate(
            "French Revolution estates general history illustration English.svg",
            description="Historical educational illustration and timeline for the French Revolution.",
            categories=("French Revolution", "History education", "Historical illustrations"),
            commons_metadata={"ImageDescription": "French Revolution history illustration with timeline context."},
        )

        relevant = relevant_diagram_candidates(
            [chemistry, history],
            topic="French Revolution",
            subject="Social Science",
            student_class="9",
        )
        ranked = rank_diagram_candidates(relevant, topic="French Revolution", subject="Social Science")

        self.assertEqual([candidate.title for candidate in ranked], [history.title])

    def test_diagram_relevance_plate_tectonics_accepts_geography_diagram(self):
        dinner_plate = self.diagram_candidate(
            "Dinner plate illustration English.svg",
            description="Decorative illustration of a ceramic dinner plate.",
            categories=("Kitchenware", "Illustrations"),
        )
        tectonics = self.diagram_candidate(
            "Plate tectonics boundary geography diagram English.svg",
            description="Geography educational diagram showing tectonic plates, continental drift, subduction, and earthquake zones.",
            categories=("Plate tectonics", "Geography education", "Earth science diagrams"),
            commons_metadata={"ImageDescription": "Plate boundary diagram for geography class."},
        )

        relevant = relevant_diagram_candidates(
            [dinner_plate, tectonics],
            topic="Plate Tectonics",
            subject="Geography",
            student_class="9",
        )
        ranked = rank_diagram_candidates(relevant, topic="Plate Tectonics", subject="Geography")

        self.assertEqual([candidate.title for candidate in ranked], [tectonics.title])
        self.assertEqual(subject_mismatch_terms(tectonics, topic="Plate Tectonics", subject="Geography"), ())

    def test_diagram_service_rejects_unrelated_generic_topic_candidates(self):
        stored_relative = self.write_test_diagram("unrelated-generic.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        unrelated = self.diagram_candidate(
            "Tectonic plate motion diagram English.svg",
            description="Geology diagram of continental drift, subduction, volcano arcs, and earthquake zones.",
            categories=("Plate tectonics", "Geology diagrams"),
        )

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [unrelated]

        with patch("diagram_library.service.download_and_store", return_value=stored_path) as download:
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Science",
                    topic="Motion",
                    student_class="9",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                )

        self.assertIsNone(diagram)
        download.assert_not_called()

    def test_diagram_ranking_prefers_english_result_over_arabic(self):
        arabic = self.diagram_candidate("Mitochondrion diagram ar.svg", width=1800, height=1200)
        english = self.diagram_candidate("Mitochondrion structure English.svg", width=1200, height=900)

        ranked = rank_diagram_candidates([arabic, english], topic="mitochondria", subject="Biology")

        self.assertEqual(ranked[0].title, english.title)
        self.assertEqual(candidate_language_category(arabic), "non_english")

    def test_diagram_ranking_prefers_english_over_other_non_english_variants(self):
        russian = self.diagram_candidate("Mitochondria structure ru.svg", width=1800, height=1200)
        chinese = self.diagram_candidate("Mitochondria diagram zh.svg", width=1800, height=1200)
        english = self.diagram_candidate("Mitochondria labelled diagram en.svg", width=900, height=700)

        ranked = rank_diagram_candidates([russian, chinese, english], topic="mitochondria", subject="Biology")

        self.assertEqual(ranked[0].title, english.title)
        self.assertEqual(candidate_language_category(russian), "non_english")
        self.assertEqual(candidate_language_category(chinese), "non_english")

    def test_diagram_ranking_falls_back_when_only_non_english_images_exist(self):
        arabic = self.diagram_candidate("Mitochondrion diagram ar.svg", width=1400, height=900)
        russian = self.diagram_candidate("Mitochondrion structure ru.svg", width=900, height=650)

        ranked = rank_diagram_candidates([russian, arabic], topic="mitochondria", subject="Biology")

        self.assertEqual([candidate.title for candidate in ranked], [arabic.title, russian.title])
        self.assertTrue(all(candidate_language_category(candidate) == "non_english" for candidate in ranked))

    def test_diagram_ranking_prefers_cell_division_mitosis_over_specialized_fungal_cycle(self):
        fungal = self.diagram_candidate(
            "Fungal Cell Cycle - Dikaryotic Basidiomycete.svg",
            width=2200,
            height=1500,
            description="Life cycle diagram of dikaryotic fungal cells in a basidiomycete species.",
            categories=("Fungal life cycles", "Basidiomycetes", "Species-specific biology diagrams"),
            commons_metadata={
                "ObjectName": "Fungal cell cycle",
                "ImageDescription": "Specialized fungal cell cycle diagram showing dikaryotic stages.",
            },
        )
        mitosis = self.diagram_candidate(
            "Stages of mitosis cell division diagram English.svg",
            width=900,
            height=650,
            description="Educational diagram of cell division showing prophase, metaphase, anaphase, telophase, chromosomes, and cytokinesis.",
            categories=("Mitosis diagrams", "Cell division", "Biology education"),
            commons_metadata={
                "ObjectName": "Stages of mitosis",
                "ImageDescription": "General school biology diagram for cell division and chromosome separation.",
            },
        )

        ranked = rank_diagram_candidates([fungal, mitosis], topic="Cell Division", subject="Biology")

        self.assertEqual(ranked[0].title, mitosis.title)

    def test_diagram_ranking_uses_commons_metadata_for_cell_division_relevance(self):
        fungal = self.diagram_candidate(
            "Cell cycle diagram English.svg",
            width=1600,
            height=1200,
            description="Dikaryotic basidiomycete fungal cell cycle.",
            categories=("Fungi", "Basidiomycete biology"),
            commons_metadata={"ImageDescription": "Specialized fungal biology example."},
        )
        mitosis = self.diagram_candidate(
            "Chromosome separation educational illustration.png",
            mime_type="image/png",
            width=1000,
            height=700,
            description="General cell division classroom diagram.",
            categories=("Biology education",),
            commons_metadata={
                "ImageDescription": "Mitosis diagram with chromosomes, cytokinesis, and stages of mitosis."
            },
        )

        ranked = rank_diagram_candidates([fungal, mitosis], topic="Cell Division", subject="Biology")

        self.assertEqual(ranked[0].title, mitosis.title)

    def test_diagram_service_downloads_ranked_english_candidate_first(self):
        stored_relative = self.write_test_diagram("ranked-english.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        arabic = self.diagram_candidate("Mitochondrion diagram ar.svg", width=1800, height=1200)
        english = self.diagram_candidate("Mitochondrion labelled diagram en.svg", width=900, height=700)

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [arabic, english]

        downloaded_titles = []

        def fake_download(candidate, cache_dir, topic):
            downloaded_titles.append(candidate.title)
            return stored_path

        with patch("diagram_library.service.download_and_store", side_effect=fake_download):
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="mitochondria",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                )
                saved_title = diagram.attribution

        self.assertEqual(downloaded_titles, [english.title])
        self.assertIn(english.title, saved_title)

    def test_diagram_service_downloads_cell_division_mitosis_before_fungal_cycle(self):
        stored_relative = self.write_test_diagram("ranked-cell-division.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        fungal = self.diagram_candidate(
            "Fungal Cell Cycle - Dikaryotic Basidiomycete.svg",
            width=2200,
            height=1500,
            description="Life cycle diagram of dikaryotic fungal cells in a basidiomycete species.",
            categories=("Fungal life cycles", "Basidiomycetes", "Species-specific biology diagrams"),
        )
        mitosis = self.diagram_candidate(
            "Mitosis cell division chromosomes diagram English.svg",
            width=900,
            height=650,
            description="General educational cell division diagram showing mitosis, chromosomes, and cytokinesis.",
            categories=("Mitosis diagrams", "Cell division", "Biology education"),
        )

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [fungal, mitosis]

        downloaded_titles = []

        def fake_download(candidate, cache_dir, topic):
            downloaded_titles.append(candidate.title)
            return stored_path

        with patch("diagram_library.service.download_and_store", side_effect=fake_download):
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Cell Division",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                )

        self.assertIsNotNone(diagram)
        self.assertEqual(downloaded_titles, [mitosis.title])

    def test_diagram_service_uses_ai_review_selected_candidate_before_download(self):
        stored_relative = self.write_test_diagram("ai-reviewed-selection.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        plant_photo = self.diagram_candidate(
            "Photosynthesis plant photo English.png",
            mime_type="image/png",
            width=1600,
            height=1200,
            description="A photograph of a plant in sunlight.",
        )
        textbook_diagram = self.diagram_candidate(
            "Photosynthesis process labelled diagram English.svg",
            description="Clean textbook diagram showing sunlight, water, carbon dioxide, glucose, and oxygen.",
            categories=("Photosynthesis diagrams", "Biology education"),
        )

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [plant_photo, textbook_diagram]

        def fake_reviewer(**kwargs):
            candidates = kwargs["candidates"]
            return DiagramReviewDecision(
                selected_index=next(
                    index for index, candidate in enumerate(candidates) if candidate.title == textbook_diagram.title
                ),
                confidence=0.96,
                reason="Best English educational diagram with clear labels.",
            )

        downloaded_titles = []

        def fake_download(candidate, cache_dir, topic):
            downloaded_titles.append(candidate.title)
            return stored_path

        with patch("diagram_library.service.download_and_store", side_effect=fake_download):
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Photosynthesis",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                    reviewer=fake_reviewer,
                )

        self.assertIsNotNone(diagram)
        self.assertEqual(downloaded_titles, [textbook_diagram.title])

    def test_diagram_service_tries_next_ranked_group_when_ai_confidence_is_low(self):
        stored_relative = self.write_test_diagram("ai-reviewed-second-group.png")
        stored_path = Path(app_module.app.static_folder) / stored_relative
        candidates = [
            self.diagram_candidate(
                f"Decorative photosynthesis image {index} English.png",
                mime_type="image/png",
                description="Decorative plant artwork.",
            )
            for index in range(8)
        ]
        selected = self.diagram_candidate(
            "Photosynthesis labelled process diagram English.svg",
            description="School diagram explaining photosynthesis inputs and outputs.",
        )
        candidates.append(selected)

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return candidates

        reviewer_calls = []
        reviewer_selected_titles = []

        def fake_reviewer(**kwargs):
            reviewer_calls.append([candidate.title for candidate in kwargs["candidates"]])
            if len(reviewer_calls) == 1:
                return DiagramReviewDecision(selected_index=0, confidence=0.62, reason="Not confident.")
            reviewer_selected_titles.append(kwargs["candidates"][0].title)
            return DiagramReviewDecision(selected_index=0, confidence=0.91, reason="Clear English textbook diagram.")

        downloaded_titles = []

        def fake_download(candidate, cache_dir, topic):
            downloaded_titles.append(candidate.title)
            return stored_path

        with patch("diagram_library.service.download_and_store", side_effect=fake_download):
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Photosynthesis",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                    reviewer=fake_reviewer,
                )

        self.assertIsNotNone(diagram)
        self.assertEqual(len(reviewer_calls), 2)
        self.assertEqual(downloaded_titles, reviewer_selected_titles)
        self.assertNotIn(downloaded_titles[0], reviewer_calls[0])

    def test_diagram_service_returns_none_when_ai_finds_no_acceptable_diagram(self):
        candidate = self.diagram_candidate(
            "Photosynthesis decorative forest photo English.png",
            mime_type="image/png",
            description="Decorative forest photograph.",
        )

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [candidate]

        def rejecting_reviewer(**kwargs):
            return DiagramReviewDecision(selected_index=None, confidence=0.0, reason="No suitable educational diagram found.")

        with patch("diagram_library.service.download_and_store") as download:
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="Photosynthesis",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                    reviewer=rejecting_reviewer,
                )

        self.assertIsNone(diagram)
        download.assert_not_called()

    def test_diagram_service_unavailable_ai_fallback_never_downloads_known_foreign_language(self):
        arabic = self.diagram_candidate("Mitochondrion diagram ar.svg", width=1800, height=1200)
        russian = self.diagram_candidate("Mitochondrion structure ru.svg", width=1600, height=1000)

        class FakeRegistry:
            def search(self, queries, limit_per_query=8):
                return [arabic, russian]

        def unavailable_reviewer(**kwargs):
            return DiagramReviewDecision(unavailable=True, reason="Gemini unavailable.")

        with patch("diagram_library.service.download_and_store") as download:
            with app_module.app.app_context():
                diagram = get_or_create_diagram(
                    lesson_id=1,
                    subject="Biology",
                    topic="mitochondria",
                    static_folder=app_module.app.static_folder,
                    provider_registry=FakeRegistry(),
                    reviewer=unavailable_reviewer,
                )

        self.assertIsNone(diagram)
        download.assert_not_called()

    def test_diagram_ai_review_caches_same_topic_and_candidate_set(self):
        clear_review_cache()
        candidate = self.diagram_candidate(
            "Photosynthesis process labelled diagram English.svg",
            description="Clean school diagram explaining photosynthesis.",
        )
        calls = []

        class FakeResponse:
            text = '{"selected_index": 0, "confidence": 0.95, "reason": "Clear English educational diagram."}'

        class FakeModel:
            def generate_content(self, prompt, **kwargs):
                calls.append(prompt)
                return FakeResponse()

        with patch.dict(os.environ, {"DIAGRAM_AI_REVIEW_ENABLED": "1"}):
            first = review_diagram_candidates(
                topic="Photosynthesis",
                subject="Biology",
                student_class="8",
                candidates=[candidate],
                model_factory=FakeModel,
            )
            second = review_diagram_candidates(
                topic="Photosynthesis",
                subject="Biology",
                student_class="8",
                candidates=[candidate],
                model_factory=FakeModel,
            )

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(second.from_cache)
        self.assertEqual(len(calls), 1)
        clear_review_cache()

    def test_wikimedia_svg_thumbnail_is_saved_with_actual_png_extension(self):
        class FakeDownloadResponse:
            headers = {"Content-Type": "image/png"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                return self.data

        fake_response = FakeDownloadResponse()
        fake_response.data = self.make_image_bytes("PNG")
        candidate = DiagramCandidate(
            provider="Wikimedia Commons",
            title="Plant cell.svg",
            image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Plant_cell.svg/1400px-Plant_cell.svg.png",
            source_url="https://commons.wikimedia.org/wiki/File:Plant_cell.svg",
            author="Commons Author",
            license="CC BY-SA 4.0",
            attribution="Plant cell by Commons Author, CC BY-SA 4.0",
            mime_type="image/svg+xml",
        )

        with patch("diagram_library.storage.urlopen", return_value=fake_response):
            stored_path = download_and_store(
                candidate,
                Path(app_module.app.static_folder) / "diagram_cache",
                "Plant Cell",
            )

        self.addCleanup(lambda: stored_path and stored_path.exists() and stored_path.unlink())
        self.assertIsNotNone(stored_path)
        self.assertEqual(stored_path.suffix, ".png")
        self.assertTrue(valid_cached_image(stored_path))

    def test_cached_mismatched_extension_repairs_to_renderable_file(self):
        relative_path = self.write_test_diagram("mismatched.svg")
        repaired = repair_cached_image_extension(app_module.app.static_folder, relative_path)
        repaired_path = Path(app_module.app.static_folder) / repaired
        self.addCleanup(lambda: repaired_path.exists() and repaired_path.unlink())

        self.assertEqual(Path(repaired).suffix, ".png")
        self.assertTrue(valid_cached_image(repaired_path))

    def test_supported_cached_image_formats_validate(self):
        cache_dir = Path(app_module.app.static_folder) / "diagram_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        samples = {
            "format-test.png": self.make_image_bytes("PNG"),
            "format-test.jpg": self.make_image_bytes("JPEG"),
            "format-test.jpeg": self.make_image_bytes("JPEG"),
            "format-test.svg": self.TEST_SVG,
            "format-test.webp": self.make_image_bytes("WEBP"),
        }

        for filename, data in samples.items():
            with self.subTest(filename=filename):
                path = cache_dir / filename
                path.write_bytes(data)
                self.addCleanup(lambda p=path: p.exists() and p.unlink())
                self.assertTrue(valid_cached_image(path))

    def test_visualization_assets_support_image_zoom_mobile_and_dark_mode(self):
        css_path = os.path.join(app_module.app.root_path, "static", "css", "visualization.css")
        js_path = os.path.join(app_module.app.root_path, "static", "js", "visualization.js")
        template_path = os.path.join(app_module.app.root_path, "templates", "visualization.html")
        with open(css_path, encoding="utf-8") as css_file:
            css = css_file.read()
        with open(js_path, encoding="utf-8") as js_file:
            script = js_file.read()
        with open(template_path, encoding="utf-8") as template_file:
            template = template_file.read()

        self.assertIn(".diagram-library-image", css)
        self.assertIn("max-width: 100%", css)
        self.assertIn("object-fit: contain", css)
        self.assertIn("height: clamp(320px, 52vw, 620px)", css)
        self.assertIn("position: absolute", css)
        self.assertIn("width: calc(100% - (var(--diagram-shell-padding) * 2))", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn(".dark-mode .diagram-library-image-shell", css)
        self.assertIn(".exhibition-mode .diagram-library-figure", css)
        self.assertIn(".diagram-lightbox", css)
        self.assertIn(".diagram-explanation-card", css)
        self.assertNotIn("scale(1.18)", css)
        self.assertIn("data-diagram-zoom", script)
        self.assertIn("data-diagram-lightbox", script)
        self.assertIn("data-diagram-explanation-panel", script)
        self.assertIn("Step-by-Step Explanation", script)
        self.assertIn("diagram-lightbox-open", script)
        self.assertIn("is-fullscreen", script)
        self.assertIn("data-diagram-lightbox", template)
        self.assertIn("data-diagram-explanation-panel", template)
        self.assertNotIn("style=\"", template)

    @patch.object(app_module.model, "generate_content")
    def test_learn_shows_no_diagram_when_no_template_matches(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Abstract Notes
This topic is best explained with text.

## Diagram JSON
{"diagram_type":"none","title":"Abstract Topic","labels":[],"arrows":[],"notes":[]}

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Life Skills",
                "topic": "Personal Reflection",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Visualization", page)
        self.assertIn("This lesson is primarily text-based and does not require a visual diagram.", page)
        self.assertNotIn("Download Diagram", page)

    @patch.object(app_module.model, "generate_content")
    def test_text_based_lessons_never_generate_visualizations(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Essay Writing
Essay writing is learned through structure, examples, and practice.

## Quick Revision
- Plan before writing.

## Visualization Decision JSON
{"visualization_required": false, "reason": "This lesson is primarily text based and is better learned through reading and examples."}

## Diagram JSON
{"type":"none","title":"Essay Writing","nodes":[],"connections":[]}

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "English",
                "topic": "Essay Writing",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Visualization", page)
        self.assertIn("This lesson is primarily text-based and does not require a visual diagram.", page)
        self.assertNotIn("Download Diagram", page)
        self.assertNotIn("data:image/svg+xml", page)
        with app_module.app.app_context():
            lesson = LearningHistory.query.first()
            saved_diagram = json.loads(lesson.diagram_data)

        self.assertFalse(lesson.visualization_required)
        self.assertFalse(saved_diagram["visualization_required"])
        self.assertFalse(saved_diagram["available"])

    @patch.object(app_module.model, "generate_content")
    def test_biology_lessons_still_generate_visualizations(self, generate_content):
        self.register_user()
        self.login_user()
        self.seed_cached_diagram(
            subject="Biology",
            topic="Photosynthesis",
            filename="biology-photosynthesis.png",
        )
        generate_content.return_value = MockResponse(
            """# Photosynthesis
Plants make food using sunlight.

## Quick Revision
- Leaves use sunlight.

## Visualization Decision JSON
{"visualization_required": true, "visualization_type": "biology_process", "confidence": 0.96}

## Diagram JSON
{"type":"scientific_process","title":"Photosynthesis","nodes":[{"id":"1","label":"Sunlight"},{"id":"2","label":"Carbon Dioxide"},{"id":"3","label":"Water"},{"id":"4","label":"Glucose"},{"id":"5","label":"Oxygen"}],"connections":[["1","4"],["2","4"],["3","4"]],"reason":"This biological process is easier to understand visually.","confidence":0.96}

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Photosynthesis",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Educational Diagram", page)
        self.assertIn('class="diagram-library-image"', page)
        self.assertIn("Download PNG", page)
        self.assertIn("Diagram Source", page)
        self.assertNotIn("ai-visualization-svg", page)
        self.assertIn("Scientific Process", page)

    @patch.object(app_module.model, "generate_content")
    def test_history_timelines_still_generate_visualizations(self, generate_content):
        self.register_user()
        self.login_user()
        self.seed_cached_diagram(
            subject="History",
            topic="French Revolution",
            filename="history-french-revolution.png",
        )
        generate_content.return_value = MockResponse(
            """# French Revolution
The French Revolution had important events in sequence.

## Quick Revision
- Events happened over time.

## Visualization Decision JSON
{"visualization_required": true, "visualization_type": "timeline", "confidence": 0.95}

## Diagram JSON
{"type":"timeline","title":"French Revolution Timeline","nodes":[{"id":"1","label":"Estates-General"},{"id":"2","label":"Tennis Court Oath"},{"id":"3","label":"Bastille"},{"id":"4","label":"Republic"},{"id":"5","label":"Napoleon"}],"connections":[["1","2"],["2","3"],["3","4"],["4","5"]],"reason":"Historical events are best shown in chronological order.","confidence":0.95}

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "9",
                "subject": "History",
                "topic": "French Revolution",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Timeline", page)
        self.assertIn("Educational Diagram", page)
        self.assertIn("Download PNG", page)

    @patch.object(app_module, "local_textbook_context_section")
    @patch.object(app_module.model, "generate_content")
    def test_learn_shortens_large_textbook_context_before_gemini(
        self,
        generate_content,
        local_textbook_context_section,
    ):
        local_textbook_context_section.return_value = (
            "Local Textbook PDF Context:\n" + ("cell structure " * 3000)
        )
        generate_content.return_value = MockResponse(
            """# Cell Notes
Cells are the basic unit of life.

## Quick Revision
- Cells make up living things.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "book_name": "Science",
                "topic": "Cells",
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertLessEqual(len(prompt), app_module.LEARN_MAX_PROMPT_CHARS)
        self.assertIn("Rules:", prompt)
        self.assertIn("Teach this topic like an experienced CBSE teacher.", prompt)
        self.assertIn("## Questions", prompt)
        self.assertIn("Prompt shortened automatically", prompt)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learn_returns_friendly_busy_page_when_gemini_times_out(self, generate_content):
        generate_content.side_effect = TimeoutError("Gemini timed out")

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn(
            "The AI is taking longer than expected.",
            response.get_data(as_text=True),
        )

    @patch.object(app_module.model, "generate_content")
    def test_learn_times_out_slow_gemini_without_retry(self, generate_content):
        def slow_generate(*args, **kwargs):
            time.sleep(0.2)
            return MockResponse(
                """# Plants
Plants need sunlight.

## Questions
Q1. What do plants need?

Q2. Why do plants need sunlight?

Q3. Name one part of a plant.

Q4. What is one use of plants?

Q5. Write one point about plants.
"""
            )

        generate_content.side_effect = slow_generate

        with patch.object(app_module, "LEARN_GEMINI_TIMEOUT_SECONDS", 0.05):
            with self.assertLogs(app_module.app.logger.name, level="INFO") as logs:
                response = self.client.post(
                    "/learn",
                    data={
                        "name": "Asha",
                        "student_class": "8",
                        "subject": "Biology",
                        "topic": "Plants",
                    },
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn(
            "The AI is taking longer than expected.",
            response.get_data(as_text=True),
        )
        self.assertEqual(generate_content.call_count, 1)
        log_output = "\n".join(logs.output)
        self.assertIn("gemini_request_start feature=Notes", log_output)
        self.assertIn("gemini_request_timeout feature=Notes", log_output)
        self.assertNotIn("gemini_request_complete feature=Notes", log_output)

    def test_gemini_exception_classifier_covers_common_failures(self):
        rate_limit = classify_gemini_exception(Exception("HTTP 429 rate limit exceeded"))
        timeout = classify_gemini_exception(TimeoutError("deadline timed out"))
        invalid_key = classify_gemini_exception(Exception("API key not valid. 401"))
        quota = classify_gemini_exception(Exception("RESOURCE_EXHAUSTED quota exceeded"))
        network = classify_gemini_exception(ConnectionError("connection reset by peer"))
        unknown = classify_gemini_exception(RuntimeError("unexpected parser failure"))

        self.assertEqual(rate_limit.title, "Rate Limit Reached")
        self.assertIn("limited number of requests per minute", rate_limit.message)
        self.assertIn("taking longer than expected", timeout.message)
        self.assertIn("configuration issue", invalid_key.message)
        self.assertIn("free AI quota", quota.message)
        self.assertIn("Unable to contact the AI service", network.message)
        self.assertEqual(unknown.code, "unknown")

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learn_rate_limit_uses_central_error_page_and_logs(self, generate_content):
        generate_content.side_effect = Exception("HTTP 429 rate limit exceeded")

        with self.assertLogs(app_module.app.logger.name, level="INFO") as logs:
            response = self.client.post(
                "/learn",
                data={
                    "name": "Asha",
                    "student_class": "8",
                    "subject": "Biology",
                    "topic": "Plants",
                },
            )

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Rate Limit Reached", page)
        self.assertIn("Please wait about one minute before trying again.", page)
        self.assertIn("Your work has already been saved.", page)
        self.assertNotIn("Flashcard service unavailable", page)
        log_output = "\n".join(logs.output)
        self.assertIn("feature=Notes", log_output)
        self.assertIn("prompt_length=", log_output)
        self.assertIn("estimated_tokens=", log_output)
        self.assertIn("response_length=0", log_output)
        self.assertIn("exception_type=Exception", log_output)
        self.assertIn("user_id=anonymous", log_output)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learn_unknown_exception_logs_traceback_and_friendly_page(self, generate_content):
        generate_content.side_effect = RuntimeError("unexpected gemini failure")

        with self.assertLogs(app_module.app.logger.name, level="INFO") as logs:
            response = self.client.post(
                "/learn",
                data={
                    "name": "Asha",
                    "student_class": "8",
                    "subject": "Biology",
                    "topic": "Plants",
                },
            )

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn("AI Service Unavailable", page)
        log_output = "\n".join(logs.output)
        self.assertIn("Unknown Gemini exception", log_output)
        self.assertIn("Traceback", log_output)
        self.assertIn("exception_type=RuntimeError", log_output)

    @patch.object(app_module.model, "generate_content")
    def test_learn_does_not_load_ai_tutor_data(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Quick Revision
- Plants need light.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        with patch.object(app_module, "get_recent_tutor_messages") as recent_messages:
            with patch.object(app_module, "get_tutor_messages") as tutor_messages:
                response = self.client.post(
                    "/learn",
                    data={
                        "name": "Asha",
                        "student_class": "8",
                        "subject": "Biology",
                        "topic": "Plants",
                    },
                )

        self.assertEqual(response.status_code, 200)
        recent_messages.assert_not_called()
        tutor_messages.assert_not_called()

    def test_download_notes_rejects_missing_notes(self):
        response = self.client.post(
            "/download_notes",
            data={"name": "Asha", "topic": "Plants"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Topic and notes are required", response.get_data(as_text=True))

    def test_quiz_displays_all_questions_and_answer_fields(self):
        response = self.client.post("/quiz", data=self.quiz_payload())

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('action="/submit_answers"', page)
        for index, question in enumerate(self.questions, start=1):
            self.assertIn(question, page)
            self.assertIn(f'name="answer{index}"', page)
            self.assertIn(f'name="question{index}"', page)

    def test_quiz_rejects_unsupported_class(self):
        payload = self.quiz_payload()
        payload["student_class"] = "11"

        response = self.client.post("/quiz", data=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn(app_module.SUPPORTED_CLASS_MESSAGE, response.get_data(as_text=True))

    def test_quiz_renders_multiline_grammar_question_types(self):
        payload = self.quiz_payload()
        payload["subject"] = "English"
        payload["topic"] = "Tenses"
        payload["question1"] = (
            "Fill in the blank with the correct form of the verb given in the brackets:\n"
            "She ____ (go) to school every day."
        )
        payload["question2"] = (
            "Correct the error in the sentence:\n"
            "He go to market yesterday."
        )
        payload["question3"] = (
            "Rearrange the words to make a meaningful sentence:\n"
            "school / goes / she / to / every day"
        )

        response = self.client.post("/quiz", data=payload)

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Fill in the blank with the correct form of the verb", page)
        self.assertIn("She ____ (go) to school every day.", page)
        self.assertIn("Correct the error in the sentence:", page)
        self.assertIn("He go to market yesterday.", page)
        self.assertIn("Rearrange the words to make a meaningful sentence:", page)
        self.assertIn("school / goes / she / to / every day", page)
        self.assertIn('name="answer1"', page)
        self.assertIn('name="answer2"', page)
        self.assertIn('name="answer3"', page)

    def test_quiz_rejects_missing_question(self):
        payload = self.quiz_payload()
        del payload["question5"]

        response = self.client.post("/quiz", data=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("All questions are required", response.get_data(as_text=True))

    @patch.object(app_module, "GEMINI_API_KEY_2", "backup-key")
    @patch.object(app_module.genai, "configure")
    @patch.object(app_module.genai, "GenerativeModel")
    @patch.object(app_module.model, "generate_content")
    def test_learn_does_not_retry_with_backup_key_on_quota_error(
        self,
        generate_content,
        generative_model,
        configure,
    ):
        generate_content.side_effect = Exception("429 quota reached")

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("AI Quota Reached", response.get_data(as_text=True))
        self.assertEqual(generate_content.call_count, 1)
        configure.assert_not_called()
        generative_model.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_submit_includes_questions_and_answers_in_evaluation(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            json.dumps(
                {
                    "questions": [
                        {
                            "question": "What is question one?",
                            "student_answer": "Answer 1",
                            "correct_answer": "Correct answer 1",
                            "status": "correct",
                            "marks_awarded": 2,
                            "max_marks": 2,
                            "teacher_feedback": "Excellent answer.",
                            "revision_tip": "",
                        },
                        {
                            "question": "What is question two?",
                            "student_answer": "Answer 2",
                            "correct_answer": "Correct answer 2",
                            "status": "partial",
                            "marks_awarded": 1,
                            "max_marks": 2,
                            "teacher_feedback": "Some key idea is present.",
                            "revision_tip": "Add the missing keyword.",
                        },
                        {
                            "question": "What is question three?",
                            "student_answer": "Answer 3",
                            "correct_answer": "Correct answer 3",
                            "status": "correct",
                            "marks_awarded": 2,
                            "max_marks": 2,
                            "teacher_feedback": "Clear answer.",
                            "revision_tip": "",
                        },
                        {
                            "question": "What is question four?",
                            "student_answer": "Answer 4",
                            "correct_answer": "Correct answer 4",
                            "status": "incorrect",
                            "marks_awarded": 0,
                            "max_marks": 2,
                            "teacher_feedback": "This answer misses the main concept.",
                            "revision_tip": "Revise the definition first.",
                        },
                        {
                            "question": "What is question five?",
                            "student_answer": "Answer 5",
                            "correct_answer": "Correct answer 5",
                            "status": "correct",
                            "marks_awarded": 2,
                            "max_marks": 2,
                            "teacher_feedback": "Good explanation.",
                            "revision_tip": "",
                        },
                    ],
                    "summary": {
                        "total_score": 7,
                        "max_score": 10,
                        "percentage": 70,
                        "grade": "B+",
                        "correct_answers": 3,
                        "incorrect_answers": 1,
                        "partial_answers": 1,
                    },
                    "teacher_report": {
                        "overall_feedback": "Good work with room for revision.",
                        "strengths": ["Clear answers", "Good effort"],
                        "weak_areas": ["Definitions need revision"],
                        "revision_suggestions": ["Revise keywords", "Practice again"],
                    },
                }
            )
        )

        response = self.client.post("/submit_answers", data=self.answer_payload())

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Q1: What is question one?\nStudent answer: Answer 1", prompt)
        self.assertIn("Q5: What is question five?\nStudent answer: Answer 5", prompt)
        self.assertIn("Class: 8", prompt)
        self.assertIn("Subject: Biology", prompt)
        page = response.get_data(as_text=True)
        self.assertIn("7/10", page)
        self.assertIn("70%", page)
        self.assertIn("Grade", page)
        self.assertIn("Question Analysis", page)
        self.assertIn("Correct answer 1", page)
        self.assertIn("Excellent answer.", page)
        self.assertIn("Add the missing keyword.", page)
        self.assertIn("AI Teacher Report", page)
        self.assertIn("Good work with room for revision.", page)
        self.assertIn('action="/download_pdf"', page)
        self.assertIn('method="POST"', page)
        self.assertIn('name="report_text"', page)
        self.assertIn('name="evaluation_json"', page)
        self.assertIn("Clear answers", page)

        with app_module.app.app_context():
            row = QuizHistory.query.first()

        self.assertEqual(
            (row.name, row.student_class, row.subject, row.topic, row.score, row.grade),
            ("Asha", "8", "Biology", "Plants", "7/10", "B+"),
        )
        saved_report = json.loads(row.report_text)
        self.assertEqual(saved_report["summary"]["correct_answers"], 3)
        self.assertEqual(saved_report["questions"][1]["status"], "partial")

        history_response = self.client.get("/history")
        self.assertEqual(history_response.status_code, 200)
        history_page = history_response.get_data(as_text=True)
        self.assertIn("Quiz History", history_page)
        self.assertIn("Asha", history_page)
        self.assertIn("Plants", history_page)

    @patch.object(app_module.model, "generate_content")
    def test_guest_submit_does_not_save_quiz_history(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Performance Summary
Score: 8/10
Grade: A
"""
        )

        response = self.client.post("/submit_answers", data=self.answer_payload())

        self.assertEqual(response.status_code, 200)
        with app_module.app.app_context():
            saved_count = QuizHistory.query.count()

        self.assertEqual(saved_count, 0)

    def test_history_requires_login(self):
        response = self.client.get("/history")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/history", response.headers["Location"])

    def test_quiz_history_alias_requires_login(self):
        response = self.client.get("/quiz-history")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/quiz-history", response.headers["Location"])

    def test_guest_home_shows_guest_mode_and_locked_modal(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Welcome, Guest!", page)
        self.assertIn("Guest Mode = Explore", page)
        self.assertIn("Why create an account?", page)
        self.assertIn("Create Free Account", page)
        self.assertIn("Login Required", page)
        self.assertIn("data-locked-feature", page)
        self.assertIn("Guest", page)

    def test_home_includes_pwa_manifest_and_install_runtime(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', page)
        self.assertIn('name="theme-color" content="#3157d5"', page)
        self.assertIn('data-pwa-install-banner', page)
        self.assertIn('/static/pwa.js', page)

    def test_navigation_pages_include_shared_transition_loader(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="page-transition-overlay"', page)
        self.assertIn("data-page-transition-overlay", page)
        self.assertIn("data-page-transition-message", page)
        self.assertIn("AI Study Buddy", page)
        self.assertIn('href="/profile"', page)
        self.assertIn('href="/learning-history"', page)

        script = Path("static/motion.js").read_text(encoding="utf-8")
        self.assertIn("setupPageTransitionOverlay", script)
        self.assertIn('document.addEventListener("click", handlePageTransitionClick, true)', script)
        self.assertIn('document.addEventListener("submit", handlePageTransitionSubmit)', script)
        self.assertIn("event.preventDefault();", script)
        self.assertIn("showPageTransitionOverlay(link)", script)
        self.assertIn("navigateAfterOverlayPaint(link)", script)
        self.assertIn("afterOverlayPaint", script)
        self.assertIn("minimumOverlayPaintDelay", script)
        self.assertNotIn("Loader triggered from:", script)
        self.assertIn("window.navigate = navigate", script)
        self.assertIn("window.goTo = navigate", script)
        self.assertIn("window.location.assign(destination)", script)
        self.assertIn("AIStudyBuddyPageLoader", script)
        self.assertIn("navigate,", script)
        self.assertIn("patchLocationMethod", script)
        self.assertIn("window.navigation.addEventListener", script)
        self.assertIn("navigationLocked", script)
        self.assertIn('document.readyState === "loading"', script)
        self.assertIn("Loading Dashboard...", script)
        self.assertIn("Opening Profile...", script)
        self.assertIn("Preparing Learning History...", script)
        self.assertIn("[data-developer-users-link]", script)
        self.assertIn("download-data", script)
        self.assertIn("download(?:", script)

        auth_nav = Path("templates/components/auth_nav.html").read_text(encoding="utf-8")
        self.assertIn("event.stopPropagation();", auth_nav)

        css = Path("static/style.css").read_text(encoding="utf-8")
        self.assertIn("z-index: 10000;", css)
        self.assertIn(".page-transition-overlay[hidden]", css)
        self.assertIn("display: none;", css)
        self.assertIn(".page-transition-overlay.is-visible", css)
        self.assertIn("opacity: 1;", css)
        self.assertIn("pointer-events: auto;", css)
        self.assertIn(".page-transition-active body", css)

    def test_full_page_templates_include_transition_overlay_runtime(self):
        missing_overlay = []
        missing_motion = []

        for template_path in Path("templates").glob("*.html"):
            source = template_path.read_text(encoding="utf-8")
            if "<body" not in source or "</body>" not in source:
                continue

            has_footer = "components/footer.html" in source
            has_overlay = "components/loading_overlay.html" in source
            has_motion = "motion.js" in source

            if not has_footer and not has_overlay:
                missing_overlay.append(template_path.name)
            if not has_footer and not has_motion:
                missing_motion.append(template_path.name)

        self.assertEqual([], missing_overlay)
        self.assertEqual([], missing_motion)

    def test_pwa_manifest_contains_install_metadata_and_icons(self):
        response = self.client.get("/manifest.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/manifest+json")
        manifest = json.loads(response.get_data(as_text=True))
        self.assertEqual(manifest["name"], "AI Study Buddy")
        self.assertEqual(manifest["short_name"], "Study Buddy")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["orientation"], "portrait-primary")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["theme_color"], "#3157d5")
        self.assertEqual(manifest["background_color"], "#f7f4ee")
        self.assertEqual(
            {(icon["sizes"], icon["src"]) for icon in manifest["icons"]},
            {
                ("192x192", "/static/icons/icon-192.png"),
                ("512x512", "/static/icons/icon-512.png"),
            },
        )
        for icon in manifest["icons"]:
            self.assertTrue(
                os.path.exists(
                    os.path.join(
                        app_module.app.root_path,
                        icon["src"].lstrip("/").replace("/", os.sep),
                    )
                )
            )

    def test_service_worker_is_root_scoped_and_avoids_dynamic_caching(self):
        response = self.client.get("/service-worker.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        script = response.get_data(as_text=True)
        self.assertIn('const CACHE_VERSION = "ai-study-buddy-pwa-v3"', script)
        self.assertIn('request.method !== "GET"', script)
        self.assertIn('request.mode === "navigate"', script)
        self.assertIn("networkOnlyNavigation(request)", script)
        self.assertIn('url.pathname.startsWith("/static/")', script)
        self.assertIn("cache.put(request, response.clone())", script)

    def test_offline_page_displays_required_message(self):
        response = self.client.get("/offline")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Study Buddy is offline.", page)
        self.assertIn("Previously loaded pages remain available.", page)
        self.assertIn("AI features require an internet connection.", page)

    def test_logged_in_home_shows_verified_student_mode(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Welcome back, Asha Student", page)
        self.assertIn("Student", page)
        self.assertIn("role-student", page)
        self.assertNotIn("Welcome, Guest!", page)
        self.assertNotIn("Why create an account?", page)

    def test_register_hashes_password_and_rejects_duplicate_username(self):
        response = self.register_user()

        self.assertEqual(response.status_code, 302)
        with app_module.app.app_context():
            row = User.query.filter_by(username="asha").first()

        self.assertEqual(row.full_name, "Asha Student")
        self.assertEqual(row.email, "asha@example.com")
        self.assertEqual(row.student_class, "8")
        self.assertEqual(row.role, "student")
        self.assertNotEqual(row.password_hash, "password123")
        self.assertTrue(app_module.check_password_hash(row.password_hash, "password123"))

        duplicate_response = self.register_user(email="different@example.com")

        self.assertEqual(duplicate_response.status_code, 400)
        self.assertIn("That username is already taken.", duplicate_response.get_data(as_text=True))

    def test_register_rejects_duplicate_email(self):
        self.register_user()

        response = self.register_user(username="asha_two")

        self.assertEqual(response.status_code, 400)
        self.assertIn("That email is already registered.", response.get_data(as_text=True))

    def test_register_ignores_submitted_role_for_normal_user(self):
        response = self.register_user(extra_data={"role": "developer"})

        self.assertEqual(response.status_code, 302)
        with app_module.app.app_context():
            row = User.query.filter_by(username="asha").first()

        self.assertEqual(row.role, "student")

    def test_public_registration_never_assigns_predefined_privileged_roles(self):
        special_accounts = [
            ("Manjit Saha", "manjit", "manjit@example.com"),
            ("Manjit Saha", "manjitsaha", "manjitsaha2026@example.com"),
            ("Gyanjyoti Mahanta", "gyanjyoti", "gyanjyoti@example.com"),
            ("Lakshya Tuwani", "lakshya", "lakshya@example.com"),
        ]

        for full_name, username, email in special_accounts:
            with self.subTest(username=username):
                self.register_user(username=username, email=email, full_name=full_name)
                with app_module.app.app_context():
                    row = User.query.filter_by(username=username).first()

                self.assertEqual(row.role, "student")

                self.client.get("/logout")
                self.login_user(identifier=username)
                dashboard_response = self.client.get("/dashboard")

                self.assertEqual(dashboard_response.status_code, 200)
                dashboard_page = dashboard_response.get_data(as_text=True)
                self.assertIn("Student", dashboard_page)
                self.assertIn("role-student", dashboard_page)
                self.assertNotIn("role-developer", dashboard_page)

    def test_existing_trusted_roles_keep_role_badges(self):
        trusted_accounts = [
            ("Manjit Saha", "manjit", "manjit@example.com", "developer", "Developer", "role-developer"),
            ("Gyanjyoti Mahanta", "gyanjyoti", "gyanjyoti@example.com", "technical_support", "Technical Support", "role-technical-support"),
            ("Lakshya Tuwani", "lakshya", "lakshya@example.com", "qa_tester", "Testing &amp; Quality Assurance", "role-qa-tester"),
        ]

        for full_name, username, email, role, badge_text, badge_class in trusted_accounts:
            with self.subTest(username=username):
                self.register_user(username=username, email=email, full_name=full_name)
                self.grant_role(username, role)
                self.client.get("/logout")
                self.login_user(identifier=username)

                dashboard_response = self.client.get("/dashboard")
                profile_response = self.client.get("/profile")

                self.assertEqual(dashboard_response.status_code, 200)
                self.assertEqual(profile_response.status_code, 200)
                dashboard_page = dashboard_response.get_data(as_text=True)
                profile_page = profile_response.get_data(as_text=True)
                self.assertIn(badge_text, dashboard_page)
                self.assertIn(badge_class, dashboard_page)
                self.assertIn(badge_text, profile_page)
                self.assertIn(badge_class, profile_page)

    def test_copycat_name_does_not_receive_developer_role(self):
        self.register_user(
            full_name="Manjit Saha",
            username="not_manjit",
            email="copycat@example.com",
        )

        with app_module.app.app_context():
            row = User.query.filter_by(username="not_manjit").first()

        self.assertEqual(row.role, "student")

        self.login_user(identifier="not_manjit")
        dashboard_response = self.client.get("/dashboard")
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("role-student", dashboard_page)
        self.assertNotIn("role-developer", dashboard_page)

    def test_dashboard_recommendations_use_history_without_database_writes(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            now = app_module.datetime.now(app_module.timezone.utc)
            photosynthesis_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                ["What is photosynthesis?"],
            )
            cell_division_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Cell Division",
                "Cells divide to grow and repair.",
                {},
                ["What is mitosis?"],
            )
            db.session.get(LearningHistory, photosynthesis_id).created_at = now - app_module.timedelta(days=8)
            db.session.get(LearningHistory, cell_division_id).created_at = now - app_module.timedelta(hours=2)
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Cell Division",
                "4/10",
                "C",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=user.id,
            )
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Photosynthesis",
                "9/10",
                "A+",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=user.id,
            )
            db.session.commit()
            before_counts = {
                model.__tablename__: model.query.count()
                for model in (
                    LearningHistory,
                    LearningSession,
                    QuizHistory,
                    DownloadedFile,
                    RevisionSheet,
                    MindMap,
                    ImportantQuestionSet,
                    FlashcardSet,
                    Flashcard,
                    TutorLesson,
                    TutorMessage,
                )
            }

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(gemini_request.called)
        page = response.get_data(as_text=True)
        self.assertIn("Recommended For You", page)
        self.assertIn("Smart AI Recommendations", page)
        self.assertIn("Revise Cell Division", page)
        self.assertIn("Study Photosynthesis again", page)
        self.assertIn("Quiz history", page)
        self.assertIn("Saved lesson", page)

        with app_module.app.app_context():
            after_counts = {
                model.__tablename__: model.query.count()
                for model in (
                    LearningHistory,
                    LearningSession,
                    QuizHistory,
                    DownloadedFile,
                    RevisionSheet,
                    MindMap,
                    ImportantQuestionSet,
                    FlashcardSet,
                    Flashcard,
                    TutorLesson,
                    TutorMessage,
                )
            }
        self.assertEqual(before_counts, after_counts)

    def test_dashboard_recommends_due_flashcard_revision(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            lesson_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Respiration",
                "Respiration releases energy from food.",
                {},
                ["What is respiration?"],
            )
            flashcard_set = FlashcardSet(
                user_id=user.id,
                learning_history_id=lesson_id,
                source_model="test",
            )
            db.session.add(flashcard_set)
            db.session.flush()
            db.session.add(
                Flashcard(
                    flashcard_set_id=flashcard_set.id,
                    user_id=user.id,
                    learning_history_id=lesson_id,
                    position=1,
                    front="What is respiration?",
                    back="The process of releasing energy from food.",
                    needs_revision=True,
                )
            )
            db.session.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Complete today&#39;s revision", page)
        self.assertIn("Open flashcards", page)
        self.assertIn("/flashcards/", page)

    def test_gamification_summary_calculates_local_xp_levels_and_badges(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            lesson_one_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Plants",
                "Plants make food.",
                {},
                ["Q1"],
            )
            lesson_two_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Cells",
                "Cells are basic units of life.",
                {},
                ["Q1"],
            )
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Plants",
                "8/10",
                "A",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=user.id,
            )
            db.session.add_all(
                [
                    RevisionSheet(
                        user_id=user.id,
                        learning_history_id=lesson_one_id,
                        content_markdown="# Quick Revision",
                        source_model="local-test",
                    ),
                    MindMap(
                        user_id=user.id,
                        learning_history_id=lesson_one_id,
                        map_json="{}",
                        source_model="local-test",
                    ),
                    FlashcardSet(
                        user_id=user.id,
                        learning_history_id=lesson_two_id,
                        source_model="local-test",
                    ),
                    TutorLesson(
                        user_id=user.id,
                        learning_history_id=lesson_two_id,
                        name="Asha Student",
                        student_class="8",
                        subject="Science",
                        book_name="Biology",
                        chapter="Cells",
                    ),
                ]
            )
            db.session.commit()

            summary = app_module.get_gamification_summary(user.id)

        self.assertEqual(summary["total_xp"], 105)
        self.assertEqual(summary["level"]["level"], 2)
        self.assertEqual(summary["level"]["progress_percentage"], 5)
        self.assertEqual(summary["counts"]["notes"], 2)
        self.assertEqual(summary["counts"]["revision"], 1)
        self.assertEqual(summary["counts"]["mind_map"], 1)
        self.assertEqual(summary["counts"]["flashcards"], 1)
        self.assertEqual(summary["counts"]["tutor"], 1)
        self.assertEqual(summary["counts"]["quiz"], 1)
        self.assertTrue(
            next(badge for badge in summary["badges"] if badge["title"] == "All-round Learner")["unlocked"]
        )

        with patch("app.gemini_request") as gemini_request:
            dashboard_response = self.client.get("/dashboard")
            profile_response = self.client.get("/profile")

        self.assertFalse(gemini_request.called)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
        dashboard_page = dashboard_response.get_data(as_text=True)
        profile_page = profile_response.get_data(as_text=True)
        self.assertIn("105 XP earned", dashboard_page)
        self.assertIn("Level 2", dashboard_page)
        self.assertIn("Daily Challenges", dashboard_page)
        self.assertIn("Notes <strong>+10</strong>", dashboard_page)
        self.assertIn("All-round Learner", dashboard_page)
        self.assertIn("Milestone Progress", dashboard_page)
        self.assertIn("Level 2 &middot; 105 XP", profile_page)
        self.assertIn("Badges Unlocked", profile_page)

    def test_study_plan_computes_local_activity_status_without_gemini(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            lesson_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Plants",
                "Plants make food.",
                {},
                ["What is photosynthesis?"],
            )
            db.session.add(
                RevisionSheet(
                    user_id=user.id,
                    learning_history_id=lesson_id,
                    content_markdown="# Quick Revision",
                    source_model="local-test",
                )
            )
            db.session.commit()

        with patch("app.gemini_request") as gemini_request:
            response = self.client.get(f"/study-plan/{lesson_id}")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(gemini_request.called)
        page = response.get_data(as_text=True)
        self.assertIn("AI Study Planner", page)
        self.assertIn("28%", page)
        self.assertIn("2/7", page)
        self.assertIn("Notes", page)
        self.assertIn("Quick Revision", page)
        self.assertIn("Complete", page)
        self.assertIn("Generate Mind Map", page)
        self.assertIn("Generate Flashcards", page)
        self.assertIn("Take Quiz", page)
        self.assertIn("Completion XP", page)

    def test_completed_study_plan_awards_xp_once_and_updates_stats(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            lesson_id = app_module.save_learning_history(
                user.id,
                "Science",
                "Biology",
                "Plants",
                "Plants make food.",
                {},
                ["What is photosynthesis?"],
            )
            db.session.add_all(
                [
                    RevisionSheet(
                        user_id=user.id,
                        learning_history_id=lesson_id,
                        content_markdown="# Quick Revision",
                        source_model="local-test",
                    ),
                    MindMap(
                        user_id=user.id,
                        learning_history_id=lesson_id,
                        map_json="{}",
                        source_model="local-test",
                    ),
                    FlashcardSet(
                        user_id=user.id,
                        learning_history_id=lesson_id,
                        source_model="local-test",
                    ),
                    MemoryChallenge(
                        user_id=user.id,
                        lesson_id=lesson_id,
                        difficulty="easy",
                        best_time=45,
                        best_accuracy=100,
                        best_moves=6,
                        highest_combo=6,
                        xp_earned=20,
                    ),
                    TutorLesson(
                        user_id=user.id,
                        learning_history_id=lesson_id,
                        name="Asha Student",
                        student_class="8",
                        subject="Science",
                        book_name="Biology",
                        chapter="Plants",
                    ),
                ]
            )
            db.session.commit()
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Plants",
                "9/10",
                "A+",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=user.id,
            )

        with patch("app.gemini_request") as gemini_request:
            first_response = self.client.get(f"/study-plan/{lesson_id}")
            second_response = self.client.get(f"/study-plan/{lesson_id}")

        self.assertFalse(gemini_request.called)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first_page = first_response.get_data(as_text=True)
        second_page = second_response.get_data(as_text=True)
        self.assertIn("+40 XP awarded", first_page)
        self.assertIn("Awarded", second_page)

        with app_module.app.app_context():
            summary = app_module.get_gamification_summary(1)
            planner_stats = app_module.get_study_planner_stats(1)
            self.assertEqual(StudyPlanProgress.query.count(), 1)

        self.assertEqual(summary["counts"]["study_plan"], 1)
        self.assertEqual(summary["total_xp"], 155)
        self.assertEqual(planner_stats["completed_lessons"], 1)
        self.assertEqual(planner_stats["xp_awarded"], 40)

        dashboard_page = self.client.get("/dashboard").get_data(as_text=True)
        profile_page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("Today's Study Goal", dashboard_page)
        self.assertIn("Study Plans Completed", dashboard_page)
        self.assertIn("Planner statistics", profile_page)
        self.assertIn("Planner XP", profile_page)

    def test_rbac_panels_require_login(self):
        for path in ["/developer", "/developer/users", "/developer/user/1", "/support", "/qa"]:
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 302)
                self.assertIn(f"/login?next={path}", response.headers["Location"])

    def test_student_is_denied_rbac_panels(self):
        self.register_user()
        self.login_user()

        for path in ["/developer", "/developer/users", "/developer/user/1", "/support", "/qa"]:
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 403)
                page = response.get_data(as_text=True)
                self.assertIn("Access Denied", page)
                self.assertIn("role-student", page)

    def test_developer_panel_shows_system_stats_and_full_access(self):
        self.register_user(full_name="Manjit Saha", username="manjit", email="manjit@example.com")
        self.grant_role("manjit", "developer")
        self.login_user(identifier="manjit")

        with app_module.app.app_context():
            app_module.save_learning_history(1, "Science", "Book", "Plants", "Notes", "Diagram", ["Q1"])
            app_module.save_quiz_history(
                "Manjit Saha",
                "8",
                "Science",
                "Plants",
                "8/10",
                "A",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=1,
            )
            app_module.save_downloaded_file(1, "performance_report", "Science", "Plants", "8/10", "A")

        developer_response = self.client.get("/developer")
        support_response = self.client.get("/support")
        qa_response = self.client.get("/qa")

        self.assertEqual(developer_response.status_code, 200)
        self.assertEqual(support_response.status_code, 200)
        self.assertEqual(qa_response.status_code, 200)

        page = developer_response.get_data(as_text=True)
        self.assertIn("Developer Panel", page)
        self.assertIn("Total Registered Users", page)
        self.assertIn("Users Registered Today", page)
        self.assertIn("Total Topics Generated", page)
        self.assertIn("Total Quizzes Taken", page)
        self.assertIn("Total Notes Saved", page)
        self.assertIn("Total Downloads", page)
        self.assertIn("Active Users Today", page)
        self.assertIn("Total XP Awarded", page)
        self.assertIn("Highest Level", page)
        self.assertIn("Badges Unlocked", page)
        self.assertIn("Average XP/User", page)
        self.assertIn(">35</strong>", page)
        self.assertIn("Recent Registrations", page)
        self.assertIn("Manage Users", page)
        self.assertIn("AI Provider Status", page)
        self.assertIn("Gemini", page)
        self.assertIn("Ollama", page)
        self.assertIn("Website Version", page)
        self.assertIn("Database Statistics", page)
        self.assertIn("Server Status", page)
        self.assertIn("Study Planner Analytics", page)
        self.assertIn("Planner-Ready Lessons", page)
        self.assertIn("Planner XP Awarded", page)
        self.assertIn("role-developer", page)
        self.assertIn("Support Panel", page)
        self.assertIn("QA Panel", page)

    def test_developer_users_page_filters_and_shows_rollups(self):
        self.register_user(full_name="Manjit Saha", username="manjit", email="manjit@example.com")
        self.grant_role("manjit", "developer")
        self.login_user(identifier="manjit")

        with app_module.app.app_context():
            student = app_module.create_user(
                "Asha Student",
                "asha_student",
                "asha.student@example.com",
                "8",
                "password123",
            )
            other_student = app_module.create_user(
                "Ravi Learner",
                "ravi",
                "ravi@example.com",
                "9",
                "password123",
            )
            old_date = app_module.datetime(2026, 6, 10, 9, 0, tzinfo=app_module.timezone.utc)
            student.created_at = old_date
            other_student.created_at = old_date
            db.session.commit()

            app_module.save_learning_history(student.id, "Science", "Book", "Plants", "Notes", "{}", ["Q1"])
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Plants",
                "8/10",
                "A",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=student.id,
            )
            app_module.save_downloaded_file(student.id, "performance_report", "Science", "Plants", "8/10", "A")

        response = self.client.get("/developer/users?search=asha&student_class=8&role=student")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Registered Users", page)
        self.assertIn("Asha Student", page)
        self.assertIn("asha.student@example.com", page)
        self.assertIn("Total Topics Studied", page)
        self.assertIn("Average Quiz Score", page)
        self.assertIn("80%", page)
        self.assertIn("Not tracked", page)
        self.assertNotIn("Ravi Learner", page)

        partial_response = self.client.get(
            "/developer/users?search=asha&partial=1",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        partial_page = partial_response.get_data(as_text=True)
        self.assertEqual(partial_response.status_code, 200)
        self.assertIn("developer-users-results", partial_page)
        self.assertIn("Asha Student", partial_page)
        self.assertNotIn("<html", partial_page.lower())

    def test_developer_users_page_paginates_25_users(self):
        self.register_user(full_name="Manjit Saha", username="manjit", email="manjit@example.com")
        self.grant_role("manjit", "developer")
        self.login_user(identifier="manjit")

        with app_module.app.app_context():
            base_date = app_module.datetime(2026, 6, 1, 9, 0, tzinfo=app_module.timezone.utc)
            db.session.add_all(
                User(
                    full_name=f"Student {index:02d}",
                    username=f"student_{index:02d}",
                    email=f"student_{index:02d}@example.com",
                    student_class="8",
                    role="student",
                    password_hash="test-hash",
                    created_at=base_date + app_module.timedelta(minutes=index),
                )
                for index in range(1, 28)
            )
            db.session.commit()

        first_page = self.client.get("/developer/users")
        second_page = self.client.get("/developer/users?page=2")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertIn("Page 1 of 2", first_page.get_data(as_text=True))
        self.assertIn("Next", first_page.get_data(as_text=True))
        self.assertIn("Page 2 of 2", second_page.get_data(as_text=True))
        self.assertIn("Previous", second_page.get_data(as_text=True))

    def test_developer_user_detail_shows_account_stats_and_activity(self):
        self.register_user(full_name="Manjit Saha", username="manjit", email="manjit@example.com")
        self.grant_role("manjit", "developer")
        self.login_user(identifier="manjit")

        with app_module.app.app_context():
            student = app_module.create_user(
                "Asha Student",
                "asha_student",
                "asha.student@example.com",
                "8",
                "password123",
            )
            app_module.save_learning_history(student.id, "Science", "Book", "Plants", "Notes", "{}", ["Q1"])
            app_module.save_quiz_history(
                "Asha Student",
                "8",
                "Science",
                "Plants",
                "9/10",
                "A+",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=student.id,
            )
            app_module.save_downloaded_file(student.id, "performance_report", "Science", "Plants", "9/10", "A+")
            student_id = student.id

        response = self.client.get(f"/developer/user/{student_id}")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Account Information", page)
        self.assertIn("Asha Student", page)
        self.assertIn("Learning Statistics", page)
        self.assertIn("Topics Studied", page)
        self.assertIn("Quizzes Attempted", page)
        self.assertIn("Average Score", page)
        self.assertIn("90%", page)
        self.assertIn("Downloads", page)
        self.assertIn("Saved Notes", page)
        self.assertIn("Total XP", page)
        self.assertIn("Level", page)
        self.assertIn("Badges Unlocked", page)
        self.assertIn("XP Progress", page)
        self.assertIn("Recent Activity", page)
        self.assertIn("Saved Note", page)
        self.assertIn("Quiz", page)

    def test_support_and_qa_panels_enforce_role_permissions(self):
        self.register_user(
            full_name="Gyanjyoti Mahanta",
            username="gyanjyoti",
            email="gyanjyoti@example.com",
        )
        self.grant_role("gyanjyoti", "technical_support")
        self.login_user(identifier="gyanjyoti")

        support_response = self.client.get("/support")
        qa_response = self.client.get("/qa")
        developer_response = self.client.get("/developer")

        self.assertEqual(support_response.status_code, 200)
        self.assertIn("Support Panel", support_response.get_data(as_text=True))
        self.assertIn("role-technical-support", support_response.get_data(as_text=True))
        self.assertEqual(qa_response.status_code, 403)
        self.assertEqual(developer_response.status_code, 403)

        self.client.get("/logout")
        self.register_user(
            full_name="Lakshya Tuwani",
            username="lakshya",
            email="lakshya@example.com",
        )
        self.grant_role("lakshya", "qa_tester")
        self.login_user(identifier="lakshya")

        qa_tester_response = self.client.get("/qa")
        support_denied_response = self.client.get("/support")

        self.assertEqual(qa_tester_response.status_code, 200)
        self.assertIn("QA Panel", qa_tester_response.get_data(as_text=True))
        self.assertIn("Testing Checklist", qa_tester_response.get_data(as_text=True))
        self.assertIn("role-qa-tester", qa_tester_response.get_data(as_text=True))
        self.assertEqual(support_denied_response.status_code, 403)

    def test_login_accepts_email_and_redirects_to_dashboard(self):
        self.register_user()

        response = self.client.post(
            "/login",
            data={
                "identifier": "asha@example.com",
                "password": "password123",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Student Dashboard", page)
        self.assertIn("Welcome back, Asha Student", page)
        self.assertIn('class="profile-menu-button"', page)
        self.assertIn('class="profile-dropdown"', page)
        self.assertIn("Student", page)
        self.assertIn("role-student", page)
        self.assertIn("Dashboard", page)
        self.assertIn("My Profile", page)
        self.assertIn("Learning History", page)
        self.assertIn("Quiz History", page)
        self.assertIn("Downloaded Reports", page)
        self.assertIn("Settings", page)
        self.assertIn("Logout", page)
        self.assertNotIn(">Login</a>", page)
        self.assertNotIn(">Register</a>", page)

    def test_account_dropdown_is_not_clipped_by_dashboard_topbar(self):
        css = Path("static/style.css").read_text(encoding="utf-8")

        self.assertIn(".profile-menu.is-open .profile-dropdown", css)
        self.assertIn("pointer-events: auto", css)
        self.assertIn(".dashboard-topbar {\n    z-index: 80;\n    overflow: visible;\n}", css)
        self.assertIn(".tutor-header,\n.hero {\n    overflow: hidden;\n}", css)
        self.assertNotIn(
            ".dashboard-topbar,\n.tutor-header,\n.hero {\n    position: relative;\n    overflow: hidden;\n}",
            css,
        )

    def test_profile_menu_button_is_excluded_from_primary_button_reset(self):
        css = Path("static/style.css").read_text(encoding="utf-8")

        self.assertIn(
            ":where(button:not(.profile-menu-button), .button-link, .back-btn):not(.secondary-link):not(.danger-link)",
            css,
        )
        self.assertNotIn(
            ":where(button, .button-link, .back-btn):not(.secondary-link):not(.danger-link)",
            css,
        )

    def test_login_session_persists_across_page_refreshes(self):
        self.register_user()
        self.login_user()

        with self.client.session_transaction() as browser_session:
            self.assertTrue(browser_session.permanent)
            self.assertEqual(browser_session["username"], "asha")

        first_dashboard_response = self.client.get("/dashboard")
        refreshed_dashboard_response = self.client.get("/dashboard")
        refreshed_profile_response = self.client.get("/profile")

        self.assertEqual(first_dashboard_response.status_code, 200)
        self.assertEqual(refreshed_dashboard_response.status_code, 200)
        self.assertEqual(refreshed_profile_response.status_code, 200)
        self.assertIn("Welcome back, Asha Student", refreshed_dashboard_response.get_data(as_text=True))
        self.assertIn("Username", refreshed_profile_response.get_data(as_text=True))

    def test_request_helpers_do_not_run_create_all(self):
        self.register_user()
        self.login_user()

        with patch.object(app_module, "create_database_tables") as create_tables:
            app_module.init_users_db()
            app_module.init_quiz_history_db()
            app_module.init_learning_history_db()
            app_module.init_account_activity_db()
            with app_module.app.app_context():
                app_module.get_user_by_id(1)
                app_module.get_user_by_username_or_email("asha")
            dashboard_response = self.client.get("/dashboard")

        self.assertEqual(dashboard_response.status_code, 200)
        create_tables.assert_not_called()

    def test_login_page_links_to_forgot_password(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Forgot Password?", page)
        self.assertIn('href="/forgot-password"', page)

    def test_forgot_password_does_not_reveal_unknown_account(self):
        response = self.client.post(
            "/forgot-password",
            data={
                "action": "find_account",
                "identifier": "missing@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("online password reset is temporarily unavailable", page)
        self.assertNotIn("We could not find an account", page)
        self.assertNotIn("missing@example.com", page)

    def test_forgot_password_does_not_reveal_known_account(self):
        self.register_user()
        response = self.client.post(
            "/forgot-password",
            data={
                "action": "find_account",
                "identifier": "asha",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("online password reset is temporarily unavailable", page)
        self.assertNotIn("Account Found", page)
        self.assertNotIn("Asha Student", page)
        self.assertNotIn("asha@example.com", page)

    def test_forgot_password_never_changes_password_hash(self):
        self.register_user()

        with app_module.app.app_context():
            old_hash = User.query.filter_by(username="asha").first().password_hash

        self.client.post(
            "/forgot-password",
            data={
                "action": "find_account",
                "identifier": "asha@example.com",
            },
        )
        response = self.client.post(
            "/forgot-password",
            data={
                "action": "reset_password",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("online password reset is temporarily unavailable", page)

        with app_module.app.app_context():
            new_hash = User.query.filter_by(username="asha").first().password_hash

        self.assertEqual(old_hash, new_hash)
        self.assertTrue(app_module.check_password_hash(new_hash, "password123"))

        old_login = self.client.post(
            "/login",
            data={"identifier": "asha", "password": "password123"},
            follow_redirects=True,
        )
        self.assertEqual(old_login.status_code, 200)
        self.assertIn("Student Dashboard", old_login.get_data(as_text=True))

        new_login = self.client.post(
            "/login",
            data={"identifier": "asha", "password": "newpassword123"},
        )
        self.assertEqual(new_login.status_code, 401)

    def test_dashboard_and_profile_require_login(self):
        dashboard_response = self.client.get("/dashboard")
        profile_response = self.client.get("/profile")

        self.assertEqual(dashboard_response.status_code, 302)
        self.assertIn("/login?next=/dashboard", dashboard_response.headers["Location"])
        self.assertEqual(profile_response.status_code, 302)
        self.assertIn("/login?next=/profile", profile_response.headers["Location"])

    def test_dashboard_shows_student_widgets_for_logged_in_user(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Topics Studied", page)
        self.assertIn("Quizzes Attempted", page)
        self.assertIn("Average Score", page)
        self.assertIn("Achievements", page)
        self.assertIn("Study Streak", page)
        self.assertIn("Start New Lesson", page)
        self.assertIn("Take Quiz", page)
        self.assertIn("No learning activity yet.", page)
        self.assertIn("Performance Analytics", page)
        self.assertIn("Gamification progress", page)
        self.assertIn("0 XP earned", page)
        self.assertIn("Daily Challenges", page)
        self.assertIn("Learning Badges", page)
        self.assertIn("Milestone Progress", page)
        self.assertIn("Student", page)
        self.assertIn("role-student", page)
        self.assertIn("Recommended For You", page)
        self.assertIn("Smart AI Recommendations", page)
        self.assertIn("Start with a focused lesson", page)
        self.assertIn("Complete today&#39;s revision", page)
        self.assertIn("Memory Challenge", page)
        self.assertIn("Not Started", page)
        self.assertIn("Back to Home", page)
        self.assertIn("sidebar-nav", page)
        self.assertIn('class="profile-menu-button"', page)

        profile_response = self.client.get("/profile")
        profile_page = profile_response.get_data(as_text=True)
        self.assertIn("Best Combo", profile_page)
        self.assertIn("Games Won", profile_page)
        self.assertIn("<strong>--</strong>", profile_page)
        self.assertIn("<strong>0</strong>", profile_page)

    def test_exhibition_mode_toggle_requires_developer(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            "/exhibition-mode",
            data={"enabled": "1", "next": "/"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_developer_can_enable_exhibition_mode_and_hide_admin_links(self):
        self.register_user(
            full_name="Manjit Saha",
            username="manjit",
            email="manjit@example.com",
        )
        self.grant_role("manjit", "developer")
        self.login_user(identifier="manjit")

        toggle_response = self.client.post(
            "/exhibition-mode",
            data={"enabled": "1", "next": "/"},
            follow_redirects=True,
        )

        self.assertEqual(toggle_response.status_code, 200)
        home_page = toggle_response.get_data(as_text=True)
        self.assertIn("Exhibition Mode", home_page)
        self.assertIn("Quick Demo", home_page)
        self.assertIn("Guided Tour", home_page)

        dashboard_response = self.client.get("/dashboard")
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Exhibition Mode", dashboard_page)
        self.assertNotIn("Developer Panel", dashboard_page)
        self.assertNotIn(">Developer</span>", dashboard_page)
        self.assertNotIn("Manage Users", dashboard_page)

    def flashcard_response(self, count=10):
        return MockResponse(
            json.dumps(
                {
                    "flashcards": [
                        {
                            "front": f"Concept {index}",
                            "back": f"Clear explanation for concept {index}.",
                        }
                        for index in range(1, count + 1)
                    ]
                }
            )
        )

    def create_saved_lesson(
        self,
        user_id=1,
        subject="Science",
        book_name="NCERT",
        topic="Photosynthesis",
        notes="Plants make food using sunlight.",
    ):
        return app_module.save_learning_history(
            user_id,
            subject,
            book_name,
            topic,
            notes,
            {},
            self.questions,
        )

    def create_saved_flashcards(self, user_id=1, count=12, topic="Photosynthesis"):
        lesson_id = self.create_saved_lesson(user_id=user_id, topic=topic, notes="Plant notes")
        flashcard_set = FlashcardSet(
            user_id=user_id,
            learning_history_id=lesson_id,
        )
        db.session.add(flashcard_set)
        db.session.flush()
        db.session.add_all(
            Flashcard(
                flashcard_set_id=flashcard_set.id,
                user_id=user_id,
                learning_history_id=lesson_id,
                position=index,
                front=f"Concept {index}",
                back=f"Explanation {index}",
            )
            for index in range(1, count + 1)
        )
        db.session.commit()
        return lesson_id

    def revision_response(self):
        return MockResponse(
            """# Quick Revision: Photosynthesis

## Important Points
1. Plants make food using sunlight.
2. Chlorophyll traps sunlight.

## Definitions
- Photosynthesis: The process by which green plants make food.

## Formulas
- Carbon dioxide + water -> glucose + oxygen.

## Common Mistakes
- Do not forget sunlight and chlorophyll.

## Exam Tips
- Write the word equation clearly.

## One-page Summary
Photosynthesis helps plants prepare food and release oxygen.
"""
        )

    def important_questions_response(self):
        return MockResponse(
            """# Important Exam Questions: Photosynthesis

## MCQs
1. What do green plants use to make food?
   A. Sunlight
   B. Sand
   C. Plastic
   D. Smoke
   Answer: A. Sunlight

## Very Short Questions
1. What is photosynthesis?
   Answer: The process by which green plants make food.

## Short Questions
1. Why is chlorophyll important?
   Answer: It helps leaves trap sunlight for photosynthesis.

## Long Questions
1. Explain photosynthesis with the word equation.
   Outline: Mention raw materials, sunlight, chlorophyll, glucose, and oxygen.

## HOTS Questions
1. Why may a covered leaf make less food?
   Hint: Think about sunlight.

## Revision Tips
- Practice the word equation.
- Revise raw materials and products.
"""
        )

    def mind_map_response(self):
        return MockResponse(
            json.dumps(
                {
                    "nodes": [
                        {"id": "root", "title": "Photosynthesis", "parent": None},
                        {"id": "light", "title": "Sunlight", "parent": "root"},
                        {"id": "chlorophyll", "title": "Chlorophyll", "parent": "root"},
                        {"id": "products", "title": "Food and oxygen", "parent": "root"},
                    ]
                }
            )
        )

    @patch.object(app_module, "generate_content_with_fallback")
    def test_revision_generates_once_and_reopens(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.revision_response()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )

        first_response = self.client.get(f"/revision/{lesson_id}")
        second_response = self.client.get(f"/revision/{lesson_id}")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        generate_content.assert_called_once()
        page = first_response.get_data(as_text=True)
        self.assertIn("Quick Revision", page)
        self.assertIn("Important Points", page)
        self.assertIn("Definitions", page)
        self.assertIn("Formulas", page)
        self.assertIn("Common Mistakes", page)
        self.assertIn("Exam Tips", page)
        self.assertIn("Download PDF", page)
        self.assertIn("Open Flashcards", page)
        self.assertIn("Learn with AI Tutor", page)
        self.assertIn("Take Quiz", page)
        with app_module.app.app_context():
            self.assertEqual(RevisionSheet.query.count(), 1)
            revision_sheet = RevisionSheet.query.first()
            self.assertEqual(revision_sheet.learning_history_id, lesson_id)
            self.assertEqual(revision_sheet.user_id, 1)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_revision_permissions_require_lesson_owner(self, generate_content):
        self.register_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")

        response = self.client.get(f"/revision/{lesson_id}")

        self.assertEqual(response.status_code, 404)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_revision_dashboard_history_and_pdf_integration(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.revision_response()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )

        revision_response = self.client.get(f"/revision/{lesson_id}")
        history_response = self.client.get("/learning-history")
        dashboard_response = self.client.get("/dashboard")
        pdf_response = self.client.get(f"/revision/{lesson_id}/download")

        self.assertEqual(revision_response.status_code, 200)
        self.assertIn("Open Revision", history_response.get_data(as_text=True))
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Revision Sheets Generated", dashboard_page)
        self.assertIn("<strong>1</strong>", dashboard_page)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF"))

    @patch.object(app_module, "generate_content_with_fallback")
    def test_important_questions_generate_once_and_reopen(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.important_questions_response()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight and chlorophyll.",
                {},
                self.questions,
            )
            db.session.add(
                RevisionSheet(
                    user_id=1,
                    learning_history_id=lesson_id,
                    content_markdown="## Important Points\n- Chlorophyll traps sunlight.",
                )
            )
            db.session.commit()

        first_response = self.client.get(f"/important-questions/{lesson_id}")
        second_response = self.client.get(f"/important-questions/{lesson_id}")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        generate_content.assert_called_once()
        prompt = generate_content.call_args.args[0]
        self.assertIn("Class: 8", prompt)
        self.assertIn("Subject: Science", prompt)
        self.assertIn("Chapter / Topic: Photosynthesis", prompt)
        self.assertIn("Plants make food using sunlight and chlorophyll.", prompt)
        self.assertIn("Chlorophyll traps sunlight.", prompt)
        page = first_response.get_data(as_text=True)
        self.assertIn('<meta name="viewport"', page)
        self.assertIn("Important Exam Questions", page)
        self.assertIn("MCQs", page)
        self.assertIn("Very Short Questions", page)
        self.assertIn("Short Questions", page)
        self.assertIn("Long Questions", page)
        self.assertIn("HOTS Questions", page)
        self.assertIn("Revision Tips", page)
        self.assertIn("Download PDF", page)
        self.assertIn("Open Revision", page)
        self.assertIn("Open Mind Map", page)
        self.assertIn("Open Flashcards", page)
        self.assertIn("AI Tutor", page)
        self.assertIn("Quiz", page)
        with app_module.app.app_context():
            self.assertEqual(ImportantQuestionSet.query.count(), 1)
            question_set = ImportantQuestionSet.query.first()
            self.assertEqual(question_set.learning_history_id, lesson_id)
            self.assertEqual(question_set.user_id, 1)
            self.assertEqual(question_set.learning_history.topic, "Photosynthesis")
            self.assertNotIn("Plants make food using sunlight and chlorophyll.", question_set.markdown)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_important_questions_permissions_require_lesson_owner(self, generate_content):
        self.register_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")

        response = self.client.get(f"/important-questions/{lesson_id}")
        pdf_response = self.client.get(f"/important-questions/{lesson_id}/download")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(pdf_response.status_code, 404)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_important_questions_dashboard_history_and_pdf_integration(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.important_questions_response()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )

        question_response = self.client.get(f"/important-questions/{lesson_id}")
        history_response = self.client.get("/learning-history")
        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        dashboard_response = self.client.get("/dashboard")
        pdf_response = self.client.get(f"/important-questions/{lesson_id}/download")

        self.assertEqual(question_response.status_code, 200)
        self.assertIn("Open Important Questions", history_response.get_data(as_text=True))
        self.assertIn("Open Important Questions", detail_response.get_data(as_text=True))
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Important Question Sets Generated", dashboard_page)
        self.assertIn("<strong>1</strong>", dashboard_page)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF"))

    def test_important_questions_pdf_requires_existing_generated_set(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )

        response = self.client.get(f"/important-questions/{lesson_id}/download")

        self.assertEqual(response.status_code, 404)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_mind_map_generates_once_and_reopens(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.mind_map_response()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight and chlorophyll.",
                {},
                self.questions,
            )

        first_response = self.client.get(f"/mindmap/{lesson_id}")
        second_response = self.client.get(f"/mindmap/{lesson_id}")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        generate_content.assert_called_once()
        page = first_response.get_data(as_text=True)
        self.assertIn('<meta name="viewport"', page)
        self.assertIn("AI Mind Map", page)
        self.assertIn("Photosynthesis", page)
        self.assertIn("Sunlight", page)
        self.assertIn("data-zoom-in", page)
        self.assertIn("data-zoom-out", page)
        self.assertIn("data-zoom-reset", page)
        self.assertIn("window.print()", page)
        self.assertIn("mindmap-stage", page)
        self.assertIn("mindmap-branches", page)
        with app_module.app.app_context():
            self.assertEqual(MindMap.query.count(), 1)
            mind_map = MindMap.query.first()
            self.assertEqual(mind_map.learning_history_id, lesson_id)
            self.assertEqual(mind_map.user_id, 1)
            self.assertEqual(mind_map.learning_history.topic, "Photosynthesis")
            self.assertNotIn("Plants make food", mind_map.map_json)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_mind_map_permissions_require_lesson_owner(self, generate_content):
        self.register_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")

        response = self.client.get(f"/mindmap/{lesson_id}")

        self.assertEqual(response.status_code, 404)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_mind_map_dashboard_history_and_json_integration(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """```json
{
  "nodes": [
    {"id": "root", "title": "Photosynthesis", "parent": null},
    {"id": "raw-materials", "title": "Raw materials", "parent": "root"},
    {"id": "water", "title": "Water", "parent": "raw-materials"}
  ]
}
```"""
        )
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                self.questions,
            )

        mind_map_response = self.client.get(f"/mindmap/{lesson_id}")
        history_response = self.client.get("/learning-history")
        dashboard_response = self.client.get("/dashboard")
        detail_response = self.client.get(f"/learning-history/{lesson_id}")

        self.assertEqual(mind_map_response.status_code, 200)
        self.assertIn("Raw materials", mind_map_response.get_data(as_text=True))
        self.assertIn("Open Mind Map", history_response.get_data(as_text=True))
        self.assertIn("Open Mind Map", detail_response.get_data(as_text=True))
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Mind Maps Generated", dashboard_page)
        self.assertIn("<strong>1</strong>", dashboard_page)

    def test_mind_map_json_parsing_limits_and_repairs_tree(self):
        payload = {
            "nodes": [
                {"id": "root", "title": "Main Topic", "parent": None},
                {"id": "duplicate", "title": "First", "parent": "root"},
                {"id": "duplicate", "title": "Second", "parent": "root"},
                {"id": "orphan", "title": "Orphan", "parent": "missing"},
            ]
            + [
                {"id": f"extra-{index}", "title": f"Extra {index}", "parent": "root"}
                for index in range(1, 40)
            ]
        }

        normalized = app_module.normalize_mind_map_payload(payload, "Main Topic")

        self.assertEqual(len(normalized["nodes"]), 30)
        ids = [node["id"] for node in normalized["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(normalized["nodes"][0]["parent"], "")
        orphan = next(node for node in normalized["nodes"] if node["id"] == "orphan")
        self.assertEqual(orphan["parent"], "root")

    @patch.object(app_module.model, "generate_content")
    def test_learning_tool_opened_from_notes_returns_to_notes_hub(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Quick Revision
- Plants need light.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        notes_response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Science",
                "book_name": "NCERT",
                "topic": "Plants",
            },
        )

        self.assertEqual(notes_response.status_code, 200)
        notes_page = notes_response.get_data(as_text=True)
        self.assertIn('href="/mindmap/1?next=/notes/1"', notes_page)

        with patch.object(app_module, "generate_content_with_fallback") as mind_map_generate:
            mind_map_generate.return_value = self.mind_map_response()
            mind_map_response = self.client.get("/mindmap/1?next=/notes/1")

        self.assertEqual(mind_map_response.status_code, 200)
        mind_map_page = mind_map_response.get_data(as_text=True)
        self.assertIn('href="/notes/1"', mind_map_page)
        self.assertNotIn('href="/learning-history/1">Back to Lesson</a>', mind_map_page)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learning_tool_opened_from_history_detail_returns_to_history_detail(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.flashcard_response(10)
        with app_module.app.app_context():
            lesson_id = self.create_saved_lesson()

        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn(
            f'href="/flashcards/{lesson_id}?next=/learning-history/{lesson_id}"',
            detail_page,
        )

        flashcard_response = self.client.get(
            f"/flashcards/{lesson_id}?next=/learning-history/{lesson_id}"
        )

        self.assertEqual(flashcard_response.status_code, 200)
        self.assertIn(
            f'href="/learning-history/{lesson_id}"',
            flashcard_response.get_data(as_text=True),
        )

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learning_tool_missing_next_uses_history_detail_fallback(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.revision_response()
        with app_module.app.app_context():
            lesson_id = self.create_saved_lesson()

        response = self.client.get(f"/revision/{lesson_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'href="/learning-history/{lesson_id}"',
            response.get_data(as_text=True),
        )

    def test_learning_tool_rejects_external_next_url(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=10)

        response = self.client.get(f"/flashcards/{lesson_id}?next=https://evil.example/phish")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(f'href="/learning-history/{lesson_id}"', page)
        self.assertNotIn("evil.example", page)

    @patch.object(app_module.model, "generate_content")
    def test_ai_tutor_preserves_return_url_through_start_redirect(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_lesson()

        start_response = self.client.post(
            "/tutor/start",
            data={
                "lesson_id": lesson_id,
                "name": "Asha",
                "student_class": "8",
                "next": f"/notes/{lesson_id}",
            },
        )

        self.assertEqual(start_response.status_code, 302)
        self.assertIn(f"/tutor/1?next=/notes/{lesson_id}", start_response.headers["Location"])

        tutor_response = self.client.get(start_response.headers["Location"])

        self.assertEqual(tutor_response.status_code, 200)
        page = tutor_response.get_data(as_text=True)
        self.assertIn(f'href="/notes/{lesson_id}"', page)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_flashcards_generate_and_render_responsive_controls(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.flashcard_response(12)
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "Plants make food using sunlight.",
                {},
                ["What do plants need?"],
            )

        response = self.client.get(f"/flashcards/{lesson_id}")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('<meta name="viewport"', page)
        self.assertIn("AI Flashcards", page)
        self.assertIn("Card 1 / 12", page)
        self.assertIn("Flip Card", page)
        self.assertIn("Shuffle", page)
        self.assertIn("Mark as Mastered", page)
        self.assertIn("Need Revision", page)
        self.assertIn("Flashcards Ready!", page)
        self.assertIn("Continue learning with the AI Memory Challenge.", page)
        self.assertIn(f'href="/memory-challenge/{lesson_id}?next=/flashcards/{lesson_id}"', page)
        generate_content.assert_called_once()
        prompt = generate_content.call_args.args[0]
        self.assertIn("Board: CBSE", prompt)
        self.assertIn("Textbook: NCERT", prompt)
        self.assertIn("Chapter: Photosynthesis", prompt)
        self.assertIn("Use the selected textbook and chapter context", prompt)
        with app_module.app.app_context():
            flashcard_set = FlashcardSet.query.first()
            self.assertIsNotNone(flashcard_set)
            self.assertEqual(flashcard_set.learning_history_id, lesson_id)
            self.assertEqual(flashcard_set.user_id, 1)
            self.assertEqual(flashcard_set.learning_history.topic, "Photosynthesis")
            self.assertEqual(len(flashcard_set.flashcards), 12)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_flashcards_reopen_without_regenerating(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.flashcard_response(10)
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Plants",
                "Plant notes.",
                {},
                ["Q1"],
            )

        first_response = self.client.get(f"/flashcards/{lesson_id}")
        second_response = self.client.get(f"/flashcards/{lesson_id}")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        generate_content.assert_called_once()
        self.assertIn("Flashcards Ready!", first_response.get_data(as_text=True))
        self.assertNotIn("Flashcards Ready!", second_response.get_data(as_text=True))
        with app_module.app.app_context():
            self.assertEqual(FlashcardSet.query.count(), 1)
            self.assertEqual(Flashcard.query.count(), 10)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_flashcard_rate_limit_shows_shared_error_page(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.side_effect = Exception("HTTP 429 rate limit exceeded")
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Plants",
                "Plant notes.",
                {},
                ["Q1"],
            )

        response = self.client.get(f"/flashcards/{lesson_id}")

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Rate Limit Reached", page)
        self.assertIn("The free Gemini API allows only a limited number of requests per minute.", page)
        self.assertNotIn("flashcard service is unavailable", page.lower())

    @patch.object(app_module, "generate_content_with_fallback")
    def test_flashcard_permissions_require_lesson_owner(self, generate_content):
        self.register_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Plants",
                "Plant notes.",
                {},
                ["Q1"],
            )
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")

        response = self.client.get(f"/flashcards/{lesson_id}")

        self.assertEqual(response.status_code, 404)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_flashcard_status_updates_are_owner_scoped(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.flashcard_response(10)
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Plants",
                "Plant notes.",
                {},
                ["Q1"],
            )
        self.client.get(f"/flashcards/{lesson_id}")
        with app_module.app.app_context():
            card_id = Flashcard.query.first().id

        response = self.client.post(
            f"/api/flashcards/{card_id}/status",
            json={"status": "mastered"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["mastered"])
        with app_module.app.app_context():
            card = db.session.get(Flashcard, card_id)
            self.assertTrue(card.mastered)
            self.assertFalse(card.needs_revision)
            self.assertEqual(card.review_count, 1)

        self.client.get("/logout")
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")
        forbidden_response = self.client.post(
            f"/api/flashcards/{card_id}/status",
            json={"status": "needs_revision"},
        )
        self.assertEqual(forbidden_response.status_code, 404)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_learning_history_and_dashboard_show_flashcards(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = self.flashcard_response(10)
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Plants",
                "Plant notes.",
                {},
                ["Q1"],
            )
        self.client.get(f"/flashcards/{lesson_id}")

        history_response = self.client.get("/learning-history")
        dashboard_response = self.client.get("/dashboard")

        self.assertIn("Open Flashcards", history_response.get_data(as_text=True))
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Flashcards Studied", dashboard_page)
        self.assertIn("<strong>10</strong>", dashboard_page)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_memory_match_loads_existing_flashcards_without_gemini(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=8)

        response = self.client.get(f"/memory-match/{lesson_id}?difficulty=easy")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Memory Challenge", page)
        self.assertIn("No new AI content is generated.", page)
        self.assertIn("Concept 1", page)
        self.assertIn("Explanation 1", page)
        self.assertIn("Open Flashcards", page)
        self.assertNotIn("Concept 7", page)
        generate_content.assert_not_called()

    def test_notes_page_memory_challenge_card_uses_existing_flashcards(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=8)

        response = self.client.get(f"/notes/{lesson_id}")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Memory Challenge", page)
        self.assertIn("Play Memory Challenge", page)
        self.assertIn(f'href="/memory-challenge/{lesson_id}?next=/notes/{lesson_id}"', page)
        self.assertIn("Play Challenge", page)

    def test_memory_match_pair_generation_shuffles_and_limits_cards(self):
        self.register_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=12)
            flashcard_set = FlashcardSet.query.filter_by(learning_history_id=lesson_id).first()
            cards = app_module.get_flashcards_for_set(flashcard_set.id, 1)

            easy_cards = app_module.build_memory_match_cards(cards, "easy", shuffle=False)
            hard_cards = app_module.build_memory_match_cards(cards, "hard", shuffle=False)
            with patch("app.random.shuffle") as shuffle:
                app_module.build_memory_match_cards(cards, "medium")

        self.assertEqual(len(easy_cards), 12)
        self.assertEqual(len({card["pairId"] for card in easy_cards}), 6)
        self.assertEqual(len(hard_cards), 24)
        self.assertEqual(len({card["pairId"] for card in hard_cards}), 12)
        shuffle.assert_called_once()

    def test_memory_match_statistics_calculation(self):
        self.assertEqual(app_module.calculate_memory_accuracy(6, 8), 75.0)
        self.assertEqual(app_module.calculate_memory_accuracy(0, 0), 0.0)
        self.assertEqual(app_module.calculate_memory_xp("easy", 75.0), 15)
        self.assertEqual(app_module.calculate_memory_xp("medium", 75.0), 25)
        self.assertEqual(app_module.calculate_memory_xp("hard", 75.0), 40)
        self.assertEqual(app_module.calculate_memory_xp("hard", 100.0, highest_combo=6, pair_count=6), 60)
        self.assertEqual(app_module.format_duration(75), "1:15")

    @patch.object(app_module, "generate_content_with_fallback")
    def test_memory_match_completion_awards_xp_updates_achievements_and_dashboard(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=10)

        response = self.client.post(
            f"/api/memory-match/{lesson_id}/complete",
            json={
                "difficulty": "medium",
                "elapsed_seconds": 42,
                "moves": 12,
                "matched_pairs": 10,
                "highest_combo": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["time"], "0:42")
        self.assertEqual(payload["accuracy"], 83.3)
        self.assertEqual(payload["moves"], 12)
        self.assertEqual(payload["best_combo"], 5)
        self.assertEqual(payload["xp_earned"], 33)
        self.assertIn("Memory Matcher", payload["newly_unlocked_badges"])
        self.assertIn("Memory Master", payload["newly_unlocked_badges"])
        self.assertIn("Memory Beginner", payload["newly_unlocked_badges"])
        self.assertIn("Speed Solver", payload["newly_unlocked_badges"])
        self.assertIn("Streak Champion", payload["newly_unlocked_badges"])
        generate_content.assert_not_called()
        with app_module.app.app_context():
            challenge = MemoryChallenge.query.one()
            self.assertIsInstance(challenge, MemoryChallengeSession)
            self.assertEqual(challenge.user_id, 1)
            self.assertEqual(challenge.lesson_id, lesson_id)
            self.assertEqual(challenge.difficulty, "medium")
            self.assertEqual(challenge.games_played, 1)
            self.assertEqual(challenge.best_time, 42)
            self.assertEqual(challenge.moves, 12)
            self.assertEqual(challenge.best_moves, 12)
            self.assertEqual(challenge.accuracy, 83.3)
            self.assertEqual(challenge.best_accuracy, 83.3)
            self.assertEqual(challenge.highest_combo, 5)
            self.assertEqual(challenge.xp_earned, 33)
            summary = app_module.get_gamification_summary(1)
            self.assertEqual(summary["counts"]["memory_match"], 1)
            self.assertEqual(summary["memory_xp"], 33)
            self.assertEqual(summary["total_xp"], 58)

        dashboard_response = self.client.get("/dashboard")
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn("Memory Challenge", dashboard_page)
        self.assertIn("Completed 1 time", dashboard_page)
        self.assertIn("Best 0:42", dashboard_page)
        self.assertIn("Avg 83.3%", dashboard_page)
        self.assertIn("33 XP", dashboard_page)

        profile_response = self.client.get("/profile")
        profile_page = profile_response.get_data(as_text=True)
        self.assertIn("Best Difficulty", profile_page)
        self.assertIn("Best Combo", profile_page)
        self.assertIn("Games Won", profile_page)

    def test_memory_challenge_alias_and_js_module_are_available(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=6)

        response = self.client.get(f"/memory-challenge/{lesson_id}")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI Memory Challenge", page)
        self.assertIn("js/memory_challenge.js", page)
        self.assertIn("/api/memory-challenge/", page)

    def test_memory_match_completion_is_user_isolated(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = self.create_saved_flashcards(count=6)
        self.client.get("/logout")
        self.register_user(username="other", email="other@example.com")
        self.login_user(identifier="other")

        page_response = self.client.get(f"/memory-match/{lesson_id}")
        complete_response = self.client.post(
            f"/api/memory-match/{lesson_id}/complete",
            json={
                "difficulty": "easy",
                "elapsed_seconds": 30,
                "moves": 6,
                "matched_pairs": 6,
            },
        )

        self.assertEqual(page_response.status_code, 404)
        self.assertEqual(complete_response.status_code, 404)
        with app_module.app.app_context():
            self.assertEqual(MemoryChallenge.query.count(), 0)

    @patch.object(app_module.model, "generate_content")
    def test_logged_in_learn_autosaves_learning_session(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Quick Revision
- Plants need light.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("AI Memory Challenge", page)
        self.assertIn("Flashcards required first.", page)
        self.assertIn("Generate Flashcards", page)
        with app_module.app.app_context():
            row = LearningSession.query.first()

        self.assertEqual((row.user_id, row.subject, row.topic), (1, "Biology", "Plants"))

        with app_module.app.app_context():
            history_row = LearningHistory.query.first()

        self.assertEqual(
            (history_row.user_id, history_row.subject, history_row.book_name, history_row.topic),
            (1, "Biology", "", "Plants"),
        )
        with app_module.app.app_context():
            self.assertEqual(FlashcardSet.query.count(), 0)
        self.assertIn("Plant Notes", history_row.notes)
        self.assertIn(f'href="/flashcards/{history_row.id}?next=/notes/{history_row.id}"', page)
        saved_diagram = json.loads(history_row.diagram_data)
        self.assertEqual(saved_diagram["template_key"], "flower")
        self.assertTrue(saved_diagram["available"])
        self.assertIn("What is question one?", history_row.quiz_questions)

        self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )
        with app_module.app.app_context():
            saved_count = LearningHistory.query.count()

        self.assertEqual(saved_count, 1)

    @patch.object(app_module.model, "generate_content")
    def test_start_tutor_uses_saved_lesson_without_calling_ai(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson = LearningHistory(
                user_id=1,
                board="CBSE",
                subject="Science",
                book_name="NCERT",
                topic="Photosynthesis",
                notes="Plants make food using sunlight.",
                diagram_data="{}",
                quiz_questions=json.dumps(self.questions),
            )
            db.session.add(lesson)
            db.session.commit()
            lesson_id = lesson.id

        response = self.client.post(
            "/tutor/start",
            data={
                "lesson_id": lesson_id,
                "name": "Asha",
                "student_class": "8",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        generate_content.assert_not_called()
        page = response.get_data(as_text=True)
        self.assertIn("AI Tutor", page)
        self.assertIn("Photosynthesis", page)
        self.assertIn("Ask anything about this lesson", page)
        self.assertIn("&#127908; Start Listening", page)
        self.assertIn("&#9209; Stop", page)
        self.assertIn("&#128266; Read Response", page)
        self.assertIn("&#128263; Mute", page)
        self.assertIn("Continue to Quiz", page)
        with app_module.app.app_context():
            tutor_lesson = TutorLesson.query.first()

        self.assertIn(f'data-endpoint="/api/tutor/{tutor_lesson.id}/message"', page)
        self.assertEqual(
            (
                tutor_lesson.user_id,
                tutor_lesson.learning_history_id,
                tutor_lesson.student_class,
                tutor_lesson.subject,
                tutor_lesson.chapter,
            ),
            (1, lesson_id, "8", "Science", "Photosynthesis"),
        )

    @patch.object(app_module.model, "generate_content")
    def test_tutor_message_saves_memory_and_reuses_context(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.side_effect = [
            MockResponse("Chlorophyll is the green pigment that helps leaves catch sunlight."),
            MockResponse("More simply, chlorophyll is like a tiny sunlight catcher in leaves."),
        ]
        with app_module.app.app_context():
            lesson = LearningHistory(
                user_id=1,
                subject="Science",
                book_name="NCERT",
                topic="Photosynthesis",
                notes="# Photosynthesis\nChlorophyll helps leaves absorb sunlight.",
                diagram_data="{}",
                quiz_questions=json.dumps(self.questions),
            )
            db.session.add(lesson)
            db.session.commit()
            tutor_lesson = app_module.get_or_create_tutor_lesson(
                1,
                lesson,
                "Asha",
                "8",
            )
            tutor_lesson_id = tutor_lesson.id

        first = self.client.post(
            f"/api/tutor/{tutor_lesson_id}/message",
            json={"message": "Explain chlorophyll."},
        )
        second = self.client.post(
            f"/api/tutor/{tutor_lesson_id}/message",
            json={"message": "Explain it more simply."},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("reply_html", second.get_json())
        prompt = generate_content.call_args.args[0]
        self.assertIn("Class: 8", prompt)
        self.assertIn("Board: CBSE", prompt)
        self.assertIn("Subject: Science", prompt)
        self.assertIn("Textbook: NCERT", prompt)
        self.assertIn("Book: NCERT", prompt)
        self.assertIn("Chapter: Photosynthesis", prompt)
        self.assertIn("Current chapter or lesson: Photosynthesis", prompt)
        self.assertIn("Treat the selected textbook as authoritative", prompt)
        self.assertIn("Answer based on the selected chapter whenever possible.", prompt)
        self.assertIn("Chlorophyll helps leaves absorb sunlight.", prompt)
        self.assertIn("Student: Explain chlorophyll.", prompt)
        self.assertIn("AI Tutor: Chlorophyll is the green pigment", prompt)
        self.assertIn("Student's latest question:\nExplain it more simply.", prompt)
        with app_module.app.app_context():
            messages = TutorMessage.query.order_by(TutorMessage.id.asc()).all()

        self.assertEqual([message.sender for message in messages], ["student", "assistant", "student", "assistant"])

    def test_tutor_voice_script_uses_browser_speech_apis_and_existing_endpoint(self):
        script_path = os.path.join(app_module.app.root_path, "static", "tutor.js")
        with open(script_path, encoding="utf-8") as script_file:
            script = script_file.read()

        self.assertIn("window.SpeechRecognition || window.webkitSpeechRecognition", script)
        self.assertIn("window.speechSynthesis", script)
        self.assertIn("new SpeechSynthesisUtterance", script)
        self.assertIn("fetch(form.dataset.endpoint", script)
        self.assertIn("submitPrompt(finalPrompt)", script)
        self.assertNotIn("/api/gemini", script)

    def test_guest_learning_history_shows_locked_message(self):
        response = self.client.get("/learning-history")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Learning History is available only for registered students.", page)
        self.assertIn("Login", page)
        self.assertIn("Register", page)
        self.assertIn("Continue as Guest", page)

    @patch.object(app_module.model, "generate_content")
    def test_learning_history_lists_and_views_saved_lesson(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Quick Revision
- Plants need light.

## Diagram Data
D1: Seed
D2: Roots
D3: Leaves

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )
        self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Science",
                "book_name": "NCERT",
                "topic": "Plants",
            },
        )

        list_response = self.client.get("/learning-history?search=plants&subject=science&sort=newest")

        self.assertEqual(list_response.status_code, 200)
        list_page = list_response.get_data(as_text=True)
        self.assertIn("Plants", list_page)
        self.assertIn("Science", list_page)
        self.assertIn("NCERT", list_page)
        self.assertIn("Download PDF", list_page)
        self.assertIn("Favourite", list_page)
        self.assertIn("Alphabetically", list_page)
        self.assertIn("Others", list_page)

        detail_response = self.client.get("/learning-history/1")
        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("Plant Notes", detail_page)
        self.assertIn("Quick Revision", detail_page)
        self.assertIn("Educational Diagram", detail_page)
        self.assertIn("No suitable educational diagram found.", detail_page)
        self.assertNotIn("ai-visualization-svg", detail_page)
        self.assertNotIn("Download Diagram", detail_page)
        self.assertIn("What is question one?", detail_page)
        self.assertIn("Generate Study Plan", detail_page)
        self.assertIn("Personalized study plan", detail_page)

        diagram_response = self.client.get("/learning-history/1/diagram/download")
        self.assertEqual(diagram_response.status_code, 404)

    def test_saved_lessons_hide_visualization_buttons_when_not_required(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "English",
                "Grammar",
                "Essay Writing",
                "# Essay Writing\nWrite with structure.",
                {
                    "available": False,
                    "visualization_required": False,
                    "visualization_type": "none",
                    "type": "none",
                    "diagram_type": "none",
                    "title": "Essay Writing Visualization",
                    "nodes": [],
                    "connections": [],
                    "labels": [],
                    "reason": "This lesson is primarily text-based and is better learned through reading and examples.",
                    "confidence": 0.96,
                },
                self.questions,
            )

        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        list_response = self.client.get("/learning-history")
        download_response = self.client.get(f"/learning-history/{lesson_id}/diagram/download")

        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("AI Visualization", detail_page)
        self.assertIn("This lesson is primarily text-based and does not require a visual diagram.", detail_page)
        self.assertNotIn("Download Diagram", detail_page)
        self.assertNotIn("Open Visualization", detail_page)
        self.assertNotIn("Generate Visualization", detail_page)
        self.assertNotIn("data:image/svg+xml", detail_page)
        self.assertEqual(list_response.status_code, 200)
        self.assertNotIn("Open Visualization", list_response.get_data(as_text=True))
        self.assertEqual(download_response.status_code, 404)

    def test_saved_lesson_renders_cached_diagram_attribution_download_and_pdf(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Biology",
                "NCERT",
                "Photosynthesis",
                "# Photosynthesis\nPlants make food.",
                {
                    "available": True,
                    "visualization_required": True,
                    "visualization_type": "biology_process",
                    "type": "scientific_process",
                    "title": "Photosynthesis",
                    "nodes": [{"id": "1", "label": "Sunlight"}],
                    "connections": [],
                    "labels": ["Sunlight"],
                    "reason": "This biological process is easier to understand visually.",
                    "confidence": 0.96,
                },
                self.questions,
            )
        self.seed_cached_diagram(
            lesson_id=lesson_id,
            subject="Biology",
            topic="Photosynthesis",
            filename="saved-lesson-diagram.png",
            author="Diagram Author",
            license_text="CC BY-SA 4.0",
        )

        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        download_response = self.client.get(f"/learning-history/{lesson_id}/diagram/download")
        pdf_response = self.client.get(f"/learning-history/{lesson_id}/download")

        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("Educational Diagram", detail_page)
        self.assertIn('class="diagram-library-image"', detail_page)
        self.assertIn("Diagram Source", detail_page)
        self.assertIn("Diagram Author", detail_page)
        self.assertIn("CC BY-SA 4.0", detail_page)
        self.assertNotIn("ai-visualization-svg", detail_page)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.mimetype, "image/png")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF"))
        self.assertIn(b"Diagram Author", pdf_response.data)
        self.assertIn(b"CC BY-SA 4.0", pdf_response.data)

    @patch.object(app_module, "generate_content_with_fallback")
    def test_diagram_explanation_generates_once_and_reuses_saved_json(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Biology",
                "NCERT",
                "Mitosis",
                "# Mitosis\nCells divide.",
                {
                    "available": True,
                    "visualization_required": True,
                    "visualization_type": "biology_process",
                    "type": "scientific_process",
                    "title": "Stages of Mitosis",
                    "labels": ["Prophase", "Metaphase", "Anaphase", "Telophase"],
                    "reason": "Stages are easier to understand visually.",
                    "confidence": 0.95,
                },
                self.questions,
            )
        self.seed_cached_diagram(
            lesson_id=lesson_id,
            subject="Biology",
            topic="Mitosis",
            filename="mitosis-explanation.png",
        )
        generate_content.return_value = MockResponse(
            json.dumps(
                {
                    "summary": "This diagram shows the main stages of mitosis.",
                    "steps": [{"title": "Prophase", "body": "Chromosomes condense."}],
                    "labels": [{"title": "Chromosome", "body": "Stores genetic information."}],
                    "key_points": [
                        "Mitosis helps growth.",
                        "It makes two daughter cells.",
                        "DNA is copied before division.",
                        "The chromosome number remains same.",
                    ],
                    "exam_tip": "Remember PMAT for the order of stages.",
                    "related_topics": ["Meiosis", "Cell Cycle", "Chromosomes"],
                }
            )
        )

        first_response = self.client.get(f"/learning-history/{lesson_id}/diagram-explanation")
        second_response = self.client.get(f"/learning-history/{lesson_id}/diagram-explanation")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(first_response.get_json()["cached"])
        self.assertTrue(second_response.get_json()["cached"])
        self.assertEqual(generate_content.call_count, 1)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Board: CBSE", prompt)
        self.assertIn("Textbook: NCERT", prompt)
        self.assertIn("Chapter: Mitosis", prompt)
        self.assertIn("Use simple NCERT textbook language.", prompt)
        self.assertIn("Do not use OCR", prompt)
        self.assertIn("Diagram metadata", prompt)
        with app_module.app.app_context():
            lesson = db.session.get(LearningHistory, lesson_id)
            saved_explanation = json.loads(lesson.diagram_explanation)
        self.assertEqual(saved_explanation["exam_tip"], "Remember PMAT for the order of stages.")

    @patch.object(app_module, "generate_content_with_fallback")
    def test_saved_lesson_renders_cached_diagram_explanation_payload(self, generate_content):
        self.register_user()
        self.login_user()
        cached_explanation = {
            "summary": "This diagram explains photosynthesis in simple textbook language.",
            "steps": [{"title": "Sunlight", "body": "Light energy helps leaves make food."}],
            "labels": [{"title": "Leaf", "body": "The main site of photosynthesis."}],
            "key_points": ["Plants make food.", "Oxygen is released."],
            "exam_tip": "Write the word equation clearly.",
            "related_topics": ["Plant Cell", "Stomata"],
        }
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Biology",
                "NCERT",
                "Photosynthesis",
                "# Photosynthesis\nPlants make food.",
                {
                    "available": True,
                    "visualization_required": True,
                    "visualization_type": "biology_process",
                    "type": "scientific_process",
                    "title": "Photosynthesis",
                    "labels": ["Leaf", "Sunlight"],
                    "reason": "This biological process is easier to understand visually.",
                    "confidence": 0.96,
                },
                self.questions,
            )
            lesson = db.session.get(LearningHistory, lesson_id)
            lesson.diagram_explanation = json.dumps(cached_explanation)
            db.session.commit()
        self.seed_cached_diagram(
            lesson_id=lesson_id,
            subject="Biology",
            topic="Photosynthesis",
            filename="photosynthesis-explanation.png",
        )

        detail_response = self.client.get(f"/learning-history/{lesson_id}")

        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("data-diagram-explanation-panel", detail_page)
        self.assertIn("data-diagram-explanation-json", detail_page)
        self.assertIn("This diagram explains photosynthesis", detail_page)
        self.assertIn('data-lesson-subject="Biology"', detail_page)
        generate_content.assert_not_called()

    @patch.object(app_module, "generate_content_with_fallback")
    def test_ncert_diagram_view_download_and_explanation_continue_working(self, generate_content):
        self.register_user()
        self.login_user()
        self.write_ncert_diagram("biology", "mitochondria.png")
        generate_content.return_value = MockResponse(
            json.dumps(
                {
                    "summary": "This diagram shows mitochondria as cell organelles.",
                    "steps": [{"title": "Outer membrane", "body": "It covers the organelle."}],
                    "labels": [{"title": "Mitochondria", "body": "They help release energy."}],
                    "key_points": ["Mitochondria are found in cells."],
                    "exam_tip": "Remember mitochondria as the powerhouse of the cell.",
                    "related_topics": ["Cell Organelles", "Respiration"],
                }
            )
        )

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Biology",
                "NCERT",
                "Mitochondria",
                "# Mitochondria\nThey release energy.",
                {
                    "available": True,
                    "visualization_required": True,
                    "visualization_type": "cell_diagram",
                    "type": "cell",
                    "title": "Mitochondria",
                    "labels": ["Outer membrane", "Matrix"],
                    "confidence": 0.95,
                },
                self.questions,
            )
            diagram = get_or_create_diagram(
                lesson_id=lesson_id,
                subject="Biology",
                topic="Mitochondria",
                static_folder=app_module.app.static_folder,
                provider_registry=ProviderRegistry([NcertProvider(static_folder=app_module.app.static_folder)]),
            )

        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        download_response = self.client.get(f"/learning-history/{lesson_id}/diagram/download")
        explanation_response = self.client.get(f"/learning-history/{lesson_id}/diagram-explanation")

        self.assertIsNotNone(diagram)
        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("NCERT Textbook Diagrams", detail_page)
        self.assertIn('class="diagram-library-image"', detail_page)
        self.assertIn("Download PNG", detail_page)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.mimetype, "image/png")
        self.assertEqual(explanation_response.status_code, 200)
        self.assertIn("Mitochondria", generate_content.call_args.args[0])
        self.assertIn("NCERT Textbook Diagrams", generate_content.call_args.args[0])

    @patch.object(app_module.model, "generate_content")
    def test_existing_visualization_records_continue_working(self, generate_content):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "NCERT",
                "Photosynthesis",
                "# Photosynthesis\nPlants make food.",
                {
                    "type": "process",
                    "title": "Photosynthesis",
                    "nodes": [
                        {"id": "1", "label": "Sunlight"},
                        {"id": "2", "label": "Water"},
                        {"id": "3", "label": "Glucose"},
                    ],
                    "connections": [["1", "3"], ["2", "3"]],
                },
                self.questions,
            )
        self.seed_cached_diagram(
            lesson_id=lesson_id,
            subject="Science",
            topic="Photosynthesis",
            filename="existing-visualization.png",
        )

        detail_response = self.client.get(f"/learning-history/{lesson_id}")
        diagram_response = self.client.get(f"/learning-history/{lesson_id}/diagram/download")

        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("Educational Diagram", detail_page)
        self.assertIn("Download PNG", detail_page)
        self.assertIn('class="diagram-library-image"', detail_page)
        self.assertNotIn("ai-visualization-svg", detail_page)
        self.assertEqual(diagram_response.status_code, 200)
        self.assertEqual(diagram_response.mimetype, "image/png")
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_saved_lesson_views_do_not_call_gemini_after_first_generation(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Photosynthesis
Plants make food using sunlight.

## Quick Revision
- Leaves use sunlight.

## Visualization Decision JSON
{"visualization_required": true, "visualization_type": "biology_process", "confidence": 0.96}

## Diagram JSON
{"type":"scientific_process","title":"Photosynthesis","nodes":[{"id":"1","label":"Sunlight"},{"id":"2","label":"Water"},{"id":"3","label":"Glucose"}],"connections":[["1","3"],["2","3"]],"reason":"This biological process is easier to understand visually.","confidence":0.96}

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )
        self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Photosynthesis",
            },
        )
        self.assertEqual(generate_content.call_count, 1)
        generate_content.reset_mock()

        self.client.get("/learning-history")
        self.client.get("/learning-history/1")
        self.client.get("/notes/1")
        self.client.get("/learning-history/1/diagram/download")

        generate_content.assert_not_called()

    def test_learning_history_filters_and_sorts_saved_lessons(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            app_module.save_learning_history(1, "Science", "NCERT", "Zebra Topic", "Notes", [], ["Q1"])
            app_module.save_learning_history(1, "History", "Reference", "Ancient Cities", "Notes", [], ["Q1"])
            app_module.save_learning_history(1, "Mathematics", "NCERT", "Algebra", "Notes", [], ["Q1"])

        alphabetical_response = self.client.get("/learning-history?sort=alphabetical")
        alphabetical_page = alphabetical_response.get_data(as_text=True)
        self.assertLess(alphabetical_page.index("Algebra"), alphabetical_page.index("Ancient Cities"))
        self.assertLess(alphabetical_page.index("Ancient Cities"), alphabetical_page.index("Zebra Topic"))

        others_response = self.client.get("/learning-history?subject=others")
        others_page = others_response.get_data(as_text=True)
        self.assertIn("Ancient Cities", others_page)
        self.assertNotIn("Zebra Topic", others_page)
        self.assertNotIn("Algebra", others_page)

    @patch.object(app_module.model, "generate_content")
    def test_learning_history_download_and_delete(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )
        self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Science",
                "topic": "Plants",
            },
        )

        download_response = self.client.get("/learning-history/1/download")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.mimetype, "application/pdf")
        self.assertTrue(download_response.data.startswith(b"%PDF"))

        delete_response = self.client.post("/learning-history/1/delete", follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn("No saved lessons yet", delete_response.get_data(as_text=True))

    def test_learning_history_pdf_contains_textbook_metadata(self):
        self.register_user(extra_data={"student_class": "10"})
        self.login_user()
        with app_module.app.app_context():
            seed_cbse_textbook_catalog(db.session)
            textbook = Textbook.query.filter_by(class_level=10, name="First Flight").first()
            chapter = Chapter.query.filter_by(textbook_id=textbook.id, title="A Letter to God").first()
            lesson_id = app_module.save_learning_history(
                1,
                "English",
                textbook.name,
                chapter.title,
                "# A Letter to God\nLencho writes a letter.",
                {"available": False},
                self.questions,
                board=textbook.board,
                textbook_id=textbook.id,
                chapter_id=chapter.id,
            )

        response = self.client.get(f"/learning-history/{lesson_id}/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(b"Board: CBSE", response.data)
        self.assertIn(b"Textbook: First Flight", response.data)
        self.assertIn(b"Chapter: A Letter to God", response.data)

    @patch.object(app_module.model, "generate_content")
    def test_dashboard_topics_studied_counts_learning_history(self, generate_content):
        self.register_user()
        self.login_user()
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants use sunlight.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
        )
        self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Science",
                "topic": "Plants",
            },
        )

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Topics Studied", page)
        self.assertIn("<strong>1</strong>", page)

    def test_performance_requires_login(self):
        response = self.client.get("/performance")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/performance", response.headers["Location"])

    def test_performance_empty_state_for_new_user(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/performance")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Performance Analytics", page)
        self.assertIn("Performance Summary", page)
        self.assertIn("Not enough data yet.", page)
        self.assertIn("No quiz scores yet.", page)
        self.assertIn("No studied topics yet.", page)
        self.assertIn("No activity yet.", page)

    def test_performance_shows_only_current_user_analytics(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            app_module.create_user(
                "Other Student",
                "otherstudent",
                "other@example.com",
                "8",
                "password123",
            )

            first_date = app_module.datetime(2026, 6, 17, 10, 0, tzinfo=app_module.timezone.utc)
            second_date = app_module.datetime(2026, 6, 18, 10, 0, tzinfo=app_module.timezone.utc)
            third_date = app_module.datetime(2026, 6, 19, 10, 0, tzinfo=app_module.timezone.utc)

            db.session.add_all(
                [
                    LearningHistory(
                        user_id=1,
                        subject="Science",
                        book_name="NCERT",
                        topic="Plants",
                        notes="Notes",
                        diagram_data="{}",
                        quiz_questions="[]",
                        created_at=first_date,
                    ),
                    LearningHistory(
                        user_id=1,
                        subject="Science",
                        book_name="NCERT",
                        topic="Light",
                        notes="Notes",
                        diagram_data="{}",
                        quiz_questions="[]",
                        created_at=second_date,
                    ),
                    LearningHistory(
                        user_id=1,
                        subject="Mathematics",
                        book_name="NCERT",
                        topic="Algebra",
                        notes="Notes",
                        diagram_data="{}",
                        quiz_questions="[]",
                        created_at=third_date,
                    ),
                    LearningHistory(
                        user_id=2,
                        subject="Geography",
                        book_name="Atlas",
                        topic="Maps",
                        notes="Other notes",
                        diagram_data="{}",
                        quiz_questions="[]",
                        created_at=third_date,
                    ),
                    LearningSession(
                        user_id=1,
                        name="Asha",
                        student_class="8",
                        subject="Science",
                        book_name="NCERT",
                        topic="Plants",
                        notes="Notes",
                        created_at=first_date,
                    ),
                    LearningSession(
                        user_id=1,
                        name="Asha",
                        student_class="8",
                        subject="Mathematics",
                        book_name="NCERT",
                        topic="Algebra",
                        notes="Notes",
                        created_at=third_date,
                    ),
                ]
            )
            db.session.commit()
            db.session.add_all(
                [
                    FlashcardSet(user_id=1, learning_history_id=1, created_at=third_date),
                    RevisionSheet(
                        user_id=1,
                        learning_history_id=1,
                        content_markdown="# Plants",
                        created_at=third_date,
                    ),
                    MindMap(
                        user_id=1,
                        learning_history_id=2,
                        map_json="{}",
                        created_at=third_date,
                    ),
                    ImportantQuestionSet(
                        user_id=1,
                        learning_history_id=3,
                        markdown="# Important Questions",
                        created_at=third_date,
                    ),
                    TutorLesson(
                        user_id=1,
                        learning_history_id=1,
                        name="Asha",
                        student_class="8",
                        subject="Science",
                        chapter="Plants",
                        created_at=third_date,
                    ),
                ]
            )
            db.session.flush()
            flashcard_set = FlashcardSet.query.filter_by(user_id=1).first()
            db.session.add_all(
                [
                    Flashcard(
                        flashcard_set_id=flashcard_set.id,
                        user_id=1,
                        learning_history_id=1,
                        position=1,
                        front="Front 1",
                        back="Back 1",
                        mastered=True,
                    ),
                    Flashcard(
                        flashcard_set_id=flashcard_set.id,
                        user_id=1,
                        learning_history_id=1,
                        position=2,
                        front="Front 2",
                        back="Back 2",
                        mastered=True,
                    ),
                    Flashcard(
                        flashcard_set_id=flashcard_set.id,
                        user_id=1,
                        learning_history_id=1,
                        position=3,
                        front="Front 3",
                        back="Back 3",
                        mastered=False,
                    ),
                ]
            )
            db.session.commit()

            app_module.save_quiz_history(
                "Asha",
                "8",
                "Science",
                "Plants",
                "8/10",
                "A",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=1,
            )
            app_module.save_quiz_history(
                "Asha",
                "8",
                "Science",
                "Light",
                "6/10",
                "B",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=1,
            )
            app_module.save_quiz_history(
                "Asha",
                "8",
                "Mathematics",
                "Algebra",
                "9/10",
                "A+",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=1,
            )
            app_module.save_quiz_history(
                "Other Student",
                "8",
                "Geography",
                "Maps",
                "10/10",
                "A+",
                ["Q1"],
                ["A1"],
                "{}",
                user_id=2,
            )

        response = self.client.get("/performance")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Average Score", page)
        self.assertIn("76.7%", page)
        self.assertIn("Overall Progress", page)
        self.assertIn("Subjects Studied", page)
        self.assertIn("Topics Studied", page)
        self.assertIn("Study Streak", page)
        self.assertIn("Flashcards Completed", page)
        self.assertIn("Revision Sheets", page)
        self.assertIn("Mind Maps", page)
        self.assertIn("Tutor Sessions", page)
        self.assertIn("Important Question Sets", page)
        self.assertIn("Highest Score", page)
        self.assertIn("90%", page)
        self.assertIn("Lowest Score", page)
        self.assertIn("60%", page)
        self.assertIn("Mathematics is currently your strongest subject.", page)
        self.assertIn("Science needs more practice.", page)
        self.assertIn("You have completed 2 flashcards.", page)
        self.assertIn("You are studying consistently.", page)
        self.assertIn("Total Learning Sessions", page)
        self.assertIn("Average Score by Subject", page)
        self.assertIn("Quiz Scores Over Time", page)
        self.assertIn("Learning Activity Timeline", page)
        self.assertIn("Learning Tools Completed", page)
        self.assertIn("Recent Progress", page)
        self.assertIn("Recent quiz average: 76.7%", page)
        self.assertIn("Plants", page)
        self.assertIn("Algebra", page)
        self.assertNotIn("Geography", page)
        self.assertNotIn("Geography &bull; Maps", page)

    @patch.object(app_module.model, "generate_content")
    def test_performance_analytics_does_not_call_gemini(self, generate_content):
        self.register_user()
        self.login_user()

        response = self.client.get("/performance")

        self.assertEqual(response.status_code, 200)
        generate_content.assert_not_called()

    def test_logged_in_download_pdf_autosaves_file(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            "/download_pdf",
            data={
                "name": "Asha",
                "subject": "Biology",
                "topic": "Plants",
                "score": "8/10",
                "grade": "A",
                "report_text": "# Performance Summary\nScore: 8/10\nGrade: A",
            },
        )

        self.assertEqual(response.status_code, 200)
        with app_module.app.app_context():
            row = DownloadedFile.query.first()

        self.assertEqual(
            (row.user_id, row.file_type, row.subject, row.topic, row.score, row.grade),
            (1, "performance_report", "Biology", "Plants", "8/10", "A"),
        )

    def test_downloaded_reports_empty_state_uses_download_center(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/downloaded-reports")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Download Center", page)
        self.assertIn("No downloaded reports yet.", page)
        self.assertIn(
            "Generate notes, revision sheets, quizzes, or performance reports and they will appear here.",
            page,
        )
        self.assertIn("page-transition-overlay", page)
        self.assertNotIn("Downloaded reports coming soon", page)

    def test_downloaded_reports_lists_existing_downloads_from_database(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            app_module.save_downloaded_file(1, "performance_report", "Science", "Plants", "8/10", "A")

        response = self.client.get("/downloaded-reports")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Plants Performance Report", page)
        self.assertIn("Performance Report", page)
        self.assertIn("Science", page)
        self.assertIn("8/10", page)
        self.assertIn("Download</a>", page)
        self.assertIn("Delete</button>", page)
        self.assertNotIn("No downloaded reports yet.", page)

    def test_downloaded_report_download_reconstructs_saved_lesson_pdf(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "Biology",
                "Photosynthesis",
                "# Notes\nPlants make food.",
                {"available": False},
                ["What do plants make?"],
            )
            download_id = app_module.save_downloaded_file(
                1,
                "saved_lesson",
                "Science",
                "Photosynthesis",
            )
            before_count = DownloadedFile.query.count()

        response = self.client.get(f"/downloaded-reports/{download_id}/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(
            "attachment; filename=Photosynthesis_notes.pdf",
            response.headers["Content-Disposition"],
        )
        self.assertTrue(response.data.startswith(b"%PDF"))
        with app_module.app.app_context():
            self.assertIsNotNone(db.session.get(LearningHistory, lesson_id))
            self.assertEqual(DownloadedFile.query.count(), before_count)

    def test_downloaded_report_delete_only_removes_download_history_row(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "Biology",
                "Photosynthesis",
                "Plants make food.",
                {"available": False},
                ["What do plants make?"],
            )
            download_id = app_module.save_downloaded_file(
                1,
                "saved_lesson",
                "Science",
                "Photosynthesis",
            )

        response = self.client.post(
            f"/downloaded-reports/{download_id}/delete",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Downloaded report removed from your download center.", page)
        self.assertIn("No downloaded reports yet.", page)
        with app_module.app.app_context():
            self.assertIsNone(db.session.get(DownloadedFile, download_id))
            self.assertIsNotNone(db.session.get(LearningHistory, lesson_id))

    def test_favourite_notes_empty_state_replaces_placeholder(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/favourite-notes")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Favourite Notes", page)
        self.assertIn("No favourite notes yet", page)
        self.assertIn(
            "Save your favourite AI-generated lessons for quick access later.",
            page,
        )
        self.assertIn("Start Learning", page)
        self.assertIn("page-transition-overlay", page)
        self.assertNotIn("Favourite notes coming soon", page)

    def test_favourite_toggle_persists_after_logout_and_login(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "Biology",
                "Photosynthesis",
                "Plants make food.",
                {"available": False},
                ["What do plants make?"],
            )

        response = self.client.post(
            f"/learning-history/{lesson_id}/favourite",
            data={"next": f"/notes/{lesson_id}"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Added to Favourite Notes.", page)
        self.assertIn("Saved Favourite", page)
        with app_module.app.app_context():
            self.assertEqual(FavouriteNote.query.count(), 1)

        self.client.get("/logout")
        self.login_user()
        response = self.client.get("/favourite-notes")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Photosynthesis", page)
        self.assertIn("Open Lesson", page)
        self.assertIn("Download PDF", page)

    def test_favourite_notes_lists_saved_lessons_as_cards(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "Biology",
                "Photosynthesis",
                "# Notes\nPlants make food.",
                {"available": False},
                ["What do plants make?"],
            )
            db.session.add(FavouriteNote(user_id=1, learning_history_id=lesson_id))
            db.session.commit()

        response = self.client.get("/favourite-notes")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("favourite-note-card", page)
        self.assertIn("Photosynthesis", page)
        self.assertIn("Subject", page)
        self.assertIn("Science", page)
        self.assertIn("Class", page)
        self.assertIn(">8<", page)
        self.assertIn("Date saved", page)
        self.assertIn(f'href="/notes/{lesson_id}"', page)
        self.assertIn(f'href="/learning-history/{lesson_id}/download"', page)
        self.assertIn("Remove from Favourites", page)
        self.assertNotIn("No favourite notes yet", page)

    def test_remove_from_favourites_keeps_saved_lesson(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            lesson_id = app_module.save_learning_history(
                1,
                "Science",
                "Biology",
                "Photosynthesis",
                "Plants make food.",
                {"available": False},
                ["What do plants make?"],
            )
            favourite = FavouriteNote(user_id=1, learning_history_id=lesson_id)
            db.session.add(favourite)
            db.session.commit()

        response = self.client.post(
            f"/learning-history/{lesson_id}/favourite",
            data={"next": "/favourite-notes"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Removed from Favourite Notes.", page)
        self.assertIn("No favourite notes yet", page)
        with app_module.app.app_context():
            self.assertEqual(FavouriteNote.query.count(), 0)
            self.assertIsNotNone(db.session.get(LearningHistory, lesson_id))

    def test_favourite_toggle_requires_lesson_owner(self):
        self.register_user()
        self.login_user()

        with app_module.app.app_context():
            app_module.create_user(
                "Other Student",
                "otherstudent",
                "other@example.com",
                "8",
                "password123",
            )
            lesson_id = app_module.save_learning_history(
                2,
                "Science",
                "Biology",
                "Other Photosynthesis",
                "Other notes.",
                {"available": False},
                ["Question?"],
            )

        response = self.client.post(f"/learning-history/{lesson_id}/favourite")

        self.assertEqual(response.status_code, 404)
        with app_module.app.app_context():
            self.assertEqual(FavouriteNote.query.count(), 0)

    def test_profile_page_shows_account_and_gamification_sections(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Full Name", page)
        self.assertIn("Asha Student", page)
        self.assertIn("Username", page)
        self.assertIn("asha", page)
        self.assertIn("Email", page)
        self.assertIn("asha@example.com", page)
        self.assertIn("Class 8", page)
        self.assertIn("Role", page)
        self.assertIn("Student", page)
        self.assertIn("role-student", page)
        self.assertIn("Account Created", page)
        self.assertIn("Gamification", page)
        self.assertIn("Level 1 &middot; 0 XP", page)
        self.assertIn("Study Streak", page)
        self.assertIn("Badges Unlocked", page)
        self.assertIn("XP Rookie", page)
        self.assertIn("Edit Profile", page)

    def test_settings_profile_update_changes_account_fields(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            "/settings",
            data={
                "action": "profile",
                "full_name": "Asha Updated",
                "username": "asha_updated",
                "email": "asha.updated@example.com",
                "student_class": "9",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Settings updated successfully.", response.get_data(as_text=True))
        with app_module.app.app_context():
            row = User.query.filter_by(username="asha_updated").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.full_name, "Asha Updated")
            self.assertEqual(row.email, "asha.updated@example.com")
            self.assertEqual(row.student_class, "9")

    def test_settings_password_change_requires_current_password_and_updates_hash(self):
        self.register_user()
        self.login_user()

        bad_response = self.client.post(
            "/settings",
            data={
                "action": "password",
                "current_password": "wrong-password",
                "new_password": "newpassword123",
                "confirm_password": "newpassword123",
            },
        )
        self.assertEqual(bad_response.status_code, 400)
        self.assertIn("Current password is incorrect.", bad_response.get_data(as_text=True))

        good_response = self.client.post(
            "/settings",
            data={
                "action": "password",
                "current_password": "password123",
                "new_password": "newpassword123",
                "confirm_password": "newpassword123",
            },
            follow_redirects=True,
        )

        self.assertEqual(good_response.status_code, 200)
        self.client.get("/logout")
        old_login = self.login_user(password="password123")
        self.assertEqual(old_login.status_code, 401)
        new_login = self.login_user(password="newpassword123")
        self.assertEqual(new_login.status_code, 302)

    def test_settings_appearance_controls_theme_across_pages(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            "/settings",
            data={
                "action": "appearance",
                "theme_preference": "dark",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Settings updated successfully.", response.get_data(as_text=True))
        with app_module.app.app_context():
            row = User.query.filter_by(username="asha").first()
            self.assertEqual(row.theme_preference, "dark")

        dashboard_response = self.client.get("/dashboard")
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_page = dashboard_response.get_data(as_text=True)
        self.assertIn('<body class="dashboard-page dark-mode', dashboard_page)
        self.assertNotIn("theme-toggle", dashboard_page)
        self.assertNotIn("toggleTheme()", dashboard_page)

    @patch.object(app_module.model, "generate_content")
    def test_settings_preferences_are_saved_and_used_for_future_ai_requests(self, generate_content):
        generate_content.return_value = MockResponse(
            """# Plant Notes
Plants make food.

## Quick Revision
- Plants need sunlight.

## Diagram JSON
{"diagram_type": "none", "title": "", "labels": [], "arrows": [], "notes": []}

## Questions
Q1. What do plants need?

Q2. What do plants make?

Q3. Why is sunlight useful?

Q4. Name one plant part.

Q5. What is photosynthesis?
"""
        )
        self.register_user()
        self.login_user()

        response = self.client.post(
            "/settings",
            data={
                "action": "ai_preferences",
                "ai_explanation_style": "detailed",
                "default_subject": "Science",
                "default_class": "9",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        learn_response = self.client.post(
            "/learn",
            data={
                "name": "Asha Student",
                "book_name": "",
                "topic": "Photosynthesis",
            },
        )

        self.assertEqual(learn_response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Class: 9", prompt)
        self.assertIn("Subject: Science", prompt)
        self.assertIn("Explanation style: Detailed", prompt)
        with app_module.app.app_context():
            row = User.query.filter_by(username="asha").first()
            self.assertEqual(row.ai_explanation_style, "detailed")
            self.assertEqual(row.default_subject, "Science")
            self.assertEqual(row.default_class, "9")

    def test_settings_permissions_require_login(self):
        settings_response = self.client.get("/settings")
        download_response = self.client.get("/settings/download-data")
        delete_response = self.client.post("/settings/delete-account")

        self.assertEqual(settings_response.status_code, 302)
        self.assertIn("/login?next=/settings", settings_response.headers["Location"])
        self.assertEqual(download_response.status_code, 302)
        self.assertIn("/login?next=/settings/download-data", download_response.headers["Location"])
        self.assertEqual(delete_response.status_code, 302)
        self.assertIn("/login?next=/settings/delete-account", delete_response.headers["Location"])

    def test_delete_account_requires_confirmation_and_removes_user_data(self):
        self.register_user()
        self.login_user()
        with app_module.app.app_context():
            user = User.query.filter_by(username="asha").first()
            user_id = user.id
            app_module.save_learning_history(
                user_id,
                "Science",
                "",
                "Plants",
                "Notes",
                {"available": False},
                ["Q1"],
            )
            app_module.save_learning_session(user_id, "Asha", "8", "Science", "", "Plants", "Notes")
            app_module.save_quiz_history(
                "Asha",
                "8",
                "Science",
                "Plants",
                "5/5",
                "A",
                ["Q1"],
                ["A1"],
                "Report",
                user_id=user_id,
            )
            app_module.save_downloaded_file(user_id, "performance_report", "Science", "Plants")

        blocked_response = self.client.post(
            "/settings/delete-account",
            data={"confirmation": "wrong", "password": "password123"},
            follow_redirects=True,
        )
        self.assertEqual(blocked_response.status_code, 200)
        with app_module.app.app_context():
            self.assertIsNotNone(db.session.get(User, user_id))

        response = self.client.post(
            "/settings/delete-account",
            data={"confirmation": "asha", "password": "password123"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Your account and saved data have been deleted.", response.get_data(as_text=True))
        with app_module.app.app_context():
            self.assertIsNone(db.session.get(User, user_id))
            self.assertEqual(LearningHistory.query.filter_by(user_id=user_id).count(), 0)
            self.assertEqual(LearningSession.query.filter_by(user_id=user_id).count(), 0)
            self.assertEqual(QuizHistory.query.filter_by(user_id=user_id).count(), 0)
            self.assertEqual(DownloadedFile.query.filter_by(user_id=user_id).count(), 0)

    def test_download_pdf_returns_full_report_attachment(self):
        evaluation = {
            "questions": [
                {
                    "question": "What is question one?",
                    "student_answer": "Answer 1",
                    "correct_answer": "Correct answer 1",
                    "status": "correct",
                    "marks_label": "2",
                    "max_marks": "2",
                    "teacher_feedback": "Excellent answer.",
                    "revision_tip": "",
                }
            ],
            "summary": {
                "score_label": "8/10",
                "percentage_label": "80%",
                "grade": "A",
                "correct_answers": 1,
                "incorrect_answers": 0,
                "partial_answers": 0,
            },
            "teacher_report": {
                "overall_feedback": "Strong attempt.",
                "strengths": ["Clear answers"],
                "weak_areas": ["Add more examples"],
                "revision_suggestions": ["Practice again"],
            },
        }
        report_text = """# Performance Summary
Score: 8/10
Grade: A

# Strengths
- Clear answers
- Good effort

# Weak Areas
- Add more examples
"""

        response = self.client.post(
            "/download_pdf",
            data={
                "name": "Asha",
                "topic": "Plants",
                "score": "8/10",
                "grade": "A",
                "report_text": report_text,
                "evaluation_json": json.dumps(evaluation),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(
            "attachment; filename=Plants_performance_report.pdf",
            response.headers["Content-Disposition"],
        )
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertGreater(len(response.data), 3000)

    def test_download_pdf_rejects_missing_report_content(self):
        app_module.latest_report = {}

        response = self.client.post(
            "/download_pdf",
            data={"name": "Asha", "topic": "Plants", "score": "8/10", "grade": "A"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Topic and report content are required", response.get_data(as_text=True))

    @patch.object(app_module.model, "generate_content")
    def test_submit_rejects_missing_answer_without_calling_ai(self, generate_content):
        payload = self.answer_payload()
        del payload["answer3"]

        response = self.client.post("/submit_answers", data=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("All answers are required", response.get_data(as_text=True))
        generate_content.assert_not_called()

    @patch.object(app_module.model, "generate_content")
    def test_learn_rejects_malformed_ai_quiz_without_retry(self, generate_content):
        generate_content.return_value = MockResponse(
            "# Notes\nUseful notes.\n\n## Questions\nQ1. Only one question."
        )

        response = self.client.post(
            "/learn",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
                "topic": "Plants",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn(
            "AI Study Buddy is temporarily busy. Please try again in a moment.",
            response.get_data(as_text=True),
        )
        self.assertEqual(generate_content.call_count, 1)


if __name__ == "__main__":
    unittest.main()


def tearDownModule():
    with app_module.app.app_context():
        db.session.remove()
        db.engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
