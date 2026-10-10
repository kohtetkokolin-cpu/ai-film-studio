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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
    db_request("PATCH", "film_projects",
        params={"id": f"eq.{pid}", "user_id": user_filter(user)},
        payload={"production_package": package, "updated_at": datetime.now(timezone.utc).isoformat()})


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
    # Treat each non-empty line as a reference entry; don't pretend to infer identities perfectly.
    for line in text.splitlines():
        line = re.sub(r"^[\s•*\-\d.)]+", "", line).strip()
        if not line:
            continue
        name = re.split(r"\s*[—:：|]\s*", line, maxsplit=1)[0].strip()
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
        name = re.split(r"\s*[—:：|]\s*", line, maxsplit=1)[0].strip()
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
    for i, name in enumerate(names):
        characters.append({
            "id": f"CHAR-{i+1:03d}", "name": name,
            "role": "ဇာတ်ကောင်အခန်းကဏ္ဍကို Story/Character Bible အတည်ပြုချိန်တွင် ဖြည့်ရန်",
            "age": "User အတည်ပြုရန်", "appearance": "မျက်နှာ၊ အသားအရောင်၊ ဆံပင်၊ ကိုယ်ခန္ဓာနှင့် မှတ်မိစေသောအမှတ်အသားကို သတ်မှတ်ရန်",
            "wardrobe": [{"id": f"WARD-{i+1:03d}-01", "description": "ဇာတ်လမ်းနှင့် ယဉ်ကျေးမှုကိုက်ညီသော ဝတ်စုံကို အတည်ပြုရန်"}],
            "expressions": ["neutral", "happy", "angry", "sad", "afraid", "surprised"],
            "movement": "Natural, physically plausible movement; preserve identity and body proportions.",
            "voice": "Dialogue voice profile requires user confirmation.",
            "reference_prompt": f"Create a professional character reference sheet for {name}, reference ID CHAR-{i+1:03d}. Use a clean neutral studio background and consistent full-body front, side, and back views, plus clear face expression studies. Show age and appearance only as specified in the approved character bible; do not invent a definitive age or ethnicity. Same face, hairstyle, proportions, wardrobe and identifying marks across every view. No labels, watermark or extra people."
        })
    locations = []
    for i, name in enumerate(places):
        lid = f"LOC-{chr(65+i)}"
        locations.append({
            "id": lid, "name": name, "environment_lock": "တံခါး၊ ပြတင်းပေါက်၊ ပရိဘောဂ၊ လမ်းကြောင်းနှင့် အခန်းအရွယ်အစားကို Reference ထဲတွင် အတည်ပြုရန်",
            "lighting_states": ["day", "dusk", "night"],
            "reference_prompt": f"Create a cinematic environment reference sheet for {name}, location ID {lid}. Show a wide establishing view, reverse angle, and a clear spatial layout. Keep architecture, entrances, windows, furniture, materials and geography consistent. Match the selected culture and visual style; where story details are missing, use a plausible restrained design and flag it for approval. No people, text, logos or watermark."
        })
    scenes = []
    for i in range(count):
        start = i * 8
        clip_duration = min(8, duration - start)
        beat_title, beat_rule = beats[min(int(i * len(beats) / count), len(beats)-1)]
        char_ids = [c["id"] for c in characters[:2]]
        loc_id = locations[min(int(i * len(locations) / count), len(locations)-1)]["id"]
        scenes.append({
            "scene_id": f"SC-{i+1:03d}", "clip_number": i+1,
            "start_seconds": start, "duration_seconds": clip_duration,
            "beat_title": beat_title, "dramatic_purpose": beat_rule,
            "location_id": loc_id, "character_ids": char_ids,
            "wardrobe_ids": [characters[j]["wardrobe"][0]["id"] for j in range(min(len(characters),2))],
            "prop_ids": [], "action": f"Advance the supplied story: {story[:500]}",
            "dialogue": "Dialogue ကို ဇာတ်လမ်းအပြည့်နှင့် Character စရိုက်အတည်ပြုပြီးမှ ရေးရန်။",
            "shot_size": ["wide establishing shot","medium shot","close-up reaction","over-the-shoulder"][i % 4],
            "camera_angle": ["eye-level","slightly low angle","three-quarter angle"][i % 3],
            "camera_movement": ["slow push-in","gentle tracking move","locked-off reaction shot"][i % 3],
            "lighting": "Motivated cinematic lighting consistent with location, time of day, and the previous scene.",
            "sound": str(project.get("sound_mode") or "dialogue"),
            "continuity": ["Keep the same approved character faces, age, hair and wardrobe.",
                "Preserve the location layout, screen direction and prop positions.",
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
        "expanded_story": story,
        "characters": characters, "locations": locations, "props": [],
        "scenes": scenes, "quality_report": validate_package({"characters": characters, "locations": locations, "scenes": scenes}, duration)
    }


def validate_package(package: dict[str, Any], duration: int) -> dict[str, Any]:
    scenes = package.get("scenes") or []
    characters = {x.get("id") for x in package.get("characters") or []}
    locations = {x.get("id") for x in package.get("locations") or []}
    issues = []
    expected = math.ceil(duration / 8)
    if len(scenes) != expected:
        issues.append(f"Scene count {len(scenes)} များသည်; {expected} ခု လိုအပ်သည်။")
    total = 0
    for i, scene in enumerate(scenes):
        total += int(scene.get("duration_seconds") or 0)
        if scene.get("location_id") not in locations:
            issues.append(f"{scene.get('scene_id','Scene')} တွင် Location ID မရှိ/မမှန်ပါ။")
        for cid in scene.get("character_ids") or []:
            if cid not in characters:
                issues.append(f"{scene.get('scene_id','Scene')} တွင် {cid} ကို Character Bible မှ မတွေ့ပါ။")
        if int(scene.get("duration_seconds") or 0) > 8:
            issues.append(f"{scene.get('scene_id','Scene')} သည် 8 seconds ထက်ရှည်နေသည်။")
        if int(scene.get("start_seconds") or 0) != sum(int(x.get("duration_seconds") or 0) for x in scenes[:i]):
            issues.append(f"{scene.get('scene_id','Scene')} ရဲ့ timeline မဆက်စပ်ပါ။")
    if total != duration:
        issues.append(f"Timeline စုစုပေါင်း {total}s ဖြစ်နေသည်; {duration}s ဖြစ်ရမည်။")
    return {"passed": not issues, "issues": issues, "scene_count": len(scenes), "total_seconds": total}


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
Need exactly {count} scenes, total duration {duration} seconds, each 8 seconds except final remainder. Use 8-second maximum. Character/location IDs must be stable and references linked. Every scene must move the plot, not just show generic scenery. Build a logical beginning, escalation, turning point, consequence and ending suitable to the duration. Avoid unsupported assumptions; put them in assumptions_to_confirm. Dialogue must be short enough to speak naturally within clip duration. Cultural setting must match user selection.
Title: {project.get('title')}
Genre: {project.get('genre')}
Visual style: {project.get('visual_style')}
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
        dialogue = str(scene.get("dialogue") or "")
        shot = str(scene.get("shot_size") or "medium shot")
        angle = str(scene.get("camera_angle") or "eye-level")
        movement = str(scene.get("camera_movement") or "subtle controlled camera movement")
        lighting = str(scene.get("lighting") or "motivated cinematic lighting")
        culture = str(project.get("culture") or "as established in references")
        style = str(project.get("visual_style") or "Realistic cinematic")
        ratio = str(project.get("aspect_ratio") or "16:9")
        common = f"Approved reference assets: {', '.join(c.get('id','') for c in char_refs)} and {loc.get('id','LOC-?')}. Character references: {char_text}. Location reference: {location_text}. Wardrobe lock: {wardrobe or 'use approved character wardrobe'}. Props: {prop_text or 'only story-required props'}. Culture: {culture}. Visual style: {style}. Aspect ratio {ratio}. Keep faces, ages, hairstyles, body proportions, wardrobe, architecture, object positions and screen direction consistent. No additional characters, no text, no subtitles, no logos or watermark."
        image_prompt = f"Create a cinematic still for {scene.get('scene_id')}. {common} Action and dramatic purpose: {action}. Shot composition: {shot}, {angle}. Lighting and color: {lighting}. Mood should support {scene.get('dramatic_purpose','the story beat')}. One coherent frame, believable anatomy and physically plausible staging."
        video_prompt = f"Use the saved reference images for {', '.join(c.get('id','') for c in char_refs) or 'the approved characters'} and location {loc.get('id','LOC-?')}. Create one continuous {scene.get('duration_seconds',8)}-second shot. Action over time: {action}. Dialogue in {project.get('language','Burmese')}: {dialogue if dialogue and dialogue.lower() not in {'none','n/a','မရှိ'} else 'No spoken dialogue; use natural environmental sound only.'} Shot: {shot}, {angle}. Camera movement: {movement}. Lighting: {lighting}. Natural facial expressions and body movement, plausible timing, clear speaker/listener behavior, no accidental lip movement for silent characters. {common}"
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
    get_owned_project(pid, user)
    allowed = {"title", "genre", "duration_seconds", "visual_style", "workflow", "aspect_ratio",
        "language", "culture", "generation_mode", "sound_mode", "story_idea", "character_bible",
        "location_bible", "continuity_notes"}
    data = {k: v for k, v in payload.items() if k in allowed}
    if not data:
        raise HTTPException(400, "ပြင်ဆင်ရန် field မရှိပါ။")
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
