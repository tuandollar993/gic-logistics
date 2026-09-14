import pytest
from app.services.cpvh_matcher import (
    CPVHMatcher,
    extract_customs_declarations,
    get_declaration_base_number,
    extract_enterprise_name,
    are_customers_compatible
)

class MockLot:
    def __init__(self, id, lot_label, customs_declaration=None, company=None, customer_name=None, source_type='gido'):
        self.id = id
        self.lot_label = lot_label
        self.customs_declaration = customs_declaration
        self.company = company
        self.display_customer_name = customer_name or company
        self.source_type = source_type
        self.is_deleted = False

    @property
    def is_sales_lot(self):
        return self.source_type != 'cpvh'


def test_clean_and_extract_customs_declarations():
    # Single decl
    assert extract_customs_declarations('108520084630') == ['108520084630']
    # Float format from Excel
    assert extract_customs_declarations('108520084630.0') == ['108520084630']
    # Multiple declarations separated by underscore
    decls = extract_customs_declarations('108524917062_108524868432_108524908333')
    assert decls == ['108524917062', '108524868432', '108524908333']
    # Multiple separated by commas and spaces
    assert extract_customs_declarations('108424186511, 108424385531/A11') == ['108424186511', '108424385531/A11']
    # Suffix /A41
    assert extract_customs_declarations('108466231160/A41') == ['108466231160/A41']
    assert get_declaration_base_number('108466231160/A41') == '108466231160'


def test_extract_enterprise_name():
    assert extract_enterprise_name('MR THẮNG_Sunluxe') == 'Sunluxe'
    assert extract_enterprise_name('MR THẮNG_Jiayi VN') == 'Jiayi VN'
    assert extract_enterprise_name('Anh Thắng') == 'Anh Thắng'
    assert extract_enterprise_name('KEEPRISE') == 'KEEPRISE'
    assert extract_enterprise_name('GINHUNG') == 'GINHUNG'


def test_matcher_exact_declaration():
    lot1 = MockLot(1, 'Lô 1', customs_declaration='108520084630', company='Sunluxe')
    lot2 = MockLot(2, 'Lô 2', customs_declaration='108537067220', company='Sunluxe')
    
    res = CPVHMatcher.match_group(
        source_customer='MR THẮNG_Sunluxe',
        source_decl='108520084630',
        sales_lots=[lot1, lot2]
    )
    assert res.status == 'matched'
    assert res.matched_lot_id == 1
    assert res.matched_by == 'customs_declaration_exact'


def test_matcher_declaration_float_and_suffix():
    lot = MockLot(10, 'Lô 10', customs_declaration='108466231160', company='Ginhung')
    
    # Source has .0 or /A41
    res = CPVHMatcher.match_group(
        source_customer='GINHUNG',
        source_decl='108466231160/A41',
        sales_lots=[lot]
    )
    assert res.status == 'matched'
    assert res.matched_lot_id == 10
    assert 'customs_declaration' in res.matched_by


def test_matcher_sales_lot_with_multiple_declarations():
    lot_multi = MockLot(4, 'Lô 4', customs_declaration='108524917062_108524868432_108524908333', company='Keep Rise')
    
    # Source matches one of the 3 declarations in lot 4
    res = CPVHMatcher.match_group(
        source_customer='Keep Rise',
        source_decl='108524868432',
        sales_lots=[lot_multi]
    )
    assert res.status == 'matched'
    assert res.matched_lot_id == 4


def test_matcher_customer_unique():
    # Only 1 Sales Lot has customer Keep Rise
    lot1 = MockLot(1, 'Lô 1', customs_declaration='108520084630', company='Sunluxe')
    lot2 = MockLot(2, 'Lô 2', customs_declaration='108537067220', company='Sunluxe')
    lot4 = MockLot(4, 'Lô 4', customs_declaration=None, company='Keep Rise')
    
    # Source CPVH has no declaration, only customer 'KEEPRISE'
    res = CPVHMatcher.match_group(
        source_customer='KEEPRISE',
        source_decl=None,
        sales_lots=[lot1, lot2, lot4]
    )
    assert res.status == 'matched'
    assert res.matched_lot_id == 4
    assert res.matched_by == 'customer_unique'


def test_matcher_customer_ambiguous():
    # Multiple lots for the same customer (e.g. Month 7 Keep Rise has Lô 1, Lô 3, Lô 5)
    lot1 = MockLot(1, 'Lô 1', customs_declaration=None, company='Keep Rise')
    lot3 = MockLot(3, 'Lô 3', customs_declaration=None, company='Keep Rise')
    lot5 = MockLot(5, 'Lô 5', customs_declaration=None, company='Keep Rise')
    
    res = CPVHMatcher.match_group(
        source_customer='KEEPRISE',
        source_decl=None,
        sales_lots=[lot1, lot3, lot5]
    )
    assert res.status == 'ambiguous'
    assert set(res.candidate_lot_ids) == {1, 3, 5}
    assert res.matched_lot_id is None


def test_matcher_customer_declaration_conflict():
    # TKHQ matches but customer is completely incompatible
    lot_sunluxe = MockLot(1, 'Lô 1', customs_declaration='108520084630', company='Sunluxe')
    
    res = CPVHMatcher.match_group(
        source_customer='GINHUNG',
        source_decl='108520084630',
        sales_lots=[lot_sunluxe]
    )
    assert res.status == 'conflict'
    assert res.matched_lot_id is None


def test_matcher_stt_not_matched_for_different_customer():
    # Ginhung has STT 1, but Lô 1 is Sunluxe -> MUST NOT MATCH!
    lot1_sunluxe = MockLot(1, 'Lô 1', customs_declaration='108520084630', company='Sunluxe')
    
    res = CPVHMatcher.match_group(
        source_customer='GINHUNG',
        source_decl='108466231160/A41',
        sales_lots=[lot1_sunluxe]
    )
    assert res.status == 'unresolved'
    assert res.matched_lot_id is None
    assert res.matched_lot_id != 1


def test_matcher_missing_all_keys():
    lot1 = MockLot(1, 'Lô 1', customs_declaration='108520084630', company='Sunluxe')
    
    res = CPVHMatcher.match_group(
        source_customer='',
        source_decl='',
        sales_lots=[lot1]
    )
    assert res.status == 'unresolved'
    assert res.matched_lot_id is None
