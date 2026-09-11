import sys
sys.stdout.reconfigure(encoding='utf-8')
from app import create_app
from app.extensions import db
from app.models import User, Supplier

app = create_app()

with app.app_context():
    # 1. STAFF TEST
    with app.test_client() as staff_client:
        r_log = staff_client.post('/login', data={'username': 'nv_ngocan', 'password': '123456'}, follow_redirects=True)
        assert r_log.status_code == 200
        
        # Staff accessing /users/ -> MUST BE BLOCKED
        r_users = staff_client.get('/users/', follow_redirects=False)
        print(f"Staff GET /users/ status: {r_users.status_code} (Blocked)")
        assert r_users.status_code == 302
        
        # Staff viewing dashboard -> Sidebar must NOT contain 'Quản Lý Nhân Viên'
        r_dash = staff_client.get('/')
        dash_html = r_dash.data.decode('utf-8')
        assert "Quản Lý Nhân Viên" not in dash_html
        assert "Thông Tin NCC" in dash_html
        print("Staff cannot see Quản Lý Nhân Viên in sidebar: PASSED")
        
        # Staff accessing /suppliers/ -> Allowed view-only
        r_supp = staff_client.get('/suppliers/')
        assert r_supp.status_code == 200
        supp_html = r_supp.data.decode('utf-8')
        assert "Thêm Nhà Cung Cấp" not in supp_html
        assert "0311907295" in supp_html
        print("Staff view-only suppliers page: PASSED")
        
        # Staff trying to add supplier -> BLOCKED
        r_add_s = staff_client.post('/suppliers/new', data={'name': 'Hacker NCC'}, follow_redirects=False)
        assert r_add_s.status_code == 302
        print("Staff blocked from adding supplier: PASSED")

    # 2. MANAGER TEST
    with app.test_client() as mgr_client:
        r_log = mgr_client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        assert r_log.status_code == 200
        
        # Manager accessing /users/ -> Allowed
        r_users = mgr_client.get('/users/')
        assert r_users.status_code == 200
        u_html = r_users.data.decode('utf-8')
        assert "Quản Lý Danh Sách Nhân Viên" in u_html
        assert "Thêm Nhân Viên Mới" in u_html
        print("Manager access /users/: PASSED")
        
        # Test adding user
        test_u = User.query.filter_by(username='test_nv_01').first()
        if test_u:
            db.session.delete(test_u)
            db.session.commit()
            
        r_add_u = mgr_client.post('/users/new', data={
            'username': 'test_nv_01',
            'full_name': 'Nguyễn Văn Test',
            'password': 'initial_password_123',
            'role': 'staff',
            'email': 'test@gic.vn',
            'telegram_chat_id': '99887766'
        }, follow_redirects=True)
        assert r_add_u.status_code == 200
        created_u = User.query.filter_by(username='test_nv_01').first()
        assert created_u is not None
        assert created_u.check_password('initial_password_123') is True
        print("Manager add user: PASSED")
        
        # Test resetting password
        r_reset = mgr_client.post(f'/users/{created_u.id}/reset-password', data={
            'new_password': 'new_secure_password_456'
        }, follow_redirects=True)
        assert r_reset.status_code == 200
        db.session.refresh(created_u)
        assert created_u.check_password('new_secure_password_456') is True
        print("Manager reset password: PASSED")
        
        # Test toggling active status
        mgr_client.post(f'/users/{created_u.id}/toggle-status', follow_redirects=True)
        db.session.refresh(created_u)
        assert created_u.is_active is False
        print("Manager toggle status: PASSED")
        
        # Test deleting test user
        mgr_client.post(f'/users/{created_u.id}/delete', follow_redirects=True)
        assert User.query.filter_by(username='test_nv_01').first() is None
        print("Manager delete user: PASSED")

        # 3. MANAGER SUPPLIERS TEST
        r_supp_mgr = mgr_client.get('/suppliers/')
        assert r_supp_mgr.status_code == 200
        supp_mgr_html = r_supp_mgr.data.decode('utf-8')
        assert "Thêm Nhà Cung Cấp" in supp_mgr_html
        assert "0311907295" in supp_mgr_html
        assert "CÔNG TY CỔ PHẦN DỊCH VỤ GIAO HÀNG NHANH" in supp_mgr_html
        print("Manager view suppliers with full controls: PASSED")
        
        # Test searching
        r_search = mgr_client.get('/suppliers/?q=MISA')
        assert "CÔNG TY CỔ PHẦN MISA" in r_search.data.decode('utf-8')
        print("Supplier search: PASSED")
        
        # Test adding supplier
        mgr_client.post('/suppliers/new', data={
            'name': 'CÔNG TY TNHH TEST VẬN TẢI',
            'tax_code': '0999888777',
            'supplier_code': 'S-0999888777',
            'address': '123 Đường Test, Quận 1, TP HCM'
        }, follow_redirects=True)
        test_s = Supplier.query.filter_by(tax_code='0999888777').first()
        assert test_s is not None
        print("Manager add supplier: PASSED")
        
        # Test editing supplier
        mgr_client.post(f'/suppliers/{test_s.id}/edit', data={
            'name': 'CÔNG TY TNHH TEST VẬN TẢI (ĐÃ SỬA)',
            'tax_code': '0999888777',
            'supplier_code': 'S-0999888777-V2',
            'address': '456 Đường Test Mới'
        }, follow_redirects=True)
        db.session.refresh(test_s)
        assert test_s.name == 'CÔNG TY TNHH TEST VẬN TẢI (ĐÃ SỬA)'
        assert test_s.supplier_code == 'S-0999888777-V2'
        print("Manager edit supplier: PASSED")
        
        # Test deleting supplier
        mgr_client.post(f'/suppliers/{test_s.id}/delete', follow_redirects=True)
        assert Supplier.query.filter_by(tax_code='0999888777').first() is None
        print("Manager delete supplier: PASSED")

    print("\nALL USER & SUPPLIER TAB TESTS PASSED SUCCESSFULLY!")
