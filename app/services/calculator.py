from datetime import date
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from app.models import Lot, Target, Customer, RevenueItem, OperatingCost, CostEntryTask

class CalculatorService:
    _cached_months = None

    @classmethod
    def invalidate_cache(cls):
        """Xóa cache danh sách tháng để tải lại dữ liệu mới nhất sau import/reconciliation"""
        cls._cached_months = None

    @staticmethod
    def get_available_months():
        """Get all unique (year, month) pairs present in the database"""
        if CalculatorService._cached_months is not None:
            return CalculatorService._cached_months
        lots = Lot.query.filter_by(is_deleted=False).with_entities(Lot.year, Lot.month).distinct().order_by(Lot.year.desc(), Lot.month.desc()).all()
        CalculatorService._cached_months = [(l.year, l.month) for l in lots]
        return CalculatorService._cached_months

    @staticmethod
    def get_monthly_kpi(month, year):
        """
        Calculate total revenue, costs, profit, and target progress for given month & year.
        Đảm bảo đúng quy tắc tài chính:
        - Số lô = số Sales Lot active (không cộng nhóm CPVH chưa đối soát).
        - Doanh thu bán = tổng doanh thu của Sales Lot.
        - Giá mua = tổng giá mua của Sales Lot.
        - CPVH kỳ = tổng CPVH đã ghép của Sales Lot + tổng CPVH chưa đối soát hợp lệ (mỗi khoản tính đúng 1 lần).
        - Lợi nhuận kỳ = Doanh thu bán - Giá mua - Tổng CPVH kỳ.
        """
        sales_lots = Lot.sales_lots_query().filter_by(month=month, year=year).options(
            selectinload(Lot.revenue_items),
            selectinload(Lot.operating_costs)
        ).all()

        unresolved_lots = Lot.unresolved_cpvh_query().filter_by(month=month, year=year).options(
            selectinload(Lot.operating_costs)
        ).all()
        
        total_sell = sum(lot.total_sell_revenue for lot in sales_lots)
        total_buy = sum(lot.total_buy_cost for lot in sales_lots)
        
        sales_ops = sum(lot.total_operating_cost for lot in sales_lots)
        unresolved_ops = sum(lot.total_operating_cost for lot in unresolved_lots)
        total_ops = sales_ops + unresolved_ops
        
        gross_profit = total_sell - total_buy
        net_profit = total_sell - total_buy - total_ops
        margin = (net_profit / total_sell * 100) if total_sell > 0 else 0.0
        
        # Target logic
        target_obj = Target.query.filter_by(year=year, month=month).first()
        has_target = target_obj is not None and (target_obj.target_amount or 0) > 0
        target_val = target_obj.target_amount_vnd if has_target else 0.0
        achievement_pct = round((total_sell / target_val * 100), 1) if (has_target and target_val > 0) else None
        target_label = f"Target tháng {month:02d}/{year}"
        
        # Sales lot counts & Cost Status KPI
        lot_count = len(sales_lots)
        
        lots_none = sum(1 for lot in sales_lots if lot.cost_status == 'none')
        lots_partial = sum(1 for lot in sales_lots if lot.cost_status == 'partial')
        lots_completed = sum(1 for lot in sales_lots if lot.cost_status == 'completed')
        lots_with_cost = lots_partial + lots_completed
        
        cost_completion_pct = round((lots_completed / lot_count * 100), 1) if lot_count > 0 else 0.0
        
        # Previous month comparison
        prev_m = 12 if month == 1 else month - 1
        prev_y = year - 1 if month == 1 else year
        prev_sales = Lot.sales_lots_query().filter_by(month=prev_m, year=prev_y).options(
            selectinload(Lot.revenue_items),
            selectinload(Lot.operating_costs)
        ).all()
        prev_sell = sum(lot.total_sell_revenue for lot in prev_sales)
        prev_buy = sum(lot.total_buy_cost for lot in prev_sales)
        
        has_prev_data = prev_sell > 0
        rev_growth = round(((total_sell - prev_sell) / prev_sell * 100), 1) if has_prev_data else None
        cost_growth = round(((total_buy - prev_buy) / prev_buy * 100), 1) if prev_buy > 0 else None
        
        return {
            'month': month,
            'year': year,
            'revenue': total_sell,
            'buy_cost': total_buy,
            'operating_cost': total_ops,
            'sales_operating_cost': sales_ops,
            'unresolved_cost_amount': unresolved_ops,
            'unresolved_group_count': len(unresolved_lots),
            'total_cost': total_buy + total_ops,
            'gross_profit': gross_profit,
            'net_profit': net_profit,
            'profit_margin': round(margin, 1),
            'target': target_val,
            'has_target': has_target,
            'target_label': target_label,
            'achievement_pct': achievement_pct,
            'lot_count': lot_count,
            'lots_none': lots_none,
            'lots_partial': lots_partial,
            'lots_completed': lots_completed,
            'lots_with_cost': lots_with_cost,
            'cost_completion_pct': cost_completion_pct,
            'has_prev_data': has_prev_data,
            'rev_growth': rev_growth,
            'cost_growth': cost_growth,
            'prev_revenue': prev_sell
        }

    @staticmethod
    def get_year_trend(year):
        """
        Get 12-month series of revenue, costs, and target for charts.
        """
        sales_year_lots = Lot.sales_lots_query().filter_by(year=year).options(
            selectinload(Lot.revenue_items),
            selectinload(Lot.operating_costs)
        ).all()
        unresolved_year_lots = Lot.unresolved_cpvh_query().filter_by(year=year).options(
            selectinload(Lot.operating_costs)
        ).all()
        
        targets = Target.query.filter_by(year=year).all()
        target_map = {t.month: t.target_amount_vnd for t in targets if t.target_amount}
        
        months_data = []
        for m in range(1, 13):
            s_lots = [l for l in sales_year_lots if l.month == m]
            u_lots = [l for l in unresolved_year_lots if l.month == m]
            sell = sum(lot.total_sell_revenue for lot in s_lots)
            buy = sum(lot.total_buy_cost for lot in s_lots)
            ops = sum(lot.total_operating_cost for lot in s_lots) + sum(lot.total_operating_cost for lot in u_lots)
            target_val = target_map.get(m, 0.0)
            
            months_data.append({
                'month': f"T{m}",
                'month_num': m,
                'revenue': sell,
                'buy_cost': buy,
                'operating_cost': ops,
                'total_cost': buy + ops,
                'profit': sell - buy - ops,
                'target': target_val
            })
        return months_data

    @staticmethod
    def get_customer_breakdown(month, year):
        """
        Get revenue and lot share grouped by customer.
        Returns Top 5 customers + 'Khác', summing to exactly 100%.
        Chỉ lấy từ Sales Lot thực tế.
        """
        lots = Lot.sales_lots_query().filter_by(month=month, year=year).options(
            joinedload(Lot.customer),
            selectinload(Lot.revenue_items)
        ).all()
        cust_map = {}
        total_rev = 0
        
        for lot in lots:
            cname = lot.customer.name if lot.customer else "Khách vãng lai"
            rev = lot.total_sell_revenue
            total_rev += rev
            if cname not in cust_map:
                cust_map[cname] = {'name': cname, 'revenue': 0, 'lot_count': 0}
            cust_map[cname]['revenue'] += rev
            cust_map[cname]['lot_count'] += 1
            
        customers = list(cust_map.values())
        customers.sort(key=lambda x: x['revenue'], reverse=True)
        
        if not customers or total_rev <= 0:
            return []
            
        if len(customers) <= 5:
            for c in customers:
                c['share'] = round((c['revenue'] / total_rev * 100), 1)
            return customers
            
        top_5 = customers[:5]
        other_rev = sum(c['revenue'] for c in customers[5:])
        other_lots = sum(c['lot_count'] for c in customers[5:])
        
        result = []
        accum_share = 0.0
        for c in top_5:
            share = round((c['revenue'] / total_rev * 100), 1)
            accum_share += share
            result.append({
                'name': c['name'],
                'revenue': c['revenue'],
                'lot_count': c['lot_count'],
                'share': share
            })
            
        other_share = max(0.0, round(100.0 - accum_share, 1))
        result.append({
            'name': 'Khác',
            'revenue': other_rev,
            'lot_count': other_lots,
            'share': other_share
        })
        return result
