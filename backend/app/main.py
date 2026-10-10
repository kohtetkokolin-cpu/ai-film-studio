import json, math, os, sqlite3, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("AI_FILM_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("AI_FILM_DB_PATH", str(DATA_DIR / "ai_film_studio.db")))
app = FastAPI(title="AI Film Studio API", version="0.1.0", description="Standalone prompt-first film planner. No paid AI API.")
origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if os.getenv("FRONTEND_ORIGIN"): origins.append(os.environ["FRONTEND_ORIGIN"].rstrip("/"))
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET","POST","DELETE","OPTIONS"], allow_headers=["Content-Type"])

NEGATIVE = ("low resolution, blurry, pixelated, compression artifacts, inconsistent character identity, face morphing, changing age, changing hairstyle, changing clothes, inconsistent proportions, extra fingers, missing fingers, malformed hands, extra limbs, duplicated people, floating objects, warped train, bent railway tracks, flickering, jitter, stuttering motion, sudden camera jump, unintended zoom, inconsistent lighting, unwanted text, subtitles, watermark, logo, UI elements, oversaturated colors, unwanted style change")

class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    genre: str = "Drama"
    duration_seconds: int = Field(default=180, ge=8, le=7200)
    visual_style: str = "2D cinematic animation"
    workflow: str = "automatic"
    aspect_ratio: str = "16:9"
    language: str = "Burmese"
    story_idea: str = Field(min_length=10, max_length=20000)
    character_bible: str = ""
    location_bible: str = ""
    continuity_notes: str = ""

def connect():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,genre TEXT NOT NULL,duration_seconds INTEGER NOT NULL,
        visual_style TEXT NOT NULL,workflow TEXT NOT NULL,aspect_ratio TEXT NOT NULL,language TEXT NOT NULL,
        story_idea TEXT NOT NULL,character_bible TEXT NOT NULL,location_bible TEXT NOT NULL,continuity_notes TEXT NOT NULL,
        created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS clips(
        id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        clip_number INTEGER NOT NULL,start_seconds INTEGER NOT NULL,duration_seconds INTEGER NOT NULL,beat_title TEXT NOT NULL,
        visual_prompt TEXT NOT NULL,negative_prompt TEXT NOT NULL,continuity_checklist TEXT NOT NULL,
        UNIQUE(project_id,clip_number))""")

@app.on_event("startup")
def startup(): init_db()

def project_or_404(c, pid):
    row = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None: raise HTTPException(404, "Project not found")
    return dict(row)

def clip_dict(row):
    x = dict(row)
    x["continuity_checklist"] = json.loads(x["continuity_checklist"])
    return x

def build_clips(p):
    total = int(p["duration_seconds"])
    count = math.ceil(total / 8)
    sentences = [x.strip() for x in re.split(r"(?<=[.!?။])\s+", " ".join(p["story_idea"].split())) if x.strip()]
    if not sentences: sentences = ["A meaningful emotional moment from the story."]
    character = p["character_bible"].strip() or "Follow the approved character reference and preserve identity."
    location = p["location_bible"].strip() or "Keep location geometry and important props consistent."
    continuity = p["continuity_notes"].strip() or "Preserve face, age, hair, costume, prop positions, lighting direction and screen direction."
    shots = ["wide establishing shot with slow push-in","medium shot with gentle lateral tracking","emotional close-up with restrained facial acting","over-the-shoulder shot with clear eyelines","insert shot of a story-relevant prop","profile close-up with natural movement","wide emotional composition with negative space","slow pull-back revealing the emotional context"]
    clips=[]; start=0
    for i in range(count):
        duration=min(8,total-start)
        beat=sentences[i] if i<len(sentences) else "Continue the story idea with a new emotional beat: "+sentences[i%len(sentences)]
        prompt=f"""Create one {duration}-second continuous video clip for a {p['genre']} film.
CLIP: {i+1:02d}; TIMECODE: {start:03d}s–{start+duration:03d}s.
STORY BEAT: {beat}

VISUAL STYLE: {p['visual_style']}. Cinematic composition, polished animation, coherent linework and texture, expressive restrained facial acting, believable weight, natural motion arcs, consistent art direction.
CHARACTER IDENTITY LOCK: {character}
LOCATION AND PROP LOCK: {location}
CONTINUITY RULES: {continuity}

ACTION: Show one clear, readable, emotionally motivated action. Begin with a brief setup, perform the main action, then settle into a pose that can cut cleanly to the next clip. Keep movement plausible and visible within {duration} seconds.
CAMERA: {shots[i%len(shots)]}. Stable horizon, intentional framing, smooth controlled movement. Maintain screen direction across neighboring clips.
LIGHTING AND COLOR: Motivated cinematic lighting, readable faces, consistent shadow direction, controlled highlights, emotionally coherent palette.
ENVIRONMENT: Layered foreground, subject plane, and background. Only relevant ambient movement. Keep important props in consistent positions.
OUTPUT: {p['aspect_ratio']} aspect ratio. One continuous shot. No embedded text, subtitles, watermark, or logo. This belongs to a larger film sequence; do not add an unrelated opening or ending."""
        clips.append({"clip_number":i+1,"start_seconds":start,"duration_seconds":duration,"beat_title":"Clip "+str(i+1).zfill(2)+" — "+beat[:80],"visual_prompt":prompt,"negative_prompt":NEGATIVE,"continuity_checklist":["Character face, age, hairstyle, proportions, and costume match the reference.","Location layout and prop placement match neighboring clips.","One clear action fits the clip duration.","Camera movement is smooth and motivated.","No unwanted text, subtitles, watermark, or logo."]})
        start += duration
    return clips

@app.get("/api/health")
def health(): return {"status":"ok","app":"AI Film Studio API","mode":"prompt-only"}

@app.get("/api/projects")
def list_projects():
    with connect() as c: return [dict(x) for x in c.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()]

@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectIn):
    d=payload.model_dump(); now=datetime.now(timezone.utc).isoformat()
    keys=list(d.keys())
    with connect() as c:
        cur=c.execute("INSERT INTO projects ("+",".join(keys)+",created_at,updated_at) VALUES ("+",".join(["?"]*(len(keys)+2))+")",[d[k] for k in keys]+[now,now])
        return project_or_404(c,cur.lastrowid)

@app.get("/api/projects/{pid}")
def get_project(pid:int):
    with connect() as c: return project_or_404(c,pid)

@app.delete("/api/projects/{pid}",status_code=204)
def delete_project(pid:int):
    with connect() as c:
        project_or_404(c,pid)
        c.execute("DELETE FROM clips WHERE project_id=?",(pid,))
        c.execute("DELETE FROM projects WHERE id=?",(pid,))

@app.post("/api/projects/{pid}/generate")
def generate(pid:int):
    with connect() as c:
        p=project_or_404(c,pid); clips=build_clips(p)
        c.execute("DELETE FROM clips WHERE project_id=?",(pid,))
        for x in clips:
            c.execute("INSERT INTO clips(project_id,clip_number,start_seconds,duration_seconds,beat_title,visual_prompt,negative_prompt,continuity_checklist) VALUES(?,?,?,?,?,?,?,?)",
            (pid,x["clip_number"],x["start_seconds"],x["duration_seconds"],x["beat_title"],x["visual_prompt"],x["negative_prompt"],json.dumps(x["continuity_checklist"],ensure_ascii=False)))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),pid))
        rows=c.execute("SELECT * FROM clips WHERE project_id=? ORDER BY clip_number",(pid,)).fetchall()
        return {"project_id":pid,"target_duration_seconds":p["duration_seconds"],"clip_count":len(rows),"clips":[clip_dict(r) for r in rows]}

@app.get("/api/projects/{pid}/clips")
def list_clips(pid:int):
    with connect() as c:
        project_or_404(c,pid)
        return [clip_dict(r) for r in c.execute("SELECT * FROM clips WHERE project_id=? ORDER BY clip_number",(pid,)).fetchall()]

@app.get("/api/projects/{pid}/export")
def export(pid:int, format:str="json"):
    if format not in ("json","txt"): raise HTTPException(400,"format must be json or txt")
    with connect() as c:
        p=project_or_404(c,pid); clips=[clip_dict(r) for r in c.execute("SELECT * FROM clips WHERE project_id=? ORDER BY clip_number",(pid,)).fetchall()]
    if not clips: raise HTTPException(409,"Generate clip prompts before exporting")
    if format=="json": return JSONResponse({"project":p,"clips":clips},headers={"Content-Disposition":f'attachment; filename="film-project-{pid}.json"'})
    out=["# "+p["title"],"Genre: "+p["genre"],"Duration: "+str(p["duration_seconds"])+"s",""]
    for x in clips: out += ["## Clip "+str(x["clip_number"]).zfill(2)+" | "+str(x["start_seconds"])+"s | "+str(x["duration_seconds"])+"s",x["beat_title"],"","VISUAL PROMPT:",x["visual_prompt"],"","NEGATIVE PROMPT:",x["negative_prompt"],"","-"*50,""]
    return PlainTextResponse("\n".join(out),headers={"Content-Disposition":f'attachment; filename="film-project-{pid}.txt"'})
