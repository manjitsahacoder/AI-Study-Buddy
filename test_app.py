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

    def register_user(self, username="asha", email="asha@example.com", password="password123"):
        return self.client.post(
            "/register",
            data={
                "full_name": "Asha Student",
                "username": username,
                "email": email,
                "student_class": "8",
                "password": password,
                "confirm_password": password,
            },
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
        self.register_user()
        self.login_user()
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
        connection = sqlite3.connect(self.db_path)
        try:
            table_exists = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'quiz_history'
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNone(table_exists)

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

    def test_logged_in_home_shows_verified_student_mode(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Welcome back, Asha Student", page)
        self.assertIn("Verified Student", page)
        self.assertNotIn("Welcome, Guest!", page)
        self.assertNotIn("Why create an account?", page)

    def test_register_hashes_password_and_rejects_duplicate_username(self):
        response = self.register_user()

        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT full_name, username, email, student_class, password_hash
                FROM users
                WHERE username = ?
                """,
                ("asha",),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(row["full_name"], "Asha Student")
        self.assertEqual(row["email"], "asha@example.com")
        self.assertEqual(row["student_class"], "8")
        self.assertNotEqual(row["password_hash"], "password123")
        self.assertTrue(app_module.check_password_hash(row["password_hash"], "password123"))

        duplicate_response = self.register_user(email="different@example.com")

        self.assertEqual(duplicate_response.status_code, 400)
        self.assertIn("That username is already taken.", duplicate_response.get_data(as_text=True))

    def test_register_rejects_duplicate_email(self):
        self.register_user()

        response = self.register_user(username="asha_two")

        self.assertEqual(response.status_code, 400)
        self.assertIn("That email is already registered.", response.get_data(as_text=True))

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
        self.assertIn("Verified Student", page)
        self.assertIn("Dashboard", page)
        self.assertIn("My Profile", page)
        self.assertIn("Learning History", page)
        self.assertIn("Quiz History", page)
        self.assertIn("Downloaded Reports", page)
        self.assertIn("Settings", page)
        self.assertIn("Logout", page)
        self.assertNotIn(">Login</a>", page)
        self.assertNotIn(">Register</a>", page)

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
        self.assertIn("Coming Soon", page)
        self.assertIn("AI Recommendations", page)
        self.assertIn("Study Planner", page)
        self.assertIn("Verified Student", page)
        self.assertIn("Recommended Topics", page)
        self.assertIn("Photosynthesis", page)
        self.assertIn("Back to Home", page)
        self.assertIn("sidebar-nav", page)
        self.assertIn('class="profile-menu-button"', page)

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
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT user_id, subject, topic
                FROM learning_sessions
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(row, (1, "Biology", "Plants"))

        connection = sqlite3.connect(self.db_path)
        try:
            history_row = connection.execute(
                """
                SELECT user_id, subject, book_name, topic, notes, diagram_data, quiz_questions
                FROM learning_history
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(history_row[0:4], (1, "Biology", "", "Plants"))
        self.assertIn("Plant Notes", history_row[4])
        self.assertIn("What is question one?", history_row[6])

    def test_guest_learning_history_shows_locked_message(self):
        response = self.client.get("/learning-history")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Learning History is available only for registered students.", page)
        self.assertIn("Login", page)
        self.assertIn("Register", page)

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

        detail_response = self.client.get("/learning-history/1")
        self.assertEqual(detail_response.status_code, 200)
        detail_page = detail_response.get_data(as_text=True)
        self.assertIn("Plant Notes", detail_page)
        self.assertIn("Quick Revision", detail_page)
        self.assertIn("data:image/png;base64,", detail_page)
        self.assertIn("What is question one?", detail_page)

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
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT user_id, file_type, subject, topic, score, grade
                FROM downloaded_files
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(row, (1, "performance_report", "Biology", "Plants", "8/10", "A"))

    def test_profile_page_shows_account_and_future_sections(self):
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
        self.assertIn("Account Created", page)
        self.assertIn("Future Achievement Section", page)
        self.assertIn("Future Study Streak", page)
        self.assertIn("Future AI Usage Statistics", page)
        self.assertIn("Edit Profile", page)

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
