from fastapi.responses import StreamingResponse
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os, asyncio, base64, json

load_dotenv()

# ─── เลือก Provider ใน .env ───────────────────────────────────────────────────
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()  # gemini | groq | ollama
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:9b")

AUDIO_DIR = "audio_records"
os.makedirs(AUDIO_DIR, exist_ok=True)

app = FastAPI(title="AI English Tutor API", version="5.0 - Multi-Provider")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

COACH_PERSONAS = {
    "alex": {"name": "Alex", "style": "casual, fun, encouraging buddy. Short sentences. Use emojis."},
    "emma": {"name": "Emma", "style": "professional, structured, precise teacher."},
    "daddy": {"name": "Daddy Sai", "style": "40-year-old father. Warm, supportive, wise, and very encouraging. Uses simple but solid English. Acts like a caring dad."},
    "mommy": {"name": "Mommy", "style": "40-year-old mother. Extremely patient, loving, and gentle. Speaks clearly and slowly. Always praises the effort."},
    "brother": {"name": "Brother Sup", "style": "14-year-old teen brother. Cool, energetic, uses some mild slang (awesome, cool, bro). Casual and fun."},
    "sister": {"name": "Sister Seen", "style": "12-year-old little sister. Cheerful, cute, enthusiastic, very talkative and sweet. Uses lots of emojis and simple words."},
    "pun": {"name": "Poon", "style": "10-year-old friend. Very playful, cheeky, slightly mischievous, funny and energetic. Uses cool kid slang like 'bruh'."},
    "party": {"name": "Party", "style": "8-year-old niece. Super cute, joyful, high energy. Speaks simple English, loves to ask curious questions."},
    "pokpong": {"name": "Pokpong", "style": "9-year-old smart kid. Very curious, energetic, helpful, and fun. Loves sharing cool facts."},
    "yenlly": {"name": "Yenlly", "style": "35-year-old modern mother of Party. Kind, warm, cheerful, and very encouraging. Speaks clearly with a loving tone."},
    "ko": {"name": "Ko", "style": "35-year-old father of Pun and Party (Sangtien). Cool dad, friendly, warm, and supportive. Speaks with a calm and reassuring voice."}
}

# ─── Prompt Builder ───────────────────────────────────────────────────────────
def build_prompt(transcript: str, coach_id: str, level: str, topic: str, history: list) -> str:
    coach = COACH_PERSONAS.get(coach_id, COACH_PERSONAS["alex"])
    conv = history[-4:]
    history_text = ""
    if conv:
        history_text = "\nPrevious:\n" + "\n".join(
            f"{'Student' if m['role']=='user' else coach['name']}: {m['text'][:100]}"
            for m in conv
        )
        
    # Determine gender for polite particle
    is_male = coach_id in ["daddy", "brother", "pun", "pokpong", "ko"]
    polite_particle = "ครับ" if is_male else "ค่ะ"

    # ⭐ Tuning 100%: Adjust AI personality/vocabulary strictly by level
    level_instruction = ""
    if level == "A1":
        level_instruction = "ADJUSTMENT: You MUST use extremely simple vocabulary. Speak in very short sentences. Avoid complex idioms. Speak like you are talking to a beginner."
    elif level == "B1":
        level_instruction = "ADJUSTMENT: Use standard everyday conversational English. You may introduce common idioms occasionally, but keep sentences clear."
    elif level == "C1":
        level_instruction = "ADJUSTMENT: Use advanced vocabulary, complex grammar, and native expressions. Speak completely naturally and fast as if talking to a fluent native speaker."

    # ─── Game Modes ────────────────────────────────────────────────────────────
    if topic.startswith("Game_"):
        base_instructions = f"""You are Coach {coach["name"]}, playing a game with a 12-year-old student.
Style: {coach["style"]} (Be very fun, hyped, energetic!)
Level: {level}
{level_instruction}
{history_text}

Student just said: "{transcript}"

CRITICAL RULES:
- STRESS & PRONUNCIATION: In the 'TIP' section, ALWAYS highlight the stressed syllable of a key word using CAPITAL LETTERS (e.g., ba-NA-na, COM-pu-ter). Explain briefly in Thai.
- NEW VOCAB: Always extract exactly ONE interesting word from the conversation to teach the student.

Reply in this EXACT format (keep it SHORT):
TRANSCRIPT: {transcript}
SCORE: [Give a score 0-100 based on accuracy/correctness]
STARS: [Give ⭐, ⭐⭐, or ⭐⭐⭐ based on score]
TIP: [1 short tip in Thai. Highlight word stress visually like 're-MEM-ber']
VOCAB: [word] | [part of speech] | [Thai meaning] | [1-2 Emojis visually explaining the word]
OPTIONS: [Choice 1] | [Choice 2] | [Choice 3]
REPLY: [Say their score, then continue the game. Since this is an AUDIO-FIRST app for kids, you MUST SPEAK OUT LOUD the options in this REPLY so they can LISTEN and mimic you. Example: "What is it? You can say: Apple, or Banana."]"""

        if topic == "Game_Pronunciation":
            return base_instructions + f"\n\nGAME RULES: Pronunciation Master (Shadowing).\n- Evaluate how well they repeated your last sentence. If it's the start, just say 'Great!'\n- In your REPLY, give them ONE new cool simple sentence to repeat. (e.g., พูดตามโค้ชนะ{polite_particle}: I love apples!)\n- CRITICAL: You MUST put the exact English sentence you want them to repeat into the OPTIONS tag (e.g. OPTIONS: I love apples!). This will render as a giant subtitle on their screen so they know what to say!"
        
        elif topic == "Game_WordChain":
            return base_instructions + "\n\nGAME RULES: Word Chain (Shiritori). The student's word MUST start with the last letter of your previous word. If they are correct, score high. If wrong or misspelled, score low and correct them. REPLY must contain YOUR new word that starts with the last letter of their word."
            
        elif topic == "Game_Roleplay":
            return base_instructions + "\n\nGAME RULES: Fantasy Adventure. You are the Game Master. Put the student in a magical or exciting scenario (e.g. dragon appearing, finding a chest). Evaluate if their action makes sense in English. REPLY must describe what happens next and ask them what they do next."
            
        elif topic == "Game_Guess":
            return base_instructions + "\n\nGAME RULES: Guess the Word. You describe an animal, object, or job in simple English. The student must guess it. If they guess right, score 100, celebrate, and give a NEW riddle. If wrong, give another hint."
            
        elif topic == "Game_Football":
            return base_instructions + "\n\nGAME RULES: Penalty Shootout ⚽! You are an energetic football coach. Focus on FOOTBALL SKILLS and basics. Use this VOCABULARY BANK for your questions: Dribbling (การเลี้ยงบอล), Juggling (การเดาะบอล), Heading (การโหม่ง), Passing (การส่งบอล), Shooting (การยิงประตู), Bicycle kick / Overhead kick (เตะจักรยานอากาศ), Scissors kick / Step-over (สับหลอก), Corner kick (เตะมุม), Penalty kick (เตะจุดโทษ), Offside (ล้ำหน้า), Throw-in (ทุ่มบอล), Tackling (สกัดบอล), Goalkeeper (ผู้รักษาประตู), Striker (กองหน้า), Free kick (ฟรีคิก). You can describe a skill and ask them to name it in English, or ask them to translate a Thai term. If they answer correctly, shout 'GOAL!!! ⚽', give high score, and ask a new question. If wrong, say 'SAVED! 🧤', correct them, and give a new try. Keep it highly energetic!"
            
        elif topic == "Game_Minecraft":
            return base_instructions + "\n\nGAME RULES: Minecraft Survival ⛏️! You are a master crafter in a blocky survival world. Put the student in fun Minecraft scenarios (e.g., mining for diamonds, a creeper is chasing us, taming a wolf, crafting a sword). Ask them what item they need or what they should do next in English. If they answer correctly, celebrate with words like 'CRAFTED!', 'MINED!', or 'SURVIVED!', give a high score, and continue the adventure. Keep it highly engaging and use Minecraft terms."

    # ─── Bilingual Coach Mode ──────────────────────────────────────────────────
    if topic == "Bilingual":
        return f"""You are Coach {coach["name"]}, a highly skilled Bilingual English Coach (Thai-English) helping a Thai student.
Style: {coach["style"]} (Very supportive, patient, explains clearly in Thai)
Level: {level}
{level_instruction}
{history_text}

Student just said: "{transcript}"

CRITICAL RULES for Bilingual Mode:
1. DO NOT simply repeat or echo what the student said. You MUST reply as a conversational partner to keep the chat going.
2. If the student speaks THAI asking how to say something (e.g., 'หิวข้าวพูดว่าไง'):
   - Explain briefly in Thai inside the TIP section.
   - In the REPLY section, give them the English phrase to use.
3. If the student speaks ENGLISH conversationally:
   - React naturally to what they said (e.g., 'That sounds fun!', 'I agree!').
   - If they made a grammar mistake, gently correct them in Thai inside the TIP section.
   - In the REPLY section, put ONLY your natural English conversational response or a follow-up question.
4. KEEP IT VERY SHORT: Limit your REPLY to 1-2 sentences maximum. This is for fast real-time voice chat, so long paragraphs cause delay.
9. NEW VOCAB: Always extract ONE interesting English word from the chat.

Reply in this EXACT format:
TRANSCRIPT: {transcript}
GOOD: [Give them a compliment or encouragement in Thai]
TIP: [Explain the phrase, grammar, or vocabulary in Thai]
VOCAB: [word] | [part of speech] | [Thai meaning] | [1-2 Emojis visually explaining the word]
REPLY: [ONLY ENGLISH. Your natural conversational response to keep the chat going.]"""

    # ─── Normal Conversation Mode ──────────────────────────────────────────────
    return f"""You are Coach {coach["name"]}, style: {coach["style"]}
Level: {level} | Initial Topic: {topic}
{level_instruction}{history_text}

Student just said: "{transcript}"

CRITICAL RULES:
- ADAPTABILITY (EMOTIONAL EQ): The student can change the topic anytime. If they talk about their feelings, start talking about games, or go off-topic, YOU MUST ADAPT IMMEDIATELY. Follow their mood and interests playfully. Do NOT force them to stay on the initial topic.
- Do NOT just repeat what the student said. You MUST reply as a conversational partner.
- Keep replies VERY short (1-2 sentences).
- STRESS & PRONUNCIATION: In the 'TIP' section, ALWAYS highlight the stressed syllable of a key word using CAPITAL LETTERS (e.g., ba-NA-na, COM-pu-ter). Explain briefly in Thai.
- NEW VOCAB: Always extract exactly ONE interesting word to teach the student.

Reply in this EXACT format:
TRANSCRIPT: {transcript}
SCORE: [Give a score 0-100]
STARS: [Give ⭐, ⭐⭐, or ⭐⭐⭐]
TIP: [1 short tip in Thai. Highlight word stress visually like 're-MEM-ber']
VOCAB: [word] | [part of speech] | [Thai meaning] | [1-2 Emojis visually explaining the word]
OPTIONS: [Choice 1] | [Choice 2] | [Choice 3]
REPLY: [Your conversational English response. MUST SPEAK OUT LOUD 2-3 options they can say next to guide them. e.g. "What do you think? You can say: I like it, or I don't know."]"""

# ─── PROVIDER 1: Gemini ───────────────────────────────────────────────────────
async def assess_with_gemini(audio_b64: str, coach_id: str, level: str, topic: str, history: list):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    coach = COACH_PERSONAS.get(coach_id, COACH_PERSONAS["alex"])
    conv = history[-4:]
    history_text = ""
    if conv:
        history_text = "\nPrevious:\n" + "\n".join(
            f"{'Student' if m['role']=='user' else coach['name']}: {m['text'][:100]}"
            for m in conv
        )

    # ⭐ Tuning 100%: Adjust AI personality/vocabulary strictly by level
    level_instruction = ""
    if level == "A1":
        level_instruction = "ADJUSTMENT: You MUST use extremely simple vocabulary. Speak in very short sentences. Avoid complex idioms. Speak like you are talking to a beginner."
    elif level == "B1":
        level_instruction = "ADJUSTMENT: Use standard everyday conversational English. You may introduce common idioms occasionally, but keep sentences clear."
    elif level == "C1":
        level_instruction = "ADJUSTMENT: Use advanced vocabulary, complex grammar, and native expressions. Speak completely naturally and fast as if talking to a fluent native speaker."

    prompt = f"""You are Coach {coach["name"]}, style: {coach["style"]}
Level: {level} | Topic: {topic}
{level_instruction}
{history_text}

Listen to student's voice. Reply in this EXACT format (SHORT):

TRANSCRIPT: [what they said]
GOOD: [one thing done well]
TIP: [one tip, explain in Thai if pronunciation issue]
VOCAB: [word] | [part of speech] | [Thai meaning] | [1-2 Emojis visually explaining the word]
REPLY: [natural English reply + ONE follow-up question about {topic}]"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part(inline_data=types.Blob(mime_type="audio/mp4", data=audio_b64)),
                    prompt
                ]
            )
            return response.text
        except Exception as e:
            err = str(e)
            if ("503" in err or "UNAVAILABLE" in err or "429" in err) and attempt < 2:
                await asyncio.sleep([3, 8][attempt])
            else:
                raise e

# ─── PROVIDER 2: Groq (Whisper STT + Llama LLM) ──────────────────────────────
async def assess_with_groq(audio_bytes: bytes, coach_id: str, level: str, topic: str, history: list, file_path: str):
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)

    # Step 1: Transcribe with Whisper Large v3 Turbo (เร็วมาก!)
    print("Groq: Transcribing with Whisper Large v3 Turbo...")
    
    # ถ้าเป็นโหมด 2 ภาษา (Bilingual) ให้ลบ language="en" ออกเพื่อให้จับเสียงภาษาไทยได้
    whisper_kwargs = {
        "model": "whisper-large-v3-turbo",
        "response_format": "text"
    }
    if topic != "Bilingual":
        whisper_kwargs["language"] = "en"

    with open(file_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(os.path.basename(file_path), f),
            **whisper_kwargs
        )
    transcript = transcription.strip()
    print(f"Groq transcript: {transcript}")
    
    # ─── Anti-Cheat Check ───
    if not transcript or len(transcript) < 2:
        # Return a special JSON string that main endpoint can parse as cheat
        import json
        return json.dumps({
            "status": "cheat",
            "message": "โค้ชไม่ได้ยินประโยคที่ชัดเจนเลยครับ ลองพูดให้ยาวและชัดกว่านี้นิดนึงนะ (ตานี้โค้ชไม่หักโควต้าพลังงานนะ!)"
        })

    # Step 2: Feedback with GPT OSS 20B via OpenAI-compatible API
    print("Groq: Getting feedback with Llama 3...")
    prompt = build_prompt(transcript, coach_id, level, topic, history)
    chat = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-20b",
        temperature=0.7,
        max_tokens=4096,
        reasoning_effort="low",  # gpt-oss เป็นโมเดลคิดก่อนตอบ ถ้าไม่จำกัด มันคิดจนหมดโควต้า token แล้วตอบกลับว่างเปล่า
    )
    return chat.choices[0].message.content

# ─── PROVIDER 3: Ollama (fully offline) ──────────────────────────────────────
async def assess_with_ollama(audio_bytes: bytes, coach_id: str, level: str, topic: str, history: list, file_path: str):
    import httpx
    import subprocess

    # Step 1: Transcribe with faster-whisper locally
    print(f"Ollama: Transcribing locally with faster-whisper...")
    try:
        result = subprocess.run(
            ["python", "-m", "faster_whisper_cli", file_path, "--language", "en"],
            capture_output=True, text=True, timeout=60
        )
        transcript = result.stdout.strip() or "Could not transcribe audio."
    except Exception:
        # Fallback: ใช้ whisper ธรรมดา
        try:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(file_path, language="en")
            transcript = result["text"].strip()
        except Exception as e:
            transcript = f"[Transcription failed: {e}]"

    print(f"Ollama transcript: {transcript}")

    # Step 2: Feedback with Ollama local model
    print(f"Ollama: Getting feedback with {OLLAMA_MODEL}...")
    prompt = build_prompt(transcript, coach_id, level, topic, history)
    async with httpx.AsyncClient(timeout=120) as http:
        resp = await http.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
        )
        data = resp.json()
        return data.get("response", "No response from Ollama")

# ─── Database Initialization ──────────────────────────────────────────────────
import database
database.init_db()

from pydantic import BaseModel
from typing import Optional

class UserRequest(BaseModel):
    name: str
    invite_code: Optional[str] = None

class SettingRequest(BaseModel):
    quota: int
    daily_goal: int = 10

# ─── Main Endpoint ────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {
        "status": "ok",
        "provider": AI_PROVIDER,
        "message": f"AI English Tutor API v5 - Using {AI_PROVIDER.upper()}"
    }

# ─── Users & Dashboard Endpoints ──────────────────────────────────────────────
@app.post("/api/v1/users")
def create_user(req: UserRequest):
    import database as db_module
    
    # 1. Check if user already exists
    conn = db_module.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE name = %s AND (is_deleted = 0 OR is_deleted IS NULL)", (req.name,))
    exists = cursor.fetchone()
    conn.close()
    
    if exists:
        return database.get_or_create_user(req.name)
    
    # 2. If NEW user, check allow_registration first
    conn = db_module.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'allow_registration'")
    reg_setting = cursor.fetchone()
    conn.close()
    
    allow_reg = True
    if reg_setting and reg_setting[0] == 'false':
        allow_reg = False

    from fastapi import HTTPException
    
    # 3. If registration is locked, THEY MUST HAVE A VALID INVITE CODE
    if not allow_reg:
        if not req.invite_code:
            raise HTTPException(status_code=403, detail="ระบบเป็นแบบปิด กรุณากรอกรหัสเชิญ (Invite Code) จากคุณพ่อครับ")
        
        # Validate code
        is_valid = database.validate_and_use_invite_code(req.invite_code, req.name)
        if not is_valid:
            raise HTTPException(status_code=403, detail="รหัสเชิญไม่ถูกต้อง หรือถูกใช้งานไปแล้ว!")
            
        # Code is valid, bypass the lock for this user
        conn = db_module.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name) VALUES (%s)", (req.name,))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return {"id": user_id, "name": req.name}

    # If registration is OPEN, just create normally
    return database.get_or_create_user(req.name)

@app.get("/api/v1/users")
def list_users():
    return {"users": database.get_all_users()}

@app.get("/api/v1/dashboard/{user_id}")
def get_dashboard(user_id: int):
    full_data = database.get_full_dashboard(user_id)
    full_data["status"] = "success"
    full_data["user_id"] = user_id
    return full_data

@app.post("/api/v1/dashboard/reset/{user_id}")
def reset_dashboard(user_id: int):
    database.reset_today_progress(user_id)
    return {"status": "success"}


from pydantic import BaseModel
class GachaRequest(BaseModel):
    user_id: int

class WithdrawRequest(BaseModel):
    user_id: int
    amount: int

@app.post("/api/v1/wallet/withdraw")
def withdraw_wallet(req: WithdrawRequest):
    success = database.withdraw_money(req.user_id, req.amount)
    if success:
        return {"status": "success", "message": f"ถอนเงิน {req.amount} บาทสำเร็จ"}
    return {"status": "error", "message": "เงินในกระปุกไม่พอครับ!"}

@app.post("/api/v1/gacha")
def open_gacha(req: GachaRequest):
    import random
    from datetime import datetime
    
    profile = database.get_user_profile(req.user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    if profile.get('gacha_claimed_date') == today:
        return {"status": "error", "message": "วันนี้รับกล่องสุ่มไปแล้วจ้า พรุ่งนี้มาใหม่นะ!"}
    
    # สุ่มเงินรางวัลแบบมีเรท (โอกาสได้ 10, 20, 30, 50, 100)
    reward_pool = [10]*5 + [20]*3 + [30]*2 + [50]*1 + [100]*1  # โอกาส 100 คือ 1/12 (Jackpot!)
    reward = random.choice(reward_pool)
    database.claim_daily_gacha(req.user_id, reward)
    
    msg = f"ว้าว! ได้รับเงินออมเพิ่ม {reward} บาท! 🎁"
    if reward >= 100:
        msg = f"🌟 JACKPOT!! แตกรับเงินออมมหาศาล {reward} บาท! 🌟"
        
    return {"status": "success", "reward": reward, "message": msg}

@app.post("/api/v1/restore-streak")
def restore_streak(req: GachaRequest): # Reusing GachaRequest for user_id
    cost = 30
    success = database.restore_user_streak(req.user_id, cost)
    if success:
        return {"status": "success", "message": "ชุบชีวิตไฟสำเร็จ! ลุยต่อเลย 🔥"}
    return {"status": "error", "message": "เงินออมไม่พอ หรือไม่มีสถิติให้กู้คืนจ้า"}

@app.post("/api/v1/settings")
def update_settings(req: SettingRequest):
    database.update_setting('daily_quota', str(req.quota))
    database.update_setting('daily_goal', str(req.daily_goal))
    return {"status": "success", "quota": req.quota}

@app.get("/api/v1/quota")
def get_quota():
    used = database.get_daily_quota_usage()
    limit = int(database.get_setting('daily_quota', '100'))
    daily_goal = int(database.get_setting('daily_goal', '10'))
    return {"used": used, "limit": limit, "daily_goal": daily_goal}

@app.post("/api/v1/assess-audio")
async def assess_audio(
    file: UploadFile = File(...),
    level: str = Form("B1"),
    topic: str = Form("General"),
    coach_id: str = Form("alex"),
    history: str = Form("[]"),
    user_id: int = Form(0),  # เพิ่มการรับ user_id
):
    try:
        # เช็คโควต้าก่อน
        used_quota = database.get_daily_quota_usage()
        daily_limit = int(database.get_setting('daily_quota', '100'))
        if used_quota >= daily_limit:
            return {"status": "error", "message": f"Quota limit reached! You have used {used_quota}/{daily_limit} requests today.", "quota_used": used_quota, "quota_limit": daily_limit}

        import uuid
        import os

        content = await file.read()
        unique_id = uuid.uuid4().hex
        file_path = os.path.join(AUDIO_DIR, f"rec_{unique_id}.m4a")
        with open(file_path, "wb") as f:
            f.write(content)

        conv_history = json.loads(history)
        print(f"[{AI_PROVIDER.upper()}] Coach: {coach_id}, Level: {level}, Topic: {topic}, User: {user_id}")

        try:
            # ─── Route to Provider ─────────────────────────────────────────
            if AI_PROVIDER == "gemini":
                audio_b64 = base64.b64encode(content).decode("utf-8")
                feedback = await assess_with_gemini(audio_b64, coach_id, level, topic, conv_history)
            elif AI_PROVIDER == "groq":
                feedback = await assess_with_groq(content, coach_id, level, topic, conv_history, file_path)
            elif AI_PROVIDER == "ollama":
                feedback = await assess_with_ollama(content, coach_id, level, topic, conv_history, file_path)
            else:
                return {"status": "error", "message": f"Unknown provider: {AI_PROVIDER}. Use gemini/groq/ollama"}
        finally:
            # ─── Cleanup: ลบไฟล์เสียงทิ้งทันทีเพื่อไม่ให้เปลืองพื้นที่ ───
            if os.path.exists(file_path):
                os.remove(file_path)

        # ─── Anti-Cheat intercept ───
        if feedback.startswith('{"status": "cheat"'):
            return json.loads(feedback)

        # ─── Log Quota if Valid ───
        database.log_api_call()
        current_used = used_quota + 1

        # ─── Extract Fields for UI ─────────────────────────────────────
        reply_text = ""
        score = None
        stars = ""
        new_vocab = None
        options = []
        for line in feedback.split('\n'):
            line_upper = line.strip().upper()
            if line_upper.startswith('REPLY:'):
                reply_text = line.split(':', 1)[1].strip()
            elif line_upper.startswith('SCORE:'):
                score_str = line.split(':', 1)[1].strip()
                try:
                    import re
                    score = int(re.search(r'\d+', score_str).group())
                except:
                    score = score_str
            elif line_upper.startswith('STARS:'):
                stars = line.split(':', 1)[1].strip()
            elif line_upper.startswith('VOCAB:'):
                vocab_parts = line.split(':', 1)[1].strip().split('|')
                if len(vocab_parts) >= 3:
                    new_vocab = {
                        "word": vocab_parts[0].strip(),
                        "pos": vocab_parts[1].strip(),
                        "meaning": vocab_parts[2].strip(),
                        "emoji": vocab_parts[3].strip() if len(vocab_parts) >= 4 else "✨"
                    }
                    if user_id > 0:
                        try:
                            database.add_vocabulary(user_id, new_vocab["word"], new_vocab["pos"], new_vocab["meaning"])
                        except Exception as e:
                            print(f"Vocab DB Error: {e}")
            elif line_upper.startswith('OPTIONS:'):
                opts = line.split(':', 1)[1].strip().split('|')
                options = [o.strip() for o in opts if o.strip()]

        # ─── Save Progress to Database ─────────────────────────────────
        if user_id > 0:
            # เก็บ Progress ทุก Interaction เพื่อให้นับจำนวนครั้งผ่านด่านได้เสมอ แม้ AI จะลืมให้คะแนน
            score_to_save = score if isinstance(score, int) else 0
            database.save_progress(user_id, topic, score_to_save, stars)
            # อัปเดต Streak ถ้าคะแนน > 0
            if score_to_save > 0:
                database.record_play_for_streak(user_id)
            
            # ระบบค่าแรงตามความยาก (Fair Exchange Rate ป้องกันเด็กลักไก่เล่นโหมดง่าย)
            star_count = stars.count('⭐')
            earned_money = 0
            
            if level == 'A1':
                # โหมดง่ายสุด: ได้เงินแค่ 1 บาท ถ้าคะแนนเกิน 70 (ดาวไม่ช่วยเพิ่มเงิน)
                if score_to_save >= 70:
                    earned_money = 1
            elif level == 'B1':
                # โหมดปานกลาง: 1 ดาว = 1 บาท
                earned_money = star_count
            elif level == 'C1':
                # โหมดยาก: 1 ดาว = 2 บาท (ให้กำลังใจเด็กที่กล้าเล่นท่ายาก)
                earned_money = star_count * 2

            if earned_money > 0:
                database.add_money(user_id, earned_money)

        return {
            "status": "success",
            "provider": AI_PROVIDER,
            "coach": COACH_PERSONAS.get(coach_id, {}).get("name", "Alex"),
            "ai_feedback": feedback,
            "reply_text": reply_text,
            "score": score,
            "stars": stars,
            "new_vocab": new_vocab,
            "options": options,
            "quota_used": current_used,
            "quota_limit": daily_limit,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

# ─── ADMIN DASHBOARD ───
from fastapi.responses import HTMLResponse

@app.get("/admin", response_class=HTMLResponse)
def get_admin_page():
    admin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")
    if not os.path.exists(admin_path):
        return HTMLResponse("<h2>admin.html not found on server - please upload backend/admin.html to GitHub</h2>", status_code=404)
    with open(admin_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/v1/admin/dashboard")
def get_admin_dashboard():
    users = database.get_admin_dashboard_data()
    return {"status": "success", "users": users}

class AdminLoginRequest(BaseModel):
    pin: str

@app.post("/api/v1/admin/verify")
def verify_admin(req: AdminLoginRequest):
    saved_pin = database.get_setting("admin_pin", "9999")
    if req.pin == saved_pin:
        return {"status": "success"}
    return {"status": "error", "message": "รหัสผ่านไม่ถูกต้อง"}

class AdminChangePinRequest(BaseModel):
    old_pin: str
    new_pin: str

@app.post("/api/v1/admin/change_pin")
def change_admin_pin(req: AdminChangePinRequest):
    saved_pin = database.get_setting("admin_pin", "9999")
    if req.old_pin != saved_pin:
        return {"status": "error", "message": "รหัสผ่านเดิมไม่ถูกต้อง"}
    database.update_setting("admin_pin", req.new_pin)
    return {"status": "success", "message": "เปลี่ยนรหัสผ่านสำเร็จ!"}

@app.get("/api/v1/admin/settings")
def get_admin_settings():
    allow_reg = database.get_setting("allow_registration", "true")
    return {"status": "success", "allow_registration": allow_reg == "true"}

class AdminSettingsRequest(BaseModel):
    allow_registration: bool

@app.post("/api/v1/admin/settings")
def update_admin_settings(req: AdminSettingsRequest):
    database.update_setting("allow_registration", "true" if req.allow_registration else "false")
    return {"status": "success", "message": "บันทึกการตั้งค่าแล้ว!"}

class AdminAdjustRequest(BaseModel):
    user_id: int
    amount: int
    reason: str

@app.post("/api/v1/admin/wallet/adjust")
def admin_adjust_wallet(req: AdminAdjustRequest):
    if req.amount >= 0:
        database.add_money(req.user_id, req.amount, req.reason)
    else:
        import database as db_module
        conn = db_module.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance + %s WHERE user_id=%s", (req.amount, str(req.user_id)))
        cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (str(req.user_id), req.amount, req.reason))
        conn.commit()
        conn.close()
    return {"status": "success", "message": f"ปรับยอดเงิน {req.amount} บาท สำเร็จ!"}

@app.delete("/api/v1/admin/user/{user_id}")
def admin_delete_user(user_id: int):
    database.delete_user(user_id)
    return {"status": "success", "message": "ลบบัญชีเรียบร้อยแล้ว"}

@app.post("/api/v1/admin/user/{user_id}/restore")
def admin_restore_user(user_id: int):
    database.restore_user(user_id)
    return {"status": "success", "message": "กู้คืนบัญชีเรียบร้อยแล้ว"}

@app.get("/api/v1/admin/invites")
def get_admin_invites():
    return {"status": "success", "invites": database.get_all_invite_codes()}

@app.post("/api/v1/admin/invites/generate")
def admin_generate_invite():
    code = database.generate_invite_code()
    return {"status": "success", "code": code}

@app.get("/api/v1/vocabulary/{user_id}")
def get_vocabulary(user_id: int):
    return {"status": "success", "vocabulary": database.get_user_vocabulary(user_id)}


import edge_tts

VOICE_MAP = {
    'daddy': {'voice': 'en-US-GuyNeural', 'pitch': '+0Hz', 'rate': '+0%'},
    'mommy': {'voice': 'en-US-AriaNeural', 'pitch': '+0Hz', 'rate': '+0%'},
    'brother': {'voice': 'en-US-ChristopherNeural', 'pitch': '+5Hz', 'rate': '+5%'},
    'sister': {'voice': 'en-US-AvaNeural', 'pitch': '+15Hz', 'rate': '+5%'}, # Seen (12yo girl)
    'pun': {'voice': 'en-US-AndrewNeural', 'pitch': '+35Hz', 'rate': '+10%'}, # Poon (12yo boy)
    'party': {'voice': 'en-US-AnaNeural', 'pitch': '+10Hz', 'rate': '+5%'}, # Party (8yo girl)
    'pokpong': {'voice': 'en-US-BrianNeural', 'pitch': '+35Hz', 'rate': '+10%'}, # Pokpong (12yo boy)
    'yenlly': {'voice': 'en-US-JennyNeural', 'pitch': '+0Hz', 'rate': '+0%'},
    'ko': {'voice': 'en-US-SteffanNeural', 'pitch': '+0Hz', 'rate': '+0%'},
    'chit': {'voice': 'en-US-RogerNeural', 'pitch': '-15Hz', 'rate': '+5%'} # 56yo strict but fun football coach
}

@app.get("/api/v1/tts")
async def get_tts(text: str, coachId: str = 'mommy'):
    profile = VOICE_MAP.get(coachId, {'voice': 'en-US-AriaNeural', 'pitch': '+0Hz', 'rate': '+0%'})
    communicate = edge_tts.Communicate(text, profile['voice'], pitch=profile['pitch'], rate=profile['rate'])
    
    async def iterfile():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(iterfile(), media_type="audio/mpeg")

