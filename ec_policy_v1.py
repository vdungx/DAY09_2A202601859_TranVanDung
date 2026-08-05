"""
EC_POLICY_V1 — E-Commerce Dispute Resolution Policy Engine

Quy tắc nghiệp vụ dùng để phân loại và giải quyết khiếu nại khách hàng
trên dữ liệu Olist. Các rule được áp dụng theo THỨ TỰ ƯU TIÊN nghiêm ngặt
(priority 1 được kiểm tra trước, nếu thỏa thì dừng ngay).

Mọi phép tính tiền làm tròn 2 chữ số thập phân.

Tham chiếu: README.md Section 4 — Quy tắc nghiệp vụ
"""

# ──────────────────────────────────────────────
# Policy Rule Definitions (ordered by priority)
# ──────────────────────────────────────────────

POLICY_RULES = [
    {
        "priority": 1,
        "primary_issue": "canceled_order_paid",
        "root_cause_code": "ORDER_CANCELED_AFTER_PAYMENT",
        "description": "Đơn hàng đã bị hủy (canceled) nhưng khách hàng đã thanh toán.",
        "conditions": {
            "order_status": "canceled",
            "total_payment_gt_zero": True,
        },
        "responsible_party_type": "platform",
        "responsible_party_id": "OLIST_PLATFORM",
        "refund_source": "total_payment",      # Hoàn toàn bộ số tiền đã thanh toán
        "resolution_action": "issue_full_refund",
        "case_status": "action_required",
    },
    {
        "priority": 2,
        "primary_issue": "unavailable_order_paid",
        "root_cause_code": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "description": "Đơn hàng ở trạng thái unavailable nhưng khách hàng đã thanh toán.",
        "conditions": {
            "order_status": "unavailable",
            "total_payment_gt_zero": True,
        },
        "responsible_party_type": "platform",
        "responsible_party_id": "OLIST_PLATFORM",
        "refund_source": "total_payment",
        "resolution_action": "issue_full_refund",
        "case_status": "action_required",
    },
    {
        "priority": 3,
        "primary_issue": "late_delivery_seller",
        "root_cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
        "description": (
            "Giao hàng trễ so với estimated date, nguyên nhân do seller bàn giao "
            "muộn cho carrier (order_delivered_carrier_date > shipping_limit_date)."
        ),
        "conditions": {
            "is_delivered_late": True,
            "has_late_seller_handoff": True,
        },
        "responsible_party_type": "seller",
        "responsible_party_id": "FROM_DATA",  # Lấy seller_id vi phạm từ dữ liệu
        "refund_source": "total_freight",      # Hoàn toàn bộ phí vận chuyển
        "resolution_action": "refund_freight",
        "case_status": "action_required",
    },
    {
        "priority": 4,
        "primary_issue": "late_delivery_logistics",
        "root_cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "description": (
            "Giao hàng trễ so với estimated date, nhưng seller đã bàn giao đúng hạn. "
            "Trách nhiệm thuộc về đơn vị vận chuyển (logistics provider)."
        ),
        "conditions": {
            "is_delivered_late": True,
            "has_late_seller_handoff": False,
        },
        "responsible_party_type": "logistics_provider",
        "responsible_party_id": "LOGISTICS_PROVIDER",
        "refund_source": "total_freight",
        "resolution_action": "refund_freight",
        "case_status": "action_required",
    },
    {
        "priority": 5,
        "primary_issue": "valid_split_payment",
        "root_cause_code": "MULTIPLE_PAYMENTS_RECONCILED",
        "description": (
            "Đơn hàng có từ 2 payment rows trở lên và tổng payment khớp "
            "tổng (item price + freight) trong sai số 0.10 BRL. Không cần hoàn tiền."
        ),
        "conditions": {
            "is_split_payment": True,
            "payment_matches_total": True,
        },
        "responsible_party_type": "none",
        "responsible_party_id": None,
        "refund_source": "zero",               # Không hoàn tiền
        "resolution_action": "explain_valid_split_payment",
        "case_status": "no_action",
    },
    {
        "priority": 6,
        "primary_issue": "unsupported_late_claim",
        "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
        "description": (
            "Khách hàng khiếu nại giao trễ nhưng dữ liệu cho thấy đơn được giao "
            "không muộn hơn estimated date và payment khớp. Bác bỏ khiếu nại."
        ),
        "conditions": {
            "is_delivered_late": False,
            "payment_matches_total": True,
        },
        "responsible_party_type": "none",
        "responsible_party_id": None,
        "refund_source": "zero",
        "resolution_action": "reject_late_refund",
        "case_status": "no_action",
    },
]

# ──────────────────────────────────────────────
# Evidence ID Format Specification
# ──────────────────────────────────────────────

EVIDENCE_FORMATS = {
    "order":   "order:<order_id>",
    "item":    "item:<order_id>:<order_item_id>",
    "payment": "payment:<order_id>:<payment_sequential>",
    "seller":  "seller:<seller_id>",
    "policy":  "policy:<root_cause_code>",
}

# ──────────────────────────────────────────────
# Constants & Constraints
# ──────────────────────────────────────────────

PAYMENT_TOLERANCE_BRL = 0.10        # Sai số cho phép khi đối soát thanh toán
DECIMAL_PRECISION = 2               # Làm tròn 2 chữ số thập phân
MAX_EVIDENCE_IDS = 10               # Tối đa 10 evidence ID
MAX_ENTITY_IDS = 5                  # Tối đa 5 ID cho mỗi entity set
MAX_ROOT_CAUSES = 3                 # Tối đa 3 root causes
MAX_RESPONSIBLE_PARTIES = 3         # Tối đa 3 responsible parties
MAX_RESOLUTION_ACTIONS = 5          # Tối đa 5 actions
CONFIDENCE_RANGE = (0.0, 1.0)       # Khoảng giá trị confidence

# Seller late handoff rule (README section 4, paragraph below table):
# "seller bị coi là bàn giao muộn nếu
#  order_delivered_carrier_date > shipping_limit_date của item thuộc seller đó"
SELLER_LATE_CONDITION = "order_delivered_carrier_date > item.shipping_limit_date"

# Delivery late rule:
# "Giao sau estimated date" means:
#  order_delivered_customer_date > order_estimated_delivery_date
DELIVERY_LATE_CONDITION = "order_delivered_customer_date > order_estimated_delivery_date"


# ──────────────────────────────────────────────
# Policy Engine — Evaluate function
# ──────────────────────────────────────────────

def evaluate_policy(analysis_facts):
    """
    Áp dụng bảng quy tắc nghiệp vụ EC_POLICY_V1 theo thứ tự ưu tiên.

    Args:
        analysis_facts (dict): Kết quả phân tích từ các specialist agents, gồm:
            - order_status (str): Trạng thái đơn hàng
            - total_payment (float): Tổng số tiền đã thanh toán
            - total_freight (float): Tổng phí vận chuyển
            - is_delivered_late (bool): Giao trễ so với estimated date?
            - has_late_seller_handoff (bool): Seller bàn giao muộn?
            - is_split_payment (bool): Có >= 2 payment rows?
            - payment_matches_total (bool): Tổng payment khớp tổng item+freight?
            - responsible_seller_ids (list): Danh sách seller IDs vi phạm

    Returns:
        dict: Policy decision gồm primary_issue, case_status, root_cause_code,
              responsible_party_type, responsible_party_id, recommended_refund_brl,
              resolution_action, matched_priority
    """
    order_status = analysis_facts.get("order_status", "")
    total_payment = analysis_facts.get("total_payment", 0)
    total_freight = analysis_facts.get("total_freight", 0)
    is_delivered_late = analysis_facts.get("is_delivered_late", False)
    has_late_seller = analysis_facts.get("has_late_seller_handoff", False)
    is_split = analysis_facts.get("is_split_payment", False)
    matches_total = analysis_facts.get("payment_matches_total", True)
    responsible_sellers = analysis_facts.get("responsible_seller_ids", [])

    for rule in POLICY_RULES:
        conditions = rule["conditions"]

        # ── Check conditions for each rule ──
        if "order_status" in conditions:
            if order_status != conditions["order_status"]:
                continue
        if "total_payment_gt_zero" in conditions:
            if not (total_payment > 0):
                continue
        if "is_delivered_late" in conditions:
            if is_delivered_late != conditions["is_delivered_late"]:
                continue
        if "has_late_seller_handoff" in conditions:
            if has_late_seller != conditions["has_late_seller_handoff"]:
                continue
        if "is_split_payment" in conditions:
            if is_split != conditions["is_split_payment"]:
                continue
        if "payment_matches_total" in conditions:
            if matches_total != conditions["payment_matches_total"]:
                continue

        # ── Rule matched — calculate refund ──
        refund_source = rule["refund_source"]
        if refund_source == "total_payment":
            refund = round(total_payment, DECIMAL_PRECISION)
        elif refund_source == "total_freight":
            refund = round(total_freight, DECIMAL_PRECISION)
        else:
            refund = 0.0

        # ── Determine responsible party ID ──
        party_id = rule["responsible_party_id"]
        if party_id == "FROM_DATA":
            party_id = responsible_sellers[0] if responsible_sellers else "UNKNOWN_SELLER"

        return {
            "primary_issue": rule["primary_issue"],
            "case_status": rule["case_status"],
            "confidence": 0.95,
            "root_cause_code": rule["root_cause_code"],
            "responsible_party_type": rule["responsible_party_type"],
            "responsible_party_id": party_id,
            "recommended_refund_brl": refund,
            "resolution_action": rule["resolution_action"],
            "matched_priority": rule["priority"],
            "matched_description": rule["description"],
        }

    # ── Fallback: không rule nào match (shouldn't happen with proper data) ──
    return {
        "primary_issue": "unsupported_late_claim",
        "case_status": "no_action",
        "confidence": 0.50,
        "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
        "responsible_party_type": "none",
        "responsible_party_id": None,
        "recommended_refund_brl": 0.0,
        "resolution_action": "reject_late_refund",
        "matched_priority": 99,
        "matched_description": "No rule matched — fallback to reject.",
    }


# ──────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== EC_POLICY_V1 Self-Test ===\n")

    test_cases = [
        {
            "name": "Canceled order with payment",
            "facts": {"order_status": "canceled", "total_payment": 150.0, "total_freight": 20.0,
                      "is_delivered_late": False, "has_late_seller_handoff": False,
                      "is_split_payment": False, "payment_matches_total": True, "responsible_seller_ids": []},
            "expected_issue": "canceled_order_paid",
        },
        {
            "name": "Unavailable order with payment",
            "facts": {"order_status": "unavailable", "total_payment": 80.0, "total_freight": 10.0,
                      "is_delivered_late": False, "has_late_seller_handoff": False,
                      "is_split_payment": False, "payment_matches_total": True, "responsible_seller_ids": []},
            "expected_issue": "unavailable_order_paid",
        },
        {
            "name": "Late delivery — seller fault",
            "facts": {"order_status": "delivered", "total_payment": 100.0, "total_freight": 15.0,
                      "is_delivered_late": True, "has_late_seller_handoff": True,
                      "is_split_payment": False, "payment_matches_total": True,
                      "responsible_seller_ids": ["seller_abc123"]},
            "expected_issue": "late_delivery_seller",
        },
        {
            "name": "Late delivery — logistics fault",
            "facts": {"order_status": "delivered", "total_payment": 100.0, "total_freight": 15.0,
                      "is_delivered_late": True, "has_late_seller_handoff": False,
                      "is_split_payment": False, "payment_matches_total": True, "responsible_seller_ids": []},
            "expected_issue": "late_delivery_logistics",
        },
        {
            "name": "Valid split payment",
            "facts": {"order_status": "delivered", "total_payment": 50.0, "total_freight": 10.0,
                      "is_delivered_late": False, "has_late_seller_handoff": False,
                      "is_split_payment": True, "payment_matches_total": True, "responsible_seller_ids": []},
            "expected_issue": "valid_split_payment",
        },
        {
            "name": "Unsupported late claim",
            "facts": {"order_status": "delivered", "total_payment": 50.0, "total_freight": 10.0,
                      "is_delivered_late": False, "has_late_seller_handoff": False,
                      "is_split_payment": False, "payment_matches_total": True, "responsible_seller_ids": []},
            "expected_issue": "unsupported_late_claim",
        },
    ]

    all_pass = True
    for tc in test_cases:
        result = evaluate_policy(tc["facts"])
        status = "PASS" if result["primary_issue"] == tc["expected_issue"] else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] {tc['name']}")
        print(f"         Expected: {tc['expected_issue']}")
        print(f"         Got:      {result['primary_issue']} (priority {result['matched_priority']})")
        print(f"         Refund:   {result['recommended_refund_brl']} BRL")
        print()

    print(f"{'All tests passed!' if all_pass else 'SOME TESTS FAILED!'}")
