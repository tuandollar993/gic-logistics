import os
import pytest
from app.services.cashflow_bot_service import handle_telegram_update, _pending_confirmations

def test_telegram_webhook_secret_token_enforcement(client, monkeypatch):
    monkeypatch.setenv('TELEGRAM_SECRET_TOKEN', 'tg_super_secret_999')

    # Missing token -> 401
    r_no_token = client.post('/advances/bot-webhook', json={'update_id': 1})
    assert r_no_token.status_code == 401

    # Invalid token -> 401
    r_bad_token = client.post(
        '/advances/bot-webhook',
        headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong_token'},
        json={'update_id': 1}
    )
    assert r_bad_token.status_code == 401

    # Valid token -> 200
    r_good = client.post(
        '/advances/bot-webhook',
        headers={'X-Telegram-Bot-Api-Secret-Token': 'tg_super_secret_999'},
        json={'update_id': 1}
    )
    assert r_good.status_code == 200
    assert r_good.get_json()['ok'] is True

def test_telegram_chat_id_authorization(monkeypatch):
    from app.services import cashflow_bot_service
    monkeypatch.setattr(cashflow_bot_service, 'ALLOWED_CHAT_IDS', ['123456789'])

    # Message from unauthorized chat
    unauth_update = {
        'message': {
            'message_id': 100,
            'chat': {'id': 999999, 'type': 'group'},
            'text': '/bc'
        }
    }
    res_unauth = handle_telegram_update(unauth_update)
    assert res_unauth == {'ok': True}

def test_telegram_callback_tampering_prevented(monkeypatch):
    from app.services import cashflow_bot_service
    monkeypatch.setattr(cashflow_bot_service, 'ALLOWED_CHAT_IDS', ['123456789'])

    # Setup a pending transaction initiated from chat 123456789
    _pending_confirmations['tx_sec_test'] = {
        'data': {'loai': 'CHI', 'so_tien': 1000000},
        'media_id': 'media_123',
        'public_url': 'https://example.com/bill',
        'chat_id': '123456789'
    }

    # Malicious callback coming from a different chat ID
    attacker_update = {
        'callback_query': {
            'id': 'cb_attack_1',
            'message': {
                'message_id': 200,
                'chat': {'id': 888888}  # Attacker chat
            },
            'data': 'confirmtx_tx_sec_test'
        }
    }

    # Should be rejected because attacker chat is not allowed or does not match pending chat_id
    res = handle_telegram_update(attacker_update)
    assert res == {'ok': True}
    # Pending transaction must still be intact (not executed or confirmed by attacker)
    assert 'tx_sec_test' in _pending_confirmations
    _pending_confirmations.pop('tx_sec_test', None)


def test_telegram_webhook_missing_server_secret(client, monkeypatch):
    # If server has no secret token configured, webhook must fail-closed (401)
    monkeypatch.delenv('TELEGRAM_SECRET_TOKEN', raising=False)
    from app import config
    monkeypatch.setattr(config.Config, 'TELEGRAM_SECRET_TOKEN', '')
    res = client.post(
        '/advances/bot-webhook',
        headers={'X-Telegram-Bot-Api-Secret-Token': 'some_token'},
        json={'update_id': 1}
    )
    assert res.status_code == 401
    assert 'not configured' in res.get_json()['error']


def test_set_telegram_webhook_rbac(client, auth_client_staff, auth_client_manager):
    # Anonymous -> 403 or 302/401
    res_anon = client.post('/advances/set-telegram-webhook')
    assert res_anon.status_code in (302, 401, 403)

    # Staff -> 403
    res_staff = auth_client_staff.post('/advances/set-telegram-webhook')
    assert res_staff.status_code == 403

    # Manager -> 403 (admin only)
    res_mgr = auth_client_manager.post('/advances/set-telegram-webhook')
    assert res_mgr.status_code == 403


def test_set_telegram_webhook_validation(auth_client_admin, monkeypatch):
    monkeypatch.setenv('TELEGRAM_SECRET_TOKEN', 'test_secret_tok_99')

    # 1. HTTP not allowed
    res_http = auth_client_admin.post('/advances/set-telegram-webhook', json={
        'url': 'http://gic-logistics.onrender.com/advances/bot-webhook'
    })
    assert res_http.status_code == 400
    assert 'HTTPS' in res_http.get_json()['error']

    # 2. Localhost not allowed
    res_local = auth_client_admin.post('/advances/set-telegram-webhook', json={
        'url': 'https://localhost/advances/bot-webhook'
    })
    assert res_local.status_code == 400
    assert 'localhost' in res_local.get_json()['error']

    # 3. Untrusted domain not allowed
    res_untrusted = auth_client_admin.post('/advances/set-telegram-webhook', json={
        'url': 'https://attacker.evil.com/advances/bot-webhook'
    })
    assert res_untrusted.status_code == 400
    assert 'không nằm trong danh sách máy chủ' in res_untrusted.get_json()['error']

    # 4. Invalid path not allowed
    res_bad_path = auth_client_admin.post('/advances/set-telegram-webhook', json={
        'url': 'https://gic-logistics.onrender.com/malicious/endpoint'
    })
    assert res_bad_path.status_code == 400
    assert 'Đường dẫn webhook không hợp lệ' in res_bad_path.get_json()['error']


def test_set_telegram_webhook_success(auth_client_admin, monkeypatch, app):
    monkeypatch.setenv('TELEGRAM_SECRET_TOKEN', 'super_secret_bot_token_abc')
    from app.services import cashflow_bot_service
    monkeypatch.setattr(cashflow_bot_service, 'CASHFLOW_BOT_TOKEN', 'mock_bot_token_123')

    sent_payload = {}

    class MockResponse:
        def __init__(self, data):
            self._data = data
        def json(self):
            return self._data

    def mock_post(url, json=None, timeout=None):
        nonlocal sent_payload
        sent_payload = json
        assert 'https://api.telegram.org/botmock_bot_token_123/setWebhook' in url
        return MockResponse({'ok': True, 'result': True, 'description': 'Webhook was set'})

    def mock_get(url, timeout=None):
        return MockResponse({'ok': True, 'result': {'url': 'https://gic-logistics.onrender.com/advances/bot-webhook'}})

    import requests
    monkeypatch.setattr(requests, 'post', mock_post)
    monkeypatch.setattr(requests, 'get', mock_get)

    res = auth_client_admin.post('/advances/set-telegram-webhook', json={
        'url': 'https://gic-logistics.onrender.com/advances/bot-webhook'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['set_result']['ok'] is True
    assert sent_payload['secret_token'] == 'super_secret_bot_token_abc'

    # Verify audit log recorded without secret leakage
    with app.app_context():
        from app.models import AuditLog
        audit = AuditLog.query.filter_by(action='set_telegram_webhook').order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert 'super_secret_bot_token_abc' not in (audit.details or '')
        assert 'super_secret_bot_token_abc' not in str(audit.after_state or '')

