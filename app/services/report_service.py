"""
AI Monthly Report Service — Báo cáo Hoạt Động Hàng Tháng
Tự động thu thập dữ liệu từ DB, gọi Gemini AI sinh nội dung narrative,
và xuất file Word .docx theo mẫu GIDO.
"""

import os
import io
import json
import requests
from datetime import datetime
from collections import defaultdict

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

from app.extensions import db
from app.models import Lot, Customer, RevenueItem, OperatingCost, Target, User
from app.services.calculator import CalculatorService
from app.services.comment_engine import CommentEngine
from sqlalchemy.orm import selectinload, joinedload

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')


# ─────────────────────────────────────────────────
# 1. ReportDataCollector — Thu thập dữ liệu từ DB
# ─────────────────────────────────────────────────

class ReportDataCollector:
    """Gom toàn bộ dữ liệu cần thiết cho báo cáo tháng từ database."""

    @staticmethod
    def collect(month, year):
        """
        Thu thập dữ liệu báo cáo cho tháng/năm chỉ định.
        Returns dict chứa tất cả số liệu cần cho báo cáo.
        """
        # 1. KPI tổng quan (tái sử dụng CalculatorService)
        kpi = CalculatorService.get_monthly_kpi(month, year)
        customers = CalculatorService.get_customer_breakdown(month, year)
        comments = CommentEngine.generate_comments(month, year, kpi=kpi, customers=customers)

        # 2. Chi tiết lô hàng tháng
        lots = Lot.query.filter_by(month=month, year=year, is_deleted=False).options(
            selectinload(Lot.revenue_items),
            selectinload(Lot.operating_costs),
            joinedload(Lot.customer)
        ).all()

        # 3. Thống kê tờ khai & container
        declarations = set()
        total_containers = 0
        total_surcharge_ca = 0  # Tổng lưu ca
        total_items_with_ca = 0

        for lot in lots:
            if lot.customs_declaration:
                declarations.add(lot.customs_declaration)
            for item in lot.revenue_items:
                total_containers += 1
                if hasattr(item, 'luu_ca') and item.luu_ca and float(item.luu_ca or 0) > 0:
                    total_surcharge_ca += 1

        total_declarations = len(declarations)
        luu_ca_rate = round((total_surcharge_ca / total_containers * 100), 1) if total_containers > 0 else 0

        # 4. Phân nhóm theo địa điểm (Lạng Sơn / Hải Phòng / Khác)
        location_breakdown = defaultdict(int)
        for lot in lots:
            for item in lot.revenue_items:
                route = (getattr(item, 'route', '') or '').lower()
                if 'lạng sơn' in route or 'lang son' in route or 'lạng' in route:
                    location_breakdown['Lạng Sơn'] += 1
                elif 'hải phòng' in route or 'hai phong' in route:
                    location_breakdown['Hải Phòng'] += 1
                else:
                    location_breakdown['Khác'] += 1

        # 5. Danh sách khách hàng hiện hữu (có giao dịch trong tháng)
        existing_customers = []
        for c in customers:
            if c.get('revenue', 0) > 0 and c.get('name') != 'Khác':
                existing_customers.append({
                    'name': c['name'],
                    'revenue': c['revenue'],
                    'lot_count': c['lot_count'],
                    'share': c.get('share', 0)
                })

        # 6. Trend data (12 tháng)
        trend = CalculatorService.get_year_trend(year)

        # 7. Chi tiết chi phí vận hành
        total_ops_cost = kpi.get('operating_cost', 0)
        ops_by_type = defaultdict(float)
        for lot in lots:
            for oc in lot.operating_costs:
                cost_type = getattr(oc, 'cost_type', 'Khác') or 'Khác'
                amount = float(getattr(oc, 'total_amount', 0) or 0)
                ops_by_type[cost_type] += amount

        # 8. Nhân viên phụ trách
        staff_assignments = defaultdict(list)
        for lot in lots:
            if lot.assigned_to:
                user = db.session.get(User, lot.assigned_to)
                if user:
                    staff_assignments[user.full_name].append({
                        'lot': lot.lot_label,
                        'customer': lot.customer.name if lot.customer else 'N/A',
                        'status': lot.status
                    })

        return {
            'month': month,
            'year': year,
            'kpi': kpi,
            'customers': customers,
            'comments': comments,
            'total_declarations': total_declarations,
            'total_containers': total_containers,
            'luu_ca_rate': luu_ca_rate,
            'location_breakdown': dict(location_breakdown),
            'existing_customers': existing_customers,
            'trend': trend,
            'ops_by_type': dict(ops_by_type),
            'staff_assignments': dict(staff_assignments),
            'lot_count': len(lots),
        }


# ─────────────────────────────────────────────────
# 2. GeminiReportWriter — Gọi Gemini AI sinh narrative
# ─────────────────────────────────────────────────

class GeminiReportWriter:
    """Sử dụng Google Gemini AI để sinh nội dung narrative cho báo cáo."""

    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    @classmethod
    def generate_report(cls, data, report_type='kqkd'):
        """
        Sinh toàn bộ nội dung báo cáo bằng AI.
        
        Args:
            data: dict từ ReportDataCollector.collect()
            report_type: 'kqkd' hoặc 'cross_border'
        
        Returns:
            dict chứa các section nội dung đã sinh
        """
        if report_type == 'cross_border':
            return cls._generate_cross_border(data)
        else:
            return cls._generate_kqkd(data)

    @classmethod
    def _generate_kqkd(cls, data):
        """Sinh báo cáo Kết Quả Kinh Doanh (KQKD)."""
        kpi = data['kpi']
        month = data['month']
        year = data['year']

        # Chuẩn bị context data cho AI
        context = cls._build_data_context(data)

        prompt = f"""Bạn là chuyên gia phân tích kinh doanh logistics của công ty GIDO (Công ty CPDVTM Xuyên Biên Giới GIC).
Hãy viết nội dung báo cáo kết quả hoạt động kinh doanh (KQKD) tháng {month:02d}/{year} dựa trên dữ liệu thực tế sau:

{context}

Yêu cầu viết theo format JSON với các trường sau:
{{
    "hoat_dong_trong_thang": "Mô tả ngắn gọn 3-5 bullet points hoạt động chính trong tháng (vận chuyển, khách hàng, thông quan). Mỗi bullet bắt đầu bằng dấu •",
    "kho_khan_nhan_su": "2-3 bullet points về khó khăn nhân sự hiện tại. Mỗi bullet bắt đầu bằng dấu •",
    "kho_khan_tai_chinh": "2-3 bullet points về khó khăn công cụ/tài chính. Mỗi bullet bắt đầu bằng dấu •",
    "ke_hoach_kinh_doanh": "3-5 bullet points kế hoạch kinh doanh tháng tới. Mỗi bullet bắt đầu bằng dấu •",
    "de_xuat": "2-3 bullet points đề xuất/phát sinh cần hỗ trợ. Mỗi bullet bắt đầu bằng dấu •"
}}

Lưu ý quan trọng:
- Viết bằng tiếng Việt chuyên nghiệp, giọng văn báo cáo hành chính
- GIDO chuyên vận chuyển hàng hóa xuyên biên giới (Cross Border) từ Trung Quốc về Việt Nam
- Đường bộ qua cửa khẩu Lạng Sơn và đường biển qua Hải Phòng
- Khách hàng chính: Keep Rise, Yunda (TMĐT), Sunluxe, công ty Quảng Hưng
- CHỈ trả về JSON thuần, không có markdown
- Mỗi nội dung cần thực tế, dựa vào dữ liệu đã cung cấp"""

        try:
            result = cls._call_gemini(prompt)
            return {
                'type': 'kqkd',
                'month': month,
                'year': year,
                'sections': result,
                'data': data,
                'generated_at': datetime.now().isoformat(),
                'status': 'success'
            }
        except Exception as e:
            print(f"[ReportService] Gemini API error: {e}")
            return cls._fallback_kqkd(data)

    @classmethod
    def _generate_cross_border(cls, data):
        """Sinh báo cáo hoạt động Cross Border."""
        kpi = data['kpi']
        month = data['month']
        year = data['year']

        context = cls._build_data_context(data)

        prompt = f"""Bạn là chuyên gia phân tích kinh doanh logistics của công ty GIDO (Công ty CPDVTM Xuyên Biên Giới GIC).
Hãy viết nội dung BÁO CÁO HOẠT ĐỘNG CROSS BORDER tháng {month:02d}/{year} dựa trên dữ liệu thực tế sau:

{context}

Yêu cầu viết theo format JSON với các trường sau:
{{
    "hoat_dong_thang": "Mô tả tổng quan hoạt động xuất nhập trong tháng, 3-5 bullet points. Mỗi bullet bắt đầu bằng dấu •",
    "nguyen_nhan_bien_dong": "Phân tích nguyên nhân tăng/giảm doanh thu so với tháng trước, 2-4 bullet points. Mỗi bullet bắt đầu bằng dấu •",
    "hoat_dong_chi_tiet": "Các hoạt động cụ thể trong tháng (công tác, ký kết, test hệ thống...), 3-5 bullet points. Mỗi bullet bắt đầu bằng dấu •",
    "ke_hoach_thang_toi": "Kế hoạch tháng tới và quý tiếp theo, 4-6 bullet points. Mỗi bullet bắt đầu bằng dấu •"
}}

Lưu ý quan trọng:
- Viết bằng tiếng Việt chuyên nghiệp, giọng văn báo cáo hành chính
- GIDO chuyên vận chuyển hàng hóa xuyên biên giới (Cross Border) từ Trung Quốc về Việt Nam
- Đường bộ qua cửa khẩu Lạng Sơn và đường biển qua Hải Phòng  
- CHỈ trả về JSON thuần, không có markdown
- Mỗi nội dung cần thực tế, dựa vào dữ liệu đã cung cấp"""

        try:
            result = cls._call_gemini(prompt)
            return {
                'type': 'cross_border',
                'month': month,
                'year': year,
                'sections': result,
                'data': data,
                'generated_at': datetime.now().isoformat(),
                'status': 'success'
            }
        except Exception as e:
            print(f"[ReportService] Gemini API error: {e}")
            return cls._fallback_cross_border(data)

    @classmethod
    def _build_data_context(cls, data):
        """Xây dựng context string từ data để gửi cho Gemini."""
        kpi = data['kpi']
        month = data['month']
        year = data['year']

        # Format tiền
        def fmt(val):
            try:
                return f"{float(val):,.0f}".replace(',', '.')
            except:
                return '0'

        lines = [
            f"=== DỮ LIỆU THÁNG {month:02d}/{year} ===",
            f"Doanh thu bán ra (chưa VAT): {fmt(kpi['revenue'])} đ",
            f"Cước mua vào (có VAT): {fmt(kpi['buy_cost'])} đ",
            f"Chi phí vận hành (CPVH): {fmt(kpi['operating_cost'])} đ",
            f"Lợi nhuận ròng: {fmt(kpi['net_profit'])} đ",
            f"Tỷ suất lợi nhuận: {kpi['profit_margin']}%",
            f"Số lô hàng: {kpi['lot_count']}",
            f"Tổng số tờ khai hải quan: {data['total_declarations']}",
            f"Tổng số container: {data['total_containers']}",
            f"Tỷ lệ lưu ca: {data['luu_ca_rate']}%",
        ]

        if kpi.get('has_target'):
            lines.append(f"Target mục tiêu: {fmt(kpi['target'])} đ")
            lines.append(f"Tỷ lệ hoàn thành target: {kpi['achievement_pct']}%")

        if kpi.get('has_prev_data'):
            lines.append(f"Tăng trưởng doanh thu MoM: {kpi['rev_growth']}%")
            lines.append(f"Doanh thu tháng trước: {fmt(kpi['prev_revenue'])} đ")

        # Phân bổ địa điểm
        if data.get('location_breakdown'):
            lines.append("\nPhân bổ theo địa điểm:")
            for loc, count in data['location_breakdown'].items():
                lines.append(f"  - {loc}: {count} cont")

        # Top khách hàng
        if data.get('existing_customers'):
            lines.append("\nKhách hàng hoạt động trong tháng:")
            for c in data['existing_customers'][:5]:
                lines.append(f"  - {c['name']}: {fmt(c['revenue'])} đ ({c['share']}% doanh thu, {c['lot_count']} lô)")

        # Trend 3 tháng gần nhất
        if data.get('trend'):
            lines.append("\nDiễn biến 3 tháng gần nhất:")
            recent = [t for t in data['trend'] if t['revenue'] > 0][-3:]
            for t in recent:
                lines.append(f"  - {t['month']}/{year}: DT {fmt(t['revenue'])} đ, CP {fmt(t['total_cost'])} đ, LN {fmt(t['profit'])} đ")

        # Nhân viên
        if data.get('staff_assignments'):
            lines.append("\nNhân viên phụ trách:")
            for staff, assignments in data['staff_assignments'].items():
                lines.append(f"  - {staff}: {len(assignments)} lô hàng")

        return '\n'.join(lines)

    @classmethod
    def _call_gemini(cls, prompt):
        """Gọi Gemini API và parse JSON response với xử lý robust."""
        api_key = os.environ.get('GEMINI_API_KEY') or GEMINI_API_KEY
        if not api_key:
            from flask import current_app
            try:
                api_key = current_app.config.get('GEMINI_API_KEY', '')
            except Exception:
                pass

        if not api_key:
            raise Exception("GEMINI_API_KEY chưa được cấu hình trong Environment Variables")

        url = f"{cls.GEMINI_URL}?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.8,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json"
            }
        }

        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"Gemini API lỗi: {resp.status_code} - {resp.text}")

        raw_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        
        # Clean markdown fences
        cleaned = raw_text.replace('```json', '').replace('```', '').strip()
        
        # Attempt 1: Direct JSON parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 2: Fix newlines inside JSON string values
        # Replace literal newlines between quotes with \\n
        import re
        try:
            # Remove any trailing commas before } or ]
            fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
            # Replace actual newlines within string values with literal \n
            # Strategy: find content between "key": " and the next ",  or "}
            def fix_multiline_strings(text):
                result = []
                in_string = False
                escape_next = False
                for ch in text:
                    if escape_next:
                        result.append(ch)
                        escape_next = False
                        continue
                    if ch == '\\':
                        escape_next = True
                        result.append(ch)
                        continue
                    if ch == '"':
                        in_string = not in_string
                        result.append(ch)
                        continue
                    if in_string and ch == '\n':
                        result.append('\\n')
                        continue
                    if in_string and ch == '\r':
                        continue
                    result.append(ch)
                return ''.join(result)

            fixed = fix_multiline_strings(fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Attempt 3: Regex extraction of key-value pairs
        try:
            result = {}
            # Match "key": "value" patterns, allowing for multiline values
            pattern = r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)?"'
            matches = re.findall(pattern, cleaned, re.DOTALL)
            for key, value in matches:
                # Unescape the value
                value = value.replace('\\n', '\n').replace('\\"', '"')
                result[key] = value
            if result:
                return result
        except Exception:
            pass

        raise Exception(f"Không thể parse JSON từ Gemini: {cleaned[:200]}")

    @classmethod
    def _fallback_kqkd(cls, data):
        """Fallback khi Gemini API không khả dụng — trả template trống."""
        month = data['month']
        year = data['year']
        return {
            'type': 'kqkd',
            'month': month,
            'year': year,
            'sections': {
                'hoat_dong_trong_thang': '• (Vui lòng điền hoạt động chính trong tháng)',
                'kho_khan_nhan_su': '• (Vui lòng điền khó khăn về nhân sự)',
                'kho_khan_tai_chinh': '• (Vui lòng điền khó khăn về tài chính/công cụ)',
                'ke_hoach_kinh_doanh': '• (Vui lòng điền kế hoạch kinh doanh tháng tới)',
                'de_xuat': '• (Vui lòng điền đề xuất cần hỗ trợ)'
            },
            'data': data,
            'generated_at': datetime.now().isoformat(),
            'status': 'fallback'
        }

    @classmethod
    def _fallback_cross_border(cls, data):
        """Fallback cho Cross Border report."""
        month = data['month']
        year = data['year']
        return {
            'type': 'cross_border',
            'month': month,
            'year': year,
            'sections': {
                'hoat_dong_thang': '• (Vui lòng điền hoạt động xuất nhập tháng)',
                'nguyen_nhan_bien_dong': '• (Vui lòng điền nguyên nhân biến động doanh thu)',
                'hoat_dong_chi_tiet': '• (Vui lòng điền hoạt động chi tiết)',
                'ke_hoach_thang_toi': '• (Vui lòng điền kế hoạch tháng tới)'
            },
            'data': data,
            'generated_at': datetime.now().isoformat(),
            'status': 'fallback'
        }


# ─────────────────────────────────────────────────
# 3. WordExporter — Xuất file Word .docx
# ─────────────────────────────────────────────────

class WordExporter:
    """Tạo file Word .docx theo đúng format mẫu báo cáo GIDO."""

    # Styling constants
    FONT_NAME = 'Times New Roman'
    HEADING_COLOR = RGBColor(0, 0, 0)
    TABLE_HEADER_BG = RGBColor(0x1F, 0x49, 0x7D)  # Navy blue
    TABLE_HEADER_FG = RGBColor(0xFF, 0xFF, 0xFF)  # White

    @classmethod
    def export_kqkd(cls, report_data):
        """
        Xuất báo cáo KQKD ra file Word.
        Returns: BytesIO buffer chứa file .docx
        """
        doc = Document()
        month = report_data['month']
        year = report_data['year']
        data = report_data['data']
        sections = report_data['sections']
        kpi = data['kpi']

        # Set default font
        style = doc.styles['Normal']
        font = style.font
        font.name = cls.FONT_NAME
        font.size = Pt(12)

        # ── Title ──
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run('BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH')
        run.bold = True
        run.font.size = Pt(16)
        run.font.name = cls.FONT_NAME

        # ── Sub-header ──
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = sub.add_run(f'Bộ phận: Cross Border      Kỳ báo cáo: Tháng {month:02d}/{year}')
        run.font.size = Pt(12)
        run.font.name = cls.FONT_NAME

        meta = doc.add_paragraph()
        run = meta.add_run(f'Người lập: ................      Ngày: {datetime.now().strftime("%d/%m/%Y")}')
        run.font.size = Pt(12)
        run.font.name = cls.FONT_NAME

        # ── I. KẾT QUẢ HOẠT ĐỘNG ──
        cls._add_heading(doc, 'I. KẾT QUẢ HOẠT ĐỘNG', level=1)

        # I.1. Kết quả kinh doanh
        cls._add_heading(doc, 'I.1. Kết quả kinh doanh', level=2)

        def fmt(val):
            try:
                return f"{float(val):,.0f}".replace(',', '.')
            except:
                return '0'

        doc.add_paragraph(f'Số topline tổng tháng {month}/{year}: {fmt(kpi["revenue"])} đ (chưa VAT)')

        doc.add_paragraph(f'Tổng số tờ khai tháng {month}/{year}: {data["total_declarations"]} tờ khai Trung Quốc nhập về Việt Nam')

        # Phân bổ theo địa điểm
        if data.get('location_breakdown'):
            for loc, count in data['location_breakdown'].items():
                p = doc.add_paragraph(style='List Bullet')
                p.add_run(f'{loc}: {count} tờ khai')

        doc.add_paragraph(f'Tổng số cont tháng {month}/{year}: {data["total_containers"]} cont')

        if data.get('location_breakdown'):
            for loc, count in data['location_breakdown'].items():
                p = doc.add_paragraph(style='List Bullet')
                p.add_run(f'{loc}: {count} cont')

        doc.add_paragraph(f'Tỷ lệ lưu ca: {data["luu_ca_rate"]}%')

        # Hoạt động trong tháng (AI)
        doc.add_paragraph('Hoạt động trong tháng:')
        cls._add_bullet_text(doc, sections.get('hoat_dong_trong_thang', ''))

        # I.2. Tiêu chí khách hàng
        cls._add_heading(doc, 'I.2. Tiêu chí khách hàng', level=2)

        doc.add_paragraph(f'a) Khách hàng hiện hữu ({len(data["existing_customers"])} khách hàng)')

        # Bảng khách hàng
        if data['existing_customers']:
            table = doc.add_table(rows=1, cols=6)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.style = 'Table Grid'
            headers = ['STT', 'Tên khách hàng', 'Mảng của KH', 'Doanh thu', 'Số lô', 'Tỷ trọng']
            for i, h in enumerate(headers):
                cell = table.rows[0].cells[i]
                cell.text = h
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True
                        run.font.size = Pt(10)

            for idx, cust in enumerate(data['existing_customers'], 1):
                row = table.add_row()
                row.cells[0].text = str(idx)
                row.cells[1].text = cust['name']
                row.cells[2].text = 'Cross Border'
                row.cells[3].text = fmt(cust['revenue']) + ' đ'
                row.cells[4].text = str(cust['lot_count'])
                row.cells[5].text = f"{cust['share']}%"

        doc.add_paragraph('b) Khách hàng tiềm năng')
        doc.add_paragraph('(Cần bổ sung thông tin khách hàng tiềm năng)')

        # ── II. NHỮNG KHÓ KHĂN, VƯỚNG MẮC ──
        cls._add_heading(doc, 'II. NHỮNG KHÓ KHĂN, VƯỚNG MẮC (cần có sự hỗ trợ)', level=1)

        cls._add_heading(doc, 'II.1. Về mặt nhân sự', level=2)
        cls._add_bullet_text(doc, sections.get('kho_khan_nhan_su', ''))

        cls._add_heading(doc, 'II.2. Về mặt công cụ dụng cụ, tài chính và những khó khăn khác', level=2)
        cls._add_bullet_text(doc, sections.get('kho_khan_tai_chinh', ''))

        # ── III. KẾ HOẠCH SẮP TỚI ──
        cls._add_heading(doc, 'III. KẾ HOẠCH SẮP TỚI', level=1)

        cls._add_heading(doc, 'III.1. Kế hoạch kinh doanh', level=2)

        # Bảng phân công nhân viên
        if data.get('staff_assignments'):
            doc.add_paragraph('Phân công khách hàng/nguồn hàng theo nhân viên phụ trách:')
            next_month = month + 1 if month < 12 else 1
            next_month2 = next_month + 1 if next_month < 12 else 1
            table = doc.add_table(rows=1, cols=3)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.style = 'Table Grid'
            for i, h in enumerate(['Nhân viên', f'Tháng {next_month}', f'Tháng {next_month2}']):
                cell = table.rows[0].cells[i]
                cell.text = h
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True

            for staff in data['staff_assignments'].keys():
                row = table.add_row()
                row.cells[0].text = staff
                row.cells[1].text = '(Cần bổ sung kế hoạch)'
                row.cells[2].text = '(Cần bổ sung kế hoạch)'

        doc.add_paragraph('Chi tiết kế hoạch:')
        cls._add_bullet_text(doc, sections.get('ke_hoach_kinh_doanh', ''))

        cls._add_heading(doc, 'III.2. Kế hoạch hỗ trợ', level=2)

        doc.add_paragraph('a) Đề xuất/Phát sinh')
        # Bảng đề xuất
        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = 'Table Grid'
        table.rows[0].cells[0].text = 'Nội dung đề xuất'
        table.rows[0].cells[1].text = 'Đơn vị/bộ phận hỗ trợ'
        for p in table.rows[0].cells[0].paragraphs:
            for run in p.runs:
                run.bold = True
        for p in table.rows[0].cells[1].paragraphs:
            for run in p.runs:
                run.bold = True

        # Thêm đề xuất từ AI
        proposals = sections.get('de_xuat', '').split('•')
        for prop in proposals:
            prop = prop.strip()
            if prop:
                row = table.add_row()
                row.cells[0].text = prop
                row.cells[1].text = '(Cần xác định)'

        # Export to buffer
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @classmethod
    def export_cross_border(cls, report_data):
        """Xuất báo cáo Cross Border ra file Word."""
        doc = Document()
        month = report_data['month']
        year = report_data['year']
        data = report_data['data']
        sections = report_data['sections']
        kpi = data['kpi']

        # Set default font
        style = doc.styles['Normal']
        font = style.font
        font.name = cls.FONT_NAME
        font.size = Pt(12)

        def fmt(val):
            try:
                return f"{float(val):,.0f}".replace(',', '.')
            except:
                return '0'

        # ── Title ──
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(f'BÁO CÁO HOẠT ĐỘNG CROSS BORDER THÁNG {month:02d}/{year}')
        run.bold = True
        run.font.size = Pt(16)
        run.font.name = cls.FONT_NAME

        # ── Tổng quan ──
        doc.add_paragraph(f'Hoạt động tháng {month:02d}/{year}:')

        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f'Tổng số tờ khai tháng {month}/{year}: {data["total_declarations"]} tờ khai Trung Quốc nhập về Việt Nam')

        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f'Tổng số cont tháng {month}/{year}: {data["total_containers"]} cont')

        # Phân bổ
        if data.get('location_breakdown'):
            for loc, count in data['location_breakdown'].items():
                p = doc.add_paragraph(style='List Bullet')
                p.add_run(f'{loc}: {count} cont')

        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f'Tỷ lệ lưu ca: {data["luu_ca_rate"]}%')

        # Doanh thu
        doc.add_paragraph(f'Doanh thu tháng {month}/{year}: {fmt(kpi["revenue"])} đ')

        if kpi.get('has_prev_data') and kpi.get('rev_growth') is not None:
            trend_text = 'tăng' if kpi['rev_growth'] > 0 else 'giảm'
            doc.add_paragraph(f'So với tháng trước: {trend_text} {abs(kpi["rev_growth"])}%')

        # Nguyên nhân biến động (AI)
        if kpi.get('has_prev_data') and kpi.get('rev_growth', 0) < 0:
            doc.add_paragraph(f'Nguyên nhân giảm doanh thu tháng {month}/{year}:')
        else:
            doc.add_paragraph(f'Phân tích biến động doanh thu tháng {month}/{year}:')
        cls._add_bullet_text(doc, sections.get('nguyen_nhan_bien_dong', ''))

        # Hoạt động trong tháng (AI)
        doc.add_paragraph('Hoạt động trong tháng:')
        cls._add_bullet_text(doc, sections.get('hoat_dong_chi_tiet', ''))

        # Tổng quan xuất nhập
        doc.add_paragraph(f'Tổng quan về hoạt động xuất nhập {month:02d}/{year}:')
        cls._add_bullet_text(doc, sections.get('hoat_dong_thang', ''))

        # Kế hoạch
        next_m = month + 1 if month < 12 else 1
        doc.add_paragraph(f'Kế hoạch trong tháng {next_m}/{year} và các tháng tiếp theo:')
        cls._add_bullet_text(doc, sections.get('ke_hoach_thang_toi', ''))

        # Export
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @classmethod
    def _add_heading(cls, doc, text, level=1):
        """Thêm heading với font Times New Roman."""
        h = doc.add_heading(text, level=level)
        for run in h.runs:
            run.font.name = cls.FONT_NAME
            run.font.color.rgb = cls.HEADING_COLOR

    @classmethod
    def _add_bullet_text(cls, doc, text):
        """Thêm nội dung dạng bullet points từ AI text."""
        if not text:
            return
        bullets = text.split('•')
        for bullet in bullets:
            bullet = bullet.strip()
            if bullet:
                # Xử lý trường hợp bullet có dấu - ở đầu
                bullet = bullet.lstrip('- ').strip()
                if bullet:
                    p = doc.add_paragraph(style='List Bullet')
                    p.add_run(bullet)
