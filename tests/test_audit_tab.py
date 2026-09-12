import pytest
from app.models import User

def test_audit_route_requires_login(client):
    """Test that /audit/ requires authentication."""
    response = client.get('/audit/', follow_redirects=False)
    assert response.status_code in [302, 401]

def test_audit_route_renders_for_logged_in_user(client, admin_user):
    """Test that /audit/ loads successfully with 200 OK and contains key audit sections."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user)
        sess['_fresh'] = True

    response = client.get('/audit/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'TRUNG TÂM KIỂM TOÁN DỮ LIỆU' in html
    assert 'RỦI RO THUẾ' in html
    assert 'ĐỨT GÃY CHI PHÍ' in html
    assert 'BÁN DƯỚI GIÁ VỐN' in html
    assert 'LỘ TRÌNH KHẮC PHỤC DỮ LIỆU' in html

def test_audit_api_data(client, admin_user):
    """Test that /audit/api/data returns valid JSON with health score."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user)
        sess['_fresh'] = True

    response = client.get('/audit/api/data')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'report' in data
    assert 'health_score' in data['report']['summary']
