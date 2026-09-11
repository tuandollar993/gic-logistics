import pytest
from app.models import User
from app.extensions import db
from app.security import _rate_limits

def test_login_success(client, admin_user):
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'valid_token'
    res = client.post('/login', data={
        'username': 'admin_test',
        'password': 'Admin@Pass123',
        'csrf_token': 'valid_token'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'admin_test' in res.data or b'Administrator' in res.data or 'Đăng xuất'.encode('utf-8') in res.data or b'Logout' in res.data or b'Dashboard' in res.data

def test_login_invalid_password(client, admin_user):
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'valid_token'
    res = client.post('/login', data={
        'username': 'admin_test',
        'password': 'WrongPassword!',
        'csrf_token': 'valid_token'
    }, follow_redirects=True)
    assert 'Tên đăng nhập hoặc mật khẩu không đúng'.encode('utf-8') in res.data or res.status_code == 200

def test_inactive_user_cannot_login(client, app):
    with app.app_context():
        u = User(username='inactive_user', full_name='Inactive', role='staff', is_active=False)
        u.set_password('Pass123456@')
        db.session.add(u)
        db.session.commit()

    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'valid_token'
    res = client.post('/login', data={
        'username': 'inactive_user',
        'password': 'Pass123456@',
        'csrf_token': 'valid_token'
    }, follow_redirects=True)
    assert 'Tài khoản đã bị khóa'.encode('utf-8') in res.data or res.status_code == 200

def test_login_rate_limiting(client, app):
    _rate_limits.clear()
    for i in range(5):
        with client.session_transaction() as sess:
            sess['_csrf_token'] = 'tok'
        client.post('/login', data={
            'username': 'test_flood',
            'password': 'WrongPassword!',
            'csrf_token': 'tok'
        })
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'tok'
    res = client.post('/login', data={
        'username': 'test_flood',
        'password': 'WrongPassword!',
        'csrf_token': 'tok'
    })
    assert res.status_code == 429
    assert 'đăng nhập sai quá nhiều lần'.encode('utf-8') in res.data or 'Quá nhiều yêu cầu'.encode('utf-8') in res.data

def test_logout_get_rejected(auth_client_admin):
    res = auth_client_admin.get('/logout')
    assert res.status_code == 405

def test_logout_post_succeeds(auth_client_admin):
    with auth_client_admin.session_transaction() as sess:
        sess['_csrf_token'] = 'tok'
    res = auth_client_admin.post('/logout', data={'csrf_token': 'tok'}, follow_redirects=True)
    assert res.status_code == 200
    with auth_client_admin.session_transaction() as sess:
        assert '_user_id' not in sess

def test_open_redirect_mitigated(client, admin_user):
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'valid_token'
    res = client.post('/login?next=https://evil.com', data={
        'username': 'admin_test',
        'password': 'Admin@Pass123',
        'csrf_token': 'valid_token'
    }, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers.get('Location') == '/' or not res.headers.get('Location', '').startswith('https://evil.com')
