import pytest

def test_reports_index_requires_auth(client):
    res = client.get('/reports/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_reports_index_requires_manager(auth_client_staff):
    res = auth_client_staff.get('/reports/')
    assert res.status_code == 403

def test_reports_index_accessible_by_manager(auth_client_manager):
    res = auth_client_manager.get('/reports/')
    assert res.status_code == 200
    assert 'Báo Cáo Hoạt Động Hàng Tháng GIDO' in res.get_data(as_text=True)

def test_reports_generate_api(auth_client_manager):
    with auth_client_manager.session_transaction() as sess:
        sess['_csrf_token'] = 'test_token'
    res = auth_client_manager.post(
        '/reports/generate',
        json={'month': 8, 'year': 2026, 'report_type': 'kqkd', 'csrf_token': 'test_token'},
        headers={'X-CSRFToken': 'test_token'}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert 'data' in data
    assert 'sections' in data
    assert 'charts_b64' in data['data']
    assert 'topline' in data['data']['charts_b64']

def test_reports_download_docx(auth_client_manager):
    with auth_client_manager.session_transaction() as sess:
        sess['_csrf_token'] = 'test_token'
    res = auth_client_manager.post(
        '/reports/download',
        json={'month': 8, 'year': 2026, 'report_type': 'kqkd', 'csrf_token': 'test_token'},
        headers={'X-CSRFToken': 'test_token'}
    )
    assert res.status_code == 200
    assert 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in res.headers['Content-Type']
    assert len(res.data) > 1000
