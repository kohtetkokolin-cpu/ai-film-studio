# AI Film Studio

မြန်မာဘာသာအခြေပြု AI film pre-production workspace။ ဇာတ်လမ်းအကျဉ်းကို Gemini နဲ့ အဓိပ္ပါယ်နားလည်စေပြီး story beats, cinematic video prompts, negative prompts နဲ့ continuity checklist များ ထုတ်ပေးသည်။ ဒီ app က ဗီဒီယိုကို တိုက်ရိုက် render မလုပ်ပါ — external video generator မှာ အသုံးပြုရန် prompt များထုတ်ပေးခြင်းဖြစ်သည်။

## Architecture

- Frontend: React + Vite, Supabase Auth
- Backend: FastAPI + Google GenAI SDK
- Persistence: Supabase Postgres REST API; projects isolated by user ID
- Authentication: Supabase Auth access-token verification on backend
- AI model default: gemini-3.8-flash (override with server-side GEMINI_MODEL)

## Main features

- Burmese-first project form with story, genre, duration, style, ratio, language/culture, character/location bibles, continuity notes
- Gemini-generated cinematic story beats and ready-to-paste detailed prompts
- Exactly ceil(duration_seconds / 8) clips; duration choices are 1–5 minutes, last clip shortened if needed
- Negative prompts and continuity checklist per clip
- Supabase-backed saved projects; users can only access their own projects
- TXT / JSON export

## Deployment

Follow DEPLOYMENT_GUIDE_MY.md. Deploy two Vercel projects from the same repo:
1. Backend project Root Directory: backend
2. Frontend project Root Directory: frontend

Run supabase/migrations/202610100001_film_projects.sql in Supabase SQL Editor before using the app.

## Local development

Backend terminal:
    cd backend
    python -m venv .venv
    # Windows: .venv\Scripts\activate
    # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt

Set environment variables from the root .env.example in your shell (do not commit secrets), then run:
    uvicorn app.main:app --reload --port 8000

Frontend terminal:
    cd frontend
    npm install

Create frontend/.env.local with:
    VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
    VITE_SUPABASE_ANON_KEY=YOUR_PUBLIC_ANON_KEY
    VITE_API_BASE_URL=http://127.0.0.1:8000

Then run:
    npm run dev

## Security notes

- Never put Gemini API keys or Supabase service-role keys in VITE_* variables.
- Backend verifies Supabase access tokens and adds the authenticated user's ID to all project queries.
- Database schema enables RLS and includes per-user policies.
- Gemini free-tier quota and access depend on the account/project/model; no fixed request allowance is guaranteed.
