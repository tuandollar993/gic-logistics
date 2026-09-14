import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any

def normalize_text_nfc(s: Optional[str]) -> str:
    """Normalize string to NFC, strip accents, collapse whitespace and lowercase."""
    if not s:
        return ''
    s = str(s).replace('đ', 'd').replace('Đ', 'd')
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.lower().split())

def clean_declaration_token(token: str) -> str:
    """Clean a single declaration token: strip whitespace and trailing .0."""
    t = str(token).strip()
    if t.endswith('.0') and t[:-2].isdigit():
        t = t[:-2]
    return t

def extract_customs_declarations(raw_decl: Optional[str]) -> List[str]:
    """
    Tách và chuẩn hóa danh sách số tờ khai từ chuỗi thô.
    Hỗ trợ phân cách bằng '_', ',', ';', '\n', '\r', khoảng trắng.
    Ví dụ: '108524917062_108524868432_108524908333' -> ['108524917062', '108524868432', '108524908333']
    '108466231160/A41' -> ['108466231160/A41']
    """
    if not raw_decl:
        return []
    s = str(raw_decl).strip()
    tokens = re.split(r'[,;_\n\r\s]+', s)
    results = []
    for tok in tokens:
        cleaned = clean_declaration_token(tok)
        if cleaned:
            norm_tok = normalize_text_nfc(cleaned)
            if norm_tok in ('dvtk', 'dvtkhq', 'hai quan', 'to khai', 'none', '-'):
                continue
            if any(w in norm_tok for w in ['nguoi lap', 'truong bo', 'ho ten', 'ky ten', 'ke toan', 'giam doc']):
                continue
            results.append(cleaned)
    return results

def get_declaration_base_number(decl: str) -> str:
    """
    Lấy phần số gốc của tờ khai (bỏ hậu tố /A11, /A12, /A41...).
    Ví dụ: '108466231160/A41' -> '108466231160'
    """
    cleaned = clean_declaration_token(decl)
    base = cleaned.split('/')[0].split('-')[0].strip()
    digits = re.sub(r'\D', '', base)
    if len(digits) >= 8:
        return digits
    return base

def extract_enterprise_name(raw_name: Optional[str]) -> str:
    """
    Trích xuất tên doanh nghiệp từ chuỗi chứa cả người liên hệ và doanh nghiệp.
    Quy tắc: Ưu tiên Doanh nghiệp hơn người liên hệ cá nhân.
    Ví dụ: 'MR THẮNG_Sunluxe' -> 'Sunluxe'
           'MR THẮNG_Jiayi VN' -> 'Jiayi VN'
           'Anh Thắng ' -> 'Anh Thắng'
           'Keep Rise' -> 'Keep Rise'
    """
    if not raw_name:
        return ''
    s = str(raw_name).strip()
    
    if '_' in s:
        parts = [p.strip() for p in s.split('_') if p.strip()]
        if len(parts) >= 2:
            p0_norm = normalize_text_nfc(parts[0])
            if any(p0_norm.startswith(pre) for pre in ['mr ', 'ms ', 'anh ', 'chi ', 'em ']):
                return parts[1]
            return parts[1] if len(parts[1]) > len(parts[0]) else parts[0]
            
    if '-' in s and not s.isdigit():
        parts = [p.strip() for p in s.split('-') if p.strip()]
        if len(parts) >= 2:
            p0_norm = normalize_text_nfc(parts[0])
            if any(p0_norm.startswith(pre) for pre in ['mr ', 'ms ', 'anh ', 'chi ', 'em ']):
                return parts[1]

    s_norm = normalize_text_nfc(s)
    for pre in ['mr ', 'ms ', 'mrs ']:
        if s_norm.startswith(pre):
            s = s[len(pre):].strip()
            break

    return s

def are_customers_compatible(cust_a: Optional[str], cust_b: Optional[str]) -> bool:
    """
    Kiểm tra xem hai tên khách hàng/công ty có tương thích nhau hay không.
    Hỗ trợ alias thông dụng: Sunluxe, Keep Rise, Huy Hoàng, Ginhung, Jiayi, etc.
    """
    if not cust_a or not cust_b:
        return True
    
    na = normalize_text_nfc(extract_enterprise_name(cust_a))
    nb = normalize_text_nfc(extract_enterprise_name(cust_b))
    
    if not na or not nb:
        return True
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
        
    aliases = [
        {'keep rise', 'keeprise', 'keep'},
        {'sunluxe', 'anh thang', 'a thang', 'thang'},
        {'jiayi', 'jiayi vn', 'jia yi', 'mr thang jiayi vn'},
        {'huy hoang', 'huyhoang'},
        {'ginhung', 'gin hung'},
        {'guangxi yunqian', 'yunqian'},
        {'johnson', 'johnson 2'}
    ]
    for group in aliases:
        if any(na in member or member in na for member in group) and \
           any(nb in member or member in nb for member in group):
            return True
            
    return False


@dataclass
class MatchResult:
    status: str            # 'matched' | 'unresolved' | 'ambiguous' | 'conflict'
    matched_lot_id: Optional[int] = None
    matched_lot_label: Optional[str] = None
    matched_by: Optional[str] = None      # 'customs_declaration_exact', 'customs_declaration_base', 'customer_unique', 'dossier_code'
    confidence: float = 0.0               # 1.0 (exact TKHQ), 0.95 (base TKHQ), 0.85 (unique customer)
    reason: str = ""
    candidate_lot_ids: List[int] = field(default_factory=list)


class CPVHMatcher:
    """
    Bộ đối soát chi phí vận hành chuẩn hóa 4-Tier dùng chung.
    Không phụ thuộc vào kỳ cụ thể, không hard-code khách hàng.
    """

    @classmethod
    def match_group(
        cls,
        source_customer: Optional[str],
        source_decl: Optional[str],
        sales_lots: List[Any],
        source_items: Optional[List[Dict[str, Any]]] = None,
        period_month: Optional[int] = None,
        period_year: Optional[int] = None
    ) -> MatchResult:
        """
        Đối soát 1 nhóm CPVH nguồn với danh sách Sales Lot trong cùng kỳ.

        sales_lots: Danh sách các bản ghi Lot (chỉ Sales Lot active: source_type != 'cpvh').
        """
        if not sales_lots:
            return MatchResult(
                status='unresolved',
                reason='Không có Sales Lot nào trong kỳ này để đối soát.'
            )

        clean_source_customer = (source_customer or '').strip()
        enterprise_source_customer = extract_enterprise_name(clean_source_customer)
        source_decl_tokens = extract_customs_declarations(source_decl)
        source_base_numbers = {get_declaration_base_number(t) for t in source_decl_tokens if len(get_declaration_base_number(t)) >= 8}

        # =========================================================================
        # TIER 1 — Số tờ khai hải quan (TKHQ) chuẩn hóa
        # =========================================================================
        if source_decl_tokens:
            # 1.1 Ưu tiên: Trùng toàn bộ mã tờ khai (Exact full match)
            exact_candidates = []
            for lot in sales_lots:
                lot_decl_tokens = extract_customs_declarations(lot.customs_declaration)
                for s_tok in source_decl_tokens:
                    if any(s_tok.lower() == l_tok.lower() for l_tok in lot_decl_tokens):
                        exact_candidates.append(lot)
                        break

            if len(exact_candidates) == 1:
                target = exact_candidates[0]
                target_cust = target.display_customer_name or target.company
                if clean_source_customer and not are_customers_compatible(enterprise_source_customer, target_cust):
                    return MatchResult(
                        status='conflict',
                        candidate_lot_ids=[target.id],
                        reason=f"Trùng số tờ khai ({source_decl}) với {target.lot_label} nhưng mâu thuẫn khách hàng ('{clean_source_customer}' vs '{target_cust}')."
                    )
                return MatchResult(
                    status='matched',
                    matched_lot_id=target.id,
                    matched_lot_label=target.lot_label,
                    matched_by='customs_declaration_exact',
                    confidence=1.0,
                    reason=f"Khớp chính xác số tờ khai '{source_decl}' với {target.lot_label} ({target_cust})."
                )
            elif len(exact_candidates) > 1:
                return MatchResult(
                    status='ambiguous',
                    candidate_lot_ids=[l.id for l in exact_candidates],
                    reason=f"Số tờ khai '{source_decl}' trùng với nhiều Sales Lot: {', '.join(l.lot_label for l in exact_candidates)}."
                )

            # 1.2 Trùng phần số gốc (Base number >= 8 chữ số, bỏ hậu tố /A41, /A11...)
            if source_base_numbers:
                base_candidates = []
                for lot in sales_lots:
                    lot_decl_tokens = extract_customs_declarations(lot.customs_declaration)
                    lot_bases = {get_declaration_base_number(t) for t in lot_decl_tokens if len(get_declaration_base_number(t)) >= 8}
                    if source_base_numbers & lot_bases:
                        base_candidates.append(lot)

                if len(base_candidates) == 1:
                    target = base_candidates[0]
                    target_cust = target.display_customer_name or target.company
                    if clean_source_customer and not are_customers_compatible(enterprise_source_customer, target_cust):
                        return MatchResult(
                            status='conflict',
                            candidate_lot_ids=[target.id],
                            reason=f"Trùng phần số gốc tờ khai với {target.lot_label} nhưng mâu thuẫn khách hàng ('{clean_source_customer}' vs '{target_cust}')."
                        )
                    matched_base = list(source_base_numbers)[0]
                    return MatchResult(
                        status='matched',
                        matched_lot_id=target.id,
                        matched_lot_label=target.lot_label,
                        matched_by='customs_declaration_base',
                        confidence=0.95,
                        reason=f"Khớp phần số gốc tờ khai '{matched_base}' với {target.lot_label} ({target_cust})."
                    )
                elif len(base_candidates) > 1:
                    return MatchResult(
                        status='ambiguous',
                        candidate_lot_ids=[l.id for l in base_candidates],
                        reason=f"Phần số gốc tờ khai trùng với nhiều Sales Lot: {', '.join(l.lot_label for l in base_candidates)}."
                    )

        # =========================================================================
        # TIER 2 — Mã hồ sơ / Mã lô nghiệp vụ
        # =========================================================================
        if source_decl and ('gido' in source_decl.lower() or 'lô' in source_decl.lower() or 'lo' in source_decl.lower()):
            norm_code = normalize_text_nfc(source_decl)
            code_matches = [
                l for l in sales_lots 
                if l.lot_label and normalize_text_nfc(l.lot_label) == norm_code
            ]
            if len(code_matches) == 1:
                target = code_matches[0]
                target_cust = target.display_customer_name or target.company
                if are_customers_compatible(enterprise_source_customer, target_cust):
                    return MatchResult(
                        status='matched',
                        matched_lot_id=target.id,
                        matched_lot_label=target.lot_label,
                        matched_by='dossier_code',
                        confidence=0.90,
                        reason=f"Khớp mã hồ sơ '{source_decl}' với {target.lot_label}."
                    )

        # =========================================================================
        # TIER 3 — Khách hàng / Doanh nghiệp
        # =========================================================================
        if enterprise_source_customer:
            cust_candidates = []
            for lot in sales_lots:
                lot_cust = lot.display_customer_name or lot.company
                if are_customers_compatible(enterprise_source_customer, lot_cust):
                    lot_decl_tokens = extract_customs_declarations(lot.customs_declaration)
                    if source_decl_tokens and lot_decl_tokens:
                        continue
                    cust_candidates.append(lot)

            # CHỈ tự động ghép khi trong cùng kỳ có đúng DUY NHẤT 1 Sales Lot phù hợp
            if len(cust_candidates) == 1:
                target = cust_candidates[0]
                return MatchResult(
                    status='matched',
                    matched_lot_id=target.id,
                    matched_lot_label=target.lot_label,
                    matched_by='customer_unique',
                    confidence=0.85,
                    reason=f"Khách hàng '{enterprise_source_customer}' có duy nhất 1 Sales Lot phù hợp trong kỳ ({target.lot_label})."
                )
            elif len(cust_candidates) > 1:
                return MatchResult(
                    status='ambiguous',
                    candidate_lot_ids=[l.id for l in cust_candidates],
                    reason=f"Khách hàng '{enterprise_source_customer}' có {len(cust_candidates)} Sales Lot trong kỳ ({', '.join(l.lot_label for l in cust_candidates)}). Cần con người chọn chính xác."
                )

        # =========================================================================
        # TIER 4 — Tín hiệu bổ sung (Ngày, Biển số, Tuyến)
        # =========================================================================
        reason_parts = []
        if source_decl_tokens:
            reason_parts.append(f"TKHQ '{source_decl}' không tồn tại trong kỳ")
        if clean_source_customer:
            reason_parts.append(f"Khách hàng '{clean_source_customer}' không có Sales Lot phù hợp")
        if not reason_parts:
            reason_parts.append("Thiếu thông tin nhận diện đối soát (TKHQ và Khách hàng)")

        return MatchResult(
            status='unresolved',
            reason='; '.join(reason_parts) + '.'
        )
