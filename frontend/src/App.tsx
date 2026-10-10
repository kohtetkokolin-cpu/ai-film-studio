import { FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase, supabaseConfigured } from "./supabase";

const API = import.meta.env.VITE_API_BASE_URL || "";
type Project = {
  id: string; title: string; genre: string; duration_seconds: number; visual_style: string;
  workflow: string; aspect_ratio: string; language: string; story_idea: string;
  character_bible: string; location_bible: string; continuity_notes: string; clips?: Clip[];
};
type Clip = {
  id?: string; clip_number: number; start_seconds: number; duration_seconds: number;
  beat_title: string; visual_prompt: string; negative_prompt: string; continuity_checklist: string[];
};
const defaults = {
  title: "နောက်ဆုံးရထား", genre: "Drama", duration_seconds: 180,
  visual_style: "Realistic cinematic", workflow: "automatic", aspect_ratio: "16:9", language: "Burmese",
  story_idea: "ငယ်ဘဝကတည်းက ချစ်ခဲ့ကြတဲ့ မောင်နဲ့ သဇင်ဟာ ဘူတာရုံဟောင်းမှာ အတူရထားစီးခဲ့ကြတယ်။ သဇင်က ပြန်လာမယ်လို့ ကတိပေးပြီး ထွက်ခွာသွားတယ်။ နှစ်ပေါင်းများစွာကြာတဲ့အခါ မောင်က ထိုင်ခုံဟောင်းလေးမှာ စောင့်နေဆဲဖြစ်တယ်။ စာအိတ်ဟောင်းတစ်ခုက သူတို့ ရထားဘူတာလွဲခဲ့ကြောင်းနဲ့ သဇင် ပြန်မလာနိုင်တော့ကြောင်း ဖော်ပြတယ်။",
  character_bible: "မောင် — ငယ်ဘဝအသက် ၁၀ နှစ်၊ ဆံပင်အနက်၊ မျက်လုံးညို။ အသက်ကြီးချိန် ၇၀ ဝန်းကျင်၊ ဆံပင်ဖြူ၊ အရောင်မှိန်အင်္ကျီနှင့် လုံချည်။ သဇင် — ငယ်ဘဝအသက် ၁၀ နှစ်၊ ဆံပင်ရှည်၊ နူးညံ့သောအပြုံး။",
  location_bible: "မြန်မာနိုင်ငံကျေးလက်ဘူတာရုံဟောင်း၊ သစ်သားထိုင်ခုံတစ်လုံး၊ ရထားလမ်းနှင့် ပြတင်းပေါက်ဘေးထိုင်ခုံ။",
  continuity_notes: "မျက်နှာ၊ အသက်၊ ဆံပင်၊ အဝတ်အစား၊ ဘူတာရုံ၊ သစ်သားထိုင်ခုံနှင့် အဝါရောင်စာအိတ်ကို clip အားလုံးတွင် တစ်သမတ်တည်းထားရန်။"
};
type FormData = typeof defaults;

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [form, setForm] = useState<FormData>(defaults);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const count = Math.ceil(Number(form.duration_seconds) / 8);
  const last = Number(form.duration_seconds) % 8 || 8;

  useEffect(() => {
    if (!supabase) { setAuthReady(true); return; }
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setAuthReady(true); });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setProjects([]);
      setProject(null);
      setClips([]);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    if (!session?.access_token) throw new Error("Login အရင်ဝင်ပါ။");
    const response = await fetch(API + path, {
      ...init,
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + session.access_token, ...(init?.headers || {}) }
    });
    if (!response.ok) {
      let msg = "Request failed " + response.status;
      try { const data = await response.json(); msg = data.detail || msg; } catch {}
      throw new Error(msg);
    }
    if (response.status === 204) return undefined as T;
    return response.json();
  }

  async function refresh() {
    if (!session) return;
    try { setProjects(await api<Project[]>("/api/projects")); }
    catch (e) { setMessage("Project များ မဖတ်နိုင်ပါ: " + String(e)); }
  }
  useEffect(() => { if (session) refresh(); }, [session?.access_token]);

  async function authenticate(event: FormEvent) {
    event.preventDefault();
    if (!supabase) return;
    setBusy(true); setMessage("");
    try {
      const result = authMode === "login"
        ? await supabase.auth.signInWithPassword({ email: email.trim(), password })
        : await supabase.auth.signUp({ email: email.trim(), password });
      if (result.error) throw result.error;
      if (authMode === "signup" && !result.data.session) {
        setMessage("အကောင့်ဖွင့်ပြီးပါပြီ။ Email confirmation လိုအပ်ပါက email ကိုအတည်ပြုပြီး Login ဝင်ပါ။");
      } else setMessage("Login အောင်မြင်ပါပြီ။");
    } catch (e) { setMessage("အမှား: " + String(e)); }
    finally { setBusy(false); }
  }

  function change<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const created = await api<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ ...form, duration_seconds: Number(form.duration_seconds) })
      });
      setProject(created);
      const result = await api<{ clips: Clip[] }>("/api/projects/" + created.id + "/generate", { method: "POST" });
      setClips(result.clips); setSelected(0);
      setMessage("အောင်မြင်ပါပြီ။ ဇာတ်လမ်းအလိုက် " + result.clips.length + " ခုသော clip prompt များ ထုတ်ပြီး သိမ်းထားပါပြီ။");
      await refresh();
    } catch (e) { setMessage("အမှား: " + String(e)); }
    finally { setBusy(false); }
  }

  async function openProject(item: Project) {
    setBusy(true);
    try {
      setProject(item);
      setForm({
        title: item.title, genre: item.genre, duration_seconds: item.duration_seconds,
        visual_style: item.visual_style, workflow: item.workflow, aspect_ratio: item.aspect_ratio,
        language: item.language, story_idea: item.story_idea, character_bible: item.character_bible,
        location_bible: item.location_bible, continuity_notes: item.continuity_notes
      });
      setClips(item.clips || await api<Clip[]>("/api/projects/" + item.id + "/clips"));
      setSelected(0); setMessage("");
    } catch (e) { setClips([]); setMessage(String(e)); }
    finally { setBusy(false); }
  }

  async function regenerate() {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api<{ clips: Clip[] }>("/api/projects/" + project.id + "/generate", { method: "POST" });
      setClips(result.clips); setSelected(0); setMessage("Prompt များ ပြန်ထုတ်ပြီး database ထဲ သိမ်းထားပါပြီ။"); await refresh();
    } catch (e) { setMessage("အမှား: " + String(e)); }
    finally { setBusy(false); }
  }

  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setMessage("Copy လုပ်ပြီးပါပြီ။"); }
    catch { setMessage("Copy မရပါ။ စာသားကို ရွေးပြီး ကူးယူပါ။"); }
  }

  function download(kind: "txt" | "json") {
    if (!project || !clips.length) return;
    const content = kind === "json" ? JSON.stringify({ project, clips }, null, 2) :
      ["# " + project.title, "Genre: " + project.genre, "Duration: " + project.duration_seconds + "s", "",
        ...clips.flatMap(c => ["## Clip " + String(c.clip_number).padStart(2, "0") + " | " + c.start_seconds + "s | " + c.duration_seconds + "s",
          c.beat_title, "", "VISUAL PROMPT:", c.visual_prompt, "", "NEGATIVE PROMPT:", c.negative_prompt,
          "", "CONTINUITY CHECKLIST:", ...c.continuity_checklist.map(x => "- " + x), "", "------------------------------", ""])].join("\n");
    const blob = new Blob([content], { type: kind === "json" ? "application/json" : "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = "ai-film-project-" + project.id + "." + kind; link.click(); URL.revokeObjectURL(url);
  }

  if (!authReady) return <div className="auth-shell"><div className="panel">AI Film Studio ဖွင့်နေပါသည်…</div></div>;
  if (!supabaseConfigured || !supabase) return <div className="auth-shell"><section className="panel auth-panel">
    <div className="logo">AI</div><h1>AI Film Studio</h1><p>Supabase Auth ချိတ်ဆက်ရန် environment variables မပြည့်စုံသေးပါ။</p>
    <p><code>VITE_SUPABASE_URL</code> နှင့် <code>VITE_SUPABASE_ANON_KEY</code> ကို Vercel project settings ထဲထည့်ပြီး redeploy လုပ်ပါ။</p>
  </section></div>;
  if (!session) return <div className="auth-shell"><form className="panel auth-panel" onSubmit={authenticate}>
    <div className="logo">AI</div><h1>AI FILM STUDIO</h1><p>ကိုယ့်ရဲ့ film project တွေကို သီးသန့်သိမ်းဆည်းဖို့ အကောင့်ဝင်ပါ။</p>
    <div className="auth-tabs"><button type="button" className={authMode === "login" ? "tab active" : "tab"} onClick={() => setAuthMode("login")}>Login</button><button type="button" className={authMode === "signup" ? "tab active" : "tab"} onClick={() => setAuthMode("signup")}>အကောင့်ဖွင့်ရန်</button></div>
    <label className="field"><span>Email</span><input type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
    <label className="field"><span>Password (အနည်းဆုံး 6 လုံး)</span><input type="password" required minLength={6} autoComplete={authMode === "login" ? "current-password" : "new-password"} value={password} onChange={e => setPassword(e.target.value)} /></label>
    {message && <div className="message">{message}</div>}<button className="primary" disabled={busy}>{busy ? "လုပ်ဆောင်နေသည်…" : authMode === "login" ? "Login ဝင်မည်" : "အကောင့်ဖွင့်မည်"}</button>
    <small className="auth-foot">Gemini နဲ့ Supabase secret key တွေကို browser ထဲ မထည့်ထားပါ။</small>
  </form></div>;

  const active = clips[selected];
  return <div className="shell"><header className="topbar"><div className="logo">AI</div><div><b>AI FILM STUDIO</b><small>Story-to-film prompt production workspace</small></div><span className="free-tag">GEMINI · SUPABASE</span><button className="logout" onClick={async () => { if (supabase) await supabase.auth.signOut(); }}>Logout</button></header>
    <div className="layout"><aside className="sidebar"><div className="side-label">WORKSPACE</div><div className="nav active">▣　Film Project</div><div className="nav">◈　Story & Characters</div><div className="nav">▤　Clip Prompt Planner</div><div className="nav">✓　Continuity Check</div>
      <div className="side-note"><b>Production workflow</b><p>Gemini က ဇာတ်လမ်းကို scene beat များအဖြစ် ခွဲပြီး video-generation prompt တစ်ခုချင်း ထုတ်ပေးသည်။ Video ကိုယ်တိုင် render မလုပ်ပါ။</p></div>
      <div className="side-label saved-label">SAVED PROJECTS</div>{projects.map(item => <button key={item.id} className={"saved " + (project?.id === item.id ? "chosen" : "")} onClick={() => openProject(item)}>{item.title}<small>{Math.round(item.duration_seconds / 60 * 10) / 10} min · {item.genre}</small></button>)}
    </aside>
    <main className="main"><div className="heading"><div><div className="eyebrow">PRODUCTION / PROJECT SETUP</div><h1>Film Project Brief</h1><p>ဇာတ်လမ်း၊ ဇာတ်ကောင်နဲ့ နေရာအချက်အလက်တွေ ဖြည့်ပါ။ Gemini က ဇာတ်လမ်းအဆက်အစပ်ရှိတဲ့ 8-second clip prompt များ ထုတ်ပေးမယ်။</p></div><span className="mode">✦ AI STORY ANALYSIS</span></div>
      {message && <div className="message">{message}<button onClick={() => setMessage("")}>×</button></div>}
      <form className="panel" onSubmit={submit}><div className="section-title"><span>01</span><div><b>Project အချက်အလက်</b><small>ဇာတ်ကားရဲ့ အခြေခံသတ်မှတ်ချက်များ</small></div></div>
        <div className="grid">
          <label className="field full"><span>ဇာတ်ကားအမည်</span><input required maxLength={160} value={form.title} onChange={e => change("title", e.target.value)} /></label>
          <label className="field"><span>Genre / အမျိုးအစား</span><select value={form.genre} onChange={e => change("genre", e.target.value)}>{["Drama","Romance","Mystery","Thriller","Action","Fantasy","Horror","Comedy","Adventure","Mixed"].map(x => <option key={x}>{x}</option>)}</select></label>
          <label className="field"><span>Visual Style</span><select value={form.visual_style} onChange={e => change("visual_style", e.target.value)}>{["Realistic cinematic","2D cinematic animation","3D animation","Anime-inspired animation","Hand-painted animation","Stop-motion animation"].map(x => <option key={x}>{x}</option>)}</select></label>
          <label className="field"><span>ကြာချိန် (အများဆုံး 5 မိနစ်)</span><select value={form.duration_seconds} onChange={e => change("duration_seconds", Number(e.target.value))}>{[60,120,180,240,300].map(x => <option value={x} key={x}>{x / 60} မိနစ်</option>)}</select></label>
          <label className="field"><span>Aspect Ratio</span><select value={form.aspect_ratio} onChange={e => change("aspect_ratio", e.target.value)}><option>16:9</option><option>9:16</option><option>1:1</option></select></label>
          <label className="field"><span>Workflow</span><select value={form.workflow} onChange={e => change("workflow", e.target.value)}><option value="automatic">Automatic — အလိုအလျောက်</option><option value="manual">Manual — ကိုယ်တိုင်ထိန်းချုပ်</option></select></label>
          <label className="field"><span>ဇာတ်လမ်း/ယဉ်ကျေးမှုဘာသာစကား</span><select value={form.language} onChange={e => change("language", e.target.value)}><option>Burmese</option><option>English</option><option>Thai</option><option>Chinese</option></select></label>
        </div>
        <div className="section-title gap-top"><span>02</span><div><b>Story Development</b><small>ဇာတ်လမ်းကို မြင်ကွင်းတွေအဖြစ် ပြောင်းဖို့ အချက်အလက်များ</small></div></div>
        <label className="field"><span>Story Idea / ဇာတ်လမ်းအကြောင်း</span><textarea required minLength={10} rows={5} value={form.story_idea} onChange={e => change("story_idea", e.target.value)} /></label>
        <div className="grid"><label className="field"><span>Character Bible / ဇာတ်ကောင်</span><textarea rows={5} value={form.character_bible} onChange={e => change("character_bible", e.target.value)} placeholder="မျက်နှာ၊ အသက်၊ ဆံပင်၊ အဝတ်အစား၊ ကိုယ်လက်လှုပ်ရှားမှု…" /></label>
          <label className="field"><span>Location Bible / နေရာ</span><textarea rows={5} value={form.location_bible} onChange={e => change("location_bible", e.target.value)} placeholder="နေရာ၊ အလင်းရောင်၊ ပစ္စည်း၊ အဆောက်အဦ…" /></label>
          <label className="field full"><span>Continuity Notes / မပြောင်းရမယ့်အချက်များ</span><textarea rows={3} value={form.continuity_notes} onChange={e => change("continuity_notes", e.target.value)} placeholder="မျက်နှာ၊ အဝတ်အစား၊ ပစ္စည်း၊ နေရာ၊ screen direction…" /></label></div>
        <div className="summary"><div><small>TARGET DURATION</small><b>{Math.floor(Number(form.duration_seconds) / 60)}:{String(Number(form.duration_seconds) % 60).padStart(2,"0")}</b></div><div><small>8-SECOND CLIPS</small><b>{count} clips</b></div><div><small>FINAL CLIP</small><b>{last}s</b></div></div>
        <button className="primary" disabled={busy}>{busy ? "Gemini က ဇာတ်လမ်းပြင်ဆင်နေသည်…" : "✦ Save Project & Generate AI Prompts"}</button>
      </form>
      {clips.length > 0 && <section className="results"><div className="result-heading"><div><div className="eyebrow">GENERATED OUTPUT</div><h2>Clip Prompt Planner</h2><p>{clips.length} clips · {clips.reduce((sum,c) => sum + c.duration_seconds, 0)}s total · Prompts saved to your account</p></div><div className="actions"><button onClick={() => download("txt")}>Export TXT</button><button onClick={() => download("json")}>Export JSON</button><button onClick={regenerate} disabled={busy}>Regenerate</button></div></div>
        <div className="clip-layout"><div className="clip-list">{clips.map((clip,index) => <button key={clip.clip_number} className={"clip " + (selected === index ? "selected" : "")} onClick={() => setSelected(index)}><span className="num">{String(clip.clip_number).padStart(2,"0")}</span><span className="clip-name"><b>{clip.beat_title}</b><small>{clip.start_seconds}s · {clip.duration_seconds}s</small></span><span>›</span></button>)}</div>
          {active && <div className="detail"><div className="detail-head"><div><div className="eyebrow">CLIP {String(active.clip_number).padStart(2,"0")}</div><h3>{active.start_seconds}s — {active.start_seconds + active.duration_seconds}s</h3></div><button onClick={() => copy(active.visual_prompt)}>Copy Prompt</button></div>
            <div className="prompt"><div><b>VISUAL PROMPT</b><button onClick={() => copy(active.visual_prompt)}>Copy</button></div><pre>{active.visual_prompt}</pre></div>
            <div className="prompt negative"><div><b>NEGATIVE PROMPT</b><button onClick={() => copy(active.negative_prompt)}>Copy</button></div><pre>{active.negative_prompt}</pre></div>
            <div className="checklist"><b>Continuity Checklist</b>{active.continuity_checklist.map((item,index) => <p key={index}>✓ {item}</p>)}</div>
          </div>}
        </div></section>}
      <footer>AI Film Studio · Gemini text generation · Supabase user-owned project storage · Video rendering is done in an external tool</footer>
    </main></div></div>;
}
