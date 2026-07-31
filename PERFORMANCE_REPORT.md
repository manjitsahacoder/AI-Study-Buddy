# AI Study Buddy Performance Report

Audit date: 2026-07-09  
Environment: Local Flask development server, SQLite, live Gemini-backed AI calls  
Method: Three runs per major feature where applicable; first run treated as cold/uncached, subsequent runs as warm/cache checks.

## Classification

- Excellent: < 500 ms
- Good: 0.5-2 s
- Needs Improvement: 2-5 s
- Slow: > 5 s

## Benchmark Table

| Feature | First Load | Cached / Repeat Load | Average | Slowest Step / Bottleneck | Status |
|---|---:|---:|---:|---|---|
| Register | 428 ms | n/a | 428 ms | Password hash + DB insert | Excellent |
| Login | 688 ms | n/a | 688 ms | Password hash/session/dashboard redirect | Good |
| Home | 54 ms | 18 ms | 30 ms | Template/static references | Excellent |
| Login page | 11 ms | 27 ms | 22 ms | Template render | Excellent |
| Register page | 40 ms | 20 ms | 27 ms | Template render | Excellent |
| Dashboard | 92 ms | 69 ms | 76 ms | Dashboard stats/gamification queries | Excellent |
| Performance Analytics | 82 ms | 31 ms | 48 ms | Analytics aggregation/render | Excellent |
| Profile | 84 ms | 69 ms | 74 ms | Template render | Excellent |
| Learning History list | 47 ms | 18 ms | 27 ms | History query | Excellent |
| Quiz History | 30 ms | 16 ms | 21 ms | Quiz query | Excellent |
| Downloads | 38 ms | 12 ms | 21 ms | Download rows | Excellent |
| Saved Notes | 48 ms | 19 ms | 29 ms | Favourite join | Excellent |
| Settings | 52 ms | 14 ms | 27 ms | Template render | Excellent |
| Manifest | 7 ms | 13 ms | 11 ms | Static file | Excellent |
| Service Worker | 7 ms | 20 ms | 16 ms | Static file | Excellent |
| Offline page | 14 ms | 10 ms | 11 ms | Template render | Excellent |
| Developer Panel | 258 ms | 147 ms | 184 ms | System/user rollups | Excellent |
| Manage Users | 265 ms | 133 ms | 177 ms | User rollups/pagination | Excellent |
| Support Panel | 35 ms | 13 ms | 20 ms | Template render | Excellent |
| QA Panel | 46 ms | 15 ms | 25 ms | Health calculations | Excellent |
| AI Lesson: Photosynthesis | 17.27 s | n/a | 17.27 s | Gemini lesson generation | Slow |
| AI Lesson: Cell Division | 20.39 s | n/a | 20.39 s | Gemini lesson generation | Slow |
| AI Lesson: Human Heart | 12.67 s | n/a | 12.67 s | Gemini lesson generation | Slow |
| AI Lesson: Digestive System | 16.64 s | n/a | 16.64 s | Gemini lesson generation | Slow |
| AI Lesson: Electric Circuit | 9.72 s | n/a | 9.72 s | Gemini lesson generation | Slow |
| AI Lesson: Water Cycle | 16.78 s | n/a | 16.78 s | Gemini lesson generation | Slow |
| AI Lesson: Democracy | 14.75 s | n/a | 14.75 s | Gemini lesson generation | Slow |
| AI Lesson: Latitude and Longitude | 12.74 s | n/a | 12.74 s | Gemini lesson generation | Slow |
| AI Lesson: Solar System | 11.93 s | n/a | 11.93 s | Gemini lesson generation | Slow |
| AI Lesson: Mitochondria | 16.36 s | n/a | 16.36 s | Gemini lesson generation | Slow |
| Learning History Detail | 15.97 s | 58 ms | 5.36 s | Diagram AI review timeout | Slow |
| Lesson Notes | 38 ms | 44 ms | 42 ms | Template render | Excellent |
| Diagram Status API | 27 ms | 40 ms | 36 ms | JSON serialization/cache lookup | Excellent |
| Diagram Explanation | 8.75 s | 56 ms | 2.95 s | Gemini diagram explanation | Needs Improvement |
| Quick Revision | 12.08 s | 35 ms | 4.05 s | Gemini revision generation | Needs Improvement |
| Flashcards | 7.98 s | 16 ms | 2.67 s | Gemini flashcard generation | Needs Improvement |
| Important Questions | 21.00 s | 66 ms | 7.04 s | Gemini important-question generation | Slow |
| Study Plan | 58 ms | 45 ms | 49 ms | Completion/status calculations | Excellent |
| Memory Match | 47 ms | 27 ms | 34 ms | Flashcard card build | Excellent |
| Learning History PDF | 516 ms | 502 ms | 506 ms | PDF generation + large response | Good |
| Diagram Download | 29 ms | 38 ms | 35 ms | File send | Excellent |
| Revision PDF | 144 ms | 95 ms | 111 ms | PDF generation | Excellent |
| Important Questions PDF | 167 ms | 185 ms | 179 ms | PDF generation | Excellent |
| AI Tutor page | 27 ms | 32 ms | 31 ms | Message retrieval | Excellent |
| AI Tutor UI message | ~3.3 s | n/a | ~3.3 s | Gemini tutor response | Needs Improvement |
| Quiz page render | 44 ms | 22 ms | 29 ms | Template render | Excellent |
| Quiz evaluation | 13.30 s | 15.45 s | 14.73 s | Gemini evaluation | Slow |
| Performance PDF | 46 ms | 44 ms | 44 ms | PDF generation | Excellent |
| Support feedback submit | 200 response | n/a | < 1 s observed | DB insert + redirect | Excellent |
| Exhibition mode toggle | 200 response | n/a | < 1 s observed | Session update + redirect | Excellent |
| Favourite toggle | 200 response | n/a | < 1 s observed | DB insert/delete + redirect | Excellent |

## Feature Performance Notes

### Authentication

Register and login are fast enough for exhibition use. Login appears slower than static routes because password hashing and dashboard redirect are included in the measured request chain.

### Dashboard

Dashboard loaded in under 100 ms for the audit user. Current dataset is small, so developer/user growth should be tested separately with seeded data.

### AI Lesson

All 10 topics succeeded, but every first-run generation is Slow by classification. The dominant bottleneck is Gemini response time. Markdown parsing, saving, and rendering were not the dominant costs.

### Diagram Library

Cached diagram status and downloads are fast. First lesson-detail load can block on diagram AI review and timed out once after about 10.9 seconds internally, producing a 15.97 second page load while still returning 200.

### AI Tutor

Tutor page load is excellent. Actual tutor message response through UI completed successfully in about 3.3 seconds in the browser pass, which is acceptable but still AI-bound.

### Quiz

Quiz render is excellent. Quiz evaluation is Slow, averaging 14.73 seconds because each submission calls Gemini.

### Quick Revision, Flashcards, Important Questions

These features perform well after cached generation. First-run costs are AI-bound:

- Flashcards: 7.98 seconds first run.
- Quick Revision: 12.08 seconds first run.
- Important Questions: 21.00 seconds first run.

### Downloads

PDF and image downloads are fast except Learning History PDF, which is Good at about 506 ms and sends a larger 254 KB response.

### Developer/Support/QA

All admin/support/QA pages are excellent with the current dataset. Manage Users and Developer Panel are the slowest non-AI pages but still under 300 ms first load.

## Top 10 Slowest Features

1. Important Questions first generation: 21.00 s.
2. Cell Division AI Lesson: 20.39 s.
3. Photosynthesis AI Lesson: 17.27 s.
4. Water Cycle AI Lesson: 16.78 s.
5. Digestive System AI Lesson: 16.64 s.
6. Mitochondria AI Lesson: 16.36 s.
7. Learning History Detail first load with diagram review: 15.97 s.
9. Quiz Evaluation: 14.73 s average.
10. Democracy AI Lesson: 14.75 s.

## Top 10 Fastest Features

1. Manifest: 10.6 ms average.
2. Offline page: 11.3 ms average.
3. Service Worker: 15.9 ms average.
4. Support Panel: 20.0 ms average.
5. Quiz History: 20.8 ms average.
6. Downloads: 21.0 ms average.
7. Login page: 21.9 ms average.
8. QA Panel: 25.0 ms average.
9. Register page: 26.6 ms average.
10. Settings: 27.1 ms average.

## Largest Bottlenecks

### AI Bottlenecks

- Gemini lesson generation for all new topics.
- Gemini evaluation for quiz answers.
- Gemini generation for important questions.
- Gemini diagram explanation and diagram review.

### Database Bottlenecks

- No major database bottleneck appeared with the small audit dataset.
- Future risk: developer rollups, dashboard aggregations, and performance analytics should be tested with hundreds/thousands of rows.
- Integrity risk: SQLite FK enforcement is off, which is not a speed issue but affects correctness under deletion/orphan scenarios.

### Frontend Bottlenecks

- Performance Analytics layout overflows on mobile.
- Dashboard stat labels have minor internal overflow.
- Loader debug logging remains enabled.
- Some dark-mode pages do not reflect saved theme preference.

### Caching Improvements

- Existing generated-artifact caching works well for revision, flashcards, and important questions after first generation.
- Diagram cache worked for repeat status/download checks.
- Major opportunity: pre-warm and reuse lesson generation and quiz evaluation for known exhibition topics.
- PDF generation could be cached for unchanged artifacts to avoid repeated 500 ms Learning History PDF builds.

## Exhibition Performance Recommendation

For the exhibition, pre-generate at least:

- Photosynthesis
- Mitochondria
- Electric Circuit
- Water Cycle
- Solar System

Then demonstrate cached history/detail/revision/flashcards/tutor flows first, and run only one live AI generation if time allows. A live generation should be introduced as a 10-20 second AI step so the wait feels expected rather than broken.

## Performance Scores

| Category | Score |
|---|---:|
| Non-AI route speed | 92 |
| AI first-run speed | 45 |
| Cache effectiveness | 86 |
| Download speed | 88 |
| Frontend responsiveness | 74 |
| Overall performance | 68 |

Overall performance score: 68 / 100
