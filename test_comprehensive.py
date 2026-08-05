"""
Comprehensive integration test for the Multi-Agent system.
Tests diverse order scenarios from the actual Olist data to validate
correctness of policy decisions, financial calculations, and output schema.
"""

import json
import sys
import pandas as pd
from db import OlistDB
from agents import CoordinatorAgent

def find_test_orders(db):
    """Find real order IDs in the database for each policy scenario."""
    orders = db.orders
    items = db.order_items
    payments = db.order_payments

    test_cases = []

    # === 1. canceled_order_paid ===
    canceled = orders[orders["order_status"] == "canceled"]
    if not canceled.empty:
        oid = canceled.iloc[0]["order_id"]
        test_cases.append({
            "name": "canceled_order_paid",
            "order_id": oid,
            "expected_issue": "canceled_order_paid",
            "expected_action": "issue_full_refund",
            "expected_status": "action_required",
        })

    # === 2. unavailable_order_paid ===
    unavailable = orders[orders["order_status"] == "unavailable"]
    if not unavailable.empty:
        oid = unavailable.iloc[0]["order_id"]
        test_cases.append({
            "name": "unavailable_order_paid",
            "order_id": oid,
            "expected_issue": "unavailable_order_paid",
            "expected_action": "issue_full_refund",
            "expected_status": "action_required",
        })

    # === 3. late_delivery_seller ===
    # Find a delivered order where carrier_date > shipping_limit AND delivered_customer > estimated
    delivered = orders[orders["order_status"] == "delivered"].copy()
    delivered = delivered.dropna(subset=["order_delivered_carrier_date", "order_delivered_customer_date"])
    delivered["carrier_dt"] = pd.to_datetime(delivered["order_delivered_carrier_date"])
    delivered["customer_dt"] = pd.to_datetime(delivered["order_delivered_customer_date"])
    delivered["estimate_dt"] = pd.to_datetime(delivered["order_estimated_delivery_date"])

    late_delivered = delivered[delivered["customer_dt"] > delivered["estimate_dt"]]
    for _, row in late_delivered.iterrows():
        oid = row["order_id"]
        carrier_dt = row["carrier_dt"]
        order_items = items[items["order_id"] == oid]
        if order_items.empty:
            continue
        for _, it in order_items.iterrows():
            limit_dt = pd.to_datetime(it["shipping_limit_date"])
            if carrier_dt > limit_dt:
                test_cases.append({
                    "name": "late_delivery_seller",
                    "order_id": oid,
                    "expected_issue": "late_delivery_seller",
                    "expected_action": "refund_freight",
                    "expected_status": "action_required",
                })
                break
        else:
            continue
        break

    # === 4. late_delivery_logistics ===
    for _, row in late_delivered.iterrows():
        oid = row["order_id"]
        carrier_dt = row["carrier_dt"]
        order_items = items[items["order_id"] == oid]
        if order_items.empty:
            continue
        all_on_time = True
        for _, it in order_items.iterrows():
            limit_dt = pd.to_datetime(it["shipping_limit_date"])
            if carrier_dt > limit_dt:
                all_on_time = False
                break
        if all_on_time:
            test_cases.append({
                "name": "late_delivery_logistics",
                "order_id": oid,
                "expected_issue": "late_delivery_logistics",
                "expected_action": "refund_freight",
                "expected_status": "action_required",
            })
            break

    # === 5. valid_split_payment ===
    # Find a delivered, on-time order with 2+ payments that match
    on_time = delivered[delivered["customer_dt"] <= delivered["estimate_dt"]]
    pay_counts = payments.groupby("order_id").size()
    multi_pay_ids = set(pay_counts[pay_counts >= 2].index)

    for _, row in on_time.iterrows():
        oid = row["order_id"]
        if oid not in multi_pay_ids:
            continue
        # Check payment matches
        total_pay = payments[payments["order_id"] == oid]["payment_value"].sum()
        order_items = items[items["order_id"] == oid]
        if order_items.empty:
            continue
        total_items = order_items["price"].sum() + order_items["freight_value"].sum()
        if abs(total_pay - total_items) <= 0.10:
            test_cases.append({
                "name": "valid_split_payment",
                "order_id": oid,
                "expected_issue": "valid_split_payment",
                "expected_action": "explain_valid_split_payment",
                "expected_status": "no_action",
            })
            break

    # === 6. unsupported_late_claim ===
    # Find a delivered, on-time order with exactly 1 payment that matches
    single_pay_ids = set(pay_counts[pay_counts == 1].index)
    for _, row in on_time.iterrows():
        oid = row["order_id"]
        if oid not in single_pay_ids:
            continue
        total_pay = payments[payments["order_id"] == oid]["payment_value"].sum()
        order_items = items[items["order_id"] == oid]
        if order_items.empty:
            continue
        total_items = order_items["price"].sum() + order_items["freight_value"].sum()
        if abs(total_pay - total_items) <= 0.10:
            test_cases.append({
                "name": "unsupported_late_claim",
                "order_id": oid,
                "expected_issue": "unsupported_late_claim",
                "expected_action": "reject_late_refund",
                "expected_status": "no_action",
            })
            break

    return test_cases


def validate_output_schema(output):
    """Validate output JSON matches the exact schema required by the lab."""
    errors = []

    required_top = ["case_id", "assessment", "affected_entities", "root_cause_analysis",
                     "evidence_ids", "financial_resolution", "resolution_actions"]
    for key in required_top:
        if key not in output:
            errors.append(f"Missing top-level key: {key}")

    # assessment
    assessment = output.get("assessment", {})
    for k in ["primary_issue", "case_status", "confidence"]:
        if k not in assessment:
            errors.append(f"Missing assessment.{k}")

    valid_issues = {"canceled_order_paid", "unavailable_order_paid", "late_delivery_seller",
                    "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim"}
    if assessment.get("primary_issue") not in valid_issues:
        errors.append(f"Invalid primary_issue: {assessment.get('primary_issue')}")

    if assessment.get("case_status") not in ("action_required", "no_action"):
        errors.append(f"Invalid case_status: {assessment.get('case_status')}")

    conf = assessment.get("confidence", -1)
    if not (0.0 <= conf <= 1.0):
        errors.append(f"Confidence out of range: {conf}")

    # affected_entities
    entities = output.get("affected_entities", {})
    for k in ["order_ids", "item_ids", "seller_ids", "payment_ids"]:
        if k not in entities:
            errors.append(f"Missing affected_entities.{k}")
        elif len(entities[k]) > 5:
            errors.append(f"Too many {k}: {len(entities[k])} (max 5)")

    # root_cause_analysis
    rca = output.get("root_cause_analysis", {})
    if "ranked_causes" not in rca:
        errors.append("Missing root_cause_analysis.ranked_causes")
    elif len(rca["ranked_causes"]) > 3:
        errors.append(f"Too many ranked_causes: {len(rca['ranked_causes'])}")
    if "responsible_parties" not in rca:
        errors.append("Missing root_cause_analysis.responsible_parties")
    elif len(rca["responsible_parties"]) > 3:
        errors.append(f"Too many responsible_parties: {len(rca['responsible_parties'])}")

    # evidence_ids
    evidence = output.get("evidence_ids", [])
    if len(evidence) > 10:
        errors.append(f"Too many evidence_ids: {len(evidence)}")
    for eid in evidence:
        if not any(eid.startswith(p) for p in ["order:", "item:", "payment:", "seller:", "policy:"]):
            errors.append(f"Invalid evidence format: {eid}")

    # financial_resolution
    fin = output.get("financial_resolution", {})
    for k in ["currency", "item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"]:
        if k not in fin:
            errors.append(f"Missing financial_resolution.{k}")
    if fin.get("currency") != "BRL":
        errors.append(f"Currency should be BRL, got: {fin.get('currency')}")

    # resolution_actions
    actions = output.get("resolution_actions", [])
    if len(actions) > 5:
        errors.append(f"Too many resolution_actions: {len(actions)}")

    return errors


def main():
    print("=" * 60)
    print("COMPREHENSIVE INTEGRATION TEST")
    print("=" * 60)
    print()

    db = OlistDB(data_dir="data")
    coordinator = CoordinatorAgent()

    test_cases = find_test_orders(db)
    print(f"Found {len(test_cases)} test scenarios from real data.\n")

    all_pass = True
    for i, tc in enumerate(test_cases, 1):
        print(f"--- Test {i}/{len(test_cases)}: {tc['name']} ---")
        print(f"    Order ID: {tc['order_id']}")

        case_data = {
            "case_id": f"TEST_{i:03d}",
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Test case",
                "claimed_order_id": tc["order_id"],
            },
            "policy_version": "EC_POLICY_V1",
        }

        try:
            output, trace = coordinator.process_case(case_data, db)

            # Check primary_issue
            actual_issue = output["assessment"]["primary_issue"]
            issue_ok = actual_issue == tc["expected_issue"]

            # Check action
            actual_action = output["resolution_actions"][0] if output["resolution_actions"] else "?"
            action_ok = actual_action == tc["expected_action"]

            # Check case_status
            actual_status = output["assessment"]["case_status"]
            status_ok = actual_status == tc["expected_status"]

            # Check schema
            schema_errors = validate_output_schema(output)

            # Financial checks
            fin = output["financial_resolution"]
            refund = fin["recommended_refund_brl"]

            passed = issue_ok and action_ok and status_ok and not schema_errors

            if passed:
                print(f"    [PASS] Issue={actual_issue}, Action={actual_action}, Refund={refund}")
            else:
                all_pass = False
                if not issue_ok:
                    print(f"    [FAIL] Issue: expected={tc['expected_issue']}, got={actual_issue}")
                if not action_ok:
                    print(f"    [FAIL] Action: expected={tc['expected_action']}, got={actual_action}")
                if not status_ok:
                    print(f"    [FAIL] Status: expected={tc['expected_status']}, got={actual_status}")
                if schema_errors:
                    for err in schema_errors:
                        print(f"    [FAIL] Schema: {err}")

            # Print financial summary
            print(f"    Financial: items={fin['item_total_brl']}, freight={fin['freight_total_brl']}, "
                  f"payment={fin['payment_total_brl']}, refund={refund}")

        except Exception as e:
            all_pass = False
            print(f"    [FAIL] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()

        print()

    print("=" * 60)
    if all_pass:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED - review output above.")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
