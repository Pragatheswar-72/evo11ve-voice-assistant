"""
FastAPI backend for the Evo11ve AI Skills voice assistant.

Endpoints
  GET  /health      - quick status check
  POST /chat        - text in -> answer (+ triggers email actions)
  POST /transcribe  - audio file in -> text (Whisper)
  POST /tts         - text in -> mp3 audio (gTTS)
"""

import csv
import io
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env before the other modules read env vars

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from gtts import gTTS
from pydantic import BaseModel

from emailer import build_emails, send_email
from llm import ask_llm, transcribe
from rag import KnowledgeBase

BASE_DIR = Path(__file__).parent
kb = KnowledgeBase(BASE_DIR / "knowledge_base" / "ai_skills_program.md")
LEADS_FILE = BASE_DIR / "leads.csv"

app = FastAPI(title="Evo11ve AI Skills Voice Assistant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    done_actions: list[str] = []


class TTSRequest(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok", "kb_sections": len(kb.chunks)}


@app.post("/chat")
def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")

    # search with the current message, and also with the previous user message added,
    # so follow-ups like "how much is it?" still find the right sections
    prev_user = [t["content"] for t in req.history if t.get("role") == "user"][-1:]
    sections = kb.search(message)
    if prev_user:
        sections += kb.search(" ".join(prev_user + [message]))
    context = "\n\n".join(list(dict.fromkeys(sections))[:5])

    try:
        result = ask_llm(message, req.history, context, req.done_actions)
    except Exception as e:
        print("LLM error:", e)
        raise HTTPException(502, "The AI service is not responding right now. Please try again.")

    action = result.get("action", "none")
    email_status = None

    if action in ("enrollment", "callback", "escalation"):
        missing = check_details(action, result)
        if missing:
            # model tried to act without enough info - don't send anything yet.
            # keep its reply if it's already asking the user something, otherwise ask for the details
            if not result["reply"].rstrip().endswith("?"):
                result["reply"] = f"Sure, I can help with that. Could you please share your {missing}?"
            action = "none"
        elif action in req.done_actions:
            action = "none"
        else:
            transcript = make_transcript(req.history, message, result["reply"])
            statuses = [send_email(to, subj, body) for to, subj, body in build_emails(action, result, transcript)]
            email_status = summarise(statuses)
            save_lead(action, result, email_status)

    return {
        "reply": result["reply"],
        "action": action,
        "email_status": email_status,
    }


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty audio")
    try:
        text = transcribe(audio, file.filename or "audio.wav")
    except Exception as e:
        print("STT error:", e)
        raise HTTPException(502, "Could not transcribe the audio.")
    return {"text": text}


@app.post("/tts")
def text_to_speech(req: TTSRequest):
    text = req.text.strip()[:1000]
    if not text:
        raise HTTPException(400, "Empty text")
    try:
        buf = io.BytesIO()
        gTTS(text=text, lang="en", tld="co.in").write_to_fp(buf)  # Indian English voice
    except Exception as e:
        print("TTS error:", e)
        raise HTTPException(502, "Text to speech failed.")
    return Response(content=buf.getvalue(), media_type="audio/mpeg")


@app.get("/leads")
def get_leads(key: str = ""):
    # tiny admin view of captured leads, protected with ADMIN_KEY
    if not os.getenv("ADMIN_KEY") or key != os.getenv("ADMIN_KEY"):
        raise HTTPException(403, "Not allowed")
    if not LEADS_FILE.exists():
        return []
    with open(LEADS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- helpers ----------

def check_details(action: str, d: dict) -> str | None:
    """Return a description of what's missing, or None if we have enough to act."""
    has_name = bool(d.get("name"))
    has_email = bool(EMAIL_RE.match(d.get("email") or ""))
    has_phone = len(re.sub(r"\D", "", d.get("phone") or "")) >= 10

    if action == "enrollment" and not (has_name and has_email):
        return "name and email address"
    if action == "callback" and not (has_name and has_phone):
        return "name and phone number"
    if action == "escalation" and not (has_name and (has_email or has_phone)):
        return "name and an email or phone number"
    return None


def make_transcript(history: list[dict], message: str, reply: str) -> str:
    lines = [f"{t['role']}: {t['content']}" for t in history[-10:]]
    lines += [f"user: {message}", f"assistant: {reply}"]
    return "\n".join(lines)


def summarise(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "simulated" in statuses:
        return "simulated"
    return "sent"


def save_lead(action: str, d: dict, email_status: str):
    is_new = not LEADS_FILE.exists()
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["time", "action", "name", "email", "phone", "student_class", "project",
                        "preferred_time", "note", "email_status"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), action, d.get("name", ""), d.get("email", ""),
                    d.get("phone", ""), d.get("student_class", ""), d.get("project", ""),
                    d.get("preferred_time", ""), d.get("note", ""), email_status])
