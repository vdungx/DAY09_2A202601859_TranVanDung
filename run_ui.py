"""
===============================================================================
VISUAL DEMO DASHBOARD SERVER - MULTI-AGENT E-COMMERCE DISPUTE RESOLUTION
===============================================================================
Khởi chạy Web Dashboard trực quan hóa đường đi & luồng xử lý của 6 Agent.
Không sử dụng thư viện ngoài (dùng HTTP Server có sẵn của Python).
Chạy: .venv\\Scripts\\python.exe run_ui.py
===============================================================================
"""

import sys
import os
import json
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configure clean UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add root dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

# Global DB instance
db_instance = None

def get_db():
    global db_instance
    if db_instance is None:
        db_instance = OlistDB()
    return db_instance


def process_case_full_flow(case_id):
    """Executes the pipeline for a case and returns detailed stage-by-stage data for UI visualization."""
    input_path = os.path.join("input", f"{case_id}.json")
    if not os.path.exists(input_path):
        return {"error": f"Case {case_id} không tồn tại!"}

    with open(input_path, "r", encoding="utf-8") as f:
        case_data = json.load(f)

    customer_req = case_data.get("customer_request", {})
    claimed_order_id = case_data.get("claimed_order_id") or customer_req.get("claimed_order_id")

    # DB facts
    db = get_db()
    db_facts = db.get_order_details(claimed_order_id)
    order_info = db_facts.get("order", {}) or {}
    items = db_facts.get("items", [])
    payments = db_facts.get("payments", [])

    # Run specialist agents
    trace = []
    order_seller_agent = OrderSellerAgent()
    seller_report = order_seller_agent.analyze(order_info, items, trace)

    payment_agent = PaymentAgent()
    payment_report = payment_agent.analyze(payments, items, trace)

    delivery_agent = DeliveryAgent()
    delivery_report = delivery_agent.analyze(order_info, trace)

    policy_agent = PolicyAgent()
    policy_proposal = policy_agent.analyze(case_data, seller_report, payment_report, delivery_report, trace)

    verifier_agent = VerifierAgent()
    final_output = verifier_agent.verify(case_id, db_facts, policy_proposal, trace)

    # Build priority rules evaluation status
    status = order_info.get("order_status")
    is_delivered_late = delivery_report.get("is_delivered_late", False)
    has_late_seller = seller_report.get("has_late_seller_handoff", False)
    is_split = payment_report.get("is_split_payment", False)
    matches_total = payment_report.get("matches_total", True)

    rules_eval = [
        {
            "priority": 1,
            "rule": "canceled_order_paid",
            "desc": "Đơn bị hủy (canceled) nhưng khách đã thanh toán",
            "matched": status == "canceled",
        },
        {
            "priority": 2,
            "rule": "unavailable_order_paid",
            "desc": "Đơn bị hết hàng (unavailable) nhưng khách đã thanh toán",
            "matched": status == "unavailable",
        },
        {
            "priority": 3,
            "rule": "late_delivery_seller",
            "desc": "Giao trễ do Seller bàn giao sau shipping_limit_date",
            "matched": is_delivered_late and has_late_seller,
        },
        {
            "priority": 4,
            "rule": "late_delivery_logistics",
            "desc": "Giao trễ nhưng Seller bàn giao đúng hạn (lỗi Logistics)",
            "matched": is_delivered_late and not has_late_seller,
        },
        {
            "priority": 5,
            "rule": "valid_split_payment",
            "desc": "Thanh toán chia nhỏ (>=2 dòng) và tổng tiền khớp",
            "matched": is_split and matches_total,
        },
        {
            "priority": 6,
            "rule": "unsupported_late_claim",
            "desc": "Giao đúng hạn/sớm hơn ước tính, bác bỏ khiếu nại",
            "matched": policy_proposal.get("matched_priority") == 6,
        },
    ]

    return {
        "case_id": case_id,
        "input_case": case_data,
        "db_facts": db_facts,
        "agent_reports": {
            "seller_report": seller_report,
            "payment_report": payment_report,
            "delivery_report": delivery_report,
        },
        "policy_eval": rules_eval,
        "policy_proposal": policy_proposal,
        "final_output": final_output,
        "trace": trace,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            with open("demo_ui.html", "rb") as f:
                self.wfile.write(f.read())

        elif path == "/api/cases":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            cases = [f"EC_{i:03d}" for i in range(1, 51)]
            self.wfile.write(json.dumps(cases).encode("utf-8"))

        elif path == "/api/process":
            case_id = query.get("case_id", ["EC_001"])[0]
            result = process_case_full_flow(case_id)
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Quiet logger
        return


def main():
    port = 8080
    print("=" * 70)
    print(f"[SERVER] MULTI-AGENT VISUAL DEMO DASHBOARD SERVER RUNNING")
    print(f"  URL: http://localhost:{port}/")
    print("=" * 70)
    
    # Pre-load DB
    print("Initializing Olist Database...")
    get_db()
    print("Database Ready!")

    # Open browser automatically
    webbrowser.open(f"http://localhost:{port}/")

    server = HTTPServer(("localhost", port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Visual Demo Dashboard Server.")
        server.server_close()


if __name__ == "__main__":
    main()
