import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
import os
import pytest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'test-secret-key-32-chars-long-here!!'
os.environ['WEBHOOK_SECRET'] = 'test-webhook-secret-token-32!!'
os.environ['FLASK_ENV'] = 'testing'
os.environ['SESSION_COOKIE_SECURE'] = '0'

from app import create_app
from app.extensions import db
from app.models import User, Customer, Lot, OperatingCost, CashAdvanceMonthly, CashAdvanceTransaction
from app.security import _rate_limits

@pytest.fixture
def app():
    _rate_limits.clear()
    flask_app = create_app()
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost'
    })

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_user(app):
    with app.app_context():
        user = User(
            username='admin_test',
            full_name='Administrator Test',
            role='admin',
            is_active=True
        )
        user.set_password('Admin@Pass123')
        db.session.add(user)
        db.session.commit()
        return user.id

@pytest.fixture
def manager_user(app):
    with app.app_context():
        user = User(
            username='manager_test',
            full_name='Manager Test',
            role='manager',
            is_active=True
        )
        user.set_password('Manager@Pass123')
        db.session.add(user)
        db.session.commit()
        return user.id

@pytest.fixture
def staff_user(app):
    with app.app_context():
        user = User(
            username='staff_test',
            full_name='Staff Test',
            role='staff',
            is_active=True
        )
        user.set_password('Staff@Pass123')
        db.session.add(user)
        db.session.commit()
        return user.id

def login(client, username, password):
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'test_csrf_token'
    return client.post('/login', data={
        'username': username,
        'password': password,
        'csrf_token': 'test_csrf_token'
    }, follow_redirects=True)

@pytest.fixture
def auth_client_admin(app, admin_user):
    client = app.test_client()
    login(client, 'admin_test', 'Admin@Pass123')
    return client

@pytest.fixture
def auth_client_manager(app, manager_user):
    client = app.test_client()
    login(client, 'manager_test', 'Manager@Pass123')
    return client

@pytest.fixture
def auth_client_staff(app, staff_user):
    client = app.test_client()
    login(client, 'staff_test', 'Staff@Pass123')
    return client
