import pytest

def test_post_without_csrf_rejected(client, admin_user):
    res = client.post('/login', data={
        'username': 'admin_test',
        'password': 'Admin@Pass123'
    })
    assert res.status_code == 400
    assert 'CSRF token missing'.encode('utf-8') in res.data or 'CSRF'.encode('utf-8') in res.data

def test_post_with_csrf_header_accepted(client, admin_user):
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'header_token'
    res = client.post('/login', 
        data={'username': 'admin_test', 'password': 'Admin@Pass123'},
        headers={'X-CSRF-Token': 'header_token'},
        follow_redirects=True
    )
    assert res.status_code == 200

def test_webhook_csrf_exempt(client):
    res = client.post('/advances/webhook', 
        json={'event': 'ping'},
        headers={'X-Webhook-Secret': 'invalid_secret'}
    )
    assert res.status_code == 401
