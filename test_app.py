import os
import json
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(TEST_DB_FD)
os.environ["QUIZ_HISTORY_DB"] = TEST_DB_PATH

import app as app_module
from database import db
from gemini_service import classify_gemini_exception
from models import (
    DownloadedFile,
    DiagramLibrary,
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
    TutorLesson,
    TutorMessage,
    User,
)
from diagram_library.metadata import DiagramCandidate, reusable_license
from diagram_library.service import get_or_create_diagram


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

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        with app_module.app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
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
            image_file.write(self.TEST_PNG)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return f"diagram_cache/{filename}"

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
        self.assertIn("## Diagram JSON", prompt)
        page = response.get_data(as_text=True)
        self.assertIn("Plant Notes", page)
        self.assertIn("<strong>Subject</strong> Biology", page)
        self.assertIn("Educational Diagram", page)
        self.assertIn("No suitable educational diagram is currently available for this lesson.", page)
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

    def test_download_notes_returns_all_notes_as_attachment(self):
        response = self.client.post(
            "/download_notes",
            data={
                "name": "Asha",
                "student_class": "8",
                "subject": "Biology",
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
        self.assertIn("Subject: Biology", notes)
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

    def test_visualization_assets_support_image_zoom_mobile_and_dark_mode(self):
        css_path = os.path.join(app_module.app.root_path, "static", "css", "visualization.css")
        js_path = os.path.join(app_module.app.root_path, "static", "js", "visualization.js")
        with open(css_path, encoding="utf-8") as css_file:
            css = css_file.read()
        with open(js_path, encoding="utf-8") as js_file:
            script = js_file.read()

        self.assertIn(".diagram-library-image", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn(".dark-mode .diagram-library-image-shell", css)
        self.assertIn("data-diagram-zoom", script)
        self.assertIn("is-fullscreen", script)

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
    def test_learn_retries_with_backup_key_on_quota_error(
        self,
        generate_content,
        generative_model,
        configure,
    ):
        generate_content.side_effect = Exception("429 quota reached")
        generative_model.return_value = MockModel(
            MockResponse(
                """# Backup Notes
Backup key worked.

## Questions
Q1. What is question one?

Q2. What is question two?

Q3. What is question three?

Q4. What is question four?

Q5. What is question five?
"""
            )
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
        configure.assert_called_with(api_key="backup-key")
        self.assertIn("Backup Notes", response.get_data(as_text=True))

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
        self.assertIn('const CACHE_VERSION = "ai-study-buddy-pwa-v1"', script)
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

    def test_predefined_accounts_receive_role_badges(self):
        special_accounts = [
            ("Manjit Saha", "manjit", "manjit@example.com", "developer", "Developer", "role-developer"),
            ("Manjit Saha", "manjitsaha", "manjitsaha2026@example.com", "developer", "Developer", "role-developer"),
            ("Gyanjyoti Mahanta", "gyanjyoti", "gyanjyoti@example.com", "technical_support", "Technical Support", "role-technical-support"),
            ("Lakshya Tuwani", "lakshya", "lakshya@example.com", "qa_tester", "Testing &amp; Quality Assurance", "role-qa-tester"),
        ]

        for full_name, username, email, expected_role, badge_text, badge_class in special_accounts:
            with self.subTest(username=username):
                self.register_user(username=username, email=email, full_name=full_name)
                with app_module.app.app_context():
                    row = User.query.filter_by(username=username).first()

                self.assertEqual(row.role, expected_role)

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

    def test_forgot_password_rejects_unknown_account(self):
        response = self.client.post(
            "/forgot-password",
            data={
                "action": "find_account",
                "identifier": "missing@example.com",
            },
        )

        self.assertEqual(response.status_code, 404)
        page = response.get_data(as_text=True)
        self.assertIn("We could not find an account with that username or email.", page)
        self.assertIn("missing@example.com", page)

    def test_forgot_password_validates_new_password(self):
        self.register_user()
        find_response = self.client.post(
            "/forgot-password",
            data={
                "action": "find_account",
                "identifier": "asha",
            },
        )

        self.assertEqual(find_response.status_code, 200)
        self.assertIn("Account Found", find_response.get_data(as_text=True))

        short_response = self.client.post(
            "/forgot-password",
            data={
                "action": "reset_password",
                "password": "short",
                "confirm_password": "short",
            },
        )

        self.assertEqual(short_response.status_code, 400)
        self.assertIn("Password must be at least 8 characters long.", short_response.get_data(as_text=True))

        mismatch_response = self.client.post(
            "/forgot-password",
            data={
                "action": "reset_password",
                "password": "newpassword123",
                "confirm_password": "different123",
            },
        )

        self.assertEqual(mismatch_response.status_code, 400)
        self.assertIn("Passwords do not match.", mismatch_response.get_data(as_text=True))

    def test_forgot_password_resets_hash_and_allows_new_login(self):
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
        self.assertIn("Your password has been reset successfully. Please log in with your new password.", page)

        with app_module.app.app_context():
            new_hash = User.query.filter_by(username="asha").first().password_hash

        self.assertNotEqual(old_hash, new_hash)
        self.assertFalse(app_module.check_password_hash(new_hash, "password123"))
        self.assertTrue(app_module.check_password_hash(new_hash, "newpassword123"))

        old_login = self.client.post(
            "/login",
            data={"identifier": "asha", "password": "password123"},
        )
        self.assertEqual(old_login.status_code, 401)

        new_login = self.client.post(
            "/login",
            data={"identifier": "asha", "password": "newpassword123"},
            follow_redirects=True,
        )
        self.assertEqual(new_login.status_code, 200)
        self.assertIn("Student Dashboard", new_login.get_data(as_text=True))

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
        self.assertIn("Subject: Science", prompt)
        self.assertIn("Book: NCERT", prompt)
        self.assertIn("Current chapter or lesson: Photosynthesis", prompt)
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
        self.assertIn("No suitable educational diagram is currently available for this lesson.", detail_page)
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
    def test_learn_rejects_malformed_ai_quiz(self, generate_content):
        generate_content.return_value = MockResponse(
            "# Notes\nUseful notes without a questions section."
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


if __name__ == "__main__":
    unittest.main()


def tearDownModule():
    with app_module.app.app_context():
        db.session.remove()
        db.engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
