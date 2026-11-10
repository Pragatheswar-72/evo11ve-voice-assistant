"""
LLM + speech-to-text calls (Groq).

Groq is used because it has a free tier and is fast, which matters for a
voice assistant. Chat uses GPT-OSS 120B (Groq retired Llama 3.3 70B),
speech-to-text uses Whisper.
"""

import json
import os

from groq import Groq

CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        # strip spaces/quotes that sometimes get copied along with the key
        api_key = os.getenv("GROQ_API_KEY", "").strip().strip("\"'")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are Evo, a friendly voice assistant for Evo11ve's AI Skills Program (evo11ve.ai/for-ai).
You talk to parents and students. Your replies are read out loud, so keep them short (2-4 sentences),
simple and conversational. Do not use markdown, bullet points or emojis.

RULES
1. Answer ONLY from the CONTEXT below. If the answer is not in the context, say you don't have that
   detail and offer to arrange a callback or connect them to the Evo11ve team. Never make up dates,
   prices, discounts or policies.
2. If the question is not about Evo11ve or the AI Skills Program, politely say you can only help with
   the AI Skills Program.
3. You can do three actions:
   - "enrollment": user wants to enroll / register / book a seat. Needs name and email.
     Also ask for the student's class and preferred project if not given (optional).
   - "callback": user wants someone to call them. Needs name and phone number. Ask for a preferred time (optional).
   - "escalation": user wants a human, is unhappy, or has a problem you cannot solve. Needs name and
     either email or phone.
4. If details are missing, ask for them and keep action as "none".
5. When you have the details, read them back and ask the user to confirm (voice input can mishear emails).
   Only set the action AFTER the user confirms (e.g. "yes", "correct", "go ahead").
6. Voice transcripts write emails like "ravi kumar at gmail dot com" - convert that to "ravikumar@gmail.com".
7. Do not set an action that is listed in ALREADY_DONE. Just tell the user it is already done.
8. When you set an action, your reply should say the request is placed and an email confirmation is on the way.

Respond with a JSON object only, in this exact format:
{"reply": "...", "action": "none | enrollment | callback | escalation",
 "name": "", "email": "", "phone": "", "student_class": "", "project": "", "preferred_time": "", "note": ""}
"note" is a one-line summary of what the user needs (used in the email to the team).

ALREADY_DONE: {done}

CONTEXT:
{context}
"""


def ask_llm(message: str, history: list[dict], context: str, done_actions: list[str]) -> dict:
    system = SYSTEM_PROMPT.replace("{context}", context).replace(
        "{done}", ", ".join(done_actions) if done_actions else "nothing yet"
    )

    messages = [{"role": "system", "content": system}]
    # last few turns are enough, keeps the prompt small
    for turn in history[-10:]:
        if turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    extra = {}
    if CHAT_MODEL.startswith("openai/gpt-oss"):
        # reasoning model - keep thinking short so voice replies stay fast
        extra["reasoning_effort"] = "low"

    resp = get_client().chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=1024,
        response_format={"type": "json_object"},
        **extra,
    )
    raw = resp.choices[0].message.content

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # model didn't return proper JSON - just use the text as the reply
        data = {"reply": raw or "Sorry, I didn't get that. Could you say it again?", "action": "none"}

    # make sure every field is a clean string (model sometimes returns null)
    for key in ("reply", "action", "name", "email", "phone", "student_class", "project", "preferred_time", "note"):
        value = data.get(key)
        data[key] = "" if value is None else str(value).strip()
    data["action"] = data["action"].lower() or "none"
    data["email"] = data["email"].replace(" ", "").lower()
    return data


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    result = get_client().audio.transcriptions.create(
        model=STT_MODEL,
        file=(filename, audio_bytes),
        language="en",
    )
    return result.text.strip()
