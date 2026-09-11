import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app import create_app
from app.extensions import db
from app.models import User

def seed():
    app = create_app()
    with app.app_context():
        db.create_all()
        
        # 1. Quản lý (Admin)
        manager = User.query.filter_by(username='admin').first()
        if not manager:
            manager = User(
                username='admin',
                full_name='Quản lý Vận hành GIC',
                role='manager',
                email='manager@gic.vn'
            )
            manager.set_password('admin123')
            db.session.add(manager)
            print("Đã tạo tài khoản Quản lý: admin / admin123")
        else:
            manager.set_password('admin123')
            print("Đã cập nhật mật khẩu admin: admin123")
            
        # 2. 10 Nhân viên vận hành
        staff_list = [
            ('nv_ngocan', 'Nguyễn Ngọc An', 'ngocan@gic.vn'),
            ('nv_haidang', 'Trần Hải Đăng', 'haidang@gic.vn'),
            ('nv_cuongtrang', 'Đặng Cường Tráng', 'cuongtrang@gic.vn'),
            ('nv_phuongthao', 'Lê Phương Thảo', 'phuongthao@gic.vn'),
            ('nv_hoangdung', 'Phạm Hoàng Dũng', 'hoangdung@gic.vn'),
            ('nv_thuanphat', 'Vũ Thuận Phát', 'thuanphat@gic.vn'),
            ('nv_maianh', 'Hoàng Thị Mai Anh', 'maianh@gic.vn'),
            ('nv_minhtri', 'Bùi Minh Trí', 'minhtri@gic.vn'),
            ('nv_thanhxuyen', 'Nguyễn Thanh Xuyên', 'thanhxuyen@gic.vn'),
            ('nv_phuonguyen', 'Đỗ Phương Uyên', 'phuonguyen@gic.vn')
        ]
        
        for username, full_name, email in staff_list:
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(
                    username=username,
                    full_name=full_name,
                    role='staff',
                    email=email
                )
                user.set_password('123456')
                db.session.add(user)
                print(f"Đã tạo nhân viên: {username} ({full_name}) / pass: 123456")
            else:
                user.set_password('123456')
                
        db.session.commit()
        print("\n✅ Hoàn tất khởi tạo 1 Quản lý + 10 Nhân viên!")

if __name__ == '__main__':
    seed()
