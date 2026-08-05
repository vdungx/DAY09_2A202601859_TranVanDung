import json
import glob
import pandas as pd
from db import OlistDB

db = OlistDB(data_dir="data")

print("=== 50 CASES FULL DIAGNOSTIC ===")
for f in sorted(glob.glob("input/EC_*.json")):
    with open(f, "r", encoding="utf-8") as file:
        data = json.load(file)
    cid = data["case_id"]
    req = data.get("customer_request", {})
    oid = req.get("claimed_order_id")
    msg = req.get("message", "")

    det = db.get_order_details(oid)
    if not det:
        print(f"[{cid}] ORDER NOT FOUND: {oid}")
        continue

    order = det["order"]
    status = order.get("order_status")
    carrier_dt = order.get("order_delivered_carrier_date")
    customer_dt = order.get("order_delivered_customer_date")
    estimated_dt = order.get("order_estimated_delivery_date")

    items = det["items"]
    payments = det["payments"]
    reviews = det["reviews"]

    p_total = sum(p.get("payment_value", 0) or 0 for p in payments)
    i_total = sum(it.get("price", 0) or 0 for it in items)
    f_total = sum(it.get("freight_value", 0) or 0 for it in items)
    expected = i_total + f_total
    diff = round(abs(p_total - expected), 2)

    # Check reviews if any
    review_score = [r.get("review_score") for r in reviews] if reviews else []
    review_msg = [r.get("review_comment_message") for r in reviews if r.get("review_comment_message")] if reviews else []

    print(f"[{cid}] status={status} | oid={oid}")
    print(f"      payments({len(payments)}): total={p_total:.2f} | items({len(items)}): price={i_total:.2f}, freight={f_total:.2f}, expected={expected:.2f}, diff={diff:.2f}")
    print(f"      carrier={carrier_dt} | customer={customer_dt} | est={estimated_dt}")
    if review_score:
        print(f"      reviews score={review_score} msg={review_msg}")
    print(f"      msg=\"{msg.encode('ascii', 'replace').decode('ascii')}\"")
    print("-" * 60)
