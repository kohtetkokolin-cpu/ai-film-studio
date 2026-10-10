# AI Film Studio

သီးခြား AI Film Production Assistant — movie recap project မဟုတ်ပါ။ ဒီ MVP က ဇာတ်လမ်းအချက်အလက်ကို အခြေခံပြီး 8-second clip prompts နဲ့ negative prompts ထုတ်ပေးတဲ့ workspace ဖြစ်ပါတယ်။

## ပါဝင်သောအရာများ
- Burmese-first project setup
- FastAPI backend + SQLite database
- Project သိမ်းဆည်းခြင်းနှင့် ပြန်ဖွင့်ခြင်း
- 8-second clip prompt generator
- Character / location / continuity notes
- Clip တစ်ခုချင်းစီအတွက် visual prompt နှင့် negative prompt
- TXT / JSON export
- Paid AI API မလိုအပ်ပါ

## Run လုပ်နည်း
လိုအပ်ချက်: Python 3.11+, Node.js 20+

Backend:
    cd backend
    python -m venv .venv
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Frontend terminal အသစ်:
    cd frontend
    npm install
    npm run dev

Vite က ပြသတဲ့ local URL ကို ဖွင့်ပါ (ပုံမှန်အားဖြင့် http://localhost:5173)။
API docs: http://127.0.0.1:8000/docs

## Clip timing
Clip တစ်ခုကို 8 seconds target ထားပါတယ်။ စုစုပေါင်းကြာချိန်က 8 နဲ့ အတိအကျမစားရင် နောက်ဆုံး clip ကို လိုအပ်သလိုတိုစေပါတယ်။ 60 seconds = 7×8 + 4 seconds; 180 seconds = 22×8 + 4 seconds.

## သတိပြုရန်
ဒီ version က prompt builder ဖြစ်ပြီး AI model ကို ချိတ်မထားသေးပါ။ ဇာတ်လမ်းစာသားကို အခြေခံပြီး prompt ကို စနစ်တကျ ဖွဲ့စည်းပေးသော်လည်း screenplay ကို အဓိပ္ပါယ်နားလည်ပြီး အလိုအလျောက် ဇာတ်လမ်းပြန်ရေးတဲ့ LLM မဟုတ်သေးပါ။ Public deployment မလုပ်မီ authentication, backups, HTTPS, database persistence, rate limiting တို့ ထည့်ရန်လိုပါတယ်။ Paid API keys များကို frontend ထဲ မထည့်ပါနှင့်။
