"""Functional tests for Notes Generator Professional Mode:
- _build_notes_prompt branches to the workplace-brief format when
  mode="professional" and stays byte-identical to student mode otherwise.
- /generate-notes-stream accepts mode="professional" and streams, and the
  captured prompt reflects the new workplace-summary format (executive
  summary, key points/decisions, action items, risks/open questions, and
  suggested next steps).
- Existing routes (/generate-quiz) still work on professional-mode content.

Run from the project root:
    ./venv/bin/python test_professional_mode.py
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
            yield "pro-chunk "
            yield "workplace-chunk"
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
PRO_FORMAT = appmod.PROFESSIONAL_MODE_FORMAT

student_prompt = appmod._build_notes_prompt(
    "Q3 Earnings Call", "Business", "Team", "English",
    has_attachment=False, note_style="detailed", mode="student")
pro_prompt = appmod._build_notes_prompt(
    "Q3 Earnings Call", "Business", "Team", "English",
    has_attachment=False, note_style="detailed", mode="professional")

check("professional prompt uses the workplace-brief format",
      PRO_FORMAT in pro_prompt
      and "1. Executive summary" in pro_prompt
      and "2. Key points / decisions made" in pro_prompt
      and "3. Action items" in pro_prompt
      and "4. Risks or open questions worth flagging" in pro_prompt
      and "5. Suggested next steps" in pro_prompt)
check("professional prompt drops the student Notes format",
      "Notes format:" not in pro_prompt and "10 MCQ Questions with Answers" not in pro_prompt)
check("professional prompt has no lesson-package sections",
      "Lesson objectives" not in pro_prompt and "Teaching outline" not in pro_prompt)
check("student prompt is untouched by professional mode",
      STUDENT_FORMAT in student_prompt and "Workplace-brief format:" not in student_prompt)
check("professional prompt uses a workplace persona",
      "workplace briefs" in pro_prompt and "expert teacher" not in pro_prompt)

# Professional Mode ignores Note Style — every style maps to the same format.
pro_base = appmod._build_notes_prompt(
    "X", "S", "C", "English", False, note_style="detailed", mode="professional")
for style in ("quick", "exam", "revision"):
    same = appmod._build_notes_prompt(
        "X", "S", "C", "English", False, note_style=style, mode="professional")
    check(f"professional prompt ignores note_style={style}", same == pro_base)

# Attachment wording branches per mode.
student_att = appmod._build_notes_prompt(
    "X", "S", "C", "English", True, note_style="detailed", mode="student")
pro_att = appmod._build_notes_prompt(
    "X", "S", "C", "English", True, note_style="detailed", mode="professional")
check("student attachment wording unchanged (base notes on that attached material)",
      "base the notes primarily on that attached material" in student_att)
check("professional attachment wording mentions the workplace brief",
      "base the workplace brief primarily on that attached material" in pro_att)

# ---------- 2. /generate-notes-stream accepts mode=professional and streams ----------
pro_res = run_notes({
    "topic": "Q3 Earnings Call", "subject": "Business",
    "class_name": "Team", "language": "English",
    "note_style": "detailed", "mode": "professional",
    "attachments": [],
})
check("generate-notes-stream (mode=professional) returns 200", pro_res[0] == 200)
check("professional streamed both chunks", pro_res[1] == "pro-chunk workplace-chunk")
pro_prompt_sent = captured["messages"][0]["content"]
check("sent professional prompt is the workplace-brief format",
      "Workplace-brief format:" in pro_prompt_sent
      and "1. Executive summary" in pro_prompt_sent
      and "3. Action items" in pro_prompt_sent
      and "5. Suggested next steps" in pro_prompt_sent)
check("sent professional prompt is NOT the student/teacher formats",
      "Notes format:" not in pro_prompt_sent
      and "Lesson-package format:" not in pro_prompt_sent)

# ---------- 3. Professional Mode with attachments still works ----------
att_res = run_notes({
    "topic": "", "subject": "Business",
    "class_name": "Team", "language": "English",
    "note_style": "detailed", "mode": "professional",
    "attachments": [{"type": "text", "filename": "meeting_transcript.txt",
                     "content": "Alice will own the migration. Decision: ship in March."}],
})
check("professional mode with an attachment returns 200", att_res[0] == 200)
att_prompt = captured["messages"][0]["content"]
check("professional prompt includes the attachment and brief wording",
      "[Attached source 1: meeting_transcript.txt]" in att_prompt
      and "base the workplace brief primarily" in att_prompt)

# ---------- 4. Existing /generate-quiz works on professional content unchanged ----------
quiz_res = client.post("/generate-quiz", json={
    "notes": "1. Executive summary\n2. Key points / decisions\n3. Action items",
    "language": "English",
})
check("/generate-quiz still returns 200 on professional content", quiz_res.status_code == 200)

print()
failed = sum(1 for r in results if not r)
print(f"{len(results) - failed}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
