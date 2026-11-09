"""
Streamlit frontend for the Evo11ve AI Skills voice assistant.
Talks to the FastAPI backend (API_URL) for chat, speech-to-text and text-to-speech.
"""

import hashlib
import os

import requests
import streamlit as st


def get_api_url() -> str:
    # Streamlit Cloud -> set API_URL in secrets, locally -> env var or default
    try:
        return st.secrets["API_URL"].rstrip("/")
    except Exception:
        return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


API_URL = get_api_url()

WELCOME = (
    "Hi! I'm Evo, the assistant for Evo11ve's AI Skills Program. "
    "Ask me about the curriculum, projects, fees, mentor support or certification. "
    "I can also book your enrollment, arrange a callback or connect you to our team."
)

QUICK_QUESTIONS = [
    "What is the AI Skills Program?",
    "How much does it cost?",
    "What projects can my child build?",
    "Will my child get a certificate?",
    "What mentor support is there?",
    "I want to enroll my child",
]

ACTION_LABELS = {
    "enrollment": "Enrollment request",
    "callback": "Callback request",
    "escalation": "Connected to a human",
}

st.set_page_config(page_title="Evo11ve AI Skills Assistant", page_icon="🎙️")

# ---------- session state ----------
defaults = {
    "messages": [{"role": "assistant", "content": WELCOME}],
    "done_actions": [],
    "actions_log": [],
    "last_audio_hash": None,
    "reply_audio": None,
    "autoplay": False,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ---------- backend calls ----------
@st.cache_data(ttl=60, show_spinner=False)
def backend_online() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=5).ok
    except requests.RequestException:
        return False


def error_text(resp: requests.Response) -> str:
    try:
        return resp.json().get("detail", "Something went wrong.")
    except ValueError:
        return "Something went wrong."


def transcribe(audio_bytes: bytes) -> str:
    resp = requests.post(
        f"{API_URL}/transcribe",
        files={"file": ("question.wav", audio_bytes, "audio/wav")},
        timeout=60,
    )
    if not resp.ok:
        st.error(error_text(resp))
        return ""
    return resp.json().get("text", "")


def text_to_speech(text: str):
    try:
        resp = requests.post(f"{API_URL}/tts", json={"text": text}, timeout=60)
        return resp.content if resp.ok else None
    except requests.RequestException:
        return None


def handle_message(text: str):
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": text})

    action, email_status = "none", None
    try:
        resp = requests.post(
            f"{API_URL}/chat",
            json={"message": text, "history": history, "done_actions": st.session_state.done_actions},
            timeout=90,
        )
        if resp.ok:
            data = resp.json()
            reply = data["reply"]
            action = data.get("action", "none")
            email_status = data.get("email_status")
        else:
            reply = error_text(resp)
    except requests.Timeout:
        reply = "The server is taking a while (it may be waking up). Please try again in a few seconds."
    except requests.RequestException:
        reply = "I can't reach the server right now. Please try again later."

    st.session_state.messages.append({"role": "assistant", "content": reply})

    if action in ACTION_LABELS:
        st.session_state.done_actions.append(action)
        st.session_state.actions_log.append(f"{ACTION_LABELS[action]} - email {email_status}")
        if email_status == "sent":
            st.toast("Confirmation email sent 📧")
        elif email_status == "simulated":
            st.toast("Email simulated (email service not configured)")
        else:
            st.toast("Request saved, but the email could not be sent")

    st.session_state.reply_audio = None
    if st.session_state.get("voice_on", True):
        st.session_state.reply_audio = text_to_speech(reply)
        st.session_state.autoplay = True


# ---------- sidebar ----------
pending = None

with st.sidebar:
    st.header("Evo11ve AI Skills")
    if backend_online():
        st.success("Assistant online", icon="✅")
    else:
        st.warning("Server is waking up / offline. First reply may be slow.", icon="⏳")

    st.toggle("Speak replies out loud", value=True, key="voice_on")

    st.subheader("Quick questions")
    for q in QUICK_QUESTIONS:
        if st.button(q, use_container_width=True):
            pending = q

    st.divider()
    if st.button("🙋 Talk to a human", use_container_width=True):
        pending = "I'd like to talk to a human from the Evo11ve team."

    if st.button("🗑️ Clear chat", use_container_width=True):
        # keep last_audio_hash so an old recording isn't sent again
        for key in ("messages", "done_actions", "actions_log", "reply_audio", "autoplay"):
            del st.session_state[key]
        st.rerun()

    if st.session_state.actions_log:
        st.subheader("Actions taken")
        for item in st.session_state.actions_log:
            st.write("•", item)

    st.caption("Program info from evo11ve.ai/for-ai")


# ---------- main area ----------
st.title("🎙️ Evo11ve AI Skills Assistant")
st.caption("Ask by voice or text about Evo11ve's AI Skills Program for Classes 6-12.")

audio = st.audio_input("Tap the mic, ask your question, then tap again to stop")
typed = st.chat_input("Or type your question here...")

if typed:
    pending = typed

if audio is not None:
    audio_bytes = audio.getvalue()
    audio_hash = hashlib.md5(audio_bytes).hexdigest()
    # streamlit reruns the script a lot - only process a recording once
    if audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        with st.spinner("Listening..."):
            heard = transcribe(audio_bytes)
        if heard:
            pending = heard
        else:
            st.warning("Sorry, I couldn't hear that clearly. Please try again.")

if pending:
    with st.spinner("Thinking..."):
        handle_message(pending)

last = len(st.session_state.messages) - 1
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "🧑"):
        st.write(msg["content"])
        # play the voice reply under the latest answer
        if i == last and msg["role"] == "assistant" and st.session_state.reply_audio:
            st.audio(st.session_state.reply_audio, format="audio/mp3", autoplay=st.session_state.autoplay)
            st.session_state.autoplay = False
