from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from flask_login import LoginManager, login_required, current_user
from ai_brain import ask_leo_stream
from models import db, User
from auth import auth_bp
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import textwrap
import os
import uuid
import tempfile
import base64
import requests
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import json

# ✅ File understanding — text/table extraction libs
import pdfplumber
from docx import Document as DocxDocument
import pandas as pd


app = Flask(__name__)

# =========================
# AUTH / DATABASE CONFIG
# =========================

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-in-.env")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///studyai.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "auth.login"  # not-logged-in users get redirected here
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


app.register_blueprint(auth_bp)

with app.app_context():
    db.create_all()  # creates studyai.db + users table on first run


# System instruction reused across chat turns — enables language auto-detect
# and keeps Leo's persona consistent across multi-turn conversation.
# NOTE: written in English (rather than Hinglish) and explicitly NOT limited
# to English/Hindi/Hinglish, so the model treats every language equally.
CHAT_SYSTEM_PROMPT = """You are "Leo", a friendly AI study assistant inside StudyAI, helping students
all over the world with their studies.

Important rule: Always reply in the SAME language and script the student used to ask their
question — this could be English, Hindi, Spanish, French, Arabic, Portuguese, Chinese, German,
Japanese, Russian, Bengali, Hinglish, or any other language. Detect it automatically, without
asking. If the user switches language mid-conversation, switch with them.

Keep answers clear, simple, and exam-oriented. Use bullet points, headings, or examples when
they help understanding.

If the user has attached a file, its extracted content will appear inline in their message
wrapped in an "[Attached file: ...]" block — treat it as ground truth context and answer based
on it. If web search results are provided in a system message, use them to give an up-to-date
answer and list the numbered sources at the end of your reply."""


# =========================
# FILE UPLOAD CONFIG
# =========================

ALLOWED_EXT = {
    "pdf", "docx", "txt", "csv",
    "png", "jpg", "jpeg",
    "py", "js", "java", "c", "cpp", "json", "md"
}
IMAGE_EXT = {"png", "jpg", "jpeg"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_EXTRACTED_CHARS = 15000  # keep token/cost usage under control


def extract_text_from_file(filepath, ext):
    """Extracts plain text from a non-image upload. Returns '' on anything
    unexpected rather than raising, so one bad file can't break the request."""
    try:
        if ext == "pdf":
            text = ""
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        elif ext == "docx":
            doc = DocxDocument(filepath)
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext == "csv":
            df = pd.read_csv(filepath)
            return df.to_string(max_rows=200)  # truncate large CSVs
        elif ext in {"txt", "py", "js", "java", "c", "cpp", "json", "md"}:
            with open(filepath, "r", errors="ignore") as f:
                return f.read()
    except Exception:
        return ""
    return ""


# =========================
# WEB SEARCH CONFIG
# =========================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
TAVILY_URL = "https://api.tavily.com/search"


def web_search(query, max_results=5):
    """Runs a Tavily search and returns a list of {title, content, url} dicts.
    Raises on failure — caller decides how to degrade gracefully."""
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY not configured.")

    res = requests.post(
        TAVILY_URL,
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        },
        timeout=15,
    )
    res.raise_for_status()
    return res.json().get("results", [])


def build_web_context(results):
    """Formats search results into a compact numbered block for the model,
    plus a parallel list the frontend can render as clickable source chips."""
    lines = []
    sources = []
    for i, r in enumerate(results):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        content = (r.get("content") or "")[:500]
        lines.append(f"[{i + 1}] {title}\n{content}\nSource: {url}")
        sources.append({"title": title, "url": url})
    return "\n\n".join(lines), sources


@app.route("/")
def home():
    # current_user is available in templates automatically via Flask-Login,
    # no need to pass it explicitly — {{ current_user.is_authenticated }}
    # and {{ current_user.name }} just work inside index.html.
    return render_template("index.html")


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy.html")


@app.route("/sitemap.xml")
def sitemap():
    # NOTE: we only serve one real version of the page (no separate /?lang=hi
    # content actually exists server-side), so hreflang now only declares
    # "en" + "x-default" instead of falsely implying a dedicated Hindi page.
    # If/when true per-language routes are added, add matching hreflang
    # entries here pointing at those real URLs.
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://zivolf.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="en" href="https://zivolf.com/"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="https://zivolf.com/"/>
  </url>
</urlset>"""
    return Response(sitemap_xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    robots_txt = """User-agent: *
Allow: /
Disallow: /ask-stream
Disallow: /generate-notes-stream
Disallow: /download-notes-pdf
Disallow: /generate-blog-stream
Disallow: /suggest-followups
Disallow: /upload-file
Disallow: /static/generated/

Sitemap: https://zivolf.com/sitemap.xml"""
    return Response(robots_txt, mimetype="text/plain")


@app.route("/ads.txt")
def ads_txt():
    return app.send_static_file("ads.txt")


# =========================
# FILE UPLOAD (used by AI Chat attachments)
# =========================

@app.route("/upload-file", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "File nahi mili."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "File nahi mili."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Unsupported file type: .{ext}"}), 400

    # Size check before saving to disk
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return jsonify({"error": "File 10MB se badi hai."}), 400

    tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{file.filename}")
    file.save(tmp_path)

    try:
        if ext in IMAGE_EXT:
            with open(tmp_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = "jpeg" if ext == "jpg" else ext
            return jsonify({
                "type": "image",
                "filename": file.filename,
                "data_url": f"data:image/{mime};base64,{b64}"
            })
        else:
            text = extract_text_from_file(tmp_path, ext)
            if not text.strip():
                return jsonify({"error": "File se text extract nahi ho paya."}), 400
            return jsonify({
                "type": "text",
                "filename": file.filename,
                "content": text[:MAX_EXTRACTED_CHARS]
            })
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# =========================
# AI CHAT (STREAMING, MULTI-TURN)
# =========================

@app.route("/ask-stream", methods=["POST"])
# @login_required   # <-- uncomment this if you want chat to require login.
                     # Left open for now so guests can keep using chat
                     # without an account, matching the current homepage copy.
def ask_stream():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    history = data.get("history", [])  # [{role, content}, ...] sent by frontend, includes current turn
    attachments = data.get("attachments", [])  # [{type, filename, content|data_url}, ...]
    web_search_enabled = bool(data.get("web_search", False))

    if not question:
        return jsonify({"error": "Sawal khaali hai."}), 400

    if not history:
        history = [{"role": "user", "content": question}]

    # Cap history length sent to the model to control token/cost growth
    MAX_TURNS = 20
    trimmed_history = history[-MAX_TURNS:]

    # --- Fold attachments into the current (last) user turn ---
    # Text-file attachments get appended as inline context; image attachments
    # turn that turn's content into a multimodal block (text + image_url parts).
    image_attachments = [a for a in attachments if a.get("type") == "image"]
    text_attachments = [a for a in attachments if a.get("type") == "text"]

    if trimmed_history and trimmed_history[-1].get("role") == "user":
        last_turn = dict(trimmed_history[-1])
        base_text = last_turn.get("content", question)

        for att in text_attachments:
            base_text += f"\n\n[Attached file: {att.get('filename', 'file')}]\n{att.get('content', '')}"

        if image_attachments:
            content_blocks = [{"type": "text", "text": base_text}]
            for att in image_attachments:
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": att.get("data_url", "")}
                })
            last_turn["content"] = content_blocks
        else:
            last_turn["content"] = base_text

        trimmed_history = trimmed_history[:-1] + [last_turn]

    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + trimmed_history

    web_sources = []
    if web_search_enabled:
        try:
            results = web_search(question)
            context, web_sources = build_web_context(results)
            if context:
                messages.append({
                    "role": "system",
                    "content": (
                        "Here are fresh web search results — use them to answer with "
                        "up-to-date information, and list the numbered sources at the "
                        "end of your reply:\n\n" + context
                    )
                })
        except Exception:
            # Search failing shouldn't block the chat — fall back to a normal answer.
            pass

    def generate():
        try:
            # Send sources first so the frontend can render them even before
            # the model finishes streaming its answer.
            if web_sources:
                yield f"data: {json.dumps({'sources': web_sources})}\n\n"
            for chunk in ask_leo_stream(messages=messages, stream=True):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# =========================
# FOLLOW-UP QUESTION SUGGESTIONS
# =========================

@app.route("/suggest-followups", methods=["POST"])
def suggest_followups():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    answer = data.get("answer", "").strip()

    if not question or not answer:
        return jsonify({"suggestions": []})

    prompt = f"""Below is a Q&A pair. Suggest exactly 3 short, natural follow-up questions a
student might ask next — write them in the SAME language/script as the question below
(whatever language that is).

Reply ONLY as a raw JSON array of exactly 3 short strings. No extra text, no markdown, no code fences.

Question: {question}
Answer: {answer[:800]}
"""

    try:
        parts = list(ask_leo_stream(
            messages=[{"role": "user", "content": prompt}],
            stream=False
        ))
        raw = "".join(parts).strip()

        # Defensive cleanup in case the model wraps the JSON in code fences
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        suggestions = json.loads(raw)
        if not isinstance(suggestions, list):
            suggestions = []
    except Exception:
        suggestions = []

    return jsonify({"suggestions": suggestions[:3]})


# =========================
# AI NOTES GENERATOR (STREAMING)
# =========================

@app.route("/generate-notes-stream", methods=["POST"])
def generate_notes_stream():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    subject = data.get("subject", "").strip()
    class_name = data.get("class_name", "").strip()
    # Global default is English rather than Hindi, since this app now
    # targets students worldwide, not just Hindi-speaking students.
    language = data.get("language", "English").strip()

    if not topic:
        return jsonify({"error": "Topic khaali hai."}), 400

    prompt = f"""
You are an expert teacher.

Create the best possible exam-ready study notes for a student.

Topic: {topic}
Subject: {subject}
Class/Level: {class_name}
Language: {language}

Write the ENTIRE output in the language specified above — this could be English, Hindi,
Spanish, French, Arabic, Portuguese, Chinese, German, Japanese, Russian, Bengali, or any other
language. Follow it exactly, including using that language's own script.

Notes format:
1. Short Introduction
2. Simple Explanation
3. Important Definitions
4. Important Points
5. Examples
6. Exam Tips
7. 10 MCQ Questions with Answers
8. Short Summary

Keep the notes simple, clear, and exam-oriented.
"""

    def generate():
        try:
            for chunk in ask_leo_stream(messages=[{"role": "user", "content": prompt}], stream=True):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# =========================
# AI BLOG WRITER (STREAMING)
# =========================

@app.route("/generate-blog-stream", methods=["POST"])
def generate_blog_stream():
    data = request.get_json(silent=True) or {}
    topic    = data.get("topic", "").strip()
    tone     = data.get("tone", "Professional").strip()
    length   = data.get("length", "Medium (600-800 words)").strip()
    keywords = data.get("keywords", "").strip()
    # Global default is English rather than Hindi (see note above).
    language = data.get("language", "English").strip()

    if not topic:
        return jsonify({"error": "Blog topic khaali hai."}), 400

    prompt = f"""
You are a professional content writer and SEO expert.

Write a blog post on this topic:

Topic: {topic}
Tone: {tone}
Length: {length}
Target keywords: {keywords if keywords else "N/A"}
Language: {language}

Write the ENTIRE blog in the language specified above — this could be English, Hindi, Spanish,
French, Arabic, Portuguese, Chinese, German, Japanese, Russian, Bengali, or any other language.
Follow it exactly, including using that language's own script.

Blog format:
1. Catchy SEO Title
2. Short Introduction (hook)
3. Main Body (with headings/subheadings, well structured)
4. Bullet points where useful
5. Conclusion
6. Call to Action

The blog should be engaging, SEO-friendly, and original.
"""

    def generate():
        try:
            for chunk in ask_leo_stream(messages=[{"role": "user", "content": prompt}], stream=True):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# =========================
# PDF DOWNLOAD
# =========================

# Unicode code-point ranges used to guess which script a piece of text is
# written in, so we can pick a font file that actually has glyphs for it.
# Add more (font_key, ttf_filename, range_check) entries here as you bundle
# more Noto Sans variants into static/fonts/.
_SCRIPT_FONT_RULES = [
    ("Devanagari",     "NotoSansDevanagari-Regular.ttf", lambda c: "\u0900" <= c <= "\u097F"),
    ("Bengali",        "NotoSansBengali-Regular.ttf",    lambda c: "\u0980" <= c <= "\u09FF"),
    ("Arabic",         "NotoSansArabic-Regular.ttf",     lambda c: "\u0600" <= c <= "\u06FF"),
    ("Hebrew",         "NotoSansHebrew-Regular.ttf",     lambda c: "\u0590" <= c <= "\u05FF"),
    ("Cyrillic",       "NotoSans-Regular.ttf",           lambda c: "\u0400" <= c <= "\u04FF"),
    ("CJK",            "NotoSansSC-Regular.ttf",         lambda c: "\u4E00" <= c <= "\u9FFF"),
    ("Japanese-Kana",  "NotoSansSC-Regular.ttf",         lambda c: "\u3040" <= c <= "\u30FF"),
    # Catch-all: any other non-ASCII character (accented Latin, Greek, etc.)
    # falls back to the broad-coverage NotoSans-Regular file.
    ("Latin-Extended",  "NotoSans-Regular.ttf",          lambda c: ord(c) > 127),
]

_registered_font_cache = {}


def pick_pdf_font(text):
    """Inspect `text` for non-ASCII scripts and return a registered
    ReportLab font name that can render it. Falls back to the built-in
    Helvetica font (Latin-only) if the text is plain ASCII, or if the
    matching Noto Sans font file isn't bundled under static/fonts/."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    FONT_DIR = os.path.join(BASE_DIR, "static", "fonts")

    sample = text[:3000]  # sampling is enough to detect the dominant script

    for key, filename, matcher in _SCRIPT_FONT_RULES:
        if not any(matcher(ch) for ch in sample):
            continue

        if key in _registered_font_cache:
            return _registered_font_cache[key]

        font_path = os.path.join(FONT_DIR, filename)
        if not os.path.exists(font_path):
            continue

        font_name = f"Font_{key}"
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            _registered_font_cache[key] = font_name
            return font_name
        except Exception:
            continue

    return "Helvetica"


@app.route("/download-notes-pdf", methods=["POST"])
def download_notes_pdf():
    data = request.get_json(silent=True) or {}
    notes = data.get("notes", "").strip()

    if not notes:
        return jsonify({"error": "Notes khaali hai."}), 400

    # Unique filename per request so concurrent users never overwrite each other's PDF
    pdf_path = os.path.join(tempfile.gettempdir(), f"ai_notes_{uuid.uuid4().hex}.pdf")

    font_name = pick_pdf_font(notes)

    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    x = 40
    y = height - 50

    c.setFont(font_name, 16)
    c.drawString(x, y, "AI Generated Notes")
    y -= 35

    c.setFont(font_name, 11)

    for paragraph in notes.split("\n"):
        lines = textwrap.wrap(paragraph, width=85)
        if not lines:
            y -= 15
            continue
        for line in lines:
            if y < 50:
                c.showPage()
                c.setFont(font_name, 11)
                y = height - 50
            c.drawString(x, y, line)
            y -= 17

    c.save()

    try:
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name="ai_notes.pdf",
            mimetype="application/pdf"
        )
    finally:
        # Clean up the temp file after sending
        try:
            os.remove(pdf_path)
        except OSError:
            pass

if __name__ == "__main__":
    # debug=False for anything beyond local development
    app.run(debug=False, port=5000)