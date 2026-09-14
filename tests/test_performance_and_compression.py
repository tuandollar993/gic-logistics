import gzip

def test_gzip_compression_on_accept_encoding(client):
    res = client.get('/login', headers={'Accept-Encoding': 'gzip, deflate'})
    assert res.status_code == 200
    assert res.headers.get('Content-Encoding') == 'gzip'
    decompressed = gzip.decompress(res.data)
    assert b'login' in decompressed.lower() or b'\xc4\x91\xc4\x83ng nh\xe1\xba\xadp' in decompressed.lower()

def test_no_gzip_without_accept_encoding(client):
    res = client.get('/login')
    assert res.status_code == 200
    assert 'Content-Encoding' not in res.headers
    assert b'login' in res.data.lower() or b'\xc4\x91\xc4\x83ng nh\xe1\xba\xadp' in res.data.lower()

def test_static_cache_control_header(client):
    res = client.get('/static/css/custom.css')
    if res.status_code == 200:
        assert 'public, max-age=86400' in res.headers.get('Cache-Control', '')
