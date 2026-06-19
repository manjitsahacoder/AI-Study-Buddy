# PostgreSQL Setup for AI Study Buddy

AI Study Buddy now uses SQLAlchemy with PostgreSQL in production and SQLite as a local fallback.

## How the App Chooses a Database

- Production: if `DATABASE_URL` exists, the app connects to that database.
- Local development: if `DATABASE_URL` is missing, the app falls back to `quiz_history.db` in the project folder.
- Credentials are never hardcoded. Render provides `DATABASE_URL` as an environment variable.

## Render Blueprint Setup

The included `render.yaml` creates:

- Web service: `ai-study-buddy`
- PostgreSQL database: `ai-study-buddy-db`
- Environment variable: `DATABASE_URL`, sourced from the database connection string

After pushing to GitHub, Render should sync the Blueprint and redeploy the app. On startup, SQLAlchemy creates missing tables automatically without deleting existing data.

## Manual Render Setup

If you are not using the Blueprint:

1. In Render, create a new PostgreSQL database.
2. Open the database page and copy the internal connection string.
3. Open the `ai-study-buddy` Web Service.
4. Add an environment variable:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
```

5. Redeploy the web service.

Use Render's internal database URL when the database and web service are in the same Render account and region.

## Local Development

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run locally without PostgreSQL:

```powershell
python app.py
```

The app will use local SQLite automatically.

Run locally with PostgreSQL:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/ai_study_buddy"
python app.py
```

## Migration Notes

This update creates PostgreSQL tables automatically, but it does not copy old SQLite rows into PostgreSQL. To migrate existing local SQLite data later, export each table from `quiz_history.db` and import it into the matching PostgreSQL table:

- `users`
- `quiz_history`
- `learning_sessions`
- `downloaded_files`
- `learning_history`

Do not delete the old SQLite file until you confirm the PostgreSQL database contains the expected users and history.

## Tables Managed by SQLAlchemy

- `users`
- `quiz_history`
- `learning_sessions`
- `downloaded_files`
- `learning_history`

The app preserves password hashing with Werkzeug, role assignment, session handling, quiz history, learning history, PDFs, dashboard counts, and the developer panel.
