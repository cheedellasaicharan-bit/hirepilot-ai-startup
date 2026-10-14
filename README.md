# HirePilot AI — Resume Screening & Applicant Tracking MVP

A deployable full-stack starter for a resume-screening SaaS. FastAPI serves the frontend and API from one public URL; SQLAlchemy stores users, jobs, candidates, screening sessions, and results.

## Features
- Email/password registration and login with hashed passwords and signed JWT sessions
- Dashboard metrics and recent activity
- Job creation and job list
- Upload resumes as PDF, DOCX, or TXT
- Candidate list and stage tracking
- Resume-to-job keyword matching, explanations, matched/missing terms, ranked results
- Persistent screening history and CSV export
- Per-user data isolation
- Responsive UI and demo/sample data option
- Health endpoint

**Important:** This MVP uses explainable keyword matching, not a trained AI model. Scores are decision-support only and must not automatically accept/reject candidates. Review resumes and use consistent, job-related criteria.

## Run locally (Windows)
1. Install Python 3.11+ and Node.js is not required (frontend is plain HTML/CSS/JS).
2. Extract this ZIP.
3. Open CMD in the extracted folder.
4. Create a virtual environment:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
5. Edit `.env` and set a long random `SECRET_KEY`.
6. Start:
   ```bat
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
7. Open http://127.0.0.1:8000

## Deploy to Render
1. Push the extracted folder contents to a GitHub repository.
2. In Render choose **New + → Blueprint** and connect the repository.
3. Render reads `render.yaml`, creates the web service and PostgreSQL database, and sets `DATABASE_URL` / `SECRET_KEY`.
4. After deployment, open the service's public URL.

If you already have a Render service, deploy this as a new branch/service first so you don't overwrite your working app before testing.

## Notes
- Add a custom domain, email verification, password reset, rate limiting, audit logging, and legal/privacy pages before charging customers.
- For production, use a managed Postgres database. Local SQLite is for development only.
- Do not upload real candidate data until you have appropriate consent, retention/deletion controls, and privacy/security review.
