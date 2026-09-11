import pytest

def test_webhook_rejects_get(client):
    res = client.get('/advances/webhook')
    assert res.status_code == 405

def test_webhook_invalid_secret(client):
    res = client.post('/advances/webhook',
        json={'event': 'sync'},
        headers={'X-Webhook-Secret': 'wrong_secret'}
    )
    assert res.status_code == 401

def test_webhook_rate_limit(client):
    from app.security import _rate_limits
    _rate_limits.clear()
    for _ in range(30):
        client.post('/advances/webhook',
            json={'event': 'ping'},
            headers={'X-Webhook-Secret': 'wrong'}
        )
    res = client.post('/advances/webhook',
        json={'event': 'ping'},
        headers={'X-Webhook-Secret': 'wrong'}
    )
    assert res.status_code == 429
