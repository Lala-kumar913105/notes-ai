from flask import Flask, render_template, request, jsonify, send_file
from ai_brain import ask_leo
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import textwrap
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)


SCREEN_KEYWORDS = [
    "meri screen par kya hai",
    "screen me kya dikh raha hai",
    "is page ko samjhao",
    "screen",
    "page",
    "tab",
    "window",
    "display",
    "kya dikh raha hai",
    "kya likha hai",
    "ye page",
    "ye screen"
]


def should_use_screen(question: str) -> bool:
    q = question.lower().strip()
    return any(keyword in q for keyword in SCREEN_KEYWORDS)



@app.route("/")
def home():
    return render_template("index.html")



# =========================
# AI CHAT + SCREEN ANALYSIS
# =========================

@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json(silent=True) or {}

    question = data.get(
        "question",
        ""
    ).strip()

    image_data = data.get("image")

    if not question:
        return jsonify({
            "answer": "Sawal khaali hai."
        }), 400


    image_path = None


    try:

        use_screen = should_use_screen(question)


        if use_screen and image_data:

            if "," in image_data:

                image_data = image_data.split(
                    ",",
                    1
                )[1]


            image_path = "browser_screen.png"


            with open(
                image_path,
                "wb"
            ) as f:

                f.write(
                    base64.b64decode(
                        image_data
                    )
                )


        answer = ask_leo(
            question=question,
            image_path=image_path
        )


        return jsonify({

            "answer": answer,

            "used_screen": use_screen

        })


    except Exception as e:

        return jsonify({

            "answer": f"Error: {str(e)}"

        }), 500




# =========================
# AI NOTES GENERATOR
# =========================

@app.route("/generate-notes", methods=["POST"])
def generate_notes():


    data = request.get_json(
        silent=True
    ) or {}


    topic = data.get(
        "topic",
        ""
    ).strip()


    subject = data.get(
        "subject",
        ""
    ).strip()


    class_name = data.get(
        "class_name",
        ""
    ).strip()


    language = data.get(
        "language",
        "Hindi"
    ).strip()



    if not topic:

        return jsonify({

            "notes": "Topic khaali hai."

        }), 400



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



    try:

        notes = ask_leo(
            question=prompt
        )


        return jsonify({

            "notes": notes

        })


    except Exception as e:

        return jsonify({

            "notes": f"Error: {str(e)}"

        }), 500






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

    font_path = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"

    try:
        pdfmetrics.registerFont(TTFont("HindiFont", font_path))
        font_name = "HindiFont"
    except Exception:
        font_name = "Helvetica"

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

    app.run(

        debug=True,

        port=5000

    )