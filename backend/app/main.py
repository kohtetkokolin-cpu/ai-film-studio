import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
TIMEOUT = (10, 120)

app = FastAPI(title="AI Film Studio API", version="2.0.0")
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
MODES = {"template", "gemini", "auto"}


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    genre: str = "Drama"
    duration_seconds: int = Field(default=180, ge=8, le=300)
    visual_style: str = "Realistic cinematic"
    workflow: str = "automatic"
    aspect_ratio: str = "16:9"
    language: str = "Burmese"
    culture: str = "Myanmar"
    generation_mode: str = "auto"
    sound_mode: str = "dialogue"
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
    headers = {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Content-Type": "application/json", "Prefer": prefer}
    if not SUPABASE_SERVICE_ROLE_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
    return headers


def db_request(method: str, table_path: str, *, params: dict | None = None, payload: Any = None) -> Any:
    require_config()
    try:
        r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{table_path}",
            headers=db_headers(), params=params, json=payload, timeout=TIMEOUT)
    except requests.RequestException:
        raise HTTPException(503, "Supabase database ကို ချိတ်မရပါ။")
    if r.status_code >= 400:
        detail = "Database request မအောင်မြင်ပါ။ Supabase SQL migration အသစ်ကို run လုပ်ထားကြောင်း စစ်ပါ။"
        try:
            info = r.json()
            if info.get("code") == "42P01":
                detail = "film_projects table မတွေ့ပါ။ Supabase migration ကို SQL Editor မှာ run လုပ်ပါ။"
            elif info.get("code") == "42703":
                detail = "Project schema အသစ်မထည့်ရသေးပါ။ 202610100002_production_workflow.sql ကို Supabase SQL Editor မှာ run လုပ်ပါ။"
            elif info.get("23505") == "23505":
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
    rows = db_request("GET", "film_projects",
        params={"select": "*", "id": f"eq.{pid}", "user_id": user_filter(user), "limit": "1"})
    if not rows:
        raise HTTPException(404, "Project မတွေ့ပါ။")
    return rows[0]


def persist_package(pid: str, user: dict[str, Any], package: dict[str, Any]) -> None:
    rows = db_request("PATCH", "film_projects",
        params={"id": f"eq.{pid}", "user_id": user_filter(user)},
        payload={"production_package": package, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(502, "Production Package ကို database ထဲ သိမ်းမရပါ။ ပြန်ကြိုးစားပြီး Project ကို စစ်ပါ။")


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model returned no JSON object")
    return json.loads(cleaned[start:end + 1])


def _character_names(project: dict[str, Any]) -> list[str]:
    text = str(project.get("character_bible") or "")
    names: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^[\s•*\-\d.)]+", "", line).strip()
        if not line:
            continue
        parts = re.split(r"\s*[—:：|]\s*", line)
        if re.match(r"^CHAR-[A-Z0-9]+$", parts[0], re.I) and len(parts) > 1:
            name = parts[1].strip()
        else:
            name = parts[0].strip()
        if name and name not in names:
            names.append(name[:80])
    if not names:
        names = ["ဇာတ်ကောင်အဓိက (အသေးစိတ်အတည်ပြုရန်)", "အခြားဇာတ်ကောင် (လိုအပ်ပါက)"]
    return names[:12]


def _location_names(project: dict[str, Any]) -> list[str]:
    text = str(project.get("location_bible") or "")
    names: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^[\s•*\-\d.)]+", "", line).strip()
        if not line:
            continue
        parts = re.split(r"\s*[—:：|]\s*", line)
        if re.match(r"^LOC-[A-Z0-9]+$", parts[0], re.I) and len(parts) > 1:
            name = parts[1].strip()
        else:
            name = parts[0].strip()
        if name and name not in names:
            names.append(name[:100])
    if not names:
        names = ["အဓိကတည်နေရာ (ဇာတ်လမ်းမှ စစ်ဆေးရန်)", "ဒုတိယတည်နေရာ (လိုအပ်ပါက)"]
    return names[:20]


def _story_beats(genre: str) -> list[tuple[str, str]]:
    if genre.lower() in {"mystery", "thriller", "horror"}:
        return [
            ("Opening hook", "Show a striking clue or unsettling situation that raises a clear question."),
            ("Context", "Establish the protagonist, ordinary situation, and immediate objective."),
            ("First clue", "Introduce a concrete clue, contradiction, or threat."),
            ("Reaction", "Show the protagonist notice and react to the new information."),
            ("Escalation", "Increase risk or emotional pressure using cause and effect."),
            ("Revelation", "Reveal a meaningful new fact that changes the interpretation."),
            ("Consequence", "Show the choice, cost, or danger caused by the revelation."),
            ("Ending hook", "Deliver a satisfying ending or a clear next-part question based on the selected format."),
        ]
    if genre.lower() in {"romance", "drama"}:
        return [
            ("Opening image", "Establish the emotional world and a memorable visual detail."),
            ("Character goal", "Show what the protagonist wants and what relationship matters."),
            ("Friction", "Introduce an obstacle, misunderstanding, or competing need."),
            ("Emotional response", "Show a specific reaction rather than generic scenery."),
            ("Pressure", "Make the relationship conflict more difficult."),
            ("Turning point", "Reveal a choice, truth, or action that changes the relationship."),
            ("Aftermath", "Show the immediate emotional consequence."),
            ("Resolution", "Close the emotional beat or set up a meaningful next chapter."),
        ]
    return [
        ("Opening hook", "Begin with a clear visual question or immediate action."),
        ("Setup", "Establish the character, place, and goal."),
        ("Problem", "Introduce the main obstacle."),
        ("Response", "Show the character's decision or reaction."),
        ("Escalation", "Make the obstacle harder with a visible consequence."),
        ("Turning point", "Change the direction of the story."),
        ("Climax or consequence", "Show the decisive action and its cost."),
        ("Ending", "Resolve the promise of this short film or create a purposeful next-part hook."),
    ]


def generate_template_package(project: dict[str, Any]) -> dict[str, Any]:
    duration = int(project["duration_seconds"])
    count = math.ceil(duration / 8)
    names = _character_names(project)
    places = _location_names(project)
    genre = str(project.get("genre") or "Drama")
    beats = _story_beats(genre)
    story = str(project.get("story_idea") or "").strip()
    characters = []
    character_lines = [line.strip() for line in str(project.get("character_bible") or "").splitlines() if line.strip()]
    for i, name in enumerate(names):
        source_line = next((line for line in character_lines if name in line), "")
        parts = re.split(r"\s*[—:：|]\s*", source_line)
        appearance = parts[-1].strip() if len(parts) > 1 else "မျက်နှာ၊ အသားအရောင်၊ ဆံပင်၊ ကိုယ်ခန္ဓာနှင့် မှတ်မိစေသောအမှတ်အသားကို User အတည်ပြုရန်"
        age_match = re.search(r"(?:အသက်\s*[^၊,။]+|age\s*[:=]?\s*\d+[^,။]*)", appearance, re.I)
        age = age_match.group(0).strip() if age_match else "User အတည်ပြုရန်"
        characters.append({
            "id": f"CHAR-{i+1:03d}", "name": name,
            "role": "ဇာတ်ကောင်အခန်းကဏ္ဍကို Story/Character Bible အတည်ပြုချိန်တွင် ဖြည့်ရန်",
            "age": age, "appearance": appearance,
            "wardrobe": [{"id": f"WARD-{i+1:03d}-01", "description": "ဇာတ်လမ်းနှင့် ယဉ်ကျေးမှုကိုက်ညီသော ဝတ်စုံကို အတည်ပြုရန်"}],
            "expressions": ["neutral", "happy", "angry", "sad", "afraid", "surprised"],
            "movement": "Natural, physically plausible movement; preserve identity and body proportions.",
            "voice": "Dialogue voice profile requires user confirmation.",
            "reference_prompt": f"Create a professional character reference sheet for {name}, reference ID CHAR-{i+1:03d}. Selected visual style: {project.get('visual_style', 'Realistic cinematic')}. Apply this style consistently to rendering, materials, linework, shading and colors. {_style_direction(str(project.get('visual_style') or 'Realistic cinematic'))}. Use a clean neutral studio background and consistent full-body front, side, and back views, plus clear face expression studies. Show age and appearance only as specified in the approved character bible; do not invent a definitive age or ethnicity. Same face, hairstyle, proportions, wardrobe and identifying marks across every view. No labels, watermark or extra people."
        })
    locations = []
    for i, name in enumerate(places):
        lid = f"LOC-{chr(65+i)}"
        locations.append({
            "id": lid, "name": name, "environment_lock": "တံခါး၊ ပြတင်းပေါက်၊ ပရိဘောဂ၊ လမ်းကြောင်းနှင့် အခန်းအရွယ်အစားကို Reference ထဲတွင် အတည်ပြုရန်",
            "lighting_states": ["day", "dusk", "night"],
            "reference_prompt": f"Create a cinematic environment reference sheet for {name}, location ID {lid}. Selected visual style: {project.get('visual_style', 'Realistic cinematic')}. Apply this exact medium consistently. {_style_direction(str(project.get('visual_style') or 'Realistic cinematic'))}. Show a wide establishing view, reverse angle, and a clear spatial layout. Keep architecture, entrances, windows, furniture, materials and geography consistent. Match the selected culture and visual style; where story details are missing, use a plausible restrained design and flag it for approval. No people, text, logos or watermark."
        })
    sentences = [part.strip() for part in re.split(r"[။.!?！？\n]+", story) if part.strip()] or [story]
    prop_catalog = [
        ("စာအိတ်", "စာအိတ်", "envelope", "Keep envelope color, shape and hand position consistent."),
        ("ဖုန်း", "ဖုန်း", "phone", "Keep phone model and hand position consistent."),
        ("သော့", "သော့", "key", "Keep key appearance and pocket/hand continuity."),
        ("အိတ်", "အိတ်", "bag", "Keep bag color, strap and carried shoulder consistent."),
        ("ဓာတ်ပုံ", "ဓာတ်ပုံ", "photograph", "Keep photograph content and orientation consistent."),
        ("ဓား", "ဓား", "knife", "Keep prop placement safe and physically consistent."),
        ("ခွက်", "ခွက်", "cup", "Keep cup level, liquid and placement consistent."),
        ("စာ", "စာ", "letter", "Keep letter/fold and handoff continuity.")
    ]
    props = []
    for keyword, display_name, english_name, rule in prop_catalog:
        if keyword in story:
            props.append({"id": f"PROP-{len(props)+1:03d}", "name": display_name,
                "description": f"Story-detected prop: {english_name}; appearance needs user confirmation.",
                "continuity": rule, "keyword": keyword})
    scenes = []
    for i in range(count):
        start = i * 8
        clip_duration = min(8, duration - start)
        beat_index = round(i * (len(beats)-1) / max(1, count-1))
        beat_title, beat_rule = beats[beat_index]
        sentence_index = min(len(sentences)-1, int(i * len(sentences) / count))
        source_sentence = sentences[sentence_index]
        involved = [ch for ch in characters if ch["name"] and ch["name"] in source_sentence]
        if not involved:
            involved = characters[:1]
        char_ids = [ch["id"] for ch in involved]
        loc_id = locations[min(int(i * len(locations) / count), len(locations)-1)]["id"]
        scene_props = [p for p in props if p.get("keyword") and p["keyword"] in source_sentence]
        quote_matches = re.findall(r'[“"「](.*?)[”"」]', story)
        quote = quote_matches[min(len(quote_matches)-1, int(i * len(quote_matches) / count))] if quote_matches else ""
        dialogue = f"Exact supplied dialogue (speaker must be confirmed): {quote}" if quote and i == min(count-1, max(0, int(count * 0.55))) else (
            "No exact dialogue supplied for this beat; write/approve dialogue before rendering."
        )
        scenes.append({
            "scene_id": f"SC-{i+1:03d}", "clip_number": i+1,
            "start_seconds": start, "duration_seconds": clip_duration,
            "beat_title": beat_title, "dramatic_purpose": beat_rule,
            "location_id": loc_id, "character_ids": char_ids,
            "wardrobe_ids": [ch["wardrobe"][0]["id"] for ch in involved if ch.get("wardrobe")],
            "prop_ids": [p["id"] for p in scene_props],
            "action": f"Story fact for this beat: {source_sentence}. Production direction: {beat_rule} Show a concrete, visible action that preserves this fact; do not invent an unsupported plot event.",
            "dialogue": dialogue,
            "shot_size": ["wide establishing shot","medium shot","close-up reaction","over-the-shoulder"][i % 4],
            "camera_angle": ["eye-level","slightly low angle","three-quarter angle"][i % 3],
            "camera_movement": ["slow push-in","gentle tracking move","locked-off reaction shot"][i % 3],
            "lighting": "Motivated cinematic lighting consistent with location, time of day, and the previous scene.",
            "sound": str(project.get("sound_mode") or "dialogue"),
            "continuity": [f"Carry forward the prior scene result and begin this beat with a motivated action: {beat_title}.",
                "Keep the same approved character faces, age, hair and wardrobe.",
                "Preserve the location layout, screen direction and prop positions; no unexplained location or time jump.",
                "End on a visible result, reaction, clue or decision that motivates the next scene.",
                "Keep action physically plausible within the clip duration."]
        })
    return {
        "schema_version": 2, "generation_source": "template",
        "notice": "Template Mode က rules-based production planner ဖြစ်သည်။ ဇာတ်လမ်းအဓိပ္ပာယ်၊ Character အသက်နှင့် Dialogue ကို အတည်ပြုရန် လိုနိုင်သည်။",
        "story_analysis": {
            "logline": story[:700], "theme": "User အတည်ပြုရန်",
            "protagonist_goal": "ဇာတ်လမ်းအကျဉ်းမှ အတည်ပြုရန်",
            "central_conflict": "ဇာတ်လမ်းအကျဉ်းမှ အတည်ပြုရန်",
            "stakes": "ဇာတ်လမ်းအကျဉ်းမှ အတည်ပြုရန်",
            "turning_point": "ဇာတ်လမ်းအကျဉ်းမှ အတည်ပြုရန်",
            "ending": "ဇာတ်လမ်းအကျဉ်းမှ အတည်ပြုရန်",
            "assumptions_to_confirm": ["ဇာတ်ကောင်အသက်၊ ရုပ်ရည်၊ ဆက်ဆံရေး", "တိကျသော Dialogue", "Scene တစ်ခုစီ၏ တည်နေရာနှင့် အချိန်"]
        },
        "expanded_story": story + "\n\nPRODUCTION STORY BEAT OUTLINE (Template Mode)\n" + "\n".join(
            f"{i+1}. {title}: {rule}\n   Source fact: {sentences[min(len(sentences)-1, int(i * len(sentences) / len(beats)))]}"
            for i, (title, rule) in enumerate(beats)
        ),
        "characters": characters, "locations": locations, "props": [{k: v for k, v in prop.items() if k != "keyword"} for prop in props],
        "scenes": scenes, "quality_report": validate_package({"characters": characters, "locations": locations, "scenes": scenes}, duration)
    }


def validate_package(package: dict[str, Any], duration: int) -> dict[str, Any]:
    """Deterministic structural QC; human review is still required for story quality."""
    scenes = package.get("scenes") or []
    character_rows = package.get("characters") or []
    location_rows = package.get("locations") or []
    character_ids = [str(x.get("id") or "") for x in character_rows]
    location_ids = [str(x.get("id") or "") for x in location_rows]
    characters, locations = set(character_ids), set(location_ids)
    issues: list[str] = []
    warnings: list[str] = []
    expected = math.ceil(duration / 8)
    if len(scenes) != expected:
        issues.append(f"Scene count {len(scenes)} များသည်; {expected} ခု လိုအပ်သည်။")
    if not character_rows:
        warnings.append("Character Bible မရှိပါ။ Character continuity ကို စစ်ဆေးရန် ခက်ခဲနိုင်သည်။")
    if not location_rows:
        issues.append("Location Bible အနည်းဆုံးတစ်ခု လိုအပ်သည်။")
    if len(character_ids) != len(characters):
        issues.append("Character ID ထပ်နေသည်။ ID တစ်ခုစီ မတူညီရပါ။")
    if len(location_ids) != len(locations):
        issues.append("Location ID ထပ်နေသည်။ ID တစ်ခုစီ မတူညီရပါ။")
    total = 0
    expected_start = 0
    for i, scene in enumerate(scenes):
        sid = str(scene.get("scene_id") or f"Scene {i+1}")
        try:
            seconds = int(scene.get("duration_seconds") or 0)
            start = int(scene.get("start_seconds") or 0)
        except (TypeError, ValueError):
            issues.append(f"{sid}: timing ကိန်းဂဏန်းမမှန်ပါ။")
            continue
        if seconds < 1:
            issues.append(f"{sid}: duration သည် 1 second အနည်းဆုံးရှိရမည်။")
        if seconds > 8:
            issues.append(f"{sid}: 8 seconds ထက်ရှည်နေသည်။")
        if start != expected_start:
            issues.append(f"{sid}: timeline မဆက်စပ်ပါ။ {expected_start}s မှ စရမည်။")
        expected_start += seconds
        total += seconds
        if scene.get("location_id") not in locations:
            issues.append(f"{sid}: Location ID မရှိ/မမှန်ပါ။")
        ids = scene.get("character_ids") or []
        if not ids:
            warnings.append(f"{sid}: Character ID မသတ်မှတ်ထားပါ။")
        for cid in ids:
            if cid not in characters:
                issues.append(f"{sid}: {cid} ကို Character Bible မှ မတွေ့ပါ။")
        for field, label in (("action", "မြင်သာသော Action"), ("dramatic_purpose", "ဇာတ်လမ်းရည်ရွယ်ချက်")):
            if not str(scene.get(field) or "").strip():
                warnings.append(f"{sid}: {label} မဖြည့်ရသေးပါ။")
        if len(scene.get("continuity") or []) < 2:
            warnings.append(f"{sid}: အရင်/နောက် Scene ချိတ်ဆက်မှုကို ပြန်စစ်ပါ။")
        if not str(scene.get("shot_size") or "").strip():
            warnings.append(f"{sid}: Shot Size မရှိပါ။")
        if not str(scene.get("lighting") or "").strip():
            warnings.append(f"{sid}: Lighting plan မရှိပါ။")
    if total != duration:
        issues.append(f"Timeline စုစုပေါင်း {total}s ဖြစ်နေသည်; {duration}s ဖြစ်ရမည်။")
    issues = list(dict.fromkeys(issues))
    warnings = list(dict.fromkeys(warnings))
    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "scene_count": len(scenes),
        "total_seconds": total,
        "duration_seconds": duration,
        "continuity_review_required": bool(warnings),
        "quality_scope": "Structural validation only; human review is required for story logic, dialogue, performance and visual quality."
    }



VISUAL_STYLE_GUIDES = {
 "Realistic cinematic": "photorealistic live-action, physically plausible skin and materials, naturalistic performances, restrained film color grade",
 "Hollywood blockbuster": "large-scale cinematic composition, motivated dramatic lighting, controlled spectacle, polished live-action production design",
 "Neo-noir": "deep shadow, motivated practical lights, selective highlights, urban tension, noir contrast, restrained desaturated palette",
 "Film noir": "black-and-white high-contrast chiaroscuro, hard key light, expressive shadows, smoky atmosphere where appropriate",
 "Indie naturalism": "observational framing, natural available light, lived-in production design, subtle performances, restrained grade",
 "Documentary realism": "credible documentary camera, available light, grounded environments, observational movement, no glossy fantasy look",
 "Found-footage horror": "diegetic handheld camera, imperfect framing, realistic exposure, grounded practical lighting, sustained spatial geography",
 "Period drama": "historically coherent wardrobe, props, architecture and materials for the specified era; no anachronisms",
 "Historical epic": "period-accurate production design, layered wide compositions, naturalistic spectacle, consistent historically informed costume",
 "Wuxia": "stylized martial-arts choreography, elegant readable movement, period Chinese visual design, controlled wire-like movement only if requested",
 "Xianxia fantasy": "Chinese immortal-fantasy visual language, ethereal atmosphere, ornate original costumes, restrained magical VFX with consistent rules",
 "Chinese costume drama": "coherent Chinese historical-inspired architecture, hair, garments and props; distinguish fantasy from strict historical realism",
 "Thai lakorn drama": "expressive contemporary melodrama, Thai cultural context and wardrobe, polished television-drama lighting",
 "Myanmar traditional drama": "Myanmar cultural authenticity in clothing, architecture, gestures and props, with the selected era respected",
 "K-drama polished realism": "polished contemporary Korean drama cinematography, clean skin tones, carefully controlled highlights, emotionally precise close-ups",
 "Japanese cinema realism": "restrained composition, naturalistic performance, careful negative space and motivated light",
 "Bollywood musical spectacle": "vivid color, choreographed visual scale and expressive movement; add musical spectacle only where story calls for it",
 "Gritty crime thriller": "grounded locations, practical light sources, tactile textures, controlled handheld or deliberate tracking, muted palette",
 "Psychological thriller": "subjective framing, negative space, controlled focus, visual tension and motivated shifts in camera distance",
 "Gothic horror": "old-world textures, layered shadow, motivated candle or moonlight, oppressive architecture, no arbitrary gore",
 "Supernatural horror": "grounded physical world with restrained supernatural cues, stable lighting logic, controlled reveal timing",
 "Dark fantasy": "coherent original fantasy design, deep tonal contrast, tactile materials, motivated magical effects",
 "High fantasy epic": "grand readable environments, consistent world-building, designed costumes and props, cinematic scale without random detail",
 "Magical realism": "everyday believable environments with one subtle extraordinary element, understated effects and natural performances",
 "Cyberpunk neon": "night-city reflections, practical neon sources, controlled cyan-magenta accents, readable faces and coherent futuristic props",
 "Science fiction hard realism": "functional engineering, physically coherent technology, restrained VFX and plausible light interaction",
 "Space opera": "grand cosmic scale, clear silhouettes, designed spacecraft and practical-looking light sources",
 "Post-apocalyptic": "weathered materials, scarcity-driven props, coherent environmental decay and practical survival clothing",
 "Dieselpunk": "industrial retro-futurist machinery, aged metal, period-consistent silhouettes and smoke only when motivated",
 "Steampunk": "brass, leather, gears and Victorian-inspired retro-tech used consistently, functional prop design",
 "Western frontier": "frontier landscapes, weathered materials, motivated sunlight, era-coherent clothing and props",
 "Romantic soft-focus": "gentle diffusion, warm skin tones, delicate highlights and emotionally motivated shallow depth of field without losing continuity",
 "Vintage 1970s film": "1970s film-stock character, restrained grain, era-appropriate palette and production design",
 "1980s retro film": "1980s lens and color character, era-appropriate props and wardrobe, controlled period texture",
 "1990s nostalgic film": "1990s film color response, natural grain, era-coherent props and grounded nostalgic mood",
 "Black-and-white monochrome": "true monochrome tonal separation, expressive luminance contrast, no color accents",
 "Technicolor classic": "rich controlled primary colors, classic studio composition and era-coherent design",
 "2D cinematic animation": "hand-designed 2D animation, deliberate line weight, consistent character model sheets, layered backgrounds and authored motion",
 "Anime-inspired animation": "original anime-inspired design, consistent line art, expressive but controlled faces, authored cel shading and intentional motion",
 "Japanese anime cel": "clean cel-shaded forms, clear line hierarchy, designed key poses, coherent anime backgrounds and consistent model proportions",
 "Watercolor animation": "translucent watercolor washes, visible paper texture, soft pigment edges and stable character designs",
 "Hand-painted animation": "painted frame aesthetic, consistent brushwork, carefully controlled palette and designed movement",
 "Studio Ghibli-inspired original animation": "original hand-painted Japanese fantasy animation aesthetic, natural environments, gentle observational movement; do not copy any existing character or shot",
 "European storybook illustration": "original illustrated storybook shapes, textured paint, graphic silhouettes and carefully composed backgrounds",
 "Disney-like family 3D (original characters)": "expressive stylized 3D family animation, appealing silhouettes, polished materials and consistent original character models",
 "Pixar-like stylized 3D (original characters)": "high-quality stylized 3D character acting, appealing shapes, nuanced materials and original non-franchise designs",
 "Stylized 3D animation": "consistent stylized 3D geometry, designed material response, stable proportions and clear keyframe-like motion",
 "Photorealistic CGI": "photoreal CGI shading, accurate material response, physically plausible lighting, coherent rendering and camera optics",
 "Unreal Engine cinematic": "real-time-engine cinematic realism, physically based materials, volumetric light only when motivated, controlled depth of field",
 "Claymation stop-motion": "tactile clay surfaces, miniature-scale lighting, frame-by-frame stop-motion cadence and consistent handcrafted models",
 "Puppet stop-motion": "physical puppet materials, miniature sets, frame-by-frame motion, consistent rig and set geography",
 "Paper cut-out animation": "layered paper shapes, visible paper fibers, cut edges, multiplane depth and deliberate limited movement",
 "Laika-style stop-motion (original design)": "handcrafted stop-motion feature aesthetic, tactile miniature sets and expressive original puppets; do not copy existing characters",
 "Comic-book ink": "bold ink contours, graphic shadow shapes, selective halftone texture and stable panel-like composition",
 "Graphic novel": "cinematic graphic-novel composition, intentional ink lines, controlled color blocks and consistent character drawing",
 "Western comic art": "confident contour lines, dramatic inking, clear anatomy and authored panel-like framing",
 "Manga black-and-white": "black-and-white manga linework, screentone values, expressive but consistent faces and clean silhouette readability",
 "Manhwa color webtoon": "polished vertical-webtoon color rendering, clean contours, controlled gradients and consistent character proportions",
 "Motion-comic": "illustrated source art with restrained parallax, selective camera movement and limited animated elements",
 "Pixel art": "consistent pixel grid, deliberate limited palette, readable pixel silhouettes and no accidental smoothing",
 "Voxel 3D": "voxel-based geometry, consistent block scale, readable lighting and stable object proportions",
 "Low-poly 3D": "intentional low-polygon geometry, faceted surfaces, coherent color blocks and consistent scale",
 "Isometric diorama": "isometric camera, miniature diorama construction, consistent perspective and carefully placed small-scale props",
 "Miniature model photography": "macro lens on practical miniatures, believable scale cues, shallow depth of field and physically coherent lighting",
 "LEGO-like brick animation": "interlocking toy-brick material and proportions, stop-motion-like movement and consistent original builds",
 "Puppet theatre": "visible handcrafted puppet aesthetic, stage-like composition, controlled practical lighting and consistent puppet movement",
 "Shadow-puppet art": "flat cut-out silhouettes, translucent screen glow, theatrical backlight and deliberate shadow movement",
 "Traditional Burmese painting": "Myanmar traditional painting vocabulary, culturally coherent motifs, flat decorative space and hand-rendered pigment texture",
 "Chinese ink wash painting": "ink wash brushwork, expressive negative space, soft ink diffusion and limited mineral color",
 "Japanese sumi-e": "economical ink brushwork, expressive negative space, monochrome ink values and deliberate strokes",
 "Ukiyo-e woodblock": "flat woodblock-print color fields, bold outlines, stylized perspective and visible print texture",
 "Thai traditional mural": "Thai mural-inspired linework, decorative patterning and culturally informed color and costume design",
 "South Asian miniature painting": "fine miniature-painting detail, flattened spatial hierarchy, patterned textiles and coherent regional motifs",
 "Persian miniature art": "intricate miniature painting, decorative architecture, patterned surfaces and flattened poetic spatial design",
 "Art nouveau": "organic flowing contours, botanical ornament, elegant asymmetry and period-informed decorative composition",
 "Art deco": "geometric symmetry, streamlined silhouettes, metallic accents and controlled luxury-era design",
 "Impressionist painting": "visible painterly brushwork, broken color, atmospheric light and impressionistic rather than photoreal surfaces",
 "Expressionist painting": "emotionally distorted shapes, bold directional strokes, deliberate color tension and expressive perspective",
 "Surrealist cinema": "dream logic, precise impossible imagery, controlled surreal transitions and coherent visual motifs",
 "Oil-painting animation": "visible oil-paint texture, layered brush strokes, stable painted forms and art-directed movement",
 "Pastel illustration": "soft pastel grain, gentle edges, muted color transitions and consistent illustrated anatomy",
 "Charcoal sketch": "charcoal texture, expressive line, tonal smudging and high-contrast hand-drawn composition",
 "Pencil storyboard": "clear pencil line, storyboard readability, simple value blocking and explicit action staging",
 "Paper collage": "layered cut-paper textures, visible edges, mixed-media composition and deliberate depth",
 "Retro-futurism": "future imagined through a coherent historical design language, analog controls and intentional retro materials",
 "Vaporwave": "surreal retro-digital palette, synthetic gradients, nostalgic architecture and stylized composition",
 "Synthwave": "neon sunset palette, graphic rim lights, retro-futurist silhouettes and deliberate high contrast",
 "Y2K digital aesthetic": "early-digital-era glossy materials, chrome accents, playful futuristic geometry and coherent period design",
 "Luxury fashion editorial": "high-end fashion photography, deliberate pose, controlled studio lighting, fabric detail and editorial composition",
 "Beauty commercial": "clean beauty lighting, accurate skin texture, macro detail and polished but believable product framing",
 "Food macro ASMR": "macro food texture, appetizing realistic light, clear tactile actions and no distracting visual clutter",
 "Satisfying process ASMR": "precise tactile close-ups, deliberate repeatable hand action, clear material textures and calm controlled framing",
 "Nature documentary": "credible natural-history cinematography, observational camera, natural light and realistic animal/environment behavior",
 "Wildlife cinematic": "long-lens wildlife framing, physically plausible animal behavior, natural habitats and restrained color grading",
 "Travel-film aesthetic": "place-specific visual detail, motivated natural light, coherent travel-documentary camera language",
 "Music-video stylized": "rhythmic composition and deliberate movement, visually coherent palette and effects synchronized to intended mood",
 "Dreamlike soft fantasy": "soft atmospheric depth, subtle magical imagery, gentle light bloom and stable character/environment design",
 "Minimalist architectural film": "precise architectural geometry, clean lines, controlled daylight and deliberate camera movement"
}

def _style_direction(style: str) -> str:
    guide = VISUAL_STYLE_GUIDES.get(style)
    if guide:
        return guide
    return f"Honor the exact requested art direction: {style}. Make its defining materials, linework/rendering, color logic, lighting, motion language and production design explicit; do not default to generic photorealistic live action."


def generate_gemini_package(project: dict[str, Any]) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key မထည့်ရသေးပါ။")
    duration = int(project["duration_seconds"])
    count = math.ceil(duration / 8)
    prompt = f"""
You are a professional screenwriter, script editor, production designer, cinematographer, continuity supervisor and AI-video prompt engineer.
Create a production package as JSON. All explanations and dialogue should be in {project.get('language','Burmese')}; all image/video prompts must be detailed English.
Do not claim media has been rendered. Character and location reference prompts are instructions for an external image generator.
Return exactly this structure:
{{
"story_analysis":{{"logline":"...","theme":"...","protagonist_goal":"...","central_conflict":"...","stakes":"...","turning_point":"...","ending":"...","assumptions_to_confirm":[]}},
"expanded_story":"complete coherent short-film story",
"characters":[{{"id":"CHAR-001","name":"...","role":"...","age":"...","appearance":"...","wardrobe":[{{"id":"WARD-001-01","description":"..."}}],"expressions":[],"movement":"...","voice":"...","reference_prompt":"detailed English character-sheet prompt, front/side/back and expressions"}}],
"locations":[{{"id":"LOC-A","name":"...","environment_lock":"...","lighting_states":[],"reference_prompt":"detailed English location reference sheet prompt with wide/reverse/layout views"}}],
"props":[{{"id":"PROP-001","name":"...","description":"...","continuity":"..."}}],
"scenes":[{{"scene_id":"SC-001","clip_number":1,"start_seconds":0,"duration_seconds":8,"beat_title":"...","dramatic_purpose":"...","location_id":"LOC-A","character_ids":["CHAR-001"],"wardrobe_ids":["WARD-001-01"],"prop_ids":[],"action":"specific visible action","dialogue":"exact speaker-tagged dialogue","shot_size":"...","camera_angle":"...","camera_movement":"...","lighting":"...","sound":"...","continuity":["..."]}}]
}}
Need exactly {count} scenes, total duration {duration} seconds, each 8 seconds except final remainder. Use 8-second maximum. Character/location IDs must be stable and references linked. Every scene must move the plot, not just show generic scenery. Build a logical beginning, escalation, turning point, consequence and ending suitable to the duration. CONTINUITY IS MANDATORY: Treat the expanded story as one film, not unrelated prompt cards. For every scene specify what changed in the prior scene, the immediate cause of this scene, one visible action with a clear beginning and result, and what information/emotion/object/position carries into the next scene. Never introduce a new location, character, costume, prop, supernatural event, time jump, or genre shift without a story-supported transition. Maintain geography and screen direction; if a character walks from A to B, show the journey/exit/arrival across adjacent scenes. Reuse character and location IDs rather than inventing variants. Dialogue must be assigned to a named speaker and listener with short speakable lines; if none is supplied, write dialogue consistent with character goals and label it as generated. Each scene must include a continuity note referencing prior setup and next-scene carryover. Vary shot size and camera movement for story purpose; avoid repeated generic close-ups and random camera moves. Respect selected visual style as a hard medium lock in all reference prompts and all scenes. Avoid unsupported assumptions; put them in assumptions_to_confirm. Dialogue must be short enough to speak naturally within clip duration. Cultural setting must match user selection.
Title: {project.get('title')}
Genre: {project.get('genre')}
Visual style: {project.get('visual_style')}\nSTYLE EXECUTION GUIDE: {_style_direction(str(project.get('visual_style') or 'Realistic cinematic'))}\nSTYLE LOCK: Every character sheet, location sheet, image prompt and video prompt must use the same selected visual medium. Do not blend styles or drift back to photorealism unless selected.
Culture: {project.get('culture')}
Language: {project.get('language')}
Aspect ratio: {project.get('aspect_ratio')}
Sound mode: {project.get('sound_mode')}
Duration: {duration}
Story idea: {project.get('story_idea')}
Existing character bible (binding): {project.get('character_bible') or 'Infer plausible characters and mark uncertain details.'}
Existing location bible (binding): {project.get('location_bible') or 'Infer plausible locations and mark uncertain details.'}
Continuity constraints: {project.get('continuity_notes') or 'Maintain identity, wardrobe, props, spatial geography and screen direction.'}
"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=32768))
    package = parse_json_response(response.text or "")
    for key in ("story_analysis", "characters", "locations", "scenes"):
        if key not in package:
            raise ValueError(f"Gemini package missing {key}")
    if not isinstance(package["scenes"], list) or len(package["scenes"]) != count:
        raise ValueError(f"Gemini scene count must be {count}")
    package["schema_version"] = 2
    package["generation_source"] = "gemini"
    package["notice"] = "Gemini AI ဖြင့် ဇာတ်လမ်းနှင့် Production Package ထုတ်လုပ်ထားသည်။"
    # Normalize exact timing from project so durations never drift.
    for i, scene in enumerate(package["scenes"]):
        scene["scene_id"] = f"SC-{i+1:03d}"
        scene["clip_number"] = i+1
        scene["start_seconds"] = i*8
        scene["duration_seconds"] = min(8, duration-i*8)
        scene.setdefault("continuity", [])
        scene.setdefault("character_ids", [])
        scene.setdefault("location_id", (package["locations"][0] if package["locations"] else {}).get("id"))
    package["quality_report"] = validate_package(package, duration)
    return package


def generate_production_package(project: dict[str, Any]) -> dict[str, Any]:
    mode = str(project.get("generation_mode") or "auto").lower()
    if mode not in MODES:
        mode = "auto"
    if mode == "template":
        return generate_template_package(project)
    try:
        package = generate_gemini_package(project)
        if package["quality_report"]["issues"]:
            # Keep output, but expose concrete warnings for user review.
            package["notice"] = str(package.get("notice","")) + " Quality Check မှာ ပြင်ဆင်ရန် အချက်များရှိသည်။"
        return package
    except Exception as exc:
        if mode == "gemini":
            message = str(exc)
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                raise HTTPException(429, "Gemini quota ပြည့်နေပါသည်။ Template Mode ကို ရွေးနိုင်သည်။")
            if "503" in message or "UNAVAILABLE" in message:
                raise HTTPException(503, "Gemini model ယာယီမရနိုင်ပါ။ Auto Mode ဖြင့် Template fallback သို့မဟုတ် Template Mode ကို ရွေးပါ။")
            raise HTTPException(502, f"Gemini Production Package မအောင်မြင်ပါ။ API key/model/quota ကို စစ်ပါ။ ({message[:160]})")
        package = generate_template_package(project)
        package["generation_source"] = "template_fallback"
        package["notice"] = "Gemini ကို ခေါ်ရာတွင် အမှားဖြစ်သဖြင့် Template Mode သို့ အလိုအလျောက်ပြောင်းထားသည်။ " + str(exc)[:180]
        return package


def compile_scene_prompts(project: dict[str, Any], package: dict[str, Any]) -> list[dict[str, Any]]:
    chars = {c.get("id"): c for c in package.get("characters", [])}
    locs = {x.get("id"): x for x in package.get("locations", [])}
    props = {x.get("id"): x for x in package.get("props", [])}
    out = []
    for i, scene in enumerate(package.get("scenes", [])):
        char_refs = [chars[cid] for cid in scene.get("character_ids", []) if cid in chars]
        loc = locs.get(scene.get("location_id"), {})
        wardrobe = ", ".join(str(x.get("id")) + ": " + str(x.get("description")) for c in char_refs for x in c.get("wardrobe", []) if x.get("id") in (scene.get("wardrobe_ids") or []))
        prop_text = ", ".join(str(props[x].get("id")) + ": " + str(props[x].get("description")) for x in scene.get("prop_ids", []) if x in props)
        char_text = "; ".join(f"{c.get('id')} {c.get('name')}: {c.get('appearance')}; preserve exact face, age, hair and proportions" for c in char_refs)
        location_text = f"{loc.get('id','LOC-?')} {loc.get('name','approved location')}: {loc.get('environment_lock','preserve established layout')}"
        action = str(scene.get("action") or scene.get("dramatic_purpose") or "Perform the scene action clearly.")
        continuity_text = " ".join(str(x) for x in (scene.get("continuity") or []) if str(x).strip())
        dialogue = str(scene.get("dialogue") or "")
        shot = str(scene.get("shot_size") or "medium shot")
        angle = str(scene.get("camera_angle") or "eye-level")
        movement = str(scene.get("camera_movement") or "subtle controlled camera movement")
        lighting = str(scene.get("lighting") or "motivated cinematic lighting")
        culture = str(project.get("culture") or "as established in references")
        style = str(project.get("visual_style") or "Realistic cinematic")
        style_direction = _style_direction(style)
        ratio = str(project.get("aspect_ratio") or "16:9")
        char_urls = ", ".join(f"{ch.get('id')}: {ch.get('reference_url')}" for ch in char_refs if ch.get("reference_url"))
        loc_url = loc.get("reference_url") or "manually attach the saved location reference image"
        common = f"Approved reference assets: {', '.join(ch.get('id','') for ch in char_refs)} and {loc.get('id','LOC-?')}. Character reference URLs if accessible: {char_urls or 'no URL saved; manually attach reference images'}. Location reference URL if accessible: {loc_url}. Character references: {char_text}. Location reference: {location_text}. Wardrobe lock: {wardrobe or 'use approved character wardrobe'}. Props: {prop_text or 'only story-required props'}. Culture: {culture}. Visual style: {style}. Style execution: {style_direction}. Apply the selected medium consistently to faces, materials, edges/linework, shading/rendering, lighting, motion, background design and color grade. Do not switch to another visual medium. Aspect ratio {ratio}. Keep faces, ages, hairstyles, body proportions, wardrobe, architecture, object positions and screen direction consistent. No additional characters, no text, no subtitles, no logos or watermark."
        image_prompt = f"Create a cinematic still for {scene.get('scene_id')}. {common} Dramatic purpose: {scene.get('dramatic_purpose', '')}. Action and dramatic purpose: {action}. Continuity constraints: {continuity_text}. Shot composition: {shot}, {angle}. Lighting and color: {lighting}. Mood should support {scene.get('dramatic_purpose','the story beat')}. One coherent frame, believable anatomy and physically plausible staging."
        video_prompt = f"Use the saved reference images for {', '.join(c.get('id','') for c in char_refs) or 'the approved characters'} and location {loc.get('id','LOC-?')}. Create one continuous {scene.get('duration_seconds',8)}-second shot. Story beat purpose: {scene.get('dramatic_purpose', '')}. Action over time: {action}. Continuity with prior and next scene: {continuity_text}. Keep one continuous action with clear start and end; do not add unsupported story events. Dialogue in {project.get('language','Burmese')}: {dialogue if dialogue and dialogue.lower() not in {'none','n/a','မရှိ'} else 'No spoken dialogue; use natural environmental sound only.'} Shot: {shot}, {angle}. Camera movement: {movement}. Lighting: {lighting}. Natural facial expressions and body movement, plausible timing, clear speaker/listener behavior, no accidental lip movement for silent characters. {common}"
        out.append({
            "clip_number": i+1, "scene_id": scene.get("scene_id", f"SC-{i+1:03d}"),
            "start_seconds": int(scene.get("start_seconds", i*8)),
            "duration_seconds": int(scene.get("duration_seconds", min(8, int(project["duration_seconds"])-i*8))),
            "beat_title": str(scene.get("beat_title") or f"Scene {i+1}"),
            "dramatic_purpose": str(scene.get("dramatic_purpose") or ""),
            "character_ids": scene.get("character_ids", []), "location_id": scene.get("location_id"),
            "dialogue": dialogue, "action": action, "image_prompt": image_prompt,
            "visual_prompt": video_prompt, "negative_prompt": NEGATIVE,
            "continuity_checklist": [str(x) for x in (scene.get("continuity") or [])][:8] + [
                f"Use approved character reference(s): {', '.join(c.get('id','') for c in char_refs) or 'confirm character references'}.",
                f"Use approved location reference: {loc.get('id','LOC-?')}.",
                "Verify wardrobe, prop positions, screen direction and time-of-day continuity."
            ]
        })
    return out


@app.get("/health")
def health():
    return {"ok": True, "service": "AI Film Studio API", "gemini_configured": bool(GEMINI_API_KEY),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY),
        "model": GEMINI_MODEL, "template_mode_available": True}


@app.get("/api/projects")
def list_projects(user: dict = Depends(current_user)):
    return db_request("GET", "film_projects",
        params={"select": "*", "user_id": user_filter(user), "order": "updated_at.desc"})


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectIn, user: dict = Depends(current_user)):
    data = payload.model_dump()
    if data["generation_mode"] not in MODES:
        raise HTTPException(422, "generation_mode သည် template, gemini သို့မဟုတ် auto ဖြစ်ရမည်။")
    data["user_id"] = user["id"]
    data["clips"] = []
    data["production_package"] = {}
    result = db_request("POST", "film_projects", payload=data)
    if not result:
        raise HTTPException(502, "Project သိမ်းမရပါ။")
    return result[0]


@app.get("/api/projects/{pid}")
def get_project(pid: str, user: dict = Depends(current_user)):
    return get_owned_project(pid, user)


@app.patch("/api/projects/{pid}")
def update_project(pid: str, payload: dict[str, Any], user: dict = Depends(current_user)):
    existing = get_owned_project(pid, user)
    allowed = {"title", "genre", "duration_seconds", "visual_style", "workflow", "aspect_ratio",
        "language", "culture", "generation_mode", "sound_mode", "story_idea", "character_bible",
        "location_bible", "continuity_notes"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(422, "မသိသော Project field: " + ", ".join(sorted(unknown)[:8]))
    data = dict(payload)
    if not data:
        raise HTTPException(400, "ပြင်ဆင်ရန် field မရှိပါ။")
    candidate = {key: existing.get(key) for key in allowed}
    candidate.update(data)
    try:
        validated = ProjectIn.model_validate(candidate)
    except Exception as exc:
        raise HTTPException(422, "Project settings မမှန်ပါ။ Title, Story Idea (အနည်းဆုံး 10 လုံး)၊ duration 8–300 seconds နှင့် settings များကို စစ်ပါ။") from exc
    data = {key: value for key, value in validated.model_dump().items() if key in data}
    if "generation_mode" in data and data["generation_mode"] not in MODES:
        raise HTTPException(422, "generation_mode သည် template, gemini သို့မဟုတ် auto ဖြစ်ရမည်။")
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = db_request("PATCH", "film_projects", params={"id": f"eq.{pid}", "user_id": user_filter(user)}, payload=data)
    if not rows:
        raise HTTPException(502, "Project ပြင်ဆင်သိမ်းဆည်းမရပါ။")
    return rows[0]


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str, user: dict = Depends(current_user)):
    get_owned_project(pid, user)
    db_request("DELETE", "film_projects", params={"id": f"eq.{pid}", "user_id": user_filter(user)}, payload=None)
    return None


@app.post("/api/projects/{pid}/analyze")
def analyze_project(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    package = generate_production_package(project)
    persist_package(pid, user, package)
    return {"project_id": pid, "generation_source": package.get("generation_source"),
        "notice": package.get("notice", ""), "production_package": package}


@app.get("/api/projects/{pid}/production")
def get_production(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    return project.get("production_package") or {}


@app.patch("/api/projects/{pid}/production")
def update_production(pid: str, payload: dict[str, Any], user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    package = project.get("production_package") or {}
    # Allow editing the approved package, but never accept arbitrary unrelated top-level keys.
    for key in ("story_analysis", "expanded_story", "characters", "locations", "props", "scenes"):
        if key in payload:
            package[key] = payload[key]
    package["quality_report"] = validate_package(package, int(project["duration_seconds"]))
    persist_package(pid, user, package)
    return package


@app.post("/api/projects/{pid}/prompts")
def generate_prompts(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    package = project.get("production_package") or {}
    if not package.get("scenes"):
        package = generate_production_package(project)
    clips = compile_scene_prompts(project, package)
    updated = db_request("PATCH", "film_projects",
        params={"id": f"eq.{pid}", "user_id": user_filter(user)},
        payload={"clips": clips, "production_package": package, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not updated:
        raise HTTPException(502, "Prompt များကို database ထဲ သိမ်းမရပါ။")
    return {"project_id": pid, "target_duration_seconds": project["duration_seconds"],
        "clip_count": len(clips), "generation_source": package.get("generation_source"), "clips": clips}


@app.post("/api/projects/{pid}/generate")
def generate(pid: str, user: dict = Depends(current_user)):
    # Backwards-compatible endpoint for existing UI clients.
    project = get_owned_project(pid, user)
    package = generate_production_package(project)
    clips = compile_scene_prompts(project, package)
    updated = db_request("PATCH", "film_projects",
        params={"id": f"eq.{pid}", "user_id": user_filter(user)},
        payload={"clips": clips, "production_package": package, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not updated:
        raise HTTPException(502, "Production Package ကို database ထဲ သိမ်းမရပါ။")
    return {"project_id": pid, "target_duration_seconds": project["duration_seconds"],
        "clip_count": len(clips), "generation_source": package.get("generation_source"),
        "production_package": package, "clips": clips}


@app.get("/api/projects/{pid}/clips")
def list_clips(pid: str, user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    return project.get("clips") or []


@app.get("/api/projects/{pid}/export")
def export(pid: str, format: str = Query(default="json", pattern="^(json|txt)$"), user: dict = Depends(current_user)):
    project = get_owned_project(pid, user)
    clips = project.get("clips") or []
    package = project.get("production_package") or {}
    if format == "json":
        return JSONResponse({"project": project, "production_package": package, "clips": clips},
            headers={"Content-Disposition": f'attachment; filename="film-project-{pid}.json"'})
    lines = [f"# {project['title']}", f"Mode: {project.get('generation_mode','auto')}",
        f"Source: {package.get('generation_source','not generated')}",
        f"Duration: {project['duration_seconds']}s", "", "## CHARACTER BIBLE"]
    for c in package.get("characters", []):
        lines += [f"### {c.get('id')} — {c.get('name')}", str(c.get("appearance","")), "REFERENCE PROMPT:", str(c.get("reference_prompt","")), ""]
    lines += ["## LOCATION BIBLE"]
    for loc in package.get("locations", []):
        lines += [f"### {loc.get('id')} — {loc.get('name')}", str(loc.get("environment_lock","")), "REFERENCE PROMPT:", str(loc.get("reference_prompt","")), ""]
    lines += ["## STORY ANALYSIS", json.dumps(package.get("story_analysis", {}), ensure_ascii=False, indent=2), "",
        "## SCENE PROMPTS"]
    for clip in clips:
        lines += [f"### {clip.get('scene_id')} | {clip.get('start_seconds')}s | {clip.get('duration_seconds')}s",
            str(clip.get("beat_title","")), "CHARACTER IDS: " + ", ".join(clip.get("character_ids", [])),
            "LOCATION ID: " + str(clip.get("location_id","")), "DIALOGUE:", str(clip.get("dialogue","")),
            "", "IMAGE PROMPT:", str(clip.get("image_prompt","")), "", "VIDEO PROMPT:", str(clip.get("visual_prompt","")),
            "", "NEGATIVE PROMPT:", str(clip.get("negative_prompt","")), "", "CONTINUITY CHECKLIST:",
            *[f"- {x}" for x in clip.get("continuity_checklist", [])], ""]
    return PlainTextResponse("\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="film-project-{pid}.txt"'})
