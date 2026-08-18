"""Functional tests for /api/export-data and /account/delete endpoints."""
import os
import sys
import json

PROJECT = "/home/freefireloverfreefirelover513/master ai/leo-assistant"
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

import app as appmod
from models import db, User, Note, QuizResult, RevisionSchedule
from datetime import datetime

appmod.app.config["TESTING"] = True
appmod.app.config["WTF_CSRF_ENABLED"] = False
client = appmod.app.test_client()

results = []

def check(name, ok, extra=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, extra)


with appmod.app.app_context():
    # Clean up any existing test users
    test_email = "test_export_delete@example.com"
    existing = User.query.filter_by(email=test_email).first()
    if existing:
        # Delete related data
        Note.query.filter_by(user_id=existing.id).delete()
        QuizResult.query.filter_by(user_id=existing.id).delete()
        RevisionSchedule.query.filter_by(user_id=existing.id).delete()
        db.session.delete(existing)
        db.session.commit()
    
    # Create a test user
    test_user = User(name="Test User", email=test_email)
    test_user.set_password("testpassword123")
    db.session.add(test_user)
    db.session.commit()
    test_user_id = test_user.id
    
    # Add some test data
    note = Note(
        user_id=test_user_id,
        topic="Test Topic",
        subject="Test Subject",
        content="This is test note content.",
        class_name="Test Class",
        language="en"
    )
    db.session.add(note)
    
    quiz = QuizResult(
        user_id=test_user_id,
        topic="Quiz Topic",
        subject="Quiz Subject",
        score=8,
        total=10
    )
    db.session.add(quiz)
    
    revision = RevisionSchedule(
        user_id=test_user_id,
        topic="Revision Topic",
        subject="Revision Subject",
        interval_stage=2,
        last_score_pct=80,
        next_review_at=datetime.utcnow()
    )
    db.session.add(revision)
    
    db.session.commit()

# Login as test user
with client.session_transaction() as sess:
    sess["_user_id"] = str(test_user_id)
    sess["_fresh"] = True

# Test 1: Export data - should return JSON download
r = client.get("/api/export-data")
check("export endpoint returns 200", r.status_code == 200, f"status={r.status_code}")
check("export has correct mimetype", r.mimetype == "application/json", f"mimetype={r.mimetype}")
check("export has Content-Disposition attachment", "attachment" in r.headers.get("Content-Disposition", ""), f"CD={r.headers.get('Content-Disposition')}")

# Parse the JSON response
export_data = json.loads(r.get_data(as_text=True))
check("export has profile", "profile" in export_data)
check("profile has name, email, created_at (no password_hash)", 
      all(k in export_data["profile"] for k in ["name", "email", "created_at"]) and "password_hash" not in export_data["profile"])
check("export has notes array", "notes" in export_data and isinstance(export_data["notes"], list))
check("export has quiz_results array", "quiz_results" in export_data and isinstance(export_data["quiz_results"], list))
check("export has revision_schedules array", "revision_schedules" in export_data and isinstance(export_data["revision_schedules"], list))
check("export has exported_at timestamp", "exported_at" in export_data)
check("notes data matches", len(export_data["notes"]) == 1 and export_data["notes"][0]["topic"] == "Test Topic")
check("quiz_results data matches", len(export_data["quiz_results"]) == 1 and export_data["quiz_results"][0]["score"] == 8)
check("revision_schedules data matches", len(export_data["revision_schedules"]) == 1 and export_data["revision_schedules"][0]["topic"] == "Revision Topic")

# Test 2: Delete account with WRONG password - should fail
with client.session_transaction() as sess:
    sess["_user_id"] = str(test_user_id)
    sess["_fresh"] = True

r = client.post("/account/delete", json={"password": "wrongpassword"}, follow_redirects=True)
check("wrong password rejected", r.status_code == 200, f"status={r.status_code}")
# Check that user still exists
with appmod.app.app_context():
    user_exists = User.query.filter_by(email=test_email).first() is not None
    check("user still exists after wrong password", user_exists)

# Test 3: Delete account with CORRECT password - should succeed
with client.session_transaction() as sess:
    sess["_user_id"] = str(test_user_id)
    sess["_fresh"] = True

r = client.post("/account/delete", json={"password": "testpassword123"}, follow_redirects=True)
check("correct password accepted (redirects to home)", r.status_code == 200, f"status={r.status_code}")

# Check that user is deleted and all related data is gone
with appmod.app.app_context():
    user_gone = User.query.filter_by(email=test_email).first() is None
    check("user deleted", user_gone)
    
    notes_gone = Note.query.filter_by(user_id=test_user_id).count() == 0
    check("notes deleted", notes_gone)
    
    quiz_gone = QuizResult.query.filter_by(user_id=test_user_id).count() == 0
    check("quiz results deleted", quiz_gone)
    
    revision_gone = RevisionSchedule.query.filter_by(user_id=test_user_id).count() == 0
    check("revision schedules deleted", revision_gone)

# Test 4: robots.txt includes new routes
r = client.get("/robots.txt")
robots_txt = r.get_data(as_text=True)
check("robots.txt disallows /api/export-data", "Disallow: /api/export-data" in robots_txt)
check("robots.txt disallows /account/delete", "Disallow: /account/delete" in robots_txt)

# Clean up test file
passed = sum(1 for ok in results if ok)
print(f"\nSUMMARY: {passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)