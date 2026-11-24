import os
import uuid
from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
documents = {}  # Demo storage: uploaded PDF text is kept in server memory.

LEVELS = ["A1.1", "A1.2", "A2.1", "A2.2", "B1.1", "B1.2", "B2.1", "B2.2"]

@app.route("/")
def home():
    session.setdefault("chat_id", str(uuid.uuid4()))
    return render_template("index.html", levels=LEVELS)

@app.post("/upload")
def upload_pdf():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify(error="ارفعي ملف PDF فقط."), 400
    try:
        reader = PdfReader(file.stream)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            return jsonify(error="الملف لا يحتوي على نص قابل للاستخراج. لو الملف صور ممسوحة ضوئيًا، نحتاج إضافة OCR."), 400
        chat_id = session.setdefault("chat_id", str(uuid.uuid4()))
        documents[chat_id] = {"name": secure_filename(file.filename), "text": text[:180000]}
        return jsonify(message=f"تم رفع {file.filename} بنجاح، وعدد الصفحات: {len(reader.pages)}.")
    except Exception as exc:
        return jsonify(error=f"تعذر قراءة الملف: {str(exc)}"), 400

def tutor_instructions(level, help_language, mode, document_text):
    lang_names = {"ar": "Arabic", "en": "English", "de": "German"}
    mode_names = {
        "conversation": "natural conversation practice",
        "grammar": "grammar practice and explanations",
        "vocabulary": "vocabulary practice",
        "exam": "exam-style questions",
    }
    return f"""
You are a patient, encouraging German tutor for an Alsun (German department) university student.
Student level: {level}. Practice type: {mode_names.get(mode, 'natural conversation practice')}.
Main conversation language: German, appropriate to {level}. Do not make the German too advanced.
When the student makes a German mistake, first respond naturally, then give a short correction and explain why.
Use the student's chosen support language ({lang_names.get(help_language, 'Arabic')}) only for explanations when useful.
Base lessons, examples, questions, and vocabulary on the uploaded course material below whenever it is relevant.
Never claim something is in the PDF if it is not present. If the PDF does not cover the topic, say so and offer general practice.
Keep the conversation interactive: ask one question at a time and wait for the student's answer.
For vocabulary questions, explain the word in the requested language or in simple German if requested.
Uploaded course material:
{document_text if document_text else '[No PDF uploaded yet. Ask the student to upload course material, or offer general level-based practice.]'}
"""

@app.post("/chat")
def chat():
    if client is None:
        return jsonify(error="لازم تضيفي OPENAI_API_KEY في ملف .env قبل تشغيل البرنامج."), 503
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error="اكتبي رسالة الأول."), 400

    level = data.get("level", "A1.1")
    if level not in LEVELS:
        level = "A1.1"
    help_language = data.get("help_language", "ar")
    if help_language not in ("ar", "en", "de"):
        help_language = "ar"
    mode = data.get("mode", "conversation")
    chat_id = session.setdefault("chat_id", str(uuid.uuid4()))
    doc = documents.get(chat_id, {})
    history = data.get("history", [])[-10:]
    input_messages = []
    for item in history:
        role = item.get("role")
        content = item.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str):
            input_messages.append({"role": role, "content": content[:4000]})
    input_messages.append({"role": "user", "content": message})

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-6.2-sol"),
            instructions=tutor_instructions(level, help_language, mode, doc.get("text", "")),
            input=input_messages,
        )
        return jsonify(reply=response.output_text)
    except Exception as exc:
        return jsonify(error=f"حصلت مشكلة في الاتصال: {str(exc)}"), 500

@app.post("/dictionary")
def dictionary():
    if client is None:
        return jsonify(error="أضيفي مفتاح API أولًا."), 503
    data = request.get_json(force=True)
    word = (data.get("word") or "").strip()
    target = data.get("target", "ar")
    if not word:
        return jsonify(error="اكتبي الكلمة أو الجملة."), 400
    targets = {"ar": "Arabic", "en": "English", "de": "simple German (German-German definition)"}
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-6.2-sol"),
            instructions="You are a precise German dictionary for a university language learner. Give: part of speech, article/plural if it is a noun, meaning in the requested language, a short German example with translation, and a useful synonym when appropriate. Be concise.",
            input=f"Explain this German word or phrase: {word}\nExplain in: {targets.get(target, 'Arabic')}.",
        )
        return jsonify(result=response.output_text)
    except Exception as exc:
        return jsonify(error=str(exc)), 500

if __name__ == "__main__":
    app.run(debug=True)
