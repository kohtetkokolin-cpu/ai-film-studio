# AI Film Studio — Production Readiness Checklist

This application currently prepares pre-production material and external-tool prompts. It does **not** render image/video files itself.

## Implemented in this repository

- Supabase-authenticated project CRUD; API checks ownership before project operations.
- Three generation modes: `template`, `gemini` and `auto` (Gemini with template fallback).
- Story/character/location/prop/scene planning, style direction, prompt generation and TXT/JSON export.
- Saved production package and clips in the project row, plus browser-local workspace recovery.
- Structural QC for clip count, exact timeline, 8-second clip maximum, duplicate asset IDs and missing character/location references.
- Project update validation before writing to the database.
- Unit tests for template timeline, invalid references, duplicate IDs/timeline gaps, JSON parsing and request validation.
- CI builds the frontend and compiles/runs backend tests.

## Required environment variables

### Frontend (Vercel project rooted at `frontend`)
- `VITE_API_BASE_URL`: backend base URL, with no trailing slash.
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`

### Backend (Vercel project rooted at `backend`)
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` — keep private; never expose this to the frontend.
- `GEMINI_API_KEY`
- `GEMINI_MODEL` — use a model name enabled for your Gemini API key.
- `FRONTEND_ORIGIN` — exact deployed frontend origin; comma-separated if there are multiple.

## Supabase

Apply the existing migrations in order in the Supabase SQL Editor:
1. `supabase/migrations/202610100001_film_projects.sql`
2. `supabase/migrations/202610100002_production_workflow.sql`

Do not put the service-role key in Vite variables. Supabase RLS should remain enabled and policies should be reviewed before allowing direct client access to project tables; the backend uses the service-role key only after verifying the caller's Supabase access token and filtering rows by that user ID.

## Manual smoke test after deployment

1. Open `/health` on the backend. Confirm `ok=true`, and confirm the expected configuration flags.
2. Sign up/login through the frontend and create a short 60-second project.
3. Choose Template mode and generate a package. Confirm eight clips with a total of 60 seconds and a final clip of 4 seconds.
4. Review and edit the story, Character Bible, Location Bible and scene plan. Approve each stage.
5. Generate prompts. Confirm image/video prompts, negative prompt and continuity checklist appear.
6. Export TXT and JSON.
7. Open another page and return, refresh, then log out/in and reopen the project. Confirm generated prompts and edits are still present.
8. Test a deliberately invalid project update and confirm the API rejects it without changing the saved project.
9. Test Gemini mode with a valid API key; then test Auto mode while Gemini is unavailable/quota-limited and confirm the fallback notice is clear.

## Known limitations before series-grade production

- Structural QC cannot prove that the story makes dramatic sense or that character continuity is visually perfect. Human review is required.
- Template mode is a deterministic rules-based fallback, not a substitute for AI story development.
- Character/location sheets are prompts and optional external URLs, not generated image assets. A user must generate/reference images in an external service and attach them to prompts.
- There is no built-in image/video rendering, voice generation, timeline editor, sound mixing, subtitle synchronization or final MP4 export yet.
- The current project duration is capped at 300 seconds. A series workflow needs episode/season bibles, longer-project segmentation, version history and resumable jobs.
- End-to-end tests against real Supabase/Gemini/Vercel are not run by unit CI; run the smoke test before relying on a production deployment.

## Suggested next milestones

1. Build persistent Character/Location reference asset storage and approval state.
2. Add episode/series bible and story continuity graph, with manual approval checkpoints.
3. Add prompt revision history and per-scene regeneration without losing approved assets.
4. Add external provider adapters or a separate rendering worker, plus job queue/progress/retry handling.
5. Add audio/dialogue timing, subtitle generation, editing timeline and final export.
6. Add integration tests and a staging deployment checklist.
