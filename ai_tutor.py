import markdown


TUTOR_MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "nl2br"]
MAX_NOTES_CONTEXT_CHARS = 14000
MAX_HISTORY_MESSAGES = 12


def render_tutor_markdown(text):
    return markdown.markdown(
        text or "",
        extensions=TUTOR_MARKDOWN_EXTENSIONS,
        output_format="html5",
    )


def lesson_context(notes):
    notes = (notes or "").strip()
    if len(notes) <= MAX_NOTES_CONTEXT_CHARS:
        return notes
    return notes[:MAX_NOTES_CONTEXT_CHARS].rsplit("\n", 1)[0].strip()


def build_tutor_prompt(tutor_lesson, notes, previous_messages, student_message):
    conversation = "\n".join(
        f"{'Student' if message.sender == 'student' else 'AI Tutor'}: {message.content}"
        for message in previous_messages[-MAX_HISTORY_MESSAGES:]
    )
    if not conversation:
        conversation = "No previous questions in this lesson yet."

    book_line = tutor_lesson.book_name or "Not specified"
    lesson_notes = lesson_context(notes)

    return f"""
You are the AI Tutor inside AI Study Buddy.
You are not a generic chatbot. You are a patient, encouraging school teacher.

Student profile:
- Name: {tutor_lesson.name}
- Class: {tutor_lesson.student_class}
- Subject: {tutor_lesson.subject}
- Book: {book_line}
- Current chapter or lesson: {tutor_lesson.chapter}

Generated lesson notes you already understand:
{lesson_notes}

Previous conversation in this lesson:
{conversation}

Student's latest question:
{student_message}

Teacher rules:
- Teach according to the student's class level.
- Use simple, age-appropriate language.
- Encourage the student and invite follow-up questions.
- Give examples and analogies when useful.
- Explain mistakes gently if the student seems confused.
- Never answer in one line unless the question genuinely needs only one line.
- Keep the discussion focused on the current lesson.
- If the student asks for another topic, switch gracefully, but make it clear when it is outside the current lesson.
- Do not ask the student to repeat their class, subject, book, chapter, or notes.
- Use Markdown with headings, bullet lists, tables, or code blocks when they make the explanation clearer.
- Sound like an interactive teacher, not a generic AI assistant.
"""
