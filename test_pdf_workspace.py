"""Functional tests for the PDF Workspace flow
(/upload-file PDF text extraction -> /pdf-workspace-stream for
summarize / ask / explain / translate / compare).

Run from the project root:
    venv/bin/python test_pdf_workspace.py
"""
import io
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
        yield "chunk-one "
        yield "chunk-two"
    return gen()


captured = {}
appmod.ask_leo_stream = fake_ask_leo_stream


def build_pdf_bytes(text):
    """Creates a real one-page PDF via reportlab (already a dependency)."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 12)
    y = 780
    for line in text.split("\n"):
        c.drawString(60, y, line[:90])
        y -= 20
    c.save()
    buf.seek(0)
    return buf.read()


def upload_pdf(name, text):
    pdf_bytes = build_pdf_bytes(text)
    res = client.post(
        "/upload-file",
        data={"file": (io.BytesIO(pdf_bytes), name)},
        content_type="multipart/form-data",
    )
    return res


def run_stream(payload):
    import json as _json
    res = client.post("/pdf-workspace-stream", json=payload)
    if res.status_code != 200:
        return res.status_code, "", res.get_json()
    body = ""
    for line in res.get_data(as_text=True).split("\n"):
        if not line.startswith("data: "):
            continue
        try:
            evt = _json.loads(line[6:])
        except Exception:
            continue
        if "chunk" in evt:
            body += evt["chunk"]
        if evt.get("done"):
            break
        if evt.get("error"):
            return res.status_code, body, evt["error"]
    return res.status_code, body, None


# ---------- 1. Upload a PDF through the existing /upload-file route ----------
PDF1_TEXT = (
    "Photosynthesis is the process by which green plants convert light into chemical energy.\n"
    "It happens in chloroplasts and requires chlorophyll, sunlight, water, and carbon dioxide.\n"
    "Oxygen is released as a by-product during the light-dependent reactions."
)
res1 = upload_pdf("chapter1.pdf", PDF1_TEXT)
check("upload-file returns 200 for a PDF", res1.status_code == 200,
      f"status={res1.status_code}")
data1 = res1.get_json()
check("upload-file returns text type + content", data1.get("type") == "text"
      and len(data1.get("content", "")) > 50)
check("uploaded content capped at MAX_EXTRACTED_CHARS",
      len(data1.get("content", "")) <= appmod.MAX_EXTRACTED_CHARS)

PDF2_TEXT = (
    "Cellular respiration breaks down glucose to release ATP energy inside mitochondria.\n"
    "It requires oxygen and produces carbon dioxide and water as waste products.\n"
    "Glycolysis, the Krebs cycle, and oxidative phosphorylation are its main stages."
)
res2 = upload_pdf("chapter2.pdf", PDF2_TEXT)
check("upload-file works for the second PDF", res2.status_code == 200)
data2 = res2.get_json()

# ---------- 2. Each action streams sensible output ----------
summary = run_stream({
    "action": "summarize",
    "pdf_text_1": data1["content"],
    "filename_1": "chapter1.pdf",
    "pdf_text_2": "",
    "filename_2": "",
    "question": "",
    "target_language": "",
})
check("summarize returns 200", summary[0] == 200)
check("summarize streams combined chunks",
      summary[1] == "chunk-one chunk-two", f"got={summary[1]!r}")
check("summarize prompt contains the document text",
      "Photosynthesis" in captured["messages"][0]["content"]
      and "[Document: chapter1.pdf]" in captured["messages"][0]["content"])

asked = run_stream({
    "action": "ask",
    "pdf_text_1": data1["content"],
    "filename_1": "chapter1.pdf",
    "pdf_text_2": "",
    "filename_2": "",
    "question": "Where does photosynthesis happen?",
    "target_language": "",
})
check("ask returns 200", asked[0] == 200)
check("ask prompt includes the question",
      "Where does photosynthesis happen?" in captured["messages"][0]["content"])

explained = run_stream({
    "action": "explain",
    "pdf_text_1": data1["content"],
    "filename_1": "chapter1.pdf",
    "pdf_text_2": "",
    "filename_2": "",
    "question": "",
    "target_language": "",
})
check("explain returns 200 and streams", explained[0] == 200 and explained[1])

translated = run_stream({
    "action": "translate",
    "pdf_text_1": data1["content"],
    "filename_1": "chapter1.pdf",
    "pdf_text_2": "",
    "filename_2": "",
    "question": "",
    "target_language": "Hindi",
})
check("translate returns 200 and streams", translated[0] == 200 and translated[1])
check("translate prompt names the target language",
      "Hindi" in captured["messages"][0]["content"])

compared = run_stream({
    "action": "compare",
    "pdf_text_1": data1["content"],
    "filename_1": "chapter1.pdf",
    "pdf_text_2": data2["content"],
    "filename_2": "chapter2.pdf",
    "question": "",
    "target_language": "",
})
check("compare returns 200 and streams", compared[0] == 200 and compared[1])
both_docs = ("[Document: chapter1.pdf]" in captured["messages"][0]["content"]
             and "[Document: chapter2.pdf]" in captured["messages"][0]["content"])
check("compare prompt contains both labelled documents", both_docs)

# ---------- 3. Validation ----------
bad_action = run_stream({"action": "translate-now", "pdf_text_1": "x"})
check("unknown action rejected 400", bad_action[0] == 400)

no_pdf = run_stream({"action": "summarize", "pdf_text_1": "", "filename_1": ""})
check("empty document rejected 400", no_pdf[0] == 400)

one_pdf_compare = run_stream({
    "action": "compare",
    "pdf_text_1": data1["content"], "filename_1": "chapter1.pdf",
    "pdf_text_2": "", "filename_2": "",
})
check("compare with only one PDF rejected 400", one_pdf_compare[0] == 400)

no_question = run_stream({
    "action": "ask",
    "pdf_text_1": data1["content"], "filename_1": "chapter1.pdf",
    "question": "", "target_language": "",
})
check("ask without a question rejected 400", no_question[0] == 400)

# ---------- 4. robots.txt includes the new route ----------
robots = client.get("/robots.txt")
check("robots.txt lists /pdf-workspace-stream",
      robots.status_code == 200
      and "Disallow: /pdf-workspace-stream" in robots.get_data(as_text=True))

# ---------- 5. Prompt builder defensive cap ----------
huge = "A" * 100000
cap = appmod._build_pdf_workspace_prompt(
    "summarize", huge, "big.pdf", question="", target_language="")
check("builder slices text to MAX_EXTRACTED_CHARS",
      len(huge) > appmod.MAX_EXTRACTED_CHARS
      and "A" * appmod.MAX_EXTRACTED_CHARS in cap
      and "A" * (appmod.MAX_EXTRACTED_CHARS + 1) not in cap)

print()
failed = sum(1 for r in results if not r)
print(f"{len(results) - failed}/{len(results)} checks passed")
sys.exit(1 if failed else 0)

