import os
import sys

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['SECRET_KEY'] = 'temp-test-key-32-chars-strictly-temp!'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['SESSION_COOKIE_SECURE'] = '0'

    from app import create_app
    from app.extensions import db
    from app.models import User, Supplier

    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        
        # Seed test users
        u_staff = User(username='nv_ngocan', full_name='Ngoc An', role='staff', is_active=True)
        u_staff.set_password('Pass123456@')
        
        u_mgr = User(username='admin', full_name='Admin User', role='admin', is_active=True)
        u_mgr.set_password('Admin@Pass123')
        
        supp = Supplier(name='CÔNG TY CỔ PHẦN DỊCH VỤ GIAO HÀNG NHANH', tax_code='0311907295')
        supp2 = Supplier(name='CÔNG TY CỔ PHẦN MISA', tax_code='0101243150')
        
        db.session.add_all([u_staff, u_mgr, supp, supp2])
        db.session.commit()

        # 1. STAFF TEST
        with app.test_client() as staff_client:
            with staff_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            r_log = staff_client.post('/login', data={'username': 'nv_ngocan', 'password': 'Pass123456@', 'csrf_token': 'tok'}, follow_redirects=True)
            assert r_log.status_code == 200
            
            # Staff accessing /users/ -> MUST BE BLOCKED (403)
            r_users = staff_client.get('/users/', follow_redirects=False)
            print(f'Staff GET /users/ status: {r_users.status_code} (Blocked)')
            assert r_users.status_code == 403
            
            # Staff accessing /suppliers/ -> Allowed view-only
            r_supp = staff_client.get('/suppliers/')
            assert r_supp.status_code == 200
            supp_html = r_supp.data.decode('utf-8')
            assert '0311907295' in supp_html
            print('Staff view-only suppliers page: PASSED')

        # 2. ADMIN / MANAGER TEST
        with app.test_client() as mgr_client:
            with mgr_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            r_log = mgr_client.post('/login', data={'username': 'admin', 'password': 'Admin@Pass123', 'csrf_token': 'tok'}, follow_redirects=True)
            assert r_log.status_code == 200
            
            # Admin accessing /users/ -> Allowed
            r_users = mgr_client.get('/users/')
            assert r_users.status_code == 200
            u_html = r_users.data.decode('utf-8')
            assert 'Quản Lý Danh Sách Nhân Viên' in u_html
            print('Admin access /users/: PASSED')
            
            # Test adding user
            with mgr_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            r_add_u = mgr_client.post('/users/new', data={
                'username': 'test_nv_01',
                'full_name': 'Nguyễn Văn Test',
                'password': 'StrongPassword123@',
                'role': 'staff',
                'email': 'test@gic.vn',
                'telegram_chat_id': '99887766',
                'csrf_token': 'tok'
            }, follow_redirects=True)
            assert r_add_u.status_code == 200
            created_u = User.query.filter_by(username='test_nv_01').first()
            assert created_u is not None
            assert created_u.check_password('StrongPassword123@') is True
            print('Admin add user: PASSED')
            
            # Test resetting password
            with mgr_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            r_reset = mgr_client.post(f'/users/{created_u.id}/reset-password', data={
                'new_password': 'NewStrongPassword456@',
                'csrf_token': 'tok'
            }, follow_redirects=True)
            assert r_reset.status_code == 200
            db.session.refresh(created_u)
            assert created_u.check_password('NewStrongPassword456@') is True
            print('Admin reset password: PASSED')
            
            # Test toggling active status
            with mgr_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            mgr_client.post(f'/users/{created_u.id}/toggle-status', data={'csrf_token': 'tok'}, follow_redirects=True)
            db.session.refresh(created_u)
            assert created_u.is_active is False
            print('Admin toggle status: PASSED')
            
            # Test deleting test user
            with mgr_client.session_transaction() as s:
                s['_csrf_token'] = 'tok'
            mgr_client.post(f'/users/{created_u.id}/delete', data={'csrf_token': 'tok'}, follow_redirects=True)
            assert User.query.filter_by(username='test_nv_01').first() is None
            print('Admin delete user: PASSED')

        print('\nALL USER & SUPPLIER TAB VERIFICATIONS PASSED SUCCESSFULLY!')
