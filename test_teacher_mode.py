"""Functional tests for Notes Generator Teacher Mode:
- _build_notes_prompt branches to the lesson-package format when
  mode="teacher" and stays byte-identical to student mode otherwise.
- /generate-notes-stream accepts mode and streams, and the
  captured prompt reflects the right format.
- Existing routes (/generate-quiz) still work on teacher-mode content.

Run from the project root:
    ./venv/bin/python test_teacher_mode.py
"""
import json
import os
import sys

PROJECT = "/home/freefireloverfreefirelover513/master ai/leo-assistant"
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

import app as appmod  # noqa: E402

appmod.app.config["TESTING"] = True
client = appmod.app.test_client()

results = []


def check(name, ok, extra=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, extra)


def fake_ask_leo_stream(messages=None, stream=True, **kw):
    captured["messages"] = messages
    def gen():
        if not stream:
            # /generate-quiz etc. ask for non-streamed raw JSON.
            yield json.dumps([{"type": "mcq", "question": "q1",
                               "options": ["a", "b", "c", "d"], "answer": 0,
                               "explanation": "e"}])
        else:
            yield "teacher-chunk "
            yield "student-chunk"
    return gen()


captured = {}
appmod.ask_leo_stream = fake_ask_leo_stream


def run_notes(payload):
    res = client.post("/generate-notes-stream", json=payload)
    if res.status_code != 200:
        return res.status_code, "", res.get_json()
    body = ""
    for line in res.get_data(as_text=True).split("\n"):
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[6:])
        except Exception:
            continue
        if "chunk" in evt:
            body += evt["chunk"]
        if evt.get("done"):
            break
        if evt.get("error"):
            return res.status_code, body, evt["error"]
    return res.status_code, body, None


# ---------- 1. Prompt builder branching ----------
STUDENT_FORMAT = appmod.NOTE_STYLES["detailed"][1]
TEACHER_FORMAT = appmod.TEACHER_MODE_FORMAT

student_prompt = appmod._build_notes_prompt(
    "Photosynthesis", "Science", "High School", "English",
    has_attachment=False, note_style="detailed", mode="student")
student_default = appmod._build_notes_prompt(
    "Photosynthesis", "Science", "High School", "English",
    has_attachment=False, note_style="detailed")
teacher_prompt = appmod._build_notes_prompt(
    "Photosynthesis", "Science", "High School", "English",
    has_attachment=False, note_style="detailed", mode="teacher")

check("student default == explicit mode='student' (byte-identical)",
      student_prompt == student_default)
check("student prompt keeps the detailed Notes format",
      STUDENT_FORMAT in student_prompt and "10 MCQ Questions with Answers" in student_prompt)
check("student prompt has no lesson-package sections",
      "Lesson objectives" not in student_prompt and "Answer key" not in student_prompt)
check("teacher prompt uses the lesson-package format",
      TEACHER_FORMAT in teacher_prompt and "1. Lesson objectives" in teacher_prompt
      and "7. An answer key for the worksheet" in teacher_prompt)
check("teacher prompt drops the student Notes format",
      "Notes format:" not in teacher_prompt and "10 MCQ Questions with Answers" not in teacher_prompt)

# Teacher Mode ignores Note Style — every style maps to the same format.
teacher_base = appmod._build_notes_prompt(
    "X", "S", "C", "English", False, note_style="detailed", mode="teacher")
for style in ("quick", "exam", "professional"):
    same = appmod._build_notes_prompt(
        "X", "S", "C", "English", False, note_style=style, mode="teacher")
    check(f"teacher prompt ignores note_style={style}", same == teacher_base)

# Attachment wording branches only in teacher mode.
student_att = appmod._build_notes_prompt(
    "X", "S", "C", "English", True, note_style="detailed", mode="student")
teacher_att = appmod._build_notes_prompt(
    "X", "S", "C", "English", True, note_style="detailed", mode="teacher")
check("student attachment wording unchanged (base notes on that attached material)",
      "base the notes primarily on that attached material" in student_att)
check("teacher attachment wording mentions the lesson-plan package",
      "base the lesson-plan package primarily on that attached material" in teacher_att)

# ---------- 2. /generate-notes-stream accepts mode and streams ----------
teacher_res = run_notes({
    "topic": "Photosynthesis", "subject": "Science",
    "class_name": "High School", "language": "English",
    "note_style": "detailed", "mode": "teacher",
    "attachments": [],
})
check("generate-notes-stream (mode=teacher) returns 200", teacher_res[0] == 200)
check("teacher streamed both chunks", teacher_res[1] == "teacher-chunk student-chunk")
teacher_prompt_sent = captured["messages"][0]["content"]
check("sent teacher prompt is the lesson-package format",
      "Lesson-package format:" in teacher_prompt_sent
      and "1. Lesson objectives" in teacher_prompt_sent)

student_res = run_notes({
    "topic": "Photosynthesis", "subject": "Science",
    "class_name": "High School", "language": "English",
    "note_style": "detailed", "mode": "student",
    "attachments": [],
})
check("generate-notes-stream (mode=student) returns 200", student_res[0] == 200)
student_prompt_sent = captured["messages"][0]["content"]
check("sent student prompt is the unchanged Notes format",
      "Notes format:" in student_prompt_sent
      and "10 MCQ Questions with Answers" in student_prompt_sent
      and "Lesson-package format:" not in student_prompt_sent)

# mode absent == student mode (defaults to "student")
absent_res = run_notes({
    "topic": "Photosynthesis", "subject": "Science",
    "class_name": "High School", "language": "English",
    "attachments": [],
})
check("mode absent behaves like student mode",
      absent_res[0] == 200
      and "Notes format:" in captured["messages"][0]["content"]
      and "Lesson-package format:" not in captured["messages"][0]["content"])

# Unknown modes fall back to student mode.
unknown_res = run_notes({
    "topic": "Photosynthesis", "subject": "Science",
    "class_name": "High School", "language": "English",
    "note_style": "detailed", "mode": "wizard",
    "attachments": [],
})
check("unknown mode falls back to student mode",
      unknown_res[0] == 200
      and "Notes format:" in captured["messages"][0]["content"]
      and "Lesson-package format:" not in captured["messages"][0]["content"])

# ---------- 3. Teacher Mode with attachments still works ----------
att_res = run_notes({
    "topic": "", "subject": "Science",
    "class_name": "High School", "language": "English",
    "note_style": "detailed", "mode": "teacher",
    "attachments": [{"type": "text", "filename": "chapter.pdf", "content": "Photosynthesis content here."}],
})
check("teacher mode with an attachment returns 200", att_res[0] == 200)
att_prompt = captured["messages"][0]["content"]
check("teacher prompt includes the attachment and teacher wording",
      "[Attached source 1: chapter.pdf]" in att_prompt
      and "base the lesson-plan package primarily" in att_prompt)

# ---------- 4. Existing /generate-quiz works on teacher-mode content unchanged ----------
quiz_res = client.post("/generate-quiz", json={
    "notes": "1. Lesson objectives\n2. Teaching outline\n6. A short worksheet",
    "language": "English",
})
check("/generate-quiz still returns 200 on teacher content", quiz_res.status_code == 200)

print()
failed = sum(1 for r in results if not r)
print(f"{len(results) - failed}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
