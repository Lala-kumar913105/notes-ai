from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from ai_brain import ask_leo_stream
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import textwrap
import os
import uuid
import tempfile
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import json


app = Flask(__name__)

# System instruction reused across chat turns — enables language auto-detect
# and keeps Leo's persona consistent across multi-turn conversation.
CHAT_SYSTEM_PROMPT = """Tum StudyAI ke andar "Leo" naam ka ek friendly AI study assistant ho, jo students ko
duniya bhar me padhai me madad karta hai.

Bahut zaroori rule: Jis language/script me student sawal poochta hai (English, Hindi, ya Hinglish),
usi language me jawab do — bina poochhe khud detect karke. Agar user language switch kare beech
conversation me, tum bhi switch kar do.

Jawab clear, simple aur exam-oriented rakho. Zaroorat ho to bullet points, headings, ya examples use karo."""


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy.html")


@app.route("/sitemap.xml")
def sitemap():
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://zivolf.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="hi" href="https://zivolf.com/"/>
    <xhtml:link rel="alternate" hreflang="en" href="https://zivolf.com/"/>
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
Disallow: /static/generated/

Sitemap: https://zivolf.com/sitemap.xml"""
    return Response(robots_txt, mimetype="text/plain")

@app.route("/ads.txt")
def ads_txt():
    return app.send_static_file("ads.txt")

# =========================
# AI CHAT (STREAMING, MULTI-TURN)
# =========================

@app.route("/ask-stream", methods=["POST"])
def ask_stream():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    history = data.get("history", [])  # [{role, content}, ...] sent by frontend, includes current turn

    if not question:
        return jsonify({"error": "Sawal khaali hai."}), 400

    # Build full message list: system prompt + conversation history.
    # Frontend already appends the current user turn to `history` before sending,
    # so we don't need to add `question` again here.
    if not history:
        history = [{"role": "user", "content": question}]

    # Cap history length sent to the model to control token/cost growth
    MAX_TURNS = 20
    trimmed_history = history[-MAX_TURNS:]

    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + trimmed_history

    def generate():
        try:
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

    prompt = f"""Neeche ek Q&A diya gaya hai. Ismein se exactly 3 chhote, natural follow-up
questions suggest karo jo ek student agla pooch sakta hai — same language/script me jismein
neeche ka question likha hai.

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
    language = data.get("language", "Hindi").strip()

    if not topic:
        return jsonify({"error": "Topic khaali hai."}), 400

    prompt = f"""
Tum ek expert teacher ho.

Student ke exam ke liye best AI notes banao.

Topic: {topic}
Subject: {subject}
Class: {class_name}
Language: {language}

Notes format:
1. Short Introduction
2. Simple Explanation
3. Important Definitions
4. Important Points
5. Examples
6. Exam Tips
7. 10 MCQ Questions with Answers
8. Short Summary

Notes simple aur exam oriented hone chahiye.
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
    language = data.get("language", "Hindi").strip()

    if not topic:
        return jsonify({"error": "Blog topic khaali hai."}), 400

    prompt = f"""
Tum ek professional content writer aur SEO expert ho.

Ek blog post likho is topic par:

Topic: {topic}
Tone: {tone}
Length: {length}
Target keywords: {keywords if keywords else "N/A"}
Language: {language}

Blog format:
1. Catchy SEO Title
2. Short Introduction (hook)
3. Main Body (headings/subheadings ke sath, well structured)
4. Bullet points jaha zarurat ho
5. Conclusion
6. Call to Action

Blog engaging, SEO-friendly aur original hona chahiye.
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

@app.route("/download-notes-pdf", methods=["POST"])
def download_notes_pdf():
    data = request.get_json(silent=True) or {}
    notes = data.get("notes", "").strip()

    if not notes:
        return jsonify({"error": "Notes khaali hai."}), 400

    # Unique filename per request so concurrent users never overwrite each other's PDF
    pdf_path = os.path.join(tempfile.gettempdir(), f"ai_notes_{uuid.uuid4().hex}.pdf")

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    font_paths = [
        os.path.join(BASE_DIR, "static", "fonts", "NotoSansDevanagari-Regular.ttf"),
    ]

    font_name = "Helvetica"
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("HindiFont", path))
                font_name = "HindiFont"
                break
            except Exception:
                continue

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