import re
import datetime
import json
import unicodedata
from pathlib import Path
import openpyxl
from app.extensions import db
from app.models import Customer, Supplier, Target, Lot, RevenueItem, OperatingCost, User

def normalize_text(s):
    """
    Normalize string: strip accents (combining marks), lowercase, collapse whitespace.
    Converts: 'TỔNG CỘNG' -> 'tong cong', 'TỔNG CƯỚC' -> 'tong cuoc', 'Tổng chi phí' -> 'tong chi phi'
    """
    if s is None:
        return ''
    s = unicodedata.normalize('NFD', str(s))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.lower().split())

def clean_str(val):
    if val is None:
        return ''
    s = str(val).strip()
    return s

def clean_float(val):
    if val is None or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(',', '')
    if '/' in s:
        try:
            parts = s.split('/')
            return float(parts[0]) / float(parts[1])
        except Exception:
            return 0.0
    if '+' in s:
        try:
            parts = s.split('+')
            return sum(float(p) for p in parts)
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def clean_date(val):
    if isinstance(val, (datetime.datetime, datetime.date)):
        if isinstance(val, datetime.datetime):
            return val.date()
        return val
    if isinstance(val, str):
        s = val.strip()
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                pass
    return None

def parse_month_year(sheet_name):
    """
    Extract (month, year) from sheet names:
    'Tháng 9.2025', 'GHNLog 11.2025', 'Gido 1.2026', 'Gido 5.2026 ', 'Gido 9. 2026', 'T08', '11.2025'
    """
    m = re.search(r'(\d{1,2})\s*[\./-]\s*(\d{4})', sheet_name)
    if m:
        return int(m.group(1)), int(m.group(2))
    
    m2 = re.search(r'T(\d{2})', sheet_name, re.IGNORECASE)
    if m2:
        return int(m2.group(1)), 2026
        
    return None, None

def is_summary_or_footer_row(row_cells):
    """
    Check if a row is a summary, total, tax, difference, advance, or signature row.
    """
    row_text = normalize_text(" ".join(str(c or '') for c in row_cells[:8]))
    keywords = [
        'tong cong', 'tong cuoc chua bao gom', 'tong cuoc bao gom', 
        'chenh lech', 'thue vat', 'tong cuoc', 'tong tien mua', 'tong tien ban',
        'tong chi phi', 'tam ung', 'hoan ung', 'truong bo phan', 'nguoi lap bieu', 'ke toan',
        'giam doc', 'ky xac nhan'
    ]
    return any(k in row_text for k in keywords)

def get_or_create_customer(name):
    if not name:
        name = "Khách vãng lai"
    name = name.strip()
    cust = Customer.query.filter_by(name=name).first()
    if not cust:
        cust = Customer(name=name)
        db.session.add(cust)
        db.session.flush()
    return cust

class ExcelParserService:
    @staticmethod
    def import_all(sales_file_path, cost_file_path, reset_excel_data=True):
        """
        Main entry point to import both Excel files.
        Idempotent: if reset_excel_data is True, safely clears previous Excel-imported data
        without touching manual user data.
        """
        results = {
            'targets': 0,
            'suppliers': 0,
            'lots': 0,
            'revenue_items': 0,
            'operating_costs': 0,
            'errors': []
        }
        
        if reset_excel_data:
            try:
                # Safely delete previously imported lots (those with source_sheet not null)
                # This cascade-deletes their revenue_items, operating_costs, and tasks
                prev_lots = Lot.query.filter(Lot.source_sheet.isnot(None)).all()
                for pl in prev_lots:
                    db.session.delete(pl)
                db.session.flush()
            except Exception as e:
                results['errors'].append(f"Lỗi dọn dẹp dữ liệu cũ: {str(e)}")
        
        # 1. Parse Targets from sales report
        try:
            t_count = ExcelParserService.parse_targets(sales_file_path)
            results['targets'] = t_count
        except Exception as e:
            results['errors'].append(f"Lỗi parse Target: {str(e)}")
            
        # 2. Parse Suppliers from cost file
        try:
            s_count = ExcelParserService.parse_suppliers(cost_file_path)
            results['suppliers'] = s_count
        except Exception as e:
            results['errors'].append(f"Lỗi parse NCC: {str(e)}")
            
        # 3. Parse Sales Report sheets
        try:
            l_count, r_count = ExcelParserService.parse_sales_report(sales_file_path)
            results['lots'] += l_count
            results['revenue_items'] += r_count
        except Exception as e:
            results['errors'].append(f"Lỗi parse Báo cáo bán hàng: {str(e)}")
            
        # 4. Parse Operating Costs sheets
        try:
            c_count = ExcelParserService.parse_operating_costs(cost_file_path)
            results['operating_costs'] += c_count
        except Exception as e:
            results['errors'].append(f"Lỗi parse Chi phí vận hành: {str(e)}")
            
        # 5. Clean up any empty placeholder lots that have no revenue items, no operating costs, and no tasks
        try:
            empty_lots = [l for l in Lot.query.all() if len(l.revenue_items) == 0 and len(l.operating_costs) == 0 and l.tasks.count() == 0]
            for el in empty_lots:
                db.session.delete(el)
            db.session.flush()
        except Exception as e:
            results['errors'].append(f"Lỗi dọn dẹp lô trống: {str(e)}")
            
        db.session.commit()
        return results

    @staticmethod
    def parse_targets(file_path):
        wb = openpyxl.load_workbook(file_path, data_only=True)
        if 'Target' not in wb.sheetnames:
            return 0
        ws = wb['Target']
        count = 0
        for col in range(1, 13):
            date_val = ws.cell(3, col).value
            target_val = ws.cell(4, col).value
            if target_val is not None:
                month = col
                year = 2026
                if isinstance(date_val, (datetime.datetime, datetime.date)):
                    month = date_val.month
                    year = date_val.year
                
                target = Target.query.filter_by(year=year, month=month).first()
                if not target:
                    target = Target(year=year, month=month, target_amount=clean_float(target_val))
                    db.session.add(target)
                else:
                    target.target_amount = clean_float(target_val)
                count += 1
        db.session.flush()
        return count

    @staticmethod
    def parse_suppliers(file_path):
        wb = openpyxl.load_workbook(file_path, data_only=True)
        if 'NCC' not in wb.sheetnames:
            return 0
        ws = wb['NCC']
        count = 0
        for r in range(4, ws.max_row + 1):
            tax_code = clean_str(ws.cell(r, 2).value)
            supp_code = clean_str(ws.cell(r, 3).value)
            name = clean_str(ws.cell(r, 4).value)
            address = clean_str(ws.cell(r, 5).value)
            
            if not name and not tax_code:
                continue
                
            supplier = None
            if tax_code:
                supplier = Supplier.query.filter_by(tax_code=tax_code).first()
            if not supplier:
                supplier = Supplier.query.filter_by(name=name).first()
                
            if not supplier:
                supplier = Supplier(
                    tax_code=tax_code,
                    supplier_code=supp_code,
                    name=name,
                    address=address
                )
                db.session.add(supplier)
                count += 1
            else:
                supplier.tax_code = tax_code or supplier.tax_code
                supplier.supplier_code = supp_code or supplier.supplier_code
                supplier.address = address or supplier.address
        db.session.flush()
        return count

    @staticmethod
    def parse_sales_report(file_path):
        wb_data = openpyxl.load_workbook(file_path, data_only=True)
        wb_raw = openpyxl.load_workbook(file_path, data_only=False)
        total_lots = 0
        total_items = 0
        
        for sn in wb_data.sheetnames:
            if sn in ['Target', 'Tính lợi nhuận']:
                continue
                
            month, year = parse_month_year(sn)
            if not month or not year:
                continue
                
            ws = wb_data[sn]
            ws_raw = wb_raw[sn]
            is_ghnlog = 'GHN' in sn.upper() or 'THÁNG' in sn.upper() or 'THÁNG' in sn.upper()
            
            # 1. Find header row
            header_row = -1
            for r in range(1, 15):
                val = normalize_text(ws.cell(r, 1).value)
                if 'stt' in val:
                    header_row = r
                    break
            if header_row == -1:
                continue
                
            # 2. Build column map with normalized names
            col_map = {}
            for c in range(1, ws.max_column + 1):
                raw_val = ws.cell(header_row, c).value
                if raw_val:
                    col_map[c] = normalize_text(raw_val)
                    
            def get_col_val(r, *keywords):
                for col_idx, col_name in col_map.items():
                    for kw in keywords:
                        if kw in col_name:
                            return ws.cell(r, col_idx).value
                return None

            # 3. Locate column for 'tong tien ban' and 'tong tien mua'
            col_tb_idx = None
            col_tm_idx = None
            for c, cn in col_map.items():
                if 'tong tien ban' in cn or 'tong ban' in cn:
                    col_tb_idx = c
                elif 'tong tien mua' in cn or 'tong mua' in cn:
                    col_tm_idx = c

            # 4. Locate total summary row
            total_row = None
            for r in range(header_row + 1, ws.max_row + 1):
                c1_norm = normalize_text(ws.cell(r, 1).value)
                if any(k in c1_norm for k in ['tong cong', 'tong cuoc']):
                    total_row = r
                    break

            sum_start_row = header_row + 1
            sum_end_row = (total_row - 1) if total_row else ws.max_row

            # Check if total row has an explicit SUM formula range
            if total_row and col_tb_idx:
                raw_formula = str(ws_raw.cell(total_row, col_tb_idx).value or '')
                m_range = re.search(r'SUM\([A-Z]+(\d+):[A-Z]+(\d+)\)', raw_formula, re.IGNORECASE)
                if m_range:
                    sum_start_row = int(m_range.group(1))
                    sum_end_row = int(m_range.group(2))

            current_lot = None
            lot_counter = 1
            
            for r in range(header_row + 1, ws.max_row + 1):
                row_vals = [ws.cell(r, c).value for c in range(1, min(10, ws.max_column + 1))]
                
                # Check if this row is a total / summary / footer row -> stop
                if (total_row and r >= total_row) or is_summary_or_footer_row(row_vals):
                    break
                    
                c1_val = clean_str(ws.cell(r, 1).value)
                
                # Read and normalize row data first
                cust_name = clean_str(get_col_val(r, 'khach hang'))
                decl_num = clean_str(get_col_val(r, 'to khai'))
                company = clean_str(get_col_val(r, 'cong ty'))
                start_date = clean_date(get_col_val(r, 'bat dau'))
                end_date = clean_date(get_col_val(r, 'ket thuc'))
                service_desc = clean_str(get_col_val(r, 'dich vu', 'lo trinh', 'noi dung'))
                
                buy_p = clean_float(get_col_val(r, 'gia mua'))
                sell_p = clean_float(get_col_val(r, 'gia ban'))
                buy_loading = clean_float(get_col_val(r, 'boc xep, ben bai', 'chi phi boc xep'))
                
                # Surcharges
                overtime_count = clean_float(get_col_val(r, 'so ca'))
                overtime_f = clean_float(get_col_val(r, 'luu ca', 'phi luu ca'))
                customs_insp = clean_float(get_col_val(r, 'giam sat', 'hai quan giam sat'))
                infra_f = clean_float(get_col_val(r, 'csht', 'phi csht'))
                ticket_f = clean_float(get_col_val(r, 've xe'))
                new_mach = clean_float(get_col_val(r, 'may moi'))
                oversize_f = clean_float(get_col_val(r, 'qua kho'))
                loading_f = clean_float(get_col_val(r, 'phi boc xep sang hang', 'phi boc xep'))
                penalty_f = clean_float(get_col_val(r, 'xu phat, xe', 'xu phat', 'hai quan phat'))
                tan_thanh_f = clean_float(get_col_val(r, 'tan thanh'))
                thuan_thanh_f = clean_float(get_col_val(r, 'thuan thanh'))
                return_doss_f = clean_float(get_col_val(r, 'quay dau'))
                storage_f = clean_float(get_col_val(r, 'luu kho'))
                penalty_doss_f = clean_float(get_col_val(r, 'ho so xu phat'))
                penalty_pay_f = clean_float(get_col_val(r, 'nop xu phat'))
                
                # GHNLog specific
                route_val = clean_str(get_col_val(r, 'lo trinh'))
                insp_pt = clean_float(get_col_val(r, 'diem kiem'))
                insp_fee = clean_float(get_col_val(r, 'phat sinh kiem'))
                rout_fee = clean_float(get_col_val(r, 'lach huyen', 'lach'))
                empty_cont = clean_float(get_col_val(r, 'chon vo', 'vo'))
                
                # Excel evaluated Total buy and Total sell from columns
                val_tb = None
                if col_tb_idx:
                    if sum_start_row <= r <= sum_end_row:
                        val_tb = clean_float(ws.cell(r, col_tb_idx).value)
                    else:
                        val_tb = 0.0

                val_tm = None
                if col_tm_idx:
                    val_tm = clean_float(ws.cell(r, col_tm_idx).value)

                has_activity = (
                    (val_tb is not None and val_tb > 0) or 
                    (val_tm is not None and val_tm > 0) or 
                    buy_p > 0 or sell_p > 0 or 
                    service_desc or buy_loading > 0 or cust_name
                )
                
                if not has_activity and not c1_val:
                    continue
                    
                is_new_lot = False
                lot_label = None
                
                if c1_val:
                    if 'lô' in c1_val.lower() or 'lo' in c1_val.lower():
                        is_new_lot = True
                        lot_label = c1_val
                    elif c1_val.isdigit():
                        is_new_lot = True
                        lot_label = f"Lô {c1_val}"
                    else:
                        is_new_lot = True
                        lot_label = f"Lô {c1_val}"
                elif current_lot is None and has_activity:
                    is_new_lot = True
                    lot_label = f"Lô {lot_counter}"
                    
                if is_new_lot:
                    # Enterprise company takes priority over individual contact (e.g. 'Anh Thắng' -> 'Sunluxe')
                    norm_c = cust_name.lower() if cust_name else ''
                    resolved_cust = company if (company and ('anh ' in norm_c or 'chi ' in norm_c or not cust_name)) else (cust_name or company or "Khách vãng lai")
                    cust = get_or_create_customer(resolved_cust)
                    current_lot = Lot(
                        lot_label=lot_label or f"Lô {lot_counter}",
                        customer_id=cust.id if cust else None,
                        company=company,
                        customs_declaration=decl_num,
                        month=month,
                        year=year,
                        start_date=start_date,
                        end_date=end_date,
                        source_sheet=sn,
                        source_type='ghnlog' if is_ghnlog else 'gido',
                        status='pending'
                    )
                    db.session.add(current_lot)
                    db.session.flush()
                    total_lots += 1
                    lot_counter += 1
                else:
                    if current_lot:
                        if (cust_name or company) and not current_lot.customer_id:
                            norm_c = cust_name.lower() if cust_name else ''
                            resolved_cust = company if (company and ('anh ' in norm_c or 'chi ' in norm_c or not cust_name)) else (cust_name or company or "Khách vãng lai")
                            cust = get_or_create_customer(resolved_cust)
                            current_lot.customer_id = cust.id
                        if decl_num and not current_lot.customs_declaration:
                            current_lot.customs_declaration = decl_num
                        if company and not current_lot.company:
                            current_lot.company = company
                        if start_date and not current_lot.start_date:
                            current_lot.start_date = start_date
                        if end_date and not current_lot.end_date:
                            current_lot.end_date = end_date
                            
                # Create RevenueItem
                if current_lot and has_activity:
                    item = RevenueItem(
                        lot_id=current_lot.id,
                        supplier=clean_str(get_col_val(r, 'nha xe', 'ncc', 'doi tac')),
                        vehicle_plate_cn=clean_str(get_col_val(r, 'xe tq')),
                        vehicle_plate_vn=clean_str(get_col_val(r, 'xe vn', 'bien so xe', 'bien so')),
                        weight_class=clean_str(get_col_val(r, 'hang xe', 'loai xe', 'trong tai')),
                        service_description=service_desc,
                        quantity=clean_float(get_col_val(r, 'so luong', 'so xe')) or 1.0,
                        buy_price=buy_p,
                        buy_price_loading=buy_loading,
                        sell_price=sell_p,
                        overtime_count=overtime_count,
                        overtime_fee=overtime_f,
                        customs_inspection=customs_insp,
                        infrastructure_fee=infra_f,
                        ticket_fee=ticket_f,
                        new_machine_surcharge=new_mach,
                        oversize_surcharge=oversize_f,
                        loading_fee=loading_f,
                        penalty_fee=penalty_f,
                        tan_thanh_fee=tan_thanh_f,
                        thuan_thanh_fee=thuan_thanh_f,
                        return_dossier_fee=return_doss_f,
                        storage_fee=storage_f,
                        penalty_dossier_fee=penalty_doss_f,
                        penalty_payment=penalty_pay_f,
                        route=route_val,
                        inspection_point=insp_pt,
                        inspection_fee=insp_fee,
                        routing_fee=rout_fee,
                        empty_container=empty_cont,
                        total_buy_price_excel=val_tm,
                        total_sell_price_excel=val_tb
                    )
                    db.session.add(item)
                    total_items += 1
                    
        db.session.flush()
        return total_lots, total_items

    @staticmethod
    def parse_operating_costs(file_path):
        wb = openpyxl.load_workbook(file_path, data_only=True)
        total_costs = 0
        
        for sn in wb.sheetnames:
            sn_norm = normalize_text(sn)
            if any(k in sn_norm for k in ['ncc', 'tong hop', 'sheet']):
                continue
                
            month, year = parse_month_year(sn)
            if not month or not year:
                continue
                
            ws = wb[sn]
            
            # ==========================================
            # SPECIAL LAYOUT: Sheet 11.2025
            # Requirement: Col C=Nội dung/Loại CP, Col E=NCC, Col G=Số tiền trước VAT
            # ==========================================
            if '11.2025' in sn:
                header_row = -1
                for r in range(1, 15):
                    val = normalize_text(ws.cell(r, 1).value)
                    if 'stt' in val:
                        header_row = r
                        break
                if header_row == -1:
                    continue
                    
                for r in range(header_row + 1, ws.max_row + 1):
                    stt_val = clean_str(ws.cell(r, 1).value)
                    desc_val = clean_str(ws.cell(r, 3).value)   # Col C
                    supp_val = clean_str(ws.cell(r, 5).value)   # Col E
                    amt_val = clean_float(ws.cell(r, 7).value)  # Col G
                    inv_num = clean_str(ws.cell(r, 8).value)   # Col H
                    doc_val = clean_str(ws.cell(r, 9).value)   # Col I
                    pic_val = clean_str(ws.cell(r, 10).value)  # Col J
                    
                    row_vals = [stt_val, desc_val, supp_val, str(amt_val)]
                    if is_summary_or_footer_row(row_vals):
                        break
                        
                    if amt_val <= 0 and not desc_val:
                        continue
                    if amt_val <= 0:
                        continue
                        
                    sales_lots = Lot.query.filter(Lot.month == month, Lot.year == year, Lot.source_type != 'cpvh').all()
                    matched_lot = None
                    
                    if supp_val:
                        supp_matches = [l for l in sales_lots if l.customer and normalize_text(supp_val) in normalize_text(l.customer.name)]
                        if len(supp_matches) == 1:
                            matched_lot = supp_matches[0]
                            
                    if not matched_lot:
                        cust = get_or_create_customer(supp_val or "CPVH 11.2025")
                        matched_lot = Lot(
                            lot_label=f"Lô CP 11.{stt_val or r}",
                            customer_id=cust.id if cust else None,
                            month=month,
                            year=year,
                            source_sheet=sn,
                            source_type='cpvh',
                            status='pending'
                        )
                        db.session.add(matched_lot)
                        db.session.flush()
                        
                    cost = OperatingCost(
                        lot_id=matched_lot.id,
                        cost_type="Chi phí vận hành",
                        description=desc_val or "Chi phí tháng 11/2025",
                        total_amount=amt_val,
                        cost_amount=amt_val,
                        invoice_number=inv_num,
                        invoice_type="Hóa đơn" if inv_num and 'không' not in inv_num.lower() else "Không HĐ",
                        supplier_name=supp_val,
                        note=doc_val,
                        pic=pic_val,
                        payment_method="Tiền mặt"
                    )
                    db.session.add(cost)
                    total_costs += 1
                continue
                
            # ==========================================
            # STANDARD LAYOUT: T07, T08, T09...
            # ==========================================
            header_row = -1
            for r in range(1, 10):
                val = normalize_text(ws.cell(r, 1).value)
                if 'stt' in val:
                    header_row = r
                    break
            if header_row == -1:
                continue

            # Dynamic column mapping from header row
            col_map = {}
            for c in range(1, ws.max_column + 1):
                hdr = normalize_text(ws.cell(header_row, c).value)
                if not hdr:
                    continue
                if hdr == 'stt':
                    col_map['stt'] = c
                elif 'khach hang' in hdr or 'ten kh' in hdr:
                    col_map['khach_hang'] = c
                elif 'ma lo' in hdr or 'to khai' in hdr or 'so tkhq' in hdr:
                    col_map['to_khai'] = c
                elif 'loai chi phi' in hdr or 'loai cp' in hdr:
                    col_map['loai_cp'] = c
                elif 'noi dung' in hdr or 'dien giai' in hdr:
                    col_map['noi_dung'] = c
                elif 'bks' in hdr or 'bien so' in hdr:
                    col_map['bks'] = c
                elif 'sl xe' in hdr or 'so luong' in hdr:
                    col_map['sl_xe'] = c
                elif 'don gia' in hdr:
                    col_map['don_gia'] = c
                elif 'tong tien' in hdr:
                    col_map['tong_tien'] = c
                elif hdr == 'chi phi' or ('chi phi' in hdr and 'loai' not in hdr and 'ky' not in hdr and 'phat sinh' not in hdr):
                    col_map['chi_phi'] = c
                elif 'vat' in hdr or 'thue' in hdr:
                    col_map['vat'] = c
                elif 'loai hd' in hdr or ('loai' in hdr and 'phieu' in hdr):
                    col_map['loai_hd'] = c
                elif 'ky hieu' in hdr:
                    col_map['ky_hieu'] = c
                elif 'so hd' in hdr or ('so' in hdr and 'phieu' in hdr):
                    col_map['so_hd'] = c
                elif 'ngay' in hdr and ('chung tu' in hdr or 'ct' in hdr):
                    col_map['ngay_ct'] = c
                elif 'mst' in hdr or 'ma so thue' in hdr:
                    col_map['mst'] = c
                elif 'nha cung cap' in hdr or hdr == 'ncc':
                    col_map['ncc'] = c
                elif 'ghi chu' in hdr:
                    col_map['ghi_chu'] = c
                elif 'pic' in hdr:
                    col_map['pic'] = c
                elif 'unc' in hdr or 'tien mat' in hdr or 'phuong thuc' in hdr:
                    col_map['payment_method'] = c

            def get_cell_val(row_idx, col_key, clean_fn=clean_str):
                c_idx = col_map.get(col_key)
                if c_idx:
                    return clean_fn(ws.cell(row_idx, c_idx).value)
                return clean_fn(None)
                
            current_lot_match = None
            current_customer_name = ''
            current_decl = ''
            source_customer_name = ''
            source_decl = ''
            detail_sequence = 0
            
            for r in range(header_row + 1, ws.max_row + 1):
                stt_val = get_cell_val(r, 'stt')
                kh_val = get_cell_val(r, 'khach_hang')
                code_val = get_cell_val(r, 'to_khai')
                cost_type = get_cell_val(r, 'loai_cp')
                desc = get_cell_val(r, 'noi_dung')

                # Values can first appear on either a group header or a
                # detail row, and then apply to subsequent blanks.
                if kh_val:
                    current_customer_name = kh_val
                    source_customer_name = kh_val
                if code_val:
                    current_decl = code_val
                    source_decl = code_val
                
                # Check footer / summary rows
                row_vals = [stt_val, kh_val, code_val, cost_type, desc]
                if is_summary_or_footer_row(row_vals):
                    continue
                    
                plate = get_cell_val(r, 'bks')
                veh_count = get_cell_val(r, 'sl_xe', clean_float) or 1.0
                unit_p = get_cell_val(r, 'don_gia', clean_float)
                total_amt = get_cell_val(r, 'tong_tien', clean_float)
                cost_amt = get_cell_val(r, 'chi_phi', clean_float)
                vat_amt = get_cell_val(r, 'vat', clean_float)
                
                if total_amt == 0 and cost_amt > 0:
                    total_amt = cost_amt + (vat_amt or 0.0)
                elif total_amt == 0 and unit_p > 0:
                    total_amt = unit_p * veh_count
                    
                # GROUP HEADER DETECTION (Sheet T07, T08, T09):
                # If row has STT, cost_type is empty: this is a group header row
                is_group_header = bool(stt_val and (not cost_type or str(cost_type).strip() == ''))
                
                if stt_val and (stt_val.isdigit() or clean_float(stt_val) > 0 or is_group_header):
                    # Spreadsheet group headers commonly omit repeated
                    # customer/declaration cells. Carry forward the last
                    # non-empty source value, exactly as the source layout
                    # represents the block.
                    doc_date = get_cell_val(r, 'ngay_ct', clean_date)
                    
                    sales_lots = Lot.query.filter(Lot.month == month, Lot.year == year, Lot.source_type != 'cpvh').all()
                    matched_lot = None
                    clean_decl = current_decl.strip() if current_decl else ''
                    
                    # 1. Exact match on customs declaration
                    if clean_decl:
                        exact_decl_matches = [l for l in sales_lots if l.customs_declaration and l.customs_declaration.strip() == clean_decl]
                        if len(exact_decl_matches) == 1:
                            matched_lot = exact_decl_matches[0]
                            
                    # 2. Unique partial match on declaration number
                    if not matched_lot and clean_decl and len(clean_decl) >= 5:
                        base_decl = clean_decl.split('/')[0].strip()
                        partial_matches = [l for l in sales_lots if l.customs_declaration and (base_decl in l.customs_declaration or l.customs_declaration in clean_decl)]
                        if len(partial_matches) == 1:
                            matched_lot = partial_matches[0]
                            
                    # 3. Match by Customer + Company if unique in month
                    if not matched_lot and current_customer_name:
                        norm_cust = normalize_text(current_customer_name)
                        cust_company_matches = [
                            l for l in sales_lots 
                            if (l.customer and norm_cust in normalize_text(l.customer.name)) and
                               (not l.company or normalize_text(l.company) in norm_cust or norm_cust in normalize_text(l.company))
                        ]
                        if len(cust_company_matches) == 1:
                            matched_lot = cust_company_matches[0]
                            
                    # 4. Match by Customer + date if unique
                    if not matched_lot and current_customer_name and doc_date:
                        norm_cust = normalize_text(current_customer_name)
                        date_matches = [
                            l for l in sales_lots 
                            if (l.customer and norm_cust in normalize_text(l.customer.name)) and
                               ((l.start_date and l.start_date <= doc_date <= (l.end_date or l.start_date)) or (l.start_date == doc_date))
                        ]
                        if len(date_matches) == 1:
                            matched_lot = date_matches[0]

                    # 4.5 Match by lot sequence number (STT in CPVH == Lot number in Sales report)
                    if not matched_lot and stt_val and (stt_val.isdigit() or clean_float(stt_val) > 0):
                        try:
                            stt_num = int(clean_float(stt_val))
                            stt_matches = [
                                l for l in sales_lots
                                if l.lot_label and (
                                    l.lot_label.strip().lower() == f"lô {stt_num}" or
                                    l.lot_label.strip().lower() == f"lô {stt_num:02d}" or
                                    l.lot_label.strip().lower() == f"lô 0{stt_num}"
                                )
                            ]
                            if len(stt_matches) == 1:
                                matched_lot = stt_matches[0]
                        except Exception:
                            pass
                            
                    current_lot_match = matched_lot
                    
                    # 5. If not matched, create/group into pending CPVH lot for that month
                    if not current_lot_match:
                        # If current_customer_name is missing, try to detect from block rows
                        if not current_customer_name:
                            for look_r in range(r, min(r + 35, ws.max_row + 1)):
                                if look_r > r and ws.cell(look_r, col_map.get('stt', 1)).value:
                                    break
                                desc_look = normalize_text(get_cell_val(look_r, 'noi_dung') or '')
                                if 'keep rise' in desc_look or 'keep' in desc_look:
                                    current_customer_name = 'Keep Rise'
                                    break
                                elif 'sunluxe' in desc_look:
                                    current_customer_name = 'Sunluxe'
                                    break
                        cust = get_or_create_customer(current_customer_name)
                        current_lot_match = Lot(
                            lot_label=f"Lô CP {stt_val}",
                            customer_id=cust.id if cust else None,
                            company=current_customer_name if current_customer_name and current_customer_name != "Khách vãng lai" else None,
                            customs_declaration=current_decl,
                            month=month,
                            year=year,
                            source_sheet=sn,
                            source_type='cpvh',
                            status='pending'
                        )
                        db.session.add(current_lot_match)
                        db.session.flush()
                        
                # If this is a group header row, SKIP adding it as an OperatingCost item
                if is_group_header:
                    continue
                    
                # A detail row is defined by its cost type, not by a positive
                # amount.  T09 has pre-filled zero-value lines whose actual
                # values may appear only later in the month; dropping them
                # breaks source-row traceability and reconciliation.
                if current_lot_match and cost_type:
                    inv_type = get_cell_val(r, 'loai_hd')
                    inv_symbol = get_cell_val(r, 'ky_hieu')
                    inv_number = get_cell_val(r, 'so_hd')
                    doc_date = get_cell_val(r, 'ngay_ct', clean_date)
                    tax_code = get_cell_val(r, 'mst')
                    supp_name = get_cell_val(r, 'ncc')
                    note = get_cell_val(r, 'ghi_chu')
                    pic = get_cell_val(r, 'pic')
                    pay_method = get_cell_val(r, 'payment_method') or 'Tiền mặt'
                    detail_sequence += 1
                    invoice_status = f"{inv_type} {inv_number}".strip() if inv_type or inv_number else 'Không HĐ'
                    source_payload = json.dumps({
                        'stt': detail_sequence,
                        'ngay_thang': doc_date.strftime('%d/%m/%Y') if doc_date else '',
                        'ma_chi_phi': cost_type or '',
                        'nha_cung_cap': supp_name or '',
                        'chi_tiet': desc or '',
                        'gia_chua_vat': cost_amt or 0.0,
                        'co_vat': vat_amt or 0.0,
                        'tong_tien': total_amt or 0.0,
                        'thanh_toan': 'Chuyển khoản' if 'hóa đơn' in (inv_type or '').lower() else 'Tiền mặt',
                        'cong_no': 0.0,
                        'da_thanh_toan': total_amt or 0.0,
                        'lo_hang': source_customer_name or '',
                        'ma_ho_so': source_decl or '',
                        'invoice_status': invoice_status,
                        'payment_status': 'Đã đối soát' if clean_str(ws.cell(r, 21).value) else 'Hoàn thành',
                        'ghi_chu': note or ''
                    }, ensure_ascii=False)
                    
                    op_cost = OperatingCost(
                        lot_id=current_lot_match.id,
                        cost_type=cost_type or "Chi phí vận hành",
                        description=desc or cost_type or 'Chi phí vận hành',
                        vehicle_plate=plate,
                        vehicle_count=veh_count,
                        unit_price=unit_p,
                        total_amount=total_amt,
                        cost_amount=cost_amt or total_amt,
                        vat_amount=vat_amt,
                        invoice_type=inv_type,
                        invoice_symbol=inv_symbol,
                        invoice_number=inv_number,
                        document_date=doc_date,
                        supplier_tax_code=tax_code,
                        supplier_name=supp_name,
                        note=note,
                        pic=pic,
                        payment_method=pay_method,
                        source_sheet=sn,
                        source_row=r,
                        source_payload=source_payload
                    )
                    db.session.add(op_cost)
                    total_costs += 1
                    
        db.session.flush()
        return total_costs
