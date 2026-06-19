# Deploy AI Study Buddy

## Required Environment Variables

Set this on your hosting platform:

```text
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_KEY_2=your_backup_gemini_api_key
```

Optional:

```text
DATABASE_URL=postgresql://user:password@host:5432/database
```

If `DATABASE_URL` is set, the app uses PostgreSQL through SQLAlchemy. If it is missing, the app falls back to local SQLite for development.

## Render Settings

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Environment: Python

Add `GEMINI_API_KEY` in the Render dashboard before opening the live site.
Add `GEMINI_API_KEY_2` if you want the app to retry with a backup key when the first key reaches quota or rate limits.
For PostgreSQL setup, see `POSTGRES_SETUP.md`.
