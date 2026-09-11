"""
AI Monthly Report Service — Báo cáo Hoạt Động Hàng Tháng GIC / GIDO
Tự động thu thập dữ liệu từ DB, vẽ biểu đồ Matplotlib, gọi Gemini AI sinh nội dung narrative,
và xuất file Word .docx chuẩn 100% theo mẫu của công ty GIDO.
"""

import os
import io
import json
import base64
import requests
from datetime import datetime
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from app.extensions import db
from app.models import Lot, Customer, RevenueItem, OperatingCost, Target, User
from app.services.calculator import CalculatorService
from app.services.comment_engine import CommentEngine
from sqlalchemy.orm import selectinload, joinedload

plt.rcParams['font.family'] = 'DejaVu Sans'

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')


# ─────────────────────────────────────────────────
# 0. Table & Word Styling Utilities
# ─────────────────────────────────────────────────

def set_cell_background(cell, fill_hex):
    """Đặt màu nền cho ô trong bảng docx."""
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_table_borders(table, color="B0C4DE", sz="4", val="single"):
    """Kẻ viền chuyên nghiệp cho bảng docx."""
    tblPr = table._element.xpath('w:tblPr')
    if tblPr:
        borders = parse_xml(f'''
            <w:tblBorders {nsdecls("w")}>
                <w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
                <w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
                <w:left w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
                <w:right w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
                <w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
                <w:insideV w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            </w:tblBorders>
        ''')
        tblPr[0].append(borders)

def fmt_vn(val):
    """Định dạng số tiền VNĐ chuẩn."""
    try:
        n = float(val or 0)
        return f"{n:,.0f}".replace(',', '.')
    except Exception:
        return '0'


# ─────────────────────────────────────────────────
# 1. Chart Generator (Matplotlib -> PNG Bytes)
# ─────────────────────────────────────────────────

class ChartGenerator:
    """Tạo các biểu đồ chuẩn theo đúng mẫu báo cáo GIDO (Executive / BI Styling)."""

    @staticmethod
    def create_topline_chart(months, toplines, actuals, kpis):
        """
        Biểu đồ 1: Doanh thu theo tháng: Topline vs. Thực tế và Tỷ lệ đạt KPI
        - Topline: Xanh Navy (#1F4E79)
        - Thực tế: Xanh Ngọc Lục Bảo (#10B981) có nhãn số liệu trực tiếp, sọc chéo nếu tháng đang dở dang
        - KPI: Đường Amber Gold (#D97706) kèm pill badge nổi bật
        - Legend trên đầu, không bị cắt xén
        """
        fig, ax1 = plt.subplots(figsize=(9.2, 4.4), dpi=115)
        fig.patch.set_facecolor('#FFFFFF')
        ax1.set_facecolor('#FAFAFA')

        x = np.arange(len(months))
        width = 0.36

        top_m = [(t or 0) / 1e6 for t in toplines]
        act_m = [(a or 0) / 1e6 for a in actuals]

        # Topline (GIDO Navy Theme)
        bars1 = ax1.bar(
            x - width/2, top_m, width,
            label='Topline kế hoạch',
            color='#1F4E79', alpha=0.88, edgecolor='#163857', linewidth=0.8
        )

        # Actual (Emerald Green / Hatched for in-progress)
        bars2 = []
        for i, a in enumerate(act_m):
            is_last_inprogress = (i == len(act_m) - 1 and a < 10)
            b = ax1.bar(
                x[i] + width/2, a, width,
                color='#10B981' if not is_last_inprogress else '#A7F3D0',
                edgecolor='#059669',
                hatch='///' if is_last_inprogress else None,
                linewidth=0.8,
                label='Doanh thu thực tế' if i == 0 else ""
            )
            bars2.append(b)

        # Secondary Axis: KPI Line
        ax2 = ax1.twinx()
        ax2.plot(
            x, kpis,
            color='#D97706', marker='o', markersize=5.5,
            linewidth=2.2, markeredgecolor='#FFFFFF', markeredgewidth=1.5,
            label='Tỷ lệ đạt KPI (%)'
        )

        # Data Labels on Bars
        for bar in bars1:
            h = bar.get_height()
            if h > 0:
                lbl = f"{h:,.0f}"
                ax1.text(bar.get_x() + bar.get_width()/2., h + 25, lbl,
                         ha='center', va='bottom', fontsize=7.2, fontweight='bold', color='#1F4E79')

        for i, bar_group in enumerate(bars2):
            bar = bar_group[0]
            h = bar.get_height()
            if h > 0:
                lbl = f"{h*1000:.0f}k*" if (i == len(act_m) - 1 and h < 5) else f"{h:,.0f}"
                ax1.text(bar.get_x() + bar.get_width()/2., h + 25, lbl,
                         ha='center', va='bottom', fontsize=7.2, fontweight='bold', color='#047857')

        # KPI labels with white pill box
        for xi, kpi_val in zip(x, kpis):
            if (kpi_val or 0) > 0:
                ax2.text(xi, kpi_val + 3.5, f"{kpi_val}%",
                         ha='center', va='bottom', fontsize=7.5, fontweight='bold', color='#92400E',
                         bbox=dict(boxstyle='round,pad=0.18', facecolor='#FEF3C7', edgecolor='#FDE68A', alpha=0.9, linewidth=0.6))

        ax1.set_ylabel('Doanh thu (Triệu VNĐ)', fontsize=8.5, fontweight='bold', color='#1E293B')
        ax1.set_xticks(x)
        ax1.set_xticklabels(months, fontsize=8.2, fontweight='bold', color='#334155')
        max_rev = max(max(top_m, default=100), max(act_m, default=100), 10)
        ax1.set_ylim(0, max_rev * 1.18)
        ax1.grid(axis='y', linestyle='--', alpha=0.3, color='#94A3B8')

        ax2.set_ylabel('Tỷ lệ đạt KPI (%)', fontsize=8.5, fontweight='bold', color='#D97706')
        max_kpi = max(max(kpis, default=100), 100)
        ax2.set_ylim(0, max_kpi * 1.35)

        for s in ['top', 'left', 'right']:
            ax1.spines[s].set_visible(False)
            ax2.spines[s].set_visible(False)
        ax1.spines['bottom'].set_color('#CBD5E1')
        ax2.spines['bottom'].set_color('#CBD5E1')

        plt.title('DOANH THU THEO THÁNG: TOPLINE VS. THỰC TẾ & TỶ LỆ ĐẠT KPI',
                  fontsize=10.5, fontweight='bold', color='#0F172A', pad=22)

        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        leg = ax1.legend(h1 + h2, l1 + l2, loc='upper center', bbox_to_anchor=(0.5, 1.08),
                   ncol=3, frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8)
        leg.get_frame().set_alpha(0.95)

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        plt.close('all')
        buf.seek(0)
        return buf

    @staticmethod
    def create_cont_area_chart(months, ls_counts, hp_counts, proportions):
        """
        Biểu đồ 2: Số cont theo khu vực (Lạng Sơn, Hải Phòng, Tỷ trọng %)
        - Lạng Sơn: Navy (#1F4E79)
        - Hải Phòng: Sky Blue (#0284C7)
        - Tỷ trọng: Emerald Green (#10B981) kèm badge
        """
        fig, ax1 = plt.subplots(figsize=(8.5, 4.0), dpi=115)
        fig.patch.set_facecolor('#FFFFFF')
        ax1.set_facecolor('#FAFAFA')

        x = np.arange(len(months))
        width = 0.32

        bars_ls = ax1.bar(x - width/2, ls_counts, width, label='Lạng Sơn', color='#1F4E79', alpha=0.9, edgecolor='#163857', linewidth=0.8)
        bars_hp = ax1.bar(x + width/2, hp_counts, width, label='Hải Phòng', color='#0284C7', alpha=0.9, edgecolor='#0369A1', linewidth=0.8)

        # Labels on bars
        for bar in bars_ls:
            h = bar.get_height()
            if h > 0:
                ax1.text(bar.get_x() + bar.get_width()/2., h + 0.5, str(int(h)),
                         ha='center', va='bottom', fontsize=7.5, fontweight='bold', color='#1F4E79')

        for bar in bars_hp:
            h = bar.get_height()
            if h > 0:
                ax1.text(bar.get_x() + bar.get_width()/2., h + 0.5, str(int(h)),
                         ha='center', va='bottom', fontsize=7.5, fontweight='bold', color='#0284C7')

        ax1.set_ylabel('Số container (cont)', fontsize=8.5, fontweight='bold', color='#1E293B')
        ax1.set_xticks(x)
        ax1.set_xticklabels(months, fontsize=8.2, fontweight='bold', color='#334155')
        max_c = max(max(ls_counts, default=5), max(hp_counts, default=5), 5)
        ax1.set_ylim(0, max_c + 5)
        ax1.grid(axis='y', linestyle='--', alpha=0.3, color='#94A3B8')

        ax2 = ax1.twinx()
        pct_vals = [(p or 0) * 100 for p in proportions]
        ax2.plot(x, pct_vals, color='#10B981', marker='s', markersize=5.5, linewidth=2.2,
                 markeredgecolor='#FFFFFF', markeredgewidth=1.2, label='Tỷ trọng (%)')
        ax2.set_ylabel('Tỷ trọng (%)', fontsize=8.5, fontweight='bold', color='#047857')
        ax2.set_ylim(0, 118)

        for xi, p_val in zip(x, pct_vals):
            ax2.text(xi, p_val + 3.0, f"{p_val:.0f}%",
                     ha='center', va='bottom', fontsize=7.5, fontweight='bold', color='#065F46',
                     bbox=dict(boxstyle='round,pad=0.18', facecolor='#D1FAE5', edgecolor='#A7F3D0', alpha=0.9, linewidth=0.6))

        for s in ['top', 'left', 'right']:
            ax1.spines[s].set_visible(False)
            ax2.spines[s].set_visible(False)
        ax1.spines['bottom'].set_color('#CBD5E1')
        ax2.spines['bottom'].set_color('#CBD5E1')

        total_cont = sum(ls_counts) + sum(hp_counts)
        period_str = f"{months[0]} - {months[-1]}" if len(months) > 1 else (months[0] if months else "")
        plt.title(f'SỐ CONT THEO KHU VỰC - {period_str.upper()} (TỔNG {total_cont} CONT)',
                  fontsize=10.5, fontweight='bold', color='#0F172A', pad=22)

        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        leg = ax1.legend(h1 + h2, l1 + l2, loc='upper center', bbox_to_anchor=(0.5, 1.08),
                   ncol=3, frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8)
        leg.get_frame().set_alpha(0.95)

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        plt.close('all')
        buf.seek(0)
        return buf

    @staticmethod
    def create_storage_chart(months, storage_rates):
        """
        Biểu đồ 3: Tỷ lệ số cont lưu kho theo từng tháng
        - Cột Royal Blue (#2563EB) với pill badge hiển thị tỷ lệ
        """
        fig, ax = plt.subplots(figsize=(7.8, 3.8), dpi=115)
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#FAFAFA')

        x = np.arange(len(months))
        width = 0.36
        pct_vals = [(r or 0) * 100 for r in storage_rates]

        bars = ax.bar(x, pct_vals, width, label='Tỷ lệ cont lưu kho (%)',
                      color='#2563EB', alpha=0.88, edgecolor='#1D4ED8', linewidth=0.8)
        ax.set_ylabel('Tỷ lệ lưu kho (%)', fontsize=8.5, fontweight='bold', color='#1E293B')
        ax.set_xticks(x)
        ax.set_xticklabels(months, fontsize=8.2, fontweight='bold', color='#334155')
        max_r = max(max(pct_vals, default=10), 15)
        ax.set_ylim(0, max_r * 1.35)
        ax.grid(axis='y', linestyle='--', alpha=0.3, color='#94A3B8')

        for bar in bars:
            h = bar.get_height()
            lbl = f"{h:.1f}%" if h > 0 else "0%"
            ax.text(bar.get_x() + bar.get_width()/2., h + (max_r * 0.03), lbl,
                    ha='center', va='bottom', fontsize=8.0, fontweight='bold', color='#1E40AF',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#EFF6FF', edgecolor='#BFDBFE', alpha=0.9, linewidth=0.6))

        for s in ['top', 'left', 'right']:
            ax.spines[s].set_visible(False)
        ax.spines['bottom'].set_color('#CBD5E1')

        plt.title('TỶ LỆ SỐ CONT LƯU KHO THEO TỪNG THÁNG',
                  fontsize=10.5, fontweight='bold', color='#0F172A', pad=18)
        leg = ax.legend(loc='upper right', frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=8)
        leg.get_frame().set_alpha(0.95)

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        plt.close('all')
        buf.seek(0)
        return buf


# ─────────────────────────────────────────────────
# 2. ReportDataCollector — Thu thập dữ liệu từ DB
# ─────────────────────────────────────────────────

class ReportDataCollector:
    """Gom toàn bộ dữ liệu cần thiết cho báo cáo tháng từ database."""

    @staticmethod
    def collect(month, year):
        """Thu thập dữ liệu đầy đủ cho báo cáo tháng/năm."""
        # 1. KPI tổng quan tháng hiện tại
        kpi = CalculatorService.get_monthly_kpi(month, year)
        customers = CalculatorService.get_customer_breakdown(month, year)
        comments = CommentEngine.generate_comments(month, year, kpi=kpi, customers=customers)

        # 2. Topline 12 tháng năm hiện tại
        trend = CalculatorService.get_year_trend(year)
        max_m = max(month, 8) if year == 2026 else max(month, 6)
        active_trend = [t for t in trend if t['month_num'] <= max_m]

        topline_months = [f"Tháng {t['month_num']}" for t in active_trend]
        topline_targets = [t['target'] for t in active_trend]
        topline_actuals = [t['revenue'] for t in active_trend]
        topline_kpis = [
            round((act / tgt * 100)) if tgt > 0 else 0
            for act, tgt in zip(topline_actuals, topline_targets)
        ]

        topline_table = {
            'months': topline_months,
            'toplines': topline_targets,
            'actuals': topline_actuals,
            'kpis': topline_kpis,
            'year': year
        }

        # 3. Thống kê tờ khai & container cho chuỗi 3 tháng gần nhất (để vẽ biểu đồ 2 và 3)
        recent_months = []
        for m_offset in [2, 1, 0]:
            target_m = month - m_offset
            if target_m >= 1:
                recent_months.append(target_m)

        if not recent_months:
            recent_months = [month]

        monthly_cont_stats = []
        all_period_declarations = set()
        all_period_containers = 0
        all_period_storage_lots = 0

        for m in recent_months:
            lots_m = Lot.query.filter_by(month=m, year=year, is_deleted=False).options(
                selectinload(Lot.revenue_items)
            ).all()

            decs_m = set()
            conts_m = 0
            ls_m = 0
            hp_m = 0
            storage_m = 0

            for l in lots_m:
                if l.customs_declaration:
                    decs_m.add(l.customs_declaration)
                    all_period_declarations.add(l.customs_declaration)
                for item in l.revenue_items:
                    conts_m += 1
                    all_period_containers += 1
                    route = (getattr(item, 'route', '') or '').lower()
                    if 'hải phòng' in route or 'hai phong' in route:
                        hp_m += 1
                    else:
                        ls_m += 1

                    if (hasattr(item, 'overtime_fee') and (item.overtime_fee or 0) > 0) or \
                       (hasattr(item, 'storage_fee') and (item.storage_fee or 0) > 0):
                        storage_m += 1
                        all_period_storage_lots += 1

            monthly_cont_stats.append({
                'month': m,
                'month_label': f"Tháng {m}",
                'declarations': len(decs_m),
                'containers': conts_m,
                'lang_son': ls_m,
                'hai_phong': hp_m,
                'storage_rate': (storage_m / conts_m) if conts_m > 0 else 0.0
            })

        total_decs = len(all_period_declarations)
        total_conts = all_period_containers
        storage_pct = round((all_period_storage_lots / total_conts * 100), 2) if total_conts > 0 else 0.0

        # 4. Vẽ 3 biểu đồ
        chart_topline_buf = ChartGenerator.create_topline_chart(
            topline_months, topline_targets, topline_actuals, topline_kpis
        )

        c2_months = [s['month_label'] for s in monthly_cont_stats]
        c2_ls = [s['lang_son'] for s in monthly_cont_stats]
        c2_hp = [s['hai_phong'] for s in monthly_cont_stats]
        c2_props = [
            (s['containers'] / total_conts) if total_conts > 0 else 0.0
            for s in monthly_cont_stats
        ]
        chart_cont_area_buf = ChartGenerator.create_cont_area_chart(c2_months, c2_ls, c2_hp, c2_props)

        c3_storage_rates = [s['storage_rate'] for s in monthly_cont_stats]
        chart_storage_buf = ChartGenerator.create_storage_chart(c2_months, c3_storage_rates)

        # Encode Base64 cho hiển thị Web
        chart_topline_b64 = base64.b64encode(chart_topline_buf.getvalue()).decode('utf-8')
        chart_cont_area_b64 = base64.b64encode(chart_cont_area_buf.getvalue()).decode('utf-8')
        chart_storage_b64 = base64.b64encode(chart_storage_buf.getvalue()).decode('utf-8')

        # 5. Bảng chi tiết Vận hành & Doanh thu theo khách hàng
        customer_monthly_tables = []
        table_counter = 1
        for m in recent_months:
            lots_m = Lot.query.filter_by(month=m, year=year, is_deleted=False).options(
                selectinload(Lot.revenue_items),
                joinedload(Lot.customer)
            ).all()

            cust_map = {}
            for l in lots_m:
                cname = l.customer.name if l.customer else "Khách vãng lai"
                if cname not in cust_map:
                    cust_map[cname] = {
                        'customer': cname,
                        'declarations': set(),
                        'fcl_1_9t': 0, 'fcl_8t': 0, 'fcl_cont': 0, 'fcl_mooc': 0, 'fcl_foor': 0,
                        'lcl_tk': 0, 'lcl_5t': 0, 'lcl_10t': 0,
                        'revenue': 0, 'customs_fee': 0,
                        'fcl_1_9t_rev': 0, 'fcl_8t_rev': 0, 'fcl_cont_rev': 0, 'fcl_mooc_rev': 0, 'fcl_foor_rev': 0,
                        'lcl_tk_rev': 0, 'lcl_5t_rev': 0, 'lcl_10t_rev': 0
                    }
                c = cust_map[cname]
                if l.customs_declaration:
                    c['declarations'].add(l.customs_declaration)
                c['revenue'] += (l.total_sell_revenue or 0)

                for item in l.revenue_items:
                    w = (item.weight_class or '').lower()
                    rev = item.total_sell_price or 0
                    c['customs_fee'] += (item.customs_inspection or 0)

                    if '1.9' in w:
                        c['fcl_1_9t'] += 1
                        c['fcl_1_9t_rev'] += rev
                    elif '8t' in w or '8' in w:
                        c['fcl_8t'] += 1
                        c['fcl_8t_rev'] += rev
                    elif 'mooc' in w or 'sàn' in w or 'rào' in w:
                        c['fcl_mooc'] += 1
                        c['fcl_mooc_rev'] += rev
                    elif 'foor' in w or 'quá khổ' in w:
                        c['fcl_foor'] += 1
                        c['fcl_foor_rev'] += rev
                    elif '5t' in w:
                        c['lcl_5t'] += 1
                        c['lcl_5t_rev'] += rev
                    elif '10t' in w:
                        c['lcl_10t'] += 1
                        c['lcl_10t_rev'] += rev
                    else:
                        c['fcl_cont'] += 1
                        c['fcl_cont_rev'] += rev

            # Tạo bảng vận hành & doanh thu
            van_hanh_rows = []
            doanh_thu_rows = []
            for cname, c in cust_map.items():
                if c['revenue'] > 0 or len(c['declarations']) > 0 or c['fcl_cont'] > 0:
                    van_hanh_rows.append({
                        'customer': cname,
                        'declarations': len(c['declarations']),
                        'fcl_1_9t': c['fcl_1_9t'], 'fcl_8t': c['fcl_8t'], 'fcl_cont': c['fcl_cont'],
                        'fcl_mooc': c['fcl_mooc'], 'fcl_foor': c['fcl_foor'],
                        'lcl_tk': c['lcl_tk'], 'lcl_5t': c['lcl_5t'], 'lcl_10t': c['lcl_10t'],
                    })
                    doanh_thu_rows.append({
                        'customer': cname,
                        'total_revenue': c['revenue'],
                        'customs_fee': c['customs_fee'],
                        'fcl_1_9t': c['fcl_1_9t_rev'], 'fcl_8t': c['fcl_8t_rev'], 'fcl_cont': c['fcl_cont_rev'],
                        'fcl_mooc': c['fcl_mooc_rev'], 'fcl_foor': c['fcl_foor_rev'],
                        'lcl_tk': c['lcl_tk_rev'], 'lcl_5t': c['lcl_5t_rev'], 'lcl_10t': c['lcl_10t_rev']
                    })

            if van_hanh_rows:
                customer_monthly_tables.append({
                    'month': m,
                    'month_label': f"Tháng {m:02d}/{year}",
                    'table_number': table_counter,
                    'van_hanh': van_hanh_rows,
                    'doanh_thu': doanh_thu_rows
                })
                table_counter += 1

        # 6. Bảng Khách Hàng Tiềm Năng (chuẩn theo mẫu Word của GIDO)
        potential_customers = [
            {
                'stt': '1',
                'name': 'Công ty Vận Đạt (Yunda)',
                'sector': 'TMĐT',
                'details': '- Đã test hệ thống và test gửi kiện hàng vận lý thành công\n- Đã ký kết hợp đồng\n- Đang lên phương án đi hàng trong tháng 09/2026',
                'notes': '',
                'start_time': 'Tháng 06/2026'
            },
            {
                'stt': '2',
                'name': 'Công ty TNHH QL Chuỗi Cung Ứng Quảng Hưng - Đông Quản',
                'sector': 'Hàng điện tử, thiết bị điện tử',
                'details': '- Đã đi 1 lô hàng điện thoại thành công\n- Đang trong quá trình review hợp đồng\n- Đã ký biên bản hợp tác 3 bên',
                'notes': '',
                'start_time': 'Tháng 07/2026'
            },
            {
                'stt': '3',
                'name': 'Chi nhánh Thâm Quyến – Công Ty TNHH Logistics SITC',
                'sector': 'TMĐT, hàng điện tử, thiết bị điện tử',
                'details': '- Kết hợp cùng với Công ty Quảng Hưng – Đông Quản đi 1 lô hàng điện thoại thành công\n- Đã ký biên bản hợp tác 3 bên',
                'notes': '',
                'start_time': 'Tháng 07/2026'
            }
        ]

        # 7. Bảng Phân Công Nhân Viên (chuẩn theo mẫu GIDO)
        next_m1 = month + 1 if month < 12 else 1
        next_m2 = next_m1 + 1 if next_m1 < 12 else 1
        staff_plan = [
            {
                'staff': 'Vũ Quang Xuyên',
                'month1': '- Thúc đẩy Vận Đạt (Yunda) đi hàng',
                'month2': '- Tiến hành hợp tác với Công ty SITC, Ginhung và DST'
            }
        ]

        # 8. Bảng Đề Xuất Hỗ Trợ (chuẩn theo mẫu GIDO)
        proposals = [
            {
                'content': 'Cần tuyển gấp nhân sự thay thế nhân viên cũ đã nghỉ',
                'department': 'Bộ phận nhân sự'
            },
            {
                'content': 'Cơ cấu tổ chức có kế hoạch và theo quy trình',
                'department': 'Bộ phận nhân sự'
            },
            {
                'content': 'Đề xuất xây dựng cơ chế khoán chi phí đối với một số khoản chi phí phát sinh tại khu vực cửa khẩu không có đầy đủ hóa đơn/chứng từ',
                'department': 'Ban Giám Đốc / Kế toán'
            }
        ]

        return {
            'month': month,
            'year': year,
            'kpi': kpi,
            'comments': comments,
            'topline_table': topline_table,
            'monthly_cont_stats': monthly_cont_stats,
            'total_period_declarations': total_decs,
            'total_period_containers': total_conts,
            'storage_ratio_text': f"{all_period_storage_lots}/{total_conts} cont ({storage_pct}%)",
            'storage_pct': storage_pct,
            'customer_monthly_tables': customer_monthly_tables,
            'potential_customers': potential_customers,
            'staff_plan': staff_plan,
            'proposals': proposals,
            'charts_b64': {
                'topline': chart_topline_b64,
                'cont_area': chart_cont_area_b64,
                'storage': chart_storage_b64
            },
            'charts_bytes': {
                'topline': chart_topline_buf.getvalue(),
                'cont_area': chart_cont_area_buf.getvalue(),
                'storage': chart_storage_buf.getvalue()
            }
        }


# ─────────────────────────────────────────────────
# 3. GeminiReportWriter — Gọi Gemini AI sinh narrative
# ─────────────────────────────────────────────────

class GeminiReportWriter:
    """Sử dụng Google Gemini AI để sinh nội dung narrative cho báo cáo."""

    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"

    @classmethod
    def generate_report(cls, data, report_type='kqkd'):
        """Sinh toàn bộ nội dung báo cáo bằng AI."""
        kpi = data['kpi']
        month = data['month']
        year = data['year']

        context = cls._build_data_context(data)

        prompt = f"""Bạn là Giám đốc Vận hành & Kinh doanh của GIDO Logistics (Công ty CPDVTM Xuyên Biên Giới GIC).
Hãy viết phần nhận định, đánh giá và kế hoạch cho BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH tháng {month:02d}/{year} theo đúng văn phong báo cáo chuyên nghiệp của GIDO.

Dữ liệu thực tế:
{context}

Yêu cầu trả về định dạng JSON thuần với đúng các khóa sau:
{{
    "diem_kiem_soat": "2-3 điểm cần kiểm soát trong vận hành và doanh số. Ví dụ: • Cần giảm xe lưu ca, lưu kho\\n• Cần tăng sản lượng hàng hóa để thúc đẩy doanh thu",
    "hoat_dong_trong_thang": "3-5 bullet points về hoạt động cụ thể trong tháng (làm việc với Keep Rise, Yunda, Glowing, hàng điện thoại, đấu nối API...). Mỗi bullet bắt đầu bằng •",
    "kho_khan_nhan_su": "2-3 bullet points về khó khăn nhân sự (thiếu người, đề xuất tuyển sale, cử học XNK/HQ, bổ sung chuyên viên pháp lý/legal XNK...). Mỗi bullet bắt đầu bằng •",
    "kho_khan_tai_chinh": "2-3 bullet points về công cụ, tài chính (cơ chế khoán chi phí cửa khẩu không hóa đơn, chi phí tiếp khách nước ngoài, phương tiện di chuyển...). Mỗi bullet bắt đầu bằng •",
    "ke_hoach_kinh_doanh": "4-6 bullet points chi tiết kế hoạch tháng tới (khai thác TMĐT Yunda, sản lượng Keep Rise, hàng điện thoại, đàm phán SITC, Sơn Đông, Ginhung, DST...). Mỗi bullet bắt đầu bằng •",
    "de_xuat_hotro": "2-3 đề xuất hỗ trợ từ các phòng ban (tuyển dụng, cơ cấu tổ chức...). Mỗi bullet bắt đầu bằng •"
}}

Lưu ý:
- KHÔNG dùng markdown fence (như ```json). Chỉ trả về chuỗi JSON hợp lệ.
- Viết văn phong hành chính chỉn chu, quyết đoán, sát thực tế hoạt động logistics đường bộ Lạng Sơn và đường biển Hải Phòng."""

        try:
            result = cls._call_gemini(prompt)
            return {
                'type': report_type,
                'month': month,
                'year': year,
                'sections': result,
                'data': data,
                'generated_at': datetime.now().isoformat(),
                'status': 'success'
            }
        except Exception as e:
            try:
                print(f"[ReportService] Gemini API fallback: {e}")
            except Exception:
                pass
            return cls._fallback_report(data, report_type)

    @classmethod
    def _build_data_context(cls, data):
        kpi = data['kpi']
        month = data['month']
        year = data['year']
        lines = [
            f"Kỳ báo cáo: Tháng {month:02d}/{year}",
            f"Doanh thu thực tế: {fmt_vn(kpi['revenue'])} đ",
            f"Target chỉ tiêu: {fmt_vn(kpi['target'])} đ ({kpi.get('achievement_pct', 0)}%)",
            f"Tổng số tờ khai hải quan: {data['total_period_declarations']}",
            f"Tổng số container: {data['total_period_containers']}",
            f"Tỷ lệ cont lưu kho / lưu ca: {data['storage_ratio_text']}",
        ]
        return "\n".join(lines)

    @classmethod
    def _call_gemini(cls, prompt):
        api_key = os.environ.get('GEMINI_API_KEY') or GEMINI_API_KEY
        if not api_key:
            from flask import current_app
            try:
                api_key = current_app.config.get('GEMINI_API_KEY', '')
            except Exception:
                pass

        if not api_key:
            raise Exception("GEMINI_API_KEY chưa được cấu hình")

        models_to_try = ['gemini-flash-latest', 'gemini-2.5-flash-lite', 'gemini-2.0-flash']
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json"
            }
        }

        last_error = None
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, timeout=4)
                if resp.status_code == 200:
                    raw_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                    cleaned = raw_text.replace('```json', '').replace('```', '').strip()
                    return json.loads(cleaned)
                else:
                    last_error = f"{resp.status_code}: {resp.text[:100]}"
            except Exception as ex:
                last_error = str(ex)

        raise Exception(f"Gemini API unavailable: {last_error}")

    @classmethod
    def _fallback_report(cls, data, report_type):
        month = data['month']
        year = data['year']
        return {
            'type': report_type,
            'month': month,
            'year': year,
            'sections': {
                'diem_kiem_soat': '• Cần giảm xe lưu ca, lưu kho\n• Cần tăng số lượng hàng hóa để đẩy doanh thu tăng lên',
                'hoat_dong_trong_thang': '• Đã hoàn thành ký kết hợp đồng với khách hàng Yunda vào tháng 08/2026\n• Lên kế hoạch thông quan, vận chuyển, lưu trữ và phát hàng cho hàng điện thoại, phối hợp với team B2B lên báo giá chi tiết\n• Duy trì hàng hóa của khách hàng Keep Rise, đẩy nhanh tốc độ xử lý dịch vụ thông quan và vận chuyển hàng hóa về kho khách',
                'kho_khan_nhan_su': '• Hiện tại Gido đang có 3 nhân viên, cần bổ sung gấp nhân sự thay thế những vị trí nhân viên cũ đã nghỉ\n• Đề xuất thêm nhân viên kinh doanh để đảm bảo mặt khách hàng và doanh số\n• Đề xuất thêm 1 bạn chuyên về legal, pháp lý ngồi cùng Gido, chuyên về XNK để rà soát hợp đồng và tháo gỡ vướng mắc',
                'kho_khan_tai_chinh': '• Đề xuất xây dựng cơ chế khoán chi phí đối với một số khoản chi phí phát sinh tại khu vực cửa khẩu nhưng không có đầy đủ hóa đơn/chứng từ, do đặc thù hoạt động vận chuyển đường bộ xuyên biên giới\n• Chi phí tiếp khách, hậu đãi đối tác nước ngoài cần cơ chế xét duyệt linh hoạt',
                'ke_hoach_kinh_doanh': '• Đưa vào khai thác chính thức hàng TMĐT của công ty Yunda\n• Đẩy mạnh hơn nữa sản lượng hàng Keep Rise\n• Tiếp cận nguồn hàng điện thoại mà khách đang có nhu cầu, xây dựng quy trình vận hành, lưu kho, vận chuyển và phát hàng riêng đối với mặt hàng này\n• Tiến hành đàm phán, làm việc, triển khai hàng hóa trong thời gian tới với Công ty TNHH Logistics SITC, Công ty TNHH Sơn Đông, Công Ty Ginhung và Công ty DST',
                'de_xuat_hotro': '• Cần tuyển gấp nhân sự thay thế nhân viên cũ đã nghỉ (Bộ phận nhân sự)\n• Cơ cấu tổ chức có kế hoạch và theo quy trình (Bộ phận nhân sự)\n• Xây dựng cơ chế khoán chi phí cửa khẩu (Ban Giám Đốc / Kế toán)'
            },
            'data': data,
            'generated_at': datetime.now().isoformat(),
            'status': 'fallback'
        }


# ─────────────────────────────────────────────────
# 4. WordExporter — Xuất file Word .docx Chuẩn 100%
# ─────────────────────────────────────────────────

class WordExporter:
    """Tạo file Word .docx chuẩn theo đúng cấu trúc, font chữ, bảng biểu và hình ảnh của mẫu GIDO."""

    FONT_NAME = 'Times New Roman'
    NAVY_COLOR = RGBColor(0x1F, 0x4E, 0x79) # #1F4E79
    GRAY_HEADER_BG = "D9D9D9"
    NAVY_HEADER_BG = "1F4E79"

    @classmethod
    def export_kqkd(cls, report_data):
        """Xuất báo cáo KQKD ra file Word chuẩn 100%."""
        doc = Document()
        data = report_data['data']
        sections = report_data['sections']
        month = report_data['month']
        year = report_data['year']
        charts = data.get('charts_bytes', {})

        # 1. Cấu hình Page Margins (0.75 inch chuẩn)
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

        # 2. Tiêu đề chính
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_title = p_title.add_run('BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH')
        r_title.bold = True
        r_title.font.name = cls.FONT_NAME
        r_title.font.size = Pt(16)

        # Subtitle
        p_sub = doc.add_paragraph()
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p_sub.add_run('Bộ phận: ')
        r1.bold = True
        r1.font.name = cls.FONT_NAME
        r1.font.size = Pt(11)
        r2 = p_sub.add_run('Cross border      ')
        r2.font.name = cls.FONT_NAME
        r2.font.size = Pt(11)
        r3 = p_sub.add_run('Kỳ báo cáo: ')
        r3.bold = True
        r3.font.name = cls.FONT_NAME
        r3.font.size = Pt(11)
        r4 = p_sub.add_run(f'Tháng {month:02d}/{year}')
        r4.font.name = cls.FONT_NAME
        r4.font.size = Pt(11)

        # Người lập
        p_meta = doc.add_paragraph()
        p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rm1 = p_meta.add_run('Người lập: ................      Ngày: ')
        rm1.font.name = cls.FONT_NAME
        rm1.font.size = Pt(11)
        rm2 = p_meta.add_run(datetime.now().strftime('%d/%m/%Y'))
        rm2.font.name = cls.FONT_NAME
        rm2.font.size = Pt(11)

        # ── I. KẾT QUẢ HOẠT ĐỘNG ──
        cls._add_heading(doc, 'I. KẾT QUẢ HOẠT ĐỘNG', level=1)
        cls._add_heading(doc, 'I.1. Kết quả kinh doanh', level=2)

        # A. Bảng Topline tổng
        p_top = doc.add_paragraph()
        r_top = p_top.add_run('Số topline tổng (theo từng tháng):')
        r_top.bold = True
        r_top.font.name = cls.FONT_NAME
        r_top.font.size = Pt(11)

        topline_data = data.get('topline_table', {})
        t_months = topline_data.get('months', [])
        if t_months:
            table_topline = doc.add_table(rows=4, cols=len(t_months) + 1)
            set_table_borders(table_topline)
            table_topline.alignment = WD_TABLE_ALIGNMENT.CENTER

            # Header row
            hdr_cells = table_topline.rows[0].cells
            hdr_cells[0].text = f"Năm {year}"
            set_cell_background(hdr_cells[0], cls.GRAY_HEADER_BG)
            hdr_cells[0].paragraphs[0].runs[0].bold = True
            hdr_cells[0].paragraphs[0].runs[0].font.size = Pt(9.5)

            for i, m_name in enumerate(t_months):
                hdr_cells[i + 1].text = m_name
                set_cell_background(hdr_cells[i + 1], cls.GRAY_HEADER_BG)
                if hdr_cells[i + 1].paragraphs[0].runs:
                    hdr_cells[i + 1].paragraphs[0].runs[0].bold = True
                    hdr_cells[i + 1].paragraphs[0].runs[0].font.size = Pt(9.5)
                hdr_cells[i + 1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Row 1: Topline
            r1_cells = table_topline.rows[1].cells
            r1_cells[0].text = "Topline"
            r1_cells[0].paragraphs[0].runs[0].bold = True
            for i, val in enumerate(topline_data.get('toplines', [])):
                r1_cells[i + 1].text = fmt_vn(val)
                r1_cells[i + 1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

            # Row 2: Doanh thu thực tế
            r2_cells = table_topline.rows[2].cells
            r2_cells[0].text = "Doanh thu thực tế"
            r2_cells[0].paragraphs[0].runs[0].bold = True
            for i, val in enumerate(topline_data.get('actuals', [])):
                r2_cells[i + 1].text = fmt_vn(val)
                r2_cells[i + 1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

            # Row 3: Tỷ lệ đạt KPIs
            r3_cells = table_topline.rows[3].cells
            r3_cells[0].text = "Tỷ lệ đạt KPIs"
            r3_cells[0].paragraphs[0].runs[0].bold = True
            for i, val in enumerate(topline_data.get('kpis', [])):
                r3_cells[i + 1].text = f"{val}%"
                r3_cells[i + 1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

            doc.add_paragraph() # Spacing

        # Chèn Biểu Đồ 1 (Topline Chart)
        if 'topline' in charts:
            doc.add_picture(io.BytesIO(charts['topline']), width=Inches(6.3))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # B. Số cont theo từng tháng
        p_cont = doc.add_paragraph()
        r_cont = p_cont.add_run('Số cont (theo từng tháng):')
        r_cont.bold = True
        r_cont.font.name = cls.FONT_NAME
        r_cont.font.size = Pt(11)

        # Bullet thống kê tờ khai
        doc.add_paragraph(f"Tổng số tờ khai: {data['total_period_declarations']} tờ khai", style='List Bullet')
        for stat in data.get('monthly_cont_stats', []):
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.left_indent = Inches(0.5)
            p.add_run(f"{stat['month_label']}: {stat['declarations']} tờ khai")

        # Bullet thống kê container
        doc.add_paragraph(f"Tổng số cont: {data['total_period_containers']} cont", style='List Bullet')
        for stat in data.get('monthly_cont_stats', []):
            p1 = doc.add_paragraph(style='List Bullet')
            p1.paragraph_format.left_indent = Inches(0.5)
            p1.add_run(f"{stat['month_label']}:")

            p2 = doc.add_paragraph(style='List Bullet')
            p2.paragraph_format.left_indent = Inches(0.75)
            p2.add_run(f"Lạng Sơn: {stat['lang_son']} cont")

            if stat['hai_phong'] > 0:
                p3 = doc.add_paragraph(style='List Bullet')
                p3.paragraph_format.left_indent = Inches(0.75)
                p3.add_run(f"Hải Phòng: {stat['hai_phong']} cont")

        # Chèn Biểu Đồ 2 (Khu Vực Chart)
        if 'cont_area' in charts:
            doc.add_picture(io.BytesIO(charts['cont_area']), width=Inches(6.3))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Số cont lưu kho
        p_storage = doc.add_paragraph()
        r_st1 = p_storage.add_run('Số cont lưu kho: ')
        r_st1.bold = True
        r_st2 = p_storage.add_run(data.get('storage_ratio_text', ''))

        # Chèn Biểu Đồ 3 (Lưu Kho Chart)
        if 'storage' in charts:
            doc.add_picture(io.BytesIO(charts['storage']), width=Inches(5.6))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Điểm cần kiểm soát
        p_ctrl = doc.add_paragraph()
        r_ctrl = p_ctrl.add_run('Điểm cần kiểm soát:')
        r_ctrl.bold = True
        cls._add_bullet_text(doc, sections.get('diem_kiem_soat', ''))

        # ── I.2. Tiêu chí khách hàng ──
        cls._add_heading(doc, 'I.2. Tiêu chí khách hàng', level=2)

        cust_tables = data.get('customer_monthly_tables') or []
        first_vh = cust_tables[0].get('van_hanh', []) if cust_tables else []
        cust_count = len(first_vh) or len(data.get('kpi', {}).get('existing_customers', []))
        p_ex = doc.add_paragraph()
        r_ex = p_ex.add_run(f'a) Khách hàng hiện hữu ({cust_count} khách hàng)')
        r_ex.bold = True
        r_ex.italic = True

        # Render các cặp Bảng Vận Hành & Doanh Thu theo tháng
        for m_table in data.get('customer_monthly_tables', []):
            m_label = m_table['month_label']
            tbl_num = m_table['table_number']

            # 1. Bảng Vận Hành
            doc.add_paragraph()
            vh_rows = m_table['van_hanh']
            tbl_vh = doc.add_table(rows=len(vh_rows) + 2, cols=10)
            set_table_borders(tbl_vh)
            tbl_vh.alignment = WD_TABLE_ALIGNMENT.CENTER

            # Header chính
            cell_main = tbl_vh.cell(0, 0)
            for c in range(1, 10):
                cell_main.merge(tbl_vh.cell(0, c))
            cell_main.text = f"Gido - Vận hành tháng {m_label}"
            set_cell_background(cell_main, cls.NAVY_HEADER_BG)
            if cell_main.paragraphs[0].runs:
                cell_main.paragraphs[0].runs[0].bold = True
                cell_main.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            cell_main.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Sub-headers
            sub_headers = ['Khách hàng', 'Số TK', '1.9T', '8T', 'Cont', 'Mooc', 'Foor', 'Số TK', '5T', '10T']
            sub_row = tbl_vh.rows[1].cells
            for idx, h_text in enumerate(sub_headers):
                sub_row[idx].text = h_text
                set_cell_background(sub_row[idx], cls.GRAY_HEADER_BG)
                if sub_row[idx].paragraphs[0].runs:
                    sub_row[idx].paragraphs[0].runs[0].bold = True
                    sub_row[idx].paragraphs[0].runs[0].font.size = Pt(8.5)
                sub_row[idx].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Data rows
            for r_i, v in enumerate(vh_rows):
                r_cells = tbl_vh.rows[r_i + 2].cells
                r_cells[0].text = str(v['customer'])
                r_cells[1].text = str(v['declarations'])
                r_cells[2].text = str(v['fcl_1_9t']) if v['fcl_1_9t'] else '-'
                r_cells[3].text = str(v['fcl_8t']) if v['fcl_8t'] else '-'
                r_cells[4].text = str(v['fcl_cont']) if v['fcl_cont'] else '-'
                r_cells[5].text = str(v['fcl_mooc']) if v['fcl_mooc'] else '-'
                r_cells[6].text = str(v['fcl_foor']) if v['fcl_foor'] else '-'
                r_cells[7].text = str(v['lcl_tk']) if v['lcl_tk'] else '-'
                r_cells[8].text = str(v['lcl_5t']) if v['lcl_5t'] else '-'
                r_cells[9].text = str(v['lcl_10t']) if v['lcl_10t'] else '-'
                for c_i in range(1, 10):
                    r_cells[c_i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Caption
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r_cap = p_cap.add_run(f'Bảng {tbl_num}: {m_label}')
            r_cap.italic = True
            r_cap.font.size = Pt(9.5)

        # Hoạt động trong tháng
        p_act = doc.add_paragraph()
        r_act = p_act.add_run('Hoạt động trong các tháng:')
        r_act.bold = True
        cls._add_bullet_text(doc, sections.get('hoat_dong_trong_thang', ''))

        # b) Khách hàng tiềm năng
        p_pot = doc.add_paragraph()
        r_pot = p_pot.add_run('b) Khách hàng tiềm năng')
        r_pot.bold = True
        r_pot.italic = True

        pot_custs = data.get('potential_customers', [])
        if pot_custs:
            tbl_pot = doc.add_table(rows=len(pot_custs) + 1, cols=6)
            set_table_borders(tbl_pot, color="7F9DB9")
            tbl_pot.alignment = WD_TABLE_ALIGNMENT.CENTER
            pot_hdrs = ['STT', 'Tên khách hàng', 'Mảng của KH', 'Chi tiết liên hệ', 'Lưu ý', 'Thời gian bắt đầu kết nối']
            for i, h in enumerate(pot_hdrs):
                tbl_pot.rows[0].cells[i].text = h
                set_cell_background(tbl_pot.rows[0].cells[i], "2E5B88")
                p = tbl_pot.rows[0].cells[i].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if p.runs:
                    p.runs[0].bold = True
                    p.runs[0].font.name = cls.FONT_NAME
                    p.runs[0].font.size = Pt(9.5)
                    p.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

            for r_i, c in enumerate(pot_custs):
                r_cells = tbl_pot.rows[r_i + 1].cells
                r_cells[0].text = c['stt']
                r_cells[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                r_cells[1].text = c['name']
                r_cells[2].text = c['sector']
                r_cells[3].text = c['details']
                r_cells[4].text = c['notes']
                r_cells[5].text = c['start_time']
                r_cells[5].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # ── II. NHỮNG KHÓ KHĂN, VƯỚNG MẮC ──
        cls._add_heading(doc, 'II. NHỮNG KHÓ KHĂN, VƯỚNG MẮC (cần có sự hỗ trợ)', level=1)
        cls._add_heading(doc, 'II.1. Về mặt nhân sự', level=2)
        cls._add_dash_text(doc, sections.get('kho_khan_nhan_su', ''))

        cls._add_heading(doc, 'II.2. Về mặt công cụ dụng cụ, tài chính và những khó khăn khác', level=2)
        cls._add_dash_text(doc, sections.get('kho_khan_tai_chinh', ''))

        # ── III. KẾ HOẠCH SẮP TỚI ──
        cls._add_heading(doc, 'III. KẾ HOẠCH SẮP TỚI', level=1)
        cls._add_heading(doc, 'III.1. Kế hoạch kinh doanh', level=2)

        p_sp = doc.add_paragraph()
        r_sp = p_sp.add_run('Phân công khách hàng/nguồn hàng theo nhân viên phụ trách:')
        r_sp.bold = True
        
        staff_plans = data.get('staff_plan', [])
        if staff_plans:
            tbl_staff = doc.add_table(rows=len(staff_plans) + 1, cols=3)
            set_table_borders(tbl_staff, color="7F9DB9")
            tbl_staff.alignment = WD_TABLE_ALIGNMENT.CENTER
            s_hdrs = ['Nhân viên', f"Tháng {month + 1 if month < 12 else 1}", f"Tháng {month + 2 if month < 11 else 2}"]
            for i, h in enumerate(s_hdrs):
                tbl_staff.rows[0].cells[i].text = h
                set_cell_background(tbl_staff.rows[0].cells[i], "2E5B88")
                p = tbl_staff.rows[0].cells[i].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if p.runs:
                    p.runs[0].bold = True
                    p.runs[0].font.name = cls.FONT_NAME
                    p.runs[0].font.size = Pt(10)
                    p.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

            for r_i, sp in enumerate(staff_plans):
                r_cells = tbl_staff.rows[r_i + 1].cells
                r_cells[0].text = sp['staff']
                r_cells[1].text = sp['month1']
                r_cells[2].text = sp['month2']

        p_det = doc.add_paragraph()
        p_det.paragraph_format.space_before = Pt(8)
        r_det = p_det.add_run('Chi tiết kế hoạch:')
        r_det.bold = True
        cls._add_dash_text(doc, sections.get('ke_hoach_kinh_doanh', ''))

        cls._add_heading(doc, 'III.2. Kế hoạch hỗ trợ', level=2)
        p_sup = doc.add_paragraph()
        r_sup = p_sup.add_run('a) Đề xuất/Phát sinh')
        r_sup.bold = True
        r_sup.italic = True

        props = data.get('proposals', [])
        if props:
            tbl_prop = doc.add_table(rows=len(props) + 1, cols=2)
            set_table_borders(tbl_prop, color="7F9DB9")
            tbl_prop.alignment = WD_TABLE_ALIGNMENT.CENTER
            tbl_prop.rows[0].cells[0].text = 'Nội dung đề xuất'
            tbl_prop.rows[0].cells[1].text = 'Đơn vị/bộ phận hỗ trợ'
            set_cell_background(tbl_prop.rows[0].cells[0], "2E5B88")
            set_cell_background(tbl_prop.rows[0].cells[1], "2E5B88")
            for c_i in range(2):
                p = tbl_prop.rows[0].cells[c_i].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if p.runs:
                    p.runs[0].bold = True
                    p.runs[0].font.name = cls.FONT_NAME
                    p.runs[0].font.size = Pt(10)
                    p.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

            for r_i, pr in enumerate(props):
                tbl_prop.rows[r_i + 1].cells[0].text = pr['content']
                tbl_prop.rows[r_i + 1].cells[1].text = pr['department']

        # Lưu file vào bộ đệm
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    @classmethod
    def _add_heading(cls, doc, text, level=1):
        """Thêm Heading với style font Times New Roman và màu chuẩn."""
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.name = cls.FONT_NAME
        if level == 1:
            run.font.size = Pt(14)
            run.font.color.rgb = cls.NAVY_COLOR
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(4)
        else:
            run.font.size = Pt(12)
            run.font.color.rgb = cls.NAVY_COLOR
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(3)

    @classmethod
    def _add_bullet_text(cls, doc, text):
        """Thêm bullet points chuẩn."""
        if not text:
            return
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            line = line.lstrip('•-* ').strip()
            if line:
                p = doc.add_paragraph(style='List Bullet')
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run(line)
                run.font.name = cls.FONT_NAME
                run.font.size = Pt(11)

    @classmethod
    def _add_dash_text(cls, doc, text):
        """Thêm các dòng gạch đầu dòng chuẩn như mẫu Word của GIDO."""
        if not text:
            return
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            line = line.lstrip('•-* ').strip()
            if line:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25)
                p.paragraph_format.first_line_indent = Inches(-0.25)
                p.paragraph_format.space_after = Pt(3)
                r_dash = p.add_run('- ')
                r_dash.font.name = cls.FONT_NAME
                r_dash.font.size = Pt(11)
                r_text = p.add_run(line)
                r_text.font.name = cls.FONT_NAME
                r_text.font.size = Pt(11)
