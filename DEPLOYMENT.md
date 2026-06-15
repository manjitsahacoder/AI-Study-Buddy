# Deploy AI Study Buddy

## Required Environment Variables

Set this on your hosting platform:

```text
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_KEY_2=your_backup_gemini_api_key
```

Optional:

```text
QUIZ_HISTORY_DB=/path/to/quiz_history.db
```

If you deploy on Render with a persistent disk mounted at `/var/data`, the app will automatically store quiz history at `/var/data/quiz_history.db`.

## Render Settings

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Environment: Python

Add `GEMINI_API_KEY` in the Render dashboard before opening the live site.
Add `GEMINI_API_KEY_2` if you want the app to retry with a backup key when the first key reaches quota or rate limits.
