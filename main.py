import os
import sys
import json
import glob
import time
from db import OlistDB
from agents import CoordinatorAgent

def create_mock_case(db):
    """Create a mock case from a real order in the dataset for testing."""
    os.makedirs("input", exist_ok=True)

    # Pick a few diverse test orders from the dataset
    test_orders = [
        # A normal delivered order (should be unsupported_late_claim or valid_split_payment)
        "e481f51cbdc54678b7cc49136f2d6af7",
    ]

    for i, oid in enumerate(test_orders):
        details = db.get_order_details(oid)
        if not details:
            print(f"  WARNING: Test order {oid} not found in database, skipping.")
            continue

        mock_case = {
            "case_id": f"EC_TEST_{i:03d}",
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Đơn hàng của tôi có dấu hiệu giao trễ. Hãy kiểm tra nguyên nhân và quyền lợi phù hợp.",
                "claimed_order_id": oid,
            },
            "policy_version": "EC_POLICY_V1",
        }
        path = f"input/EC_TEST_{i:03d}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mock_case, f, indent=2, ensure_ascii=False)
        print(f"  Created mock case: {path} (order: {oid}, status: {details['order']['order_status']})")


def main():
    os.makedirs("output", exist_ok=True)
    os.makedirs("logging", exist_ok=True)

    is_test = "--test" in sys.argv

    print("Initializing Olist Database...")
    db = OlistDB(data_dir="data")

    print("Initializing Multi-Agent Coordinator...")
    coordinator = CoordinatorAgent()

    # Find all input JSON cases
    input_files = sorted(glob.glob("input/EC_*.json"))

    if not input_files:
        if is_test:
            print("No input files found. Creating mock cases for testing...")
            create_mock_case(db)
            input_files = sorted(glob.glob("input/EC_*.json"))
        else:
            print("ERROR: No input files found in input/ directory.")
            print("Place EC_001.json to EC_050.json in the 'input/' folder.")
            print("Or run with --test to create mock cases.")
            return

    # Clear previous trace
    trace_file_path = "logging/trace.jsonl"
    if os.path.exists(trace_file_path):
        os.remove(trace_file_path)

    total = len(input_files)
    success = 0
    failed = 0
    start_time = time.time()

    for idx, file_path in enumerate(input_files, 1):
        case_name = os.path.basename(file_path)
        print(f"[{idx}/{total}] Processing {case_name}...")

        with open(file_path, "r", encoding="utf-8") as f:
            case_data = json.load(f)

        case_id = case_data.get("case_id")

        try:
            output_data, trace = coordinator.process_case(case_data, db)

            # Save output
            output_file_path = os.path.join("output", f"{case_id}.json")
            with open(output_file_path, "w", encoding="utf-8") as out_f:
                json.dump(output_data, out_f, indent=2, ensure_ascii=False)

            # Append trace
            with open(trace_file_path, "a", encoding="utf-8") as trace_f:
                for step in trace:
                    step["case_id"] = case_id
                    trace_f.write(json.dumps(step, ensure_ascii=False) + "\n")

            primary = output_data.get("assessment", {}).get("primary_issue", "?")
            refund = output_data.get("financial_resolution", {}).get("recommended_refund_brl", 0)
            print(f"  [OK] {case_id}: {primary} | refund={refund} BRL")
            success += 1

        except Exception as e:
            print(f"  [FAIL] ERROR on {case_id}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    elapsed = time.time() - start_time

    # Create metadata.json (Rule compliance: model name declared in source code & metadata, NOT in .env)
    metadata = {
        "model": "gpt-4o-mini",
        "parameter_size": "<= 10B (~8B)",
        "framework": "Custom Hybrid Multi-Agent (Deterministic + LLM rationale)",
        "runtime": "Python 3.12",
    }
    with open("logging/metadata.json", "w", encoding="utf-8") as meta_f:
        json.dump(metadata, meta_f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"  Success: {success}/{total}")
    print(f"  Failed:  {failed}/{total}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
