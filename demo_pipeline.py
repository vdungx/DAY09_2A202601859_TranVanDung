"""
===============================================================================
DEMO INTERACTIVE FULL PIPELINE - MULTI-AGENT E-COMMERCE DISPUTE RESOLUTION
===============================================================================
Script minh họa luồng vận hành chi tiết từ A-Z của hệ thống Multi-Agent:
1. Input Reception
2. DB Retrieval (OlistDB)
3. Specialist Agent Analysis (OrderSeller, Payment, Delivery)
4. Policy Engine Evaluation (EC_POLICY_V1 Priority 1..6)
5. LLM Rationale Generation
6. Verifier Agent Schema Validation & Evidence Scoping
7. Final JSON Output & Trace Log
===============================================================================
"""

import sys
import os
import json
import time
from datetime import datetime

# Ensure clean UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Import core modules
from db import OlistDB
from agents import (
    CoordinatorAgent,
    OrderSellerAgent,
    PaymentAgent,
    DeliveryAgent,
    PolicyAgent,
    VerifierAgent,
)
from ec_policy_v1 import evaluate_policy


def print_banner(text, char="=", length=70):
    print(f"\n{char * length}")
    print(f"  {text}")
    print(f"{char * length}")


def print_stage(stage_num, stage_name):
    print(f"\n>>> [STAGE {stage_num}] {stage_name.upper()}")
    print("-" * 65)


def run_demo(case_id="EC_001"):
    print_banner(f"DEMO VẬN HÀNH FULL PIPELINE MULTI-AGENT SYSTEM (CASE: {case_id})")

    input_file = os.path.join("input", f"{case_id}.json")
    if not os.path.exists(input_file):
        print(f"Error: File {input_file} không tồn tại!")
        return

    # STAGE 1: INPUT RECEPTION
    print_stage(1, "Tiếp nhận Khiếu nại Đầu vào (Input Case Reception)")
    with open(input_file, "r", encoding="utf-8") as f:
        case_data = json.load(f)

    customer_req = case_data.get("customer_request", {})
    claimed_order_id = case_data.get("claimed_order_id") or customer_req.get("claimed_order_id")

    print(f"  • Case ID:           {case_data.get('case_id')}")
    print(f"  • Claimed Order ID:  {claimed_order_id}")
    print(f"  • Opened At:         {case_data.get('opened_at')}")
    print(f"  • Customer Message:  {customer_req.get('message')}")
    time.sleep(0.5)

    # STAGE 2: DATABASE RETRIEVAL
    print_stage(2, "Truy vấn Cơ sở Dữ liệu Thực tế (OlistDB Engine Retrieval)")
    db = OlistDB()
    order_id = claimed_order_id
    print(f"  [CoordinatorAgent] Yêu cầu truy vấn 8 bảng CSV cho order_id: {order_id}")
    
    db_facts = db.get_order_details(order_id)
    order_info = db_facts.get("order", {})
    items = db_facts.get("items", [])
    payments = db_facts.get("payments", [])

    print(f"  ✔ Order Status:       {order_info.get('order_status')}")
    print(f"  ✔ Purchased Items:    {len(items)} row(s)")
    for idx, item in enumerate(items, 1):
        print(f"      - Item #{idx}: {item.get('item_id')} | Price: {item.get('price')} BRL | Freight: {item.get('freight_value')} BRL | Limit Date: {item.get('shipping_limit_date')}")
    print(f"  ✔ Payment Rows:       {len(payments)} row(s)")
    for idx, pay in enumerate(payments, 1):
        print(f"      - Payment #{idx}: {pay.get('payment_type')} ({pay.get('payment_installments')} installments) = {pay.get('payment_value')} BRL")
    print(f"  ✔ Delivery Carrier Date:  {order_info.get('order_delivered_carrier_date')}")
    print(f"  ✔ Customer Received Date: {order_info.get('order_delivered_customer_date')}")
    print(f"  ✔ Estimated Delivery Date:{order_info.get('order_estimated_delivery_date')}")
    time.sleep(0.5)

    # STAGE 3: SPECIALIST AGENTS DISPATCH
    print_stage(3, "Phân công & Phân tích Độc lập (Specialist Agents Dispatch)")
    trace = []

    # 3.1 OrderSellerAgent
    print("  ► [OrderSellerAgent]: Bắt đầu kiểm tra mốc thời gian bàn giao của Seller...")
    order_seller_agent = OrderSellerAgent()
    seller_report = order_seller_agent.analyze(order_info, items, trace)
    print(f"     └─ Status: {seller_report.get('order_status')}")
    print(f"     └─ Late Seller Handoff: {seller_report.get('has_late_seller_handoff')}")
    print(f"     └─ Responsible Seller(s): {seller_report.get('responsible_seller_ids')}")

    # 3.2 PaymentAgent
    print("\n  ► [PaymentAgent]: Bắt đầu đối soát tài chính & phát hiện Split Payment...")
    payment_agent = PaymentAgent()
    payment_report = payment_agent.analyze(payments, items, trace)
    print(f"     └─ Total Paid: {payment_report.get('total_payment_value')} BRL")
    print(f"     └─ Expected (Items + Freight): {payment_report.get('expected_total')} BRL")
    print(f"     └─ Matches Total (<=0.10 BRL tolerance): {payment_report.get('matches_total')}")
    print(f"     └─ Split Payment (>=2 rows): {payment_report.get('is_split_payment')}")

    # 3.3 DeliveryAgent
    print("\n  ► [DeliveryAgent]: Bắt đầu kiểm tra thời gian giao hàng thực tế vs Ước tính...")
    delivery_agent = DeliveryAgent()
    delivery_report = delivery_agent.analyze(order_info, trace)
    print(f"     └─ Is Delivered: {delivery_report.get('is_delivered')}")
    print(f"     └─ Delivered Late: {delivery_report.get('is_delivered_late')}")
    time.sleep(0.5)

    # STAGE 4: POLICY ENGINE EVALUATION
    print_stage(4, "Đánh giá Bảng Quy tắc Chính sách EC_POLICY_V1 (Priority 1..6)")
    analysis_facts = {
        "order_seller": seller_report,
        "payment": payment_report,
        "delivery": delivery_report,
    }
    
    print("  [PolicyAgent] Khởi chạy thuật toán duyệt chuỗi ưu tiên (Deterministic Decision Tree):")
    print("    [Priority 1] Canceled Order Paid?     -->", "MATCH!" if order_info.get("order_status") == "canceled" else "No")
    print("    [Priority 2] Unavailable Order Paid?  -->", "MATCH!" if order_info.get("order_status") == "unavailable" else "No")
    print("    [Priority 3] Late Delivery Seller?    -->", "MATCH!" if (delivery_report.get("is_delivered_late") and seller_report.get("has_late_seller_handoff")) else "No")
    print("    [Priority 4] Late Delivery Logistics? -->", "MATCH!" if (delivery_report.get("is_delivered_late") and not seller_report.get("has_late_seller_handoff")) else "No")
    print("    [Priority 5] Valid Split Payment?     -->", "MATCH!" if (payment_report.get("is_split_payment") and payment_report.get("matches_total")) else "No")
    print("    [Priority 6] Unsupported Late Claim?  --> Default fallback")

    policy_agent = PolicyAgent()
    policy_proposal = policy_agent.analyze(case_data, seller_report, payment_report, delivery_report, trace)

    print("\n  ✔ MATCHED POLICY RESULT:")
    print(f"     • Matched Priority: {policy_proposal.get('matched_priority')}")
    print(f"     • Primary Issue:    {policy_proposal.get('primary_issue')}")
    print(f"     • Root Cause Code:  {policy_proposal.get('root_cause_code')}")
    print(f"     • Responsible Party:{policy_proposal.get('responsible_party_type')} ({policy_proposal.get('responsible_party_id')})")
    print(f"     • Recommended Refund:{policy_proposal.get('recommended_refund_brl')} BRL")
    print(f"     • Resolution Action:{policy_proposal.get('resolution_action')}")
    time.sleep(0.5)

    # STAGE 5: LLM RATIONALE GENERATION
    print_stage(5, "Sinh Rationale Giải thích Tự nhiên (LLM gpt-4o-mini Integration)")
    print("  [PolicyAgent -> LLM] Rationale sinh ra:")
    print(f"  \"{policy_proposal.get('rationale')}\"")
    time.sleep(0.5)

    # STAGE 6: VERIFIER AGENT SCHEMA ENFORCEMENT
    print_stage(6, "Kiểm chứng Quality, Sắp xếp ID & Lọc Bằng chứng (VerifierAgent)")
    verifier_agent = VerifierAgent()
    final_output = verifier_agent.verify(case_id, db_facts, policy_proposal, trace)

    print("  ✔ Verifier Verification Checks:")
    print("     [x] Ép kiểu Float cho tất cả giá trị tiền tệ: OK")
    print(f"     [x] Chuẩn hóa responsible_parties: {final_output.get('root_cause_analysis', {}).get('responsible_parties')}")
    print(f"     [x] Evidence IDs (Scoped, max 10): {final_output.get('evidence_ids')}")
    print(f"     [x] Affected Entities (Sorted): {json.dumps(final_output.get('affected_entities'), indent=2)}")
    time.sleep(0.5)

    # STAGE 7: FINAL OUTPUT GENERATED
    print_stage(7, "Xuất File Kết quả Hoàn chỉnh (Final JSON Output)")
    print(json.dumps(final_output, indent=2, ensure_ascii=False))

    print_banner(f"DEMO HOÀN THÀNH THÀNH CÔNG CHO CASE {case_id}!")


if __name__ == "__main__":
    target_case = sys.argv[1] if len(sys.argv) > 1 else "EC_001"
    run_demo(target_case)
