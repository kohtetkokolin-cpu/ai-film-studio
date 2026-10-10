# AI Film Studio — Deployment Guide (မြန်မာ)

ဒီ project ကို GitHub repo တစ်ခုတည်းကနေ Vercel project နှစ်ခု တင်ပါမယ်။

- Frontend Vercel project: React/Vite UI
- Backend Vercel project: FastAPI + Gemini + Supabase
- Supabase: Login/Auth နဲ့ project သိမ်းဆည်းရန်
- Gemini API: ဇာတ်လမ်းကို နားလည်ပြီး clip prompt များထုတ်ရန်

ဒီ guide က setup လုပ်နည်းဖြစ်ပါတယ်။ သင့် Vercel/Supabase/Gemini account ထဲကို assistant က ဝင်ပြီး key/deployment ဖန်တီးထားတာ မဟုတ်ပါ။ အောက်ပါအဆင့်တွေကို သင့် account ထဲမှာ လုပ်ရပါမယ်။

## 1. GitHub

Repo: https://github.com/kohtetkokolin-cpu/ai-film-studio

Repo ကို private အဖြစ်ထားနိုင်ပါတယ်။ API key အစစ်ကို GitHub ထဲ မတင်ပါနဲ့။ .env.example ဖိုင်တွေမှာ placeholder တွေပဲ ပါပါတယ်။

## 2. Supabase project

1. https://supabase.com ကိုဖွင့်ပြီး account ဝင်ပါ။
2. New project ကိုနှိပ်ပါ။ Project name/password/region ရွေးပါ။ Database password ကို လုံခြုံတဲ့နေရာမှာ သိမ်းပါ။
3. Project ပြီးသွားလျှင် SQL Editor ကိုဖွင့်ပါ။
4. GitHub ထဲက supabase/migrations/202610100001_film_projects.sql ဖိုင်ကို ဖွင့်ပါ။
5. SQL အားလုံးကို copy လုပ်ပြီး Supabase SQL Editor ထဲ paste လုပ်ပါ၊ Run နှိပ်ပါ။
6. Table Editor ထဲမှာ film_projects table ပေါ်လာကြောင်း စစ်ပါ။

Table မှာ user_id နဲ့ RLS policies ပါပါတယ်။ Backend က access token ကို verify လုပ်ပြီး database query တိုင်းမှာ user ID ကို စစ်ပါတယ်။

## 3. Supabase API keys

Supabase dashboard မှာ Project Settings → API (သို့မဟုတ် API Keys) ကိုဖွင့်ပါ။ အောက်ပါအချက်တွေ လိုပါတယ်။

- Project URL — https://....supabase.co
- Publishable/anon key — Frontend အတွက်
- service_role/secret key — Backend အတွက်သာ

အရေးကြီး: service_role/secret key ကို VITE_ နဲ့စတဲ့ environment variable ထဲ၊ browser code ထဲ၊ GitHub ထဲ မထည့်ပါနဲ့။ ဒီ key က RLS ကို ကျော်နိုင်တဲ့ အခွင့်အာဏာရှိလို့ backend မှာသာ ထားပါ။

### Email login setting

1. Supabase → Authentication → Providers → Email ကိုဖွင့်ပါ။
2. Email provider enabled ဖြစ်ကြောင်း စစ်ပါ။
3. Email confirmation enabled ဖြစ်ပါက signup ပြီး confirmation email ကိုဖွင့်ပါ။
4. Authentication → URL Configuration ထဲမှာ နောက်ဆုံးရမယ့် Frontend Vercel URL ကို Site URL နဲ့ Redirect URLs ထဲ ထည့်ပါ။ ဥပမာ https://your-frontend.vercel.app/** — တကယ့် URL နဲ့ အစားထိုးပါ။

## 4. Gemini API key

1. https://aistudio.google.com/apikey ကိုဖွင့်ပါ။
2. Google account နဲ့ဝင်ပြီး API key ဖန်တီးပါ။
3. Key ကို private password လို သိမ်းပါ။ GitHub/Chat/Frontend source ထဲ မထည့်ပါနဲ့။

Default model က gemini-3.8-flash ဖြစ်ပါတယ်။ Google ရဲ့ official model documentation မှာ stable/GA model အဖြစ် ဖော်ပြထားပါတယ်။ သို့သော် free quota သေချာပေါက်ရမယ်၊ request ဘယ်နှစ်ခါရမယ်ဆိုတာ အာမခံမရပါ။ Quota က AI Studio project, model availability, region, usage/tier နဲ့ Google ရဲ့ လက်ရှိစည်းမျဉ်းပေါ် မူတည်ပါတယ်။ AI Studio ရဲ့ Rate limits/usage ကို စစ်ပါ။ Model ပြောင်းလိုပါက Backend environment ထဲက GEMINI_MODEL ကို ပြင်နိုင်ပါတယ်။

## 5. Backend Vercel project

1. https://vercel.com ကိုဖွင့်ပြီး Continue with GitHub နဲ့ဝင်ပါ။
2. Add New → Project ကိုနှိပ်ပါ။
3. kohtetkokolin-cpu/ai-film-studio repo ကို Import လုပ်ပါ။
4. Project Name ကို ဥပမာ ai-film-studio-api ထားပါ။
5. Root Directory ကို backend လို့ရွေးပါ။ Python/FastAPI ကို detect လုပ်သင့်ပါတယ်။
6. Environment Variables ထည့်ပါ။

| Name | Value |
|---|---|
| GEMINI_API_KEY | သင့် Gemini API key အစစ် |
| GEMINI_MODEL | gemini-3.8-flash |
| SUPABASE_URL | Supabase Project URL |
| SUPABASE_ANON_KEY | Supabase publishable/anon key |
| SUPABASE_SERVICE_ROLE_KEY | Supabase service_role/secret key |
| FRONTEND_ORIGIN | Frontend deploy ပြီးရင် ရမယ့် URL; ဥပမာ https://your-frontend.vercel.app |

7. Deploy နှိပ်ပါ။ Frontend URL မသိသေးရင် FRONTEND_ORIGIN ကို နောက်မှထည့်ပြီး Redeploy လုပ်နိုင်ပါတယ်။
8. Deploy ပြီးရင် Backend URL ကို copy လုပ်ပါ။ ဥပမာ https://ai-film-studio-api.vercel.app။
9. Browser မှာ https://YOUR-BACKEND-URL/health ကိုဖွင့်ပါ။ JSON ထဲမှာ ok: true, gemini_configured: true, supabase_configured: true ဖြစ်သင့်ပါတယ်။ False ဖြစ်ရင် Environment Variables နဲ့ Redeploy ကို စစ်ပါ။

## 6. Frontend Vercel project

1. Vercel Dashboard → Add New → Project ကို ထပ်နှိပ်ပါ။
2. အဲဒီ GitHub repo တစ်ခုတည်းကို ထပ် Import လုပ်ပါ။
3. Project Name ကို ဥပမာ ai-film-studio ထားပါ။
4. Root Directory ကို frontend ရွေးပါ။
5. Framework Preset Vite ဖြစ်ကြောင်း စစ်ပါ။ Build command npm run build, Output Directory dist ဖြစ်သင့်ပါတယ်။
6. Environment Variables မှာ အောက်ပါ 3 ခုထည့်ပါ။

| Name | Value |
|---|---|
| VITE_SUPABASE_URL | Supabase Project URL |
| VITE_SUPABASE_ANON_KEY | Supabase publishable/anon key |
| VITE_API_BASE_URL | Backend Vercel URL — https://... (နောက်ဆုံး slash မထည့်ပါနဲ့) |

7. Deploy နှိပ်ပါ။
8. Frontend URL ရပြီးလျှင် Backend Vercel project → Settings → Environment Variables မှာ FRONTEND_ORIGIN ကို အဲဒီ URL နဲ့ ပြင်ပါ။ ထို့နောက် Backend ကို Redeploy လုပ်ပါ။
9. Supabase → Authentication → URL Configuration မှာ Frontend URL ကို Site URL/Redirect URLs ထဲထည့်ပါ။

## 7. App စမ်းသပ်ရန်

1. Frontend URL ကိုဖွင့်ပါ။
2. Email/password နဲ့ account ဖွင့်ပါ။ Email confirmation enabled ဖြစ်ပါက email ကို confirm လုပ်ပါ။
3. Login ဝင်ပါ။
4. Story Idea ကို ကိုယ့်ဇာတ်လမ်းနဲ့ အစားထိုးပါ။ Character Bible/Location Bible/Continuity Notes ကို အသေးစိတ်ဖြည့်ပါ။
5. 1 minute ရွေးလျှင် 8 clips ထုတ်ပေးရပါမယ်။ 3 minutes ဆို 23 clips (22×8 + နောက်ဆုံး 4 seconds) ဖြစ်ရပါမယ်။
6. Save Project & Generate AI Prompts ကိုနှိပ်ပါ။ Gemini request အချိန်ယူနိုင်ပါတယ်။
7. Prompt, Negative Prompt, Continuity Checklist ကို စစ်ပါ။ Copy/Export TXT/JSON လုပ်ပါ။
8. Browser refresh လုပ်ပြီး project ကို ပြန်ဖွင့်ပါ။ Supabase ထဲသိမ်းထားတာကြောင့် ပြန်မြင်ရပါမယ်။
9. Account အသစ်နဲ့ Login ဝင်ပြီး အခြား account ရဲ့ project မမြင်ရကြောင်း စမ်းပါ။

## 8. Error ဖြေရှင်းနည်း

- Login မရ: Supabase Email provider, email confirmation, URL configuration, Frontend environment variables စစ်ပါ။
- Supabase table error: SQL migration ကို SQL Editor မှာ အောင်မြင်စွာ Run လုပ်ထားသလား စစ်ပါ။
- 401 Login သက်တမ်းကုန်: Logout/Login ပြန်လုပ်ပါ။
- Gemini 429 / RESOURCE_EXHAUSTED: Quota ပြည့်နေနိုင်ပါတယ်။ ခဏစောင့်ပြီး ပြန်ကြိုးစားပါ၊ AI Studio usage/rate limit စစ်ပါ။ App က quota ကို တိုးပေးလို့မရပါ။
- Gemini model access error: AI Studio မှာ သင့် project အတွက် model အသုံးပြုခွင့်ရှိမရှိ စစ်ပြီး GEMINI_MODEL ကို available stable model နဲ့ ပြောင်းပါ။
- 502/504 timeout: Story/context အလွန်ရှည်ခြင်း သို့မဟုတ် model response ကြာခြင်းဖြစ်နိုင်ပါတယ်။ Story ကိုတိုအောင်လုပ်ပြီး ပြန်စမ်းပါ။ Vercel Function Logs ကိုစစ်ပါ။
- CORS error: Backend FRONTEND_ORIGIN မှာ Frontend URL အတိအကျထည့်ပြီး backend redeploy လုပ်ပါ။
- Backend မချိတ်နိုင်: VITE_API_BASE_URL မှာ backend URL အမှန်ထည့်ထားပြီး frontend redeploy လုပ်ထားသလား စစ်ပါ။

## 9. Free quota နဲ့ လုံခြုံရေး

- Vercel, Supabase, Gemini free usage က provider ရဲ့ လက်ရှိ plan/usage policy ပေါ်မူတည်ပါတယ်။ Account တစ်ခုချင်းစီ quota မတူနိုင်ပြီး ပြောင်းလဲနိုင်ပါတယ်။
- ဒီ app က AI video ကို ကိုယ်တိုင် generate/render မလုပ်ပါ။ Gemini က story analysis နဲ့ video-generation prompts ထုတ်ပေးတာသာဖြစ်ပြီး video ကို external tool မှာ ဖန်တီးရပါမယ်။
- API key တွေကို browser console, screenshot, public GitHub repo ထဲ မပေါ်စေပါနဲ့။
- Key leak ဖြစ်သွားရင် provider dashboard မှာ revoke/rotate လုပ်ပါ။
- Public users အများကြီးသုံးမယ်ဆိုရင် usage limits, abuse protection, email verification, logs, backup/restore, quota monitoring တို့ကို ထပ်ထည့်ဖို့လိုပါတယ်။
