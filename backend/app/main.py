import json
import math
import os
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from google import genai
from pydantic import BaseModel, Field

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
TIMEOUT = (10, 120)

app = FastAPI(title="AI Film Studio API", version="1.0.0")
origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
origins += [x.strip().rstrip("/") for x in os.getenv("FRONTEND_ORIGIN", "").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "apikey"],
)

NEGATIVE = (
    "low resolution, blurry, pixelated, compression artifacts, inconsistent character identity, "
    "face morphing, changing age, changing hairstyle, changing clothes, inconsistent proportions, "
    "extra fingers, missing fingers, malformed hands, extra limbs, duplicated people, floating objects, "
    "flickering, jitter, stuttering motion, sudden camera jump, unintended zoom, inconsistent lighting, "
    "unwanted text, subtitles, watermark, logo, UI elements, oversaturated colors, unwanted style change"
)


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    genre: str = "Drama"
    duration_seconds: int = Field(default=180, ge=8, le=300)
    visual_style: str = "Realistic cinematic"
    workflow: str = "automatic"
    aspect_ratio: str = "16:9"
    language: str = "Burmese"
    story_idea: str = Field(min_length=10, max_length=20000)
    character_bible: str = Field(default="", max_length=12000)
    location_bible: str = Field(default="", max_length=12000)
    continuity_notes: str = Field(default="", max_length=12000)


def require_config() -> None:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "Supabase မချိတ်ရသေးပါ။ Vercel environment variables ကို စစ်ပါ။")


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_config()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "အရင် Login ဝင်ပါ။")
    token = authorization.split(" ", 1)[1].strip()
    try:
        r = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(503, "Supabase Auth ကို ချိတ်မရပါ။")
    if r.status_code != 200:
        raise HTTPException(401, "Login သက်တမ်းကုန်သွားပါပြီ။ ပြန် Login ဝင်ပါ။")
    user = r.json()
    if not user.get("id"):
        raise HTTPException(401, "အသုံးပြုသူကို အတည်မပြုနိုင်ပါ။")
    return user


def db_headers(prefer: str = "return=representation") -> dict[str, str]:
    # New Supabase secret keys (sb_secret_...) are API keys, not JWTs.
    # Legacy service_role keys are JWTs and can also be sent as Authorization.
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    if not SUPABASE_SERVICE_ROLE_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
    return headers


def db_request(method: str, table_path: str, *, params: dict | None = None, payload: Any = None) -> Any:
    require_config()
    try:
        r = requests.request(
            method, f"{SUPABASE_URL}/rest/v1/{table_path}",
            headers=db_headers(), params=params, json=payload, timeout=TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(503, "Supabase database ကို ချိတ်မရပါ။")
    if r.status_code >= 400:
        detail = "Database request မအောင်မြင်ပါ။ Supabase SQL schema ကို run လုပ်ထားကြောင်း စစ်ပါ။"
        try:
            info = r.json()
            if info.get("code") == "42P01":
                detail = "film_projects table မတွေ့ပါ။ supabase/migrations ထဲက SQL ကို Supabase SQL Editor မှာ run လုပ်ပါ။"
            elif info.get("code") == "23505":
                detail = "ဒီ project ကို ထပ်မံဖန်တီးထားပြီးဖြစ်သည်။"
        except ValueError:
            pass
        raise HTTPException(502, detail)
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def user_filter(user: dict[str, Any]) -> str:
    return f"eq.{user['id']}"


def get_owned_project(pid: str, user: dict[str, Any]) -> dict[str, Any]:
    rows = db_request(
        "GET", "film_projects",
        params={"select": "*", "id": f"eq.{pid}", "user_id": user_filter(user), "limit": "1"},
    )
    if not rows:
        raise HTTPException(404, "Project မတွေ့ပါ။")
    return rows[0]


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini returned no JSON object")
    return json.loads(cleaned[start:end + 1])


def generate_clips(project: dict[str, Any]) -> list[dict[str, Any]]:
    if not GEMINI_API_KEY:
        raise HTTPException(503, "Gemini API key မထည့်ရသေးပါ။ Vercel Environment Variables မှာ GEMINI_API_KEY ထည့်ပါ။")
    duration = int(project["duration_seconds"])
    count = math.ceil(duration / 8)
    timings = [
        {"clip_number": i + 1, "start_seconds": i * 8, "duration_seconds": min(8, duration - i * 8)}
        for i in range(count)
    ]
    prompt = f"""
You are a professional film director, screenplay editor, cinematographer, and AI-video prompt engineer.
Turn the supplied story into a coherent, shootable micro-film. Do not invent unrelated scenes or repeat generic scenery.
Return ONLY valid JSON: {{ "clips": [ {{ "clip_number": 1, "beat_title": "...", "visual_prompt": "...", "continuity_checklist": ["..."] }} ] }}.
Exactly {count} clips are required. Use the supplied timing table exactly; every clip is 8 seconds except the final remainder if applicable.
Each clip must advance the story with a clear dramatic beat: setup, character intention, action, reaction, reveal/turn, consequence, or ending as appropriate. Maintain chronological cause-and-effect and a satisfying ending within the selected duration.
Write all natural-language output in {project.get("language", "Burmese")}, except standard cinematography terms and the video-generation prompt itself may use concise English when that improves model compatibility. The visual_prompt MUST be a ready-to-paste detailed English video-generation prompt, not an explanation.
Each visual_prompt must specify: shot size and composition, camera angle/movement, character identity and appearance, precise visible action/motion over the clip, facial emotion/body language, environment and props, lighting, color palette, atmosphere, style, aspect ratio {project.get("aspect_ratio")}, and temporal continuity from the previous clip. Keep action physically plausible and achievable in 8 seconds. Do not ask for multiple unrelated shots in one clip.
Preserve story meaning, culture, language, clothing, architecture, and locations. Character bible and location bible are binding. If absent, infer a consistent design from the story and keep it unchanged across clips. Use named recurring props and explicit continuity anchors.
For dialogue, show only brief exact dialogue if essential; do not generate captions, text overlays, title cards, logos, or watermarks.
Story title: {project.get("title")}
Genre: {project.get("genre")}
Duration seconds: {duration}
Visual style: {project.get("visual_style")}
Aspect ratio: {project.get("aspect_ratio")}
Language/culture: {project.get("language")}
Workflow: {project.get("workflow")}
Story:
{project.get("story_idea")}
Character bible:
{project.get("character_bible") or "(Infer consistent character designs from story.)"}
Location bible:
{project.get("location_bible") or "(Infer consistent location design from story.)"}
Continuity notes:
{project.get("continuity_notes") or "(Keep identity, costume, props, geography, lighting progression, and screen direction consistent.)"}
Exact clip timing JSON:
{json.dumps(timings)}
Each checklist should contain 3-6 concrete continuity checks. Return exactly {count} clip objects.
"""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        data = parse_json_response(response.text or "")
        raw = data.get("clips")
        if not isinstance(raw, list) or len(raw) != count:
            raise ValueError(f"Expected {count} clips; received {len(raw) if isinstance(raw, list) else 'invalid'}")
        out = []
        for i, timing in enumerate(timings):
            item = raw[i]
            if not isinstance(item, dict) or not item.get("visual_prompt"):
                raise ValueError(f"Clip {i + 1} is missing visual_prompt")
            out.append({
                **timing,
                "beat_title": str(item.get("beat_title") or f"Clip {i + 1}"),
                "visual_prompt": str(item["visual_prompt"]),
                "negative_prompt": NEGATIVE,
                "continuity_checklist": [str(x) for x in (item.get("continuity_checklist") or [])][:8],
            })
        return out
    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc)
        if "429" in message or "RESOURCE_EXHAUSTED" in message:
            raise HTTPException(429, "Gemini quota ပြည့်သွားပါပြီ။ AI Studio မှာ quota စစ်ပြီး နောက်မှ ပြန်ကြိုးစားပါ။")
        if "API_KEY_INVALID" in message or "API key not valid" in message:
            raise HTTPException(503, "Gemini API key မမှန်ပါ။ GEMINI_API_KEY ကို စစ်ပါ။")
        raise HTTPException(502, f"Gemini prompt generation မအောင်မြင်ပါ။ Model access/quota စစ်ပြီး ပြန်ကြိုးစားပါ။ ({message[:180]})")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "AI Film Studio API",
        "gemini_configured": bool(GEMINI_API_KEY),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY),
        "model": GEMINI_MODEL,
    }


@app.get("/api/projects")
def list_projects(user: dict = Depends(current_user)):
    return db_request(
        "GET", "film_projects",
        params={"select": "*", "user_id": user_filter(user), "order": "updated_at.desc"},
    )


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectIn, user: dict = Depends(current_user)):
    data = payload.model_dump()
    data["user_id"] = user["id"]
    data["clips"] = []
    result = db_request("POST", "film_projects", payload=data)
    if not result:
        raise HTTPException(502, "Project သိမ်းမရပါ။")
    return result[0]


@app.get("/api/projects/{pid}")
def get_project(pid: str, user: dict = Depends(current_user)):
    return get_owned_project(pid, user)


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str, user: dict = Depends(current_user)):
    get_owned_project(pid, user)
    db_request("DELETE", "film_projects", params={"id": f"eq.{pid}", "user_id": user_filter(user)}, payload=None)
    return None


@app.post("/api/projects/{pid}/generate")
def generate(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    clips = generate_clips(project)
    updated = db_request(
        "PATCH", "film_projects",
        params={"id": f"eq.{pid}", "user_id": user_filter(user)},
        payload={"clips": clips, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    if not updated:
        raise HTTPException(502, "Generated clips ကို database ထဲ သိမ်းမရပါ။")
    return {"project_id": pid, "target_duration_seconds": project["duration_seconds"], "clip_count": len(clips), "clips": clips}


@app.get("/api/projects/{pid}/clips")
def list_clips(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    return project.get("clips") or []


@app.get("/api/projects/{pid}/export")
def export(pid: str, format: str = Query(default="json", pattern="^(json|txt)$"), user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    clips = project.get("clips") or []
    if not clips:
        raise HTTPException(409, "Export မလုပ်ခင် Generate Prompts ကို အရင်နှိပ်ပါ။")
    if format == "json":
        return JSONResponse(
            {"project": project, "clips": clips},
            headers={"Content-Disposition": f'attachment; filename="film-project-{pid}.json"'},
        )
    lines = [
        f"# {project['title']}", f"Genre: {project['genre']}",
        f"Duration: {project['duration_seconds']}s", "",
    ]
    for clip in clips:
        lines += [
            f"## Clip {clip['clip_number']:02d} | {clip['start_seconds']}s | {clip['duration_seconds']}s",
            clip["beat_title"], "", "VISUAL PROMPT:", clip["visual_prompt"], "",
            "NEGATIVE PROMPT:", clip["negative_prompt"], "",
            "CONTINUITY CHECKLIST:", *[f"- {x}" for x in clip.get("continuity_checklist", [])],
            "", "-" * 50, "",
        ]
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="film-project-{pid}.txt"'},
    )
