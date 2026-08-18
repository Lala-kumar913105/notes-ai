"""Frontend smoke test: renders the home page and checks the account UI.

The header's account links ("Export My Data" / "Delete My Account") only
render for authenticated users, so this test logs a user in first. It runs
against an isolated temporary database so the real instance/studyai.db is
never touched.
"""
import os
import sys
import tempfile

PROJECT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

# Point the app at an isolated temp DB for this test.
tmpdb = os.path.join(tempfile.gettempdir(), 'frontend_test_' + os.urandom(4).hex() + '.db')
src = open('app.py', encoding='utf-8').read()
src = src.replace('sqlite:///studyai.db', 'sqlite:///' + tmpdb)
g = {'__name__': 'frontend_test_app'}
exec(compile(src, 'app.py', 'exec'), g)

app = g['app']
from models import db, User  # noqa: E402

with app.app_context():
    db.create_all()
    u = User(name='Tester', email='tester@example.com')
    u.set_password('password1')
    db.session.add(u)
    db.session.commit()

with app.test_client() as client:
    # Logged-in home page shows the account links + the delete-account modal.
    client.post('/login', data={'email': 'tester@example.com', 'password': 'password1'})
    r = client.get('/')
    print('Home page:', r.status_code)
    assert r.status_code == 200
    content = r.get_data(as_text=True)
    assert 'Export My Data' in content
    assert 'Delete My Account' in content
    assert 'delete-account-modal' in content
    print('All frontend elements present')

    # Anonymous home page hides the account links but keeps the modal.
    client.get('/logout')
    r = client.get('/')
    content = r.get_data(as_text=True)
    assert 'Export My Data' not in content
    assert 'delete-account-modal' in content
    print('Anonymous home page correct')

try:
    os.remove(tmpdb)
except OSError:
    pass