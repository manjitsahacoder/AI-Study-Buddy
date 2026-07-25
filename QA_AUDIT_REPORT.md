# AI Study Buddy Complete QA Audit Report

Audit date: 2026-07-09  
Scope: End-to-end QA, security, performance, UI, accessibility, database, PWA, code audit  
Mode: Audit only. No fixes implemented.

## Executive Summary

AI Study Buddy is feature-rich and functionally demonstrable. The automated suite passed, live route checks returned expected statuses, and all 10 requested AI lesson topics generated successfully with lessons, diagrams, quizzes, and English output.

The main exhibition risks are not basic functionality. They are first-run AI latency, a diagram AI-review timeout on first lesson-detail load, inconsistent persisted dark mode, mobile overflow on Performance Analytics, and several security hardening gaps that should be addressed before any public deployment.

Exhibition readiness score: 74 / 100

Recommendation: Ready for a controlled exhibition demo if content is pre-warmed and a presenter expects 10-20 second AI waits. Not ready for public/production launch until authentication, authorization, CSRF, secret handling, and database integrity issues are fixed.

## Methodology

- Inspected route map, templates, static files, models, database configuration, diagram library, AI services, and tests.
- Ran automated tests: `python -m unittest test_app.py test_visualization_layouts.py`.
- Started the Flask app locally with performance timing enabled.
- Created disposable audit accounts using real registration/login flows:
  - Student: `auditstudent_1783573545`
  - Developer: `manjitsaha`
  - Support: `gyanjyoti`
  - QA: `lakshya`
- Benchmarked major routes and workflows three times where applicable.
- Generated live AI lessons for: Photosynthesis, Cell Division, Human Heart, Digestive System, Electric Circuit, Water Cycle, Democracy, Latitude and Longitude, Solar System, Mitochondria.
- Tested browser rendering, console logs, persisted dark mode, responsive mobile viewport, navigation, downloads, saved notes, tutor, quiz, support, QA, developer pages.

## Feature Inventory

Discovered features:

- Authentication: register, login, logout, forgot password.
- Guest mode lesson generation with account upsell/locked cards.
- Dashboard with stats, activity, recommendations, gamification, study plan summary.
- Profile page.
- Settings: profile, password, appearance, AI defaults, notifications, data export, delete account.
- Learning History list, filters, detail, delete, PDF export.
- Saved Notes / Favourite Notes.
- Download Center / Downloaded Reports.
- Performance Analytics with charts and insights.
- AI Lesson generation.
- AI Diagram Library / diagram cache / diagram status / AI diagram explanation / image download.
- Quiz generation and quiz evaluation.
- Quiz History.
- AI Tutor with saved conversations.
- Quick Revision.
- Flashcards with status update.
- Memory Match / Memory Challenge.
- Mind Maps.
- Important Questions.
- Study Planner.
- Recommendations engine.
- Gamification / XP / badges / daily challenges.
- Developer Panel.
- Manage Users.
- Support Panel and feedback form.
- QA Panel.
- Role-based navigation and access control.
- Dark Mode toggle and persisted appearance preference.
- Exhibition Mode with demo buttons and guided tour.
- PWA manifest, service worker, offline page, install prompt.
- Responsive design and mobile sidebar.
- Loading/page transition overlay.
- PDF generation for notes, revision, important questions, quiz/performance reports.

## Passed Tests

- Automated suite: 176 tests passed.
- Public pages loaded: Home, Login, Register, Offline, Manifest, Service Worker.
- Student pages loaded: Dashboard, Performance, Profile, Learning History, Quiz History, Downloads, Saved Notes, Settings.
- Developer pages loaded for developer role: Developer Panel, Manage Users.
- Support page loaded for support role and saved feedback.
- QA panel loaded for QA role.
- Student access to developer/support/QA pages returned 403 with access denied page.
- Exhibition mode enabled for developer and hid admin links in exhibition view.
- PWA manifest and service worker were present and returned 200.
- All 10 AI topics returned 200, included lesson signals, diagram/visualization signals, and 5 quiz questions.
- Quick Revision, Mind Map, Flashcards, Important Questions, Study Plan, Memory Match, downloads, and PDFs returned 200.
- Tutor UI accepted a real message and displayed an assistant response.
- Quiz render and AI evaluation returned 200.
- No browser console errors were captured.

## Failed Tests And Issues

### High Severity

1. Password reset allows account takeover without email/OTP verification

- Severity: High
- Steps to reproduce:
  1. Open `/forgot-password`.
  2. Enter any known username/email.
  3. Set a new password without proving email ownership.
  4. Log in as that account.
- Files involved:
  - `app.py:8363`
  - `app.py:8381`
  - `app.py:8390`
  - `templates/forgot_password.html`
- Recommended fix: Require a time-limited signed reset token delivered out-of-band, or disable password reset in deployed builds.
- Estimated effort: 1-2 days.

2. Role elevation is based on self-submitted full name and username

- Severity: High
- Steps to reproduce:
  1. Register with full name `Manjit Saha` and username `manjitsaha`.
  2. Log in.
  3. Developer pages are available.
- Files involved:
  - `app.py:353`
  - `app.py:975`
  - `app.py:999`
- Recommended fix: Remove registration-time role auto-assignment. Seed privileged accounts server-side or manage roles through an admin-only workflow.
- Estimated effort: 0.5-1 day.

3. No CSRF protection on state-changing forms

- Severity: High
- Steps to reproduce:
  1. Inspect forms for settings, delete, logout, support, favourite, learning delete, downloads, exhibition mode.
  2. No CSRF token exists.
- Files involved:
  - `app.py` POST routes: `/settings`, `/settings/delete-account`, `/support`, `/learning-history/<id>/delete`, `/exhibition-mode`, etc.
  - Multiple templates with POST forms.
- Recommended fix: Add Flask-WTF/CSRFProtect or equivalent signed CSRF tokens for all state-changing requests.
- Estimated effort: 1 day.

4. SQLite foreign-key enforcement is off

- Severity: High
- Steps to reproduce:
  1. Run `PRAGMA foreign_keys` against `quiz_history.db`.
  2. Result is `0`.
- Files involved:
  - `database.py`
  - `models.py`
- Recommended fix: Enable SQLite `PRAGMA foreign_keys=ON` on connection and add a regression test.
- Estimated effort: 0.5 day.

5. Hard-coded development secret fallback

- Severity: High
- Steps to reproduce:
  1. Inspect app config.
  2. `SECRET_KEY` falls back to `ai-study-buddy-dev-secret-key`.
- Files involved:
  - `app.py:111`
- Recommended fix: Require `SECRET_KEY` in non-test/non-local environments and fail fast if missing.
- Estimated effort: 0.25 day.

### Medium Severity

6. AI first-run latency is too high for an unprepared exhibition demo

- Severity: Medium
- Steps to reproduce:
  1. Submit new AI lesson topics.
  2. Observe 9.7-20.4 second lesson generation.
  3. Generate Important Questions, Mind Map, Quick Revision, Quiz Evaluation.
- Files involved:
  - `app.py:9594`
  - `app.py:2857`
  - `app.py:3029`
  - `app.py:3154`
  - `app.py:3192`
  - `app.py:10013`
- Recommended fix: Pre-warm demo topics, show clearer progress, cache by topic/user, and consider async jobs for AI-heavy tools.
- Estimated effort: 2-4 days.

7. Diagram AI review timed out during first lesson-detail load

- Severity: Medium
- Steps to reproduce:
  1. Generate Mitochondria lesson.
  2. Open `/learning-history/10`.
  3. Server logged `Diagram AI review` timeout, while page eventually returned 200 after 15.97 seconds.
- Files involved:
  - `app.py:2107`
  - `app.py:2320`
  - `diagram_library/ai_review.py`
- Recommended fix: Move diagram AI review to background/cache-first path or cap first-page blocking time.
- Estimated effort: 1-2 days.

8. Persisted dark mode is inconsistent across pages

- Severity: Medium
- Steps to reproduce:
  1. Save dark theme in `/settings`.
  2. Visit `/dashboard`, `/performance`, `/learning-history`.
  3. Body lacks `dark-mode`.
  4. Visit `/settings`, `/downloaded-reports`, `/favourite-notes`; body includes `dark-mode`.
- Files involved:
  - `templates/dashboard.html:11`
  - `templates/performance.html:12`
  - `templates/learning_history.html:12`
  - Working examples: `templates/settings.html:11`, `templates/downloaded_reports.html:11`, `templates/favourite_notes.html:11`
- Recommended fix: Apply `account.theme_preference == 'dark'` consistently in all authenticated body classes or centralize layout.
- Estimated effort: 0.5 day.

9. Performance Analytics overflows horizontally on mobile

- Severity: Medium
- Steps to reproduce:
  1. Set viewport to 390x844.
  2. Open `/performance`.
  3. Document width exceeds viewport by about 499px.
- Files involved:
  - `templates/performance.html:265`
  - `static/style.css`
- Recommended fix: Adjust `performance-content-grid` and chart/table containers for mobile wrapping and max-width.
- Estimated effort: 0.5-1 day.

10. Deprecated Gemini SDK

- Severity: Medium
- Steps to reproduce:
  1. Run tests or import app.
  2. Warning reports `google.generativeai` support has ended.
- Files involved:
  - `requirements.txt:3`
  - `app.py:28`
- Recommended fix: Migrate to `google.genai`.
- Estimated effort: 1-2 days.

11. Direct app startup runs Flask debug mode

- Severity: Medium
- Steps to reproduce:
  1. Run `python app.py`.
  2. Debug server starts.
- Files involved:
  - `app.py:10264`
- Recommended fix: Gate debug mode behind an environment variable or use only `flask run`/Gunicorn for deployment.
- Estimated effort: 0.25 day.

### Low Severity

12. Loader debug logs appear in browser console

- Severity: Low
- Steps to reproduce:
  1. Log in through browser.
  2. Inspect console logs.
  3. See `Loader triggered from...`.
- Files involved:
  - `static/motion.js:344`
  - `static/motion.js:428`
- Recommended fix: Disable debug logging by default.
- Estimated effort: 0.25 day.

13. ResourceWarning: unclosed files during tests

- Severity: Low
- Steps to reproduce:
  1. Run `python -m unittest test_app.py test_visualization_layouts.py`.
  2. Observe ResourceWarnings for manifest, service worker, and diagram cache image reads.
- Files involved:
  - `test_app.py`
  - static file read paths exercised by app/test helpers
- Recommended fix: Ensure file handles are opened with context managers in tests and helper paths.
- Estimated effort: 0.5 day.

14. Several templates duplicate theme toggle JavaScript

- Severity: Low
- Steps to reproduce:
  1. Search for `toggleTheme()` and `innerHTML`.
  2. Repeated inline implementations appear across templates.
- Files involved:
  - `templates/*.html`
- Recommended fix: Move common theme behavior into one static JS module.
- Estimated effort: 1 day.

15. Hidden diagnostic route remains available

- Severity: Low
- Steps to reproduce:
  1. Open `/test`.
  2. Returns `PDF Route Test`.
- Files involved:
  - `app.py:10193`
- Recommended fix: Remove or protect diagnostic route before exhibition/public deployment.
- Estimated effort: 0.1 day.

## AI Topic Results

| Topic | Status | Time | Lesson | Diagram | Quiz Questions | English |
|---|---:|---:|---|---|---:|---|
| Photosynthesis | 200 | 17.27s | Pass | Pass | 5 | Pass |
| Cell Division | 200 | 20.39s | Pass | Pass | 5 | Pass |
| Human Heart | 200 | 12.67s | Pass | Pass | 5 | Pass |
| Digestive System | 200 | 16.64s | Pass | Pass | 5 | Pass |
| Electric Circuit | 200 | 9.72s | Pass | Pass | 5 | Pass |
| Water Cycle | 200 | 16.78s | Pass | Pass | 5 | Pass |
| Democracy | 200 | 14.75s | Pass | Pass | 5 | Pass |
| Latitude and Longitude | 200 | 12.74s | Pass | Pass | 5 | Pass |
| Solar System | 200 | 11.93s | Pass | Pass | 5 | Pass |
| Mitochondria | 200 | 16.36s | Pass | Pass | 5 | Pass |

## Database Audit

Tables verified:

- `users`
- `learning_history`
- `learning_sessions`
- `quiz_history`
- `downloaded_files`
- `favourite_notes`
- `support_feedback`
- `diagram_library`
- `revision_sheets`
- `mind_maps`
- `important_question_sets`
- `flashcard_sets`
- `flashcards`
- `memory_challenges`
- `study_plan_progress`
- `tutor_lessons`
- `tutor_messages`

Indexes are present on most user/time/topic lookups. Unique constraints exist for one-per-user generated artifacts such as favourite notes, revision sheets, mind maps, important question sets, flashcard sets, tutor lessons, and study plan progress.

Warning: SQLite foreign keys exist in schema metadata but are not enforced in the live connection (`PRAGMA foreign_keys = 0`).

Post-audit live data counts:

| Table | Count |
|---|---:|
| users | 7 |
| learning_history | 10 |
| quiz_history | 3 |
| downloaded_files | 12 |
| favourite_notes | 0 |
| support_feedback | 1 |
| diagram_library | 1 |
| revision_sheets | 1 |
| mind_maps | 1 |
| important_question_sets | 1 |
| flashcard_sets | 1 |
| flashcards | 12 |
| memory_challenges | 0 |
| tutor_lessons | 1 |
| tutor_messages | 2 |

## Accessibility And UI Notes

Passed:

- Browser check found no unnamed buttons on sampled pages.
- Sampled images had alt attributes.
- Keyboard-esc behavior exists in menu/sidebar scripts.
- PWA install prompt has dismiss controls.

Warnings:

- Some controls rely on emoji/icon text rather than consistent icon components.
- Mobile Performance Analytics overflows horizontally.
- Dashboard stat labels show small internal overflow at desktop width.
- Dark mode persistence is inconsistent.
- Many inline `onclick` and duplicated theme scripts increase maintenance risk.

## Top 20 Improvements Before Exhibition

1. Pre-generate and cache the intended demo topics.
2. Fix password reset or disable it for exhibition.
3. Remove self-service role auto-elevation.
4. Add CSRF protection.
5. Enable SQLite foreign-key enforcement.
6. Fix dark-mode persistence on dashboard, performance, learning history, and generated tool pages.
7. Fix mobile overflow on Performance Analytics.
8. Disable loader debug console logging.
9. Migrate away from deprecated `google.generativeai`.
10. Make diagram AI review non-blocking on lesson-detail load.
11. Add a visible AI wait-time expectation in the exhibition script.
12. Add a cached demo mode that uses real saved lessons.
13. Protect/remove `/test`.
14. Use environment-required `SECRET_KEY`.
15. Ensure app direct run does not default to debug in deployed contexts.
16. Add a QA smoke script for all role pages.
17. Centralize theme toggle JS.
18. Add cache hit/miss UI or admin telemetry for diagrams/AI artifacts.
19. Add tutor API regression coverage for frontend JSON path.
20. Run one final mobile pass after CSS fixes.

## Top 10 Bugs

1. Password reset does not verify identity.
2. Role elevation can be obtained by registering privileged names/usernames.
3. Missing CSRF protection.
4. SQLite foreign keys are disabled.
5. Dark mode saved preference is not applied on several pages.
6. Mobile `/performance` horizontal overflow.
7. Diagram AI review can block lesson detail and timeout.
8. Deprecated Gemini SDK warning.
9. Debug loader console logs leak into browser console.
10. Diagnostic `/test` route is public.

## Top 10 UI Improvements

1. Fix mobile Performance Analytics layout.
2. Apply dark mode consistently.
3. Reduce dashboard stat label overflow.
4. Use a shared theme toggle component.
5. Replace emoji-heavy controls with consistent icons where appropriate.
6. Improve AI loading progress with route-specific estimated wait text.
7. Add clearer empty states for memory challenge/tutor on dashboard.
8. Ensure generated diagrams and charts fit small screens.
9. Standardize button spacing in generated tool pages.
10. Keep exhibition mode visually focused but avoid hiding critical escape/navigation paths.

## Top 10 Performance Improvements

1. Cache/pre-warm AI lessons for demo topics.
2. Make diagram AI review asynchronous.
3. Cache quiz evaluations where identical question/answer payloads repeat.
4. Add AI job queue/status polling for long requests.
5. Record cache hit/miss metrics per feature.
6. Reduce first-load chart/grid payload on `/performance`.
7. Cache developer rollups for large user counts.
8. Avoid generating PDFs repeatedly for unchanged artifacts.
9. Compress large PDF/image responses where applicable.
10. Add client-visible timeout recovery for AI routes.

## Top 10 Code Quality Improvements

1. Add CSRF middleware and tests.
2. Remove registration-time role mapping.
3. Enforce `SECRET_KEY`.
4. Enable SQLite FK pragma.
5. Migrate Gemini SDK.
6. Centralize layout/body classes.
7. Centralize theme JS.
8. Remove debug route/logging.
9. Replace `print()` AI logs with structured logger calls.
10. Address unclosed-file ResourceWarnings.

## Scores

| Category | Score |
|---|---:|
| Performance | 68 |
| Reliability | 82 |
| UI | 76 |
| Code Quality | 70 |
| Stability | 78 |
| Security | 58 |
| Exhibition Readiness | 74 |

Overall score: 74 / 100

## Final Recommendation

Proceed with a controlled demonstration only after pre-warming at least three demo topics and avoiding live first-run generation when judges are moving quickly. Before any wider release, address the high-severity authentication, authorization, CSRF, secret, and database integrity issues.
