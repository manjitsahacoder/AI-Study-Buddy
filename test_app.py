import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as app_module


class MockResponse:
    def __init__(self, text):
        self.text = text


class MockModel:
    def __init__(self, response):
        self.response = response

    def generate_content(self, prompt):
        return self.response


class RouteTests(unittest.TestCase):
    def setUp(self):
        db_fd, self.db_path = tempfile.mkstemp()
        os.close(db_fd)
        app_module.app.config.update(TESTING=True)
        app_module.app.config["QUIZ_HISTORY_DB"] = self.db_path
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
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def answer_payload(self):
        payload = self.quiz_payload()
        payload.update(
            {
                f"answer{index}": f"Answer {index}"
                for index in range(1, 6)
            }
        )
        return payload

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
        page = response.get_data(as_text=True)
        self.assertIn("Plant Notes", page)
        self.assertIn("<strong>Subject</strong> Biology", page)
        self.assertIn('<img class="diagram-image"', page)
        self.assertIn("data:image/png;base64,", page)
        self.assertNotIn("D1: Seed", page)
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
        generate_content.return_value = MockResponse(
            """# Performance Summary
Score: 8/10
Grade: A

# Strengths
- Clear answers
"""
        )

        response = self.client.post("/submit_answers", data=self.answer_payload())

        self.assertEqual(response.status_code, 200)
        prompt = generate_content.call_args.args[0]
        self.assertIn("Q1: What is question one?\nStudent answer: Answer 1", prompt)
        self.assertIn("Q5: What is question five?\nStudent answer: Answer 5", prompt)
        self.assertIn("Class: 8", prompt)
        self.assertIn("Subject: Biology", prompt)
        page = response.get_data(as_text=True)
        self.assertIn("8/10", page)
        self.assertIn("Grade", page)
        self.assertIn('action="/download_pdf"', page)
        self.assertIn('method="POST"', page)
        self.assertIn('name="report_text"', page)
        self.assertIn("Clear answers", page)

        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT name, student_class, subject, topic, score, grade
                FROM quiz_history
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(row, ("Asha", "8", "Biology", "Plants", "8/10", "A"))

        history_response = self.client.get("/history")
        self.assertEqual(history_response.status_code, 200)
        history_page = history_response.get_data(as_text=True)
        self.assertIn("Quiz History", history_page)
        self.assertIn("Asha", history_page)
        self.assertIn("Plants", history_page)

    def test_download_pdf_returns_full_report_attachment(self):
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

        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
