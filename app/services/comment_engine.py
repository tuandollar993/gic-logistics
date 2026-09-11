from app.services.calculator import CalculatorService
from app.models import CostEntryTask, Lot
from datetime import date

class CommentEngine:
    @staticmethod
    def generate_comments(month, year):
        """
        Generates automatic executive commentary for monthly performance.
        Returns a list of structured comment items with status/tag.
        """
        kpi = CalculatorService.get_monthly_kpi(month, year)
        customers = CalculatorService.get_customer_breakdown(month, year)
        
        comments = []
        
        # 1. Doanh thu & Tăng trưởng MoM
        rev = kpi['revenue']
        if rev > 0:
            if kpi['prev_revenue'] > 0:
                growth = kpi['rev_growth']
                if growth > 0:
                    comments.append({
                        'type': 'success',
                        'icon': 'trending-up',
                        'title': 'Tăng trưởng doanh thu tích cực',
                        'content': f"Doanh thu tháng {month}/{year} đạt {rev:,.0f} ₫, tăng trưởng +{growth:.1f}% so với tháng trước ({kpi['prev_revenue']:,.0f} ₫). Động lực tăng trưởng duy trì ổn định."
                    })
                elif growth < 0:
                    comments.append({
                        'type': 'warning',
                        'icon': 'trending-down',
                        'title': 'Doanh thu sụt giảm so với tháng trước',
                        'content': f"Doanh thu tháng {month}/{year} đạt {rev:,.0f} ₫, giảm {abs(growth):.1f}% so với tháng liền kề. Cần đẩy mạnh khai thác đơn hàng và gia tăng tần suất vận chuyển."
                    })
                else:
                    comments.append({
                        'type': 'info',
                        'icon': 'minus',
                        'title': 'Doanh thu duy trì ổn định',
                        'content': f"Doanh thu tháng {month}/{year} đạt {rev:,.0f} ₫, tương đương mức ghi nhận của tháng trước."
                    })
            else:
                comments.append({
                    'type': 'info',
                    'icon': 'calendar',
                    'title': 'Ghi nhận doanh thu ban đầu',
                    'content': f"Doanh thu tháng {month}/{year} đạt tổng cộng {rev:,.0f} ₫ trên {kpi['lot_count']} lô hàng vận hành."
                })
        else:
            comments.append({
                'type': 'warning',
                'icon': 'alert-circle',
                'title': 'Chưa phát sinh doanh thu',
                'content': f"Tháng {month}/{year} chưa ghi nhận dữ liệu doanh thu hoặc chưa có lô hàng hoàn tất."
            })
            
        # 2. Đánh giá hoàn thành Target
        target = kpi['target']
        if target > 0:
            achieve = kpi['achievement_pct']
            diff = rev - target
            if achieve >= 100:
                comments.append({
                    'type': 'success',
                    'icon': 'award',
                    'title': 'Vượt chỉ tiêu Target tháng',
                    'content': f"Đã hoàn thành {achieve:.1f}% chỉ tiêu tháng (Mục tiêu: {target:,.0f} ₫). Doanh số vượt kế hoạch {diff:,.0f} ₫."
                })
            elif achieve >= 80:
                comments.append({
                    'type': 'info',
                    'icon': 'target',
                    'title': 'Bám sát chỉ tiêu Target',
                    'content': f"Tiến độ đạt {achieve:.1f}% Target tháng (Mục tiêu: {target:,.0f} ₫). Còn thiếu {abs(diff):,.0f} ₫ ({100-achieve:.1f}%) để hoàn thành kế hoạch."
                })
            else:
                comments.append({
                    'type': 'danger',
                    'icon': 'alert-triangle',
                    'title': 'Chưa đạt kỳ vọng Target',
                    'content': f"Mới đạt {achieve:.1f}% chỉ tiêu kế hoạch tháng. Cần hành động quyết liệt và thúc đẩy các lô hàng tiềm năng."
                })
                
        # 3. Cơ cấu khách hàng trọng điểm
        if customers:
            top_c = customers[0]
            if top_c['share'] >= 40:
                comments.append({
                    'type': 'info',
                    'icon': 'users',
                    'title': 'Khách hàng đóng góp chủ lực',
                    'content': f"Khách hàng '{top_c['name']}' chiếm tỷ trọng lớn nhất với {top_c['revenue']:,.0f} ₫ ({top_c['share']}%) tổng doanh thu trên {top_c['lot_count']} lô hàng. Cần chú trọng chăm sóc và duy trì năng lực vận chuyển."
                })
            elif len(customers) > 1:
                names_shares = [f"{c['name']} ({c['share']}%)" for c in customers[:3]]
                comments.append({
                    'type': 'info',
                    'icon': 'pie-chart',
                    'title': 'Cơ cấu khách hàng phân bổ đa dạng',
                    'content': f"Doanh thu phân bổ tốt giữa các đối tác chủ lực: {', '.join(names_shares)}."
                })

        # 4. Hiệu quả chi phí & Tỷ suất lợi nhuận
        margin = kpi['profit_margin']
        net_p = kpi['net_profit']
        if rev > 0:
            if margin >= 20:
                comments.append({
                    'type': 'success',
                    'icon': 'dollar-sign',
                    'title': 'Biên lợi nhuận ròng xuất sắc',
                    'content': f"Lợi nhuận ước đạt {net_p:,.0f} ₫ với tỷ suất {margin:.1f}%. Hiệu quả đàm phán giá mua và kiểm soát chi phí vận chuyển đạt mức rất tốt."
                })
            elif margin >= 10:
                comments.append({
                    'type': 'info',
                    'icon': 'check-circle',
                    'title': 'Biên lợi nhuận đạt tiêu chuẩn',
                    'content': f"Lợi nhuận đạt {net_p:,.0f} ₫ với tỷ suất {margin:.1f}%. Hoạt động vận hành duy trì hiệu quả tài chính lành mạnh."
                })
            else:
                comments.append({
                    'type': 'warning',
                    'icon': 'percent',
                    'title': 'Biên lợi nhuận thấp, cần tối ưu chi phí',
                    'content': f"Tỷ suất lợi nhuận chỉ đạt {margin:.1f}%. Cần rà soát lại chi phí cước mua từ các đơn vị vận tải và các phụ phí kiểm hoá, bốc xếp phát sinh."
                })

        # 5. Tiến độ điền chi phí vận hành & Cảnh báo Task
        overdue_tasks = CostEntryTask.query.join(Lot).filter(
            Lot.month == month,
            Lot.year == year,
            CostEntryTask.status != 'completed',
            CostEntryTask.deadline < date.today()
        ).count()
        
        pending_tasks = CostEntryTask.query.join(Lot).filter(
            Lot.month == month,
            Lot.year == year,
            CostEntryTask.status != 'completed'
        ).count()
        
        comp_pct = kpi['cost_completion_pct']
        if overdue_tasks > 0:
            comments.append({
                'type': 'danger',
                'icon': 'bell-ring',
                'title': f'Cảnh báo: {overdue_tasks} lô hàng QUÁ HẠN điền chi phí',
                'content': f"Hiện có {overdue_tasks} lô hàng đã quá thời hạn điền chi phí vận hành. Quản lý cần kiểm tra và gửi thông báo đốc thúc nhân viên phụ trách ngay."
            })
        elif pending_tasks > 0:
            comments.append({
                'type': 'warning',
                'icon': 'clock',
                'title': f'Tiến độ điền chi phí vận hành: {comp_pct}%',
                'content': f"Đã có {kpi['lots_with_cost']}/{kpi['lot_count']} lô được hoàn thiện chi phí. Còn {pending_tasks} nhiệm vụ đang trong thời hạn xử lý."
            })
        elif kpi['lot_count'] > 0 and comp_pct == 100:
            comments.append({
                'type': 'success',
                'icon': 'check-check',
                'title': '100% lô hàng đã điền đủ chi phí',
                'content': f"Toàn bộ {kpi['lot_count']} lô hàng trong tháng đã được nhân viên điền và xác nhận đầy đủ số liệu chi phí vận hành thực tế."
            })
            
        return comments
