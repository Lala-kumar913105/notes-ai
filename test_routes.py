from app import app
from flask import url_for

with app.test_request_context():
    print('dashboard:', url_for('dashboard'))
    print('api_export_data:', url_for('api_export_data'))
    print('account_delete:', url_for('account_delete'))