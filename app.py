from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from ai_brain import ask_leo_stream
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import textwrap
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import json

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy.html")

# ... existing imports ...

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

Sitemap: https://zivolf.com/sitemap.xml"""
    return Response(robots_txt, mimetype="text/plain")

@app.route("/ads.txt")
def ads_txt():
    return app.send_static_file("ads.txt")

# =========================
# AI CHAT (STREAMING)
# =========================

@app.route("/ask-stream", methods=["POST"])
def ask_stream():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Sawal khaali hai."}), 400

    def generate():
        try:
            for chunk in ask_leo_stream(question=question, stream=True):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


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
            for chunk in ask_leo_stream(question=prompt, stream=True):
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

    pdf_path = "ai_notes.pdf"

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
            except:
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

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name="ai_notes.pdf",
        mimetype="application/pdf"
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)