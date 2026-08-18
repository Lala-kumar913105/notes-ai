"""Functional tests for the multi-attachment /generate-notes-stream flow."""
import os
import sys

PROJECT = "/home/freefireloverfreefirelover513/master ai/leo-assistant"
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

import app as appmod  # noqa: E402

appmod.app.config["TESTING"] = True
client = appmod.app.test_client()

captured = {}
results = []


def check(name, ok, extra=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, extra)


def fake_ask_leo_stream(messages=None, stream=True, **kw):
    captured["messages"] = messages
    def gen():
        yield "gen chunk"
    return gen()


appmod.ask_leo_stream = fake_ask_leo_stream


def post(body):
    r = client.post("/generate-notes-stream", json=body)
    data = r.get_data(as_text=True)
    return r, data


# 1) 0 attachments + typed topic (must work exactly as before)
r, data = post({"topic": "Photosynthesis"})
msgs = captured["messages"]
check("topic-only -> 200", r.status_code == 200, "status=%s" % r.status_code)
check("topic-only: plain string content",
      isinstance(msgs[0]["content"], str) and "Topic: Photosynthesis" in msgs[0]["content"])
check("topic-only: no attachment block", "[Attached" not in msgs[0]["content"])
check("topic-only: no source_note", "Source material" not in msgs[0]["content"])

# 2) Nothing at all -> 400
r, data = post({})
check("empty body -> 400", r.status_code == 400, str(data)[:80])

# 3) Single text attachment via new plural key
r, data = post({
    "attachments": [{"type": "text", "filename": "chapter1.pdf",
                     "content": "Glycolysis converts glucose into pyruvate."}]
})
msgs = captured["messages"]
check("1 text -> 200", r.status_code == 200)
check("1 text: labelled block", "[Attached source 1: chapter1.pdf]" in msgs[0]["content"])
check("1 text: content included", "Glycolysis converts glucose" in msgs[0]["content"])

# 4) Three text attachments combine coherently
r, data = post({
    "attachments": [
        {"type": "text", "filename": "chapter1.pdf", "content": "AAAA photosynthesis basics"},
        {"type": "text", "filename": "chapter2.pdf", "content": "BBBB chlorophyll pigments"},
        {"type": "text", "filename": "chapter3.pdf", "content": "CCCC light reactions"},
    ]
})
msgs = captured["messages"]
c = msgs[0]["content"]
check("3 text -> 200", r.status_code == 200)
check("3 text: all three labels",
      all(f"[Attached source {i}: chapter{i}.pdf]" in c for i in (1, 2, 3)))
check("3 text: all three contents",
      all(s in c for s in ("AAAA photosynthesis basics", "BBBB chlorophyll pigments",
                           "CCCC light reactions")))
check("3 text: source_note present (infer topic)", "infer a sensible topic" in c)

# 5) Legacy singular 'attachment' key still works (backward compat)
r, data = post({
    "attachment": {"type": "text", "filename": "old.pdf", "content": "OLD CACHED CLIENT"}
})
msgs = captured["messages"]
# 6) Two images -> multimodal with two image_url blocks (mirror /ask-stream)
img1 = "data:image/jpeg;base64,AAAA"
img2 = "data:image/png;base64,BBBB"
r, data = post({
    "attachments": [
        {"type": "image", "filename": "page1.jpg", "data_url": img1},
        {"type": "image", "filename": "page2.png", "data_url": img2},
    ]
})
msgs = captured["messages"]
blocks = msgs[0]["content"]
check("2 images -> 200", r.status_code == 200)
check("2 images: content is list", isinstance(blocks, list), str(type(blocks)))
check("2 images: first block is text prompt",
      blocks[0]["type"] == "text" and "Topic: the attached material" in blocks[0]["text"])
check("2 images: exactly 2 image_url blocks",
      sum(b["type"] == "image_url" for b in blocks) == 2)
check("2 images: correct urls",
      blocks[1]["image_url"]["url"] == img1 and blocks[2]["image_url"]["url"] == img2)

# 7) Single image still works
r, data = post({"attachments": [{"type": "image", "filename": "page1.jpg", "data_url": img1}]})
blocks = captured["messages"][0]["content"]
check("1 image: one image_url block", isinstance(blocks, list) and len(blocks) == 2
      and blocks[1]["type"] == "image_url")

# 8) Mixed: 2 text + 1 image
r, data = post({
    "attachments": [
        {"type": "text", "filename": "notes.txt", "content": "DDDD text source"},
        {"type": "image", "filename": "photo.jpg", "data_url": img2},
        {"type": "text", "filename": "extra.txt", "content": "EEEE extra text"},
    ]
})
msgs = captured["messages"]
blocks = msgs[0]["content"]
c = blocks[0]["text"]
check("mixed -> 200", r.status_code == 200)
check("mixed: text folded into prompt",
      "[Attached source 1: notes.txt]" in c and "[Attached source 2: extra.txt]" in c)
check("mixed: image block present",
      isinstance(blocks, list) and any(b.get("type") == "image_url" for b in blocks))
check("mixed: prompt text is block 0", blocks[0]["type"] == "text")

# 9) Combined char budget (MAX_NOTES_TEXT_ATTACHMENT_CHARS = 30,000)
r, data = post({
    "attachments": [
        {"type": "text", "filename": "ch1.pdf", "content": "X" * 20000},
        {"type": "text", "filename": "ch2.pdf", "content": "Y" * 20000},
        {"type": "text", "filename": "ch3.pdf", "content": "Z" * 20000},
    ]
})
c = captured["messages"][0]["content"]
check("budget: source1 kept in full", "X" * 20000 in c)
check("budget: source2 truncated to remaining 10k", "Y" * 10000 in c and "Y" * 10001 not in c)
check("budget: source3 dropped entirely", "Z" * 50 not in c and "[Attached source 3:" not in c)

# 10) Malformed/junk attachments are filtered out
r, data = post({
    "attachments": [
        "garbage",
        {"type": "text", "filename": "clean.pdf", "content": "CLEAN ONLY"},
        {"type": "text", "filename": "", "content": ""},
        {"type": "video", "filename": "x.mp4", "content": "nope"},
        {},
    ]
})
c = captured["messages"][0]["content"]
check("junk filtered: clean kept", "[Attached source 1: clean.pdf]" in c and "CLEAN ONLY" in c)
check("junk filtered: only 1 label used", "[Attached source 2:" not in c)

# 11) Images only + no topic still gets source_note inference guidance
r, data = post({"attachments": [{"type": "image", "filename": "page1.jpg", "data_url": img1}]})
blocks = captured["messages"][0]["content"]
check("image-only: inference guidance in prompt",
      "infer a sensible topic" in blocks[0]["text"])

passed = sum(1 for ok in results if ok)
print("\nSUMMARY: %d/%d passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
check("legacy singular -> 200", r.status_code == 200)
check("legacy singular: wrapped as 1 item", "[Attached source 1: old.pdf]" in msgs[0]["content"])