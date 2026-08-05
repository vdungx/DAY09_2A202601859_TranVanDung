"""
Multi-Agent Dispute Resolution System — V2 (Hybrid Deterministic + LLM)

Design philosophy:
- All math, date comparisons, and policy priority logic are done in DETERMINISTIC Python code.
- LLM is used ONLY for generating natural-language rationale/explanations (required for trace).
- Each agent has real handoff: receives structured input, produces structured output.
- VerifierAgent uses code-based validation (not LLM).
"""

import os
import json
import re
import time
from datetime import datetime
from openai import OpenAI
from google import genai
from google.genai import types
from dotenv import load_dotenv
from ec_policy_v1 import evaluate_policy

# Load env variables
load_dotenv()

# ──────────────────────────────────────────────
# LLM Client (singleton) & call helper
# ──────────────────────────────────────────────

_llm_cache = {}

# Model declaration in source code (Rule compliance: model <= 10B parameters, declared in code not .env)
MODEL_NAME = "gpt-4o-mini"

def get_llm_client():
    """Returns (provider, client, model_name). Cached after first call."""
    if "client" in _llm_cache:
        return _llm_cache["provider"], _llm_cache["client"], MODEL_NAME

    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = MODEL_NAME

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        client = genai.Client(api_key=api_key)
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in .env")
        client = OpenAI(api_key=api_key)
    elif provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in .env")
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_API_BASE", "http://localhost:11434/v1")
        client = OpenAI(base_url=base_url, api_key="ollama")
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    _llm_cache.update({"provider": provider, "client": client, "model": model_name})
    return provider, client, model_name


def call_llm(system_prompt, user_content, max_retries=3):
    """Call LLM with retry + exponential backoff."""
    provider, client, model_name = get_llm_client()

    for attempt in range(max_retries):
        try:
            if provider == "gemini":
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                return response.text
            else:  # openai, groq, ollama
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                return response.choices[0].message.content

        except Exception as e:
            wait = 2 ** attempt
            print(f"  LLM call attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)

    raise RuntimeError(f"LLM call failed after {max_retries} retries")


def extract_json(text):
    """Extract JSON object from LLM response text."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def safe_parse_datetime(dt_str):
    """Parse a datetime string, returning None on failure."""
    if not dt_str or str(dt_str).strip() in ("", "nan", "None", "NaT"):
        return None
    try:
        return datetime.fromisoformat(str(dt_str).strip())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(dt_str).strip(), fmt)
        except ValueError:
            continue
    return None


# ──────────────────────────────────────────────
# Base Agent
# ──────────────────────────────────────────────

class BaseAgent:
    def __init__(self, name):
        self.name = name

    def log_step(self, trace_list, action, details):
        trace_list.append({
            "agent": self.name,
            "action": action,
            "details": details,
        })


# ──────────────────────────────────────────────
# OrderSellerAgent — DETERMINISTIC date comparison
# ──────────────────────────────────────────────

class OrderSellerAgent(BaseAgent):
    def __init__(self):
        super().__init__("OrderSellerAgent")

    def analyze(self, order, items, trace):
        """Deterministic analysis of order status and seller handoff timing."""
        self.log_step(trace, "start_analysis", "Analyzing order status and seller handoff timestamps (deterministic).")

        order_status = order.get("order_status") if order else None
        carrier_date_str = order.get("order_delivered_carrier_date") if order else None
        carrier_date = safe_parse_datetime(carrier_date_str)
        order_id = order.get("order_id") if order else None

        items_checked = []
        has_late = False
        responsible_sellers = []

        for it in items:
            item_id_num = it.get("order_item_id")
            seller_id = it.get("seller_id")
            limit_str = it.get("shipping_limit_date")
            limit_date = safe_parse_datetime(limit_str)

            is_late = False
            if carrier_date and limit_date:
                is_late = carrier_date > limit_date

            if is_late:
                has_late = True
                if seller_id and seller_id not in responsible_sellers:
                    responsible_sellers.append(seller_id)

            items_checked.append({
                "item_id": f"{order_id}:{item_id_num}",
                "seller_id": seller_id,
                "shipping_limit_date": limit_str,
                "order_delivered_carrier_date": carrier_date_str,
                "is_late_seller_handoff": is_late,
            })

        result = {
            "order_status": order_status,
            "items_checked": items_checked,
            "has_late_seller_handoff": has_late,
            "responsible_seller_ids": responsible_sellers,
            "rationale": (
                f"Order status: {order_status}. "
                f"Carrier pickup date: {carrier_date_str}. "
                f"{'Late seller handoff detected for seller(s): ' + ', '.join(responsible_sellers) if has_late else 'No late seller handoff detected.'}"
            ),
        }

        self.log_step(trace, "complete_analysis", result)
        return result


# ──────────────────────────────────────────────
# PaymentAgent — DETERMINISTIC arithmetic
# ──────────────────────────────────────────────

class PaymentAgent(BaseAgent):
    def __init__(self):
        super().__init__("PaymentAgent")

    def analyze(self, payments, items, trace):
        """Deterministic payment reconciliation."""
        self.log_step(trace, "start_analysis", "Reconciling payments vs items (deterministic).")

        total_payment = round(sum(p.get("payment_value", 0) or 0 for p in payments), 2)
        payment_count = len(payments)
        is_split = payment_count >= 2

        total_price = round(sum(it.get("price", 0) or 0 for it in items), 2)
        total_freight = round(sum(it.get("freight_value", 0) or 0 for it in items), 2)
        expected = round(total_price + total_freight, 2)
        diff = abs(total_payment - expected)
        matches = diff <= 0.10

        result = {
            "payment_count": payment_count,
            "total_payment_value": total_payment,
            "total_items_price": total_price,
            "total_freight_value": total_freight,
            "expected_total": expected,
            "matches_total": matches,
            "is_split_payment": is_split,
            "rationale": (
                f"Payments: {payment_count} row(s), total={total_payment} BRL. "
                f"Items: price={total_price}, freight={total_freight}, expected={expected}. "
                f"Diff={diff:.2f} BRL ({'within' if matches else 'exceeds'} 0.10 tolerance). "
                f"Split payment: {is_split}."
            ),
        }

        self.log_step(trace, "complete_analysis", result)
        return result


# ──────────────────────────────────────────────
# DeliveryAgent — DETERMINISTIC date comparison
# ──────────────────────────────────────────────

class DeliveryAgent(BaseAgent):
    def __init__(self):
        super().__init__("DeliveryAgent")

    def analyze(self, order, trace):
        """Deterministic delivery timing analysis."""
        self.log_step(trace, "start_analysis", "Comparing delivery date vs estimate (deterministic).")

        delivered_str = order.get("order_delivered_customer_date") if order else None
        estimated_str = order.get("order_estimated_delivery_date") if order else None

        delivered_dt = safe_parse_datetime(delivered_str)
        estimated_dt = safe_parse_datetime(estimated_str)

        is_delivered = delivered_dt is not None
        is_late = False
        if delivered_dt and estimated_dt:
            is_late = delivered_dt > estimated_dt

        result = {
            "is_delivered": is_delivered,
            "order_delivered_customer_date": delivered_str,
            "order_estimated_delivery_date": estimated_str,
            "is_delivered_late": is_late,
            "rationale": (
                f"Delivered: {delivered_str or 'N/A'}. "
                f"Estimated: {estimated_str or 'N/A'}. "
                f"{'Delivery was LATE (after estimate).' if is_late else 'Delivery was on time or early.'}"
            ),
        }

        self.log_step(trace, "complete_analysis", result)
        return result


# ──────────────────────────────────────────────
# PolicyAgent — DETERMINISTIC if-elif priority chain
# ──────────────────────────────────────────────

class PolicyAgent(BaseAgent):
    """
    Applies business rules in STRICT priority order using Python if-elif.
    LLM is called ONLY to generate a natural-language rationale for the trace.
    """

    def __init__(self):
        super().__init__("PolicyAgent")

    def analyze(self, customer_request, order_seller_report, payment_report, delivery_report, trace):
        self.log_step(trace, "start_analysis", "Applying EC_POLICY_V1 business rules (deterministic priority chain).")

        # Build the analysis facts dict for the policy engine
        analysis_facts = {
            "order_status": order_seller_report.get("order_status", ""),
            "total_payment": payment_report.get("total_payment_value", 0),
            "total_freight": payment_report.get("total_freight_value", 0),
            "is_delivered_late": delivery_report.get("is_delivered_late", False),
            "has_late_seller_handoff": order_seller_report.get("has_late_seller_handoff", False),
            "is_split_payment": payment_report.get("is_split_payment", False),
            "payment_matches_total": payment_report.get("matches_total", True),
            "responsible_seller_ids": order_seller_report.get("responsible_seller_ids", []),
        }

        # Delegate to the formal policy engine
        result = evaluate_policy(analysis_facts)

        # Generate rationale via LLM (non-critical, fallback to static text)
        rationale = self._generate_rationale(customer_request, order_seller_report, payment_report, delivery_report, result)
        result["rationale"] = rationale

        self.log_step(trace, "complete_analysis", result)
        return result

    def _generate_rationale(self, customer_request, os_report, pay_report, del_report, decision):
        """Use LLM to explain the policy decision in natural language. Non-critical."""
        try:
            system_prompt = (
                "You are a dispute resolution policy explainer. "
                "Given the analysis reports and the policy decision, write a brief 2-3 sentence rationale "
                "explaining WHY this policy was applied. Be specific about the data that led to this conclusion. "
                "Output JSON with a single field: rationale (string)."
            )
            user_content = json.dumps({
                "decision": decision,
                "order_seller_summary": {
                    "order_status": os_report.get("order_status"),
                    "has_late_seller_handoff": os_report.get("has_late_seller_handoff"),
                },
                "payment_summary": {
                    "total_payment": pay_report.get("total_payment_value"),
                    "is_split": pay_report.get("is_split_payment"),
                    "matches": pay_report.get("matches_total"),
                },
                "delivery_summary": {
                    "is_delivered_late": del_report.get("is_delivered_late"),
                    "delivered": del_report.get("order_delivered_customer_date"),
                    "estimated": del_report.get("order_estimated_delivery_date"),
                },
            })
            resp = call_llm(system_prompt, user_content, max_retries=2)
            parsed = json.loads(extract_json(resp))
            return parsed.get("rationale", decision.get("primary_issue", ""))
        except Exception:
            # Fallback: deterministic rationale
            return (
                f"Policy '{decision['primary_issue']}' applied. "
                f"Order status: {os_report.get('order_status')}. "
                f"Late delivery: {del_report.get('is_delivered_late')}. "
                f"Late seller: {os_report.get('has_late_seller_handoff')}."
            )


# ──────────────────────────────────────────────
# VerifierAgent — DETERMINISTIC code validation
# ──────────────────────────────────────────────

class VerifierAgent(BaseAgent):
    """
    Constructs the final output JSON using deterministic code.
    Validates schema constraints, evidence ID formats, and financial calculations.
    NO LLM calls — pure Python.
    """

    def __init__(self):
        super().__init__("VerifierAgent")

    def verify(self, case_id, db_facts, policy_proposal, trace):
        self.log_step(trace, "start_verification", "Building and validating final output (deterministic).")

        order = db_facts.get("order", {}) or {}
        items = db_facts.get("items", [])
        payments = db_facts.get("payments", [])
        order_id = order.get("order_id", "")

        # ── Affected entities (sorted deterministically) ──
        order_ids = [order_id] if order_id else []

        sorted_items = sorted(items, key=lambda x: int(x.get('order_item_id', 0) or 0))
        item_ids = [f"{order_id}:{int(it.get('order_item_id'))}" for it in sorted_items if it.get('order_item_id') is not None][:5]

        seller_ids = sorted(list({it.get("seller_id") for it in items if it.get("seller_id")}))[:5]

        sorted_payments = sorted(payments, key=lambda x: int(x.get('payment_sequential', 0) or 0))
        payment_ids = [f"{order_id}:{int(p.get('payment_sequential'))}" for p in sorted_payments if p.get('payment_sequential') is not None][:5]

        # ── Financial resolution (calculated from raw data, not LLM) ──
        item_total = round(float(sum(it.get("price", 0) or 0 for it in items)), 2)
        freight_total = round(float(sum(it.get("freight_value", 0) or 0 for it in items)), 2)
        payment_total = round(float(sum(p.get("payment_value", 0) or 0 for p in payments)), 2)
        refund = round(float(policy_proposal.get("recommended_refund_brl", 0)), 2)

        # ── Root cause & Responsible parties ──
        root_cause_code = policy_proposal.get("root_cause_code", "DELIVERY_WITHIN_ESTIMATE")
        party_type = policy_proposal.get("responsible_party_type", "none")
        party_id = policy_proposal.get("responsible_party_id")

        # CRITICAL FIX: If party_type is "none", responsible_parties MUST be [] (empty list)
        responsible_parties = []
        if party_type == "seller":
            resp_sellers = policy_proposal.get("responsible_seller_ids", [party_id] if party_id else seller_ids[:1])
            for sid in resp_sellers[:3]:
                if sid:
                    responsible_parties.append({"party_type": "seller", "party_id": sid})
        elif party_type in ("platform", "logistics_provider"):
            if party_id:
                responsible_parties.append({"party_type": party_type, "party_id": party_id})

        # ── Evidence IDs ──
        evidence = []
        if order_id:
            evidence.append(f"order:{order_id}")
        for iid in item_ids:
            evidence.append(f"item:{iid}")
        for pid in payment_ids:
            evidence.append(f"payment:{pid}")
        # Include seller in evidence_ids ONLY if seller is in responsible_parties (prevents false positive evidence IDs)
        if party_type == "seller":
            for sid in seller_ids:
                evidence.append(f"seller:{sid}")
        evidence.append(f"policy:{root_cause_code}")
        evidence = evidence[:10]  # max 10

        # ── Construct final output ──
        output = {
            "case_id": case_id,
            "assessment": {
                "primary_issue": policy_proposal.get("primary_issue", "unsupported_late_claim"),
                "case_status": policy_proposal.get("case_status", "no_action"),
                "confidence": 1.0,
            },
            "affected_entities": {
                "order_ids": order_ids,
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": root_cause_code, "rank": 1}],
                "responsible_parties": responsible_parties[:3],
            },
            "evidence_ids": evidence,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": item_total,
                "freight_total_brl": freight_total,
                "payment_total_brl": payment_total,
                "recommended_refund_brl": refund,
            },
            "resolution_actions": [policy_proposal.get("resolution_action", "reject_late_refund")],
        }

        # ── Validation checks ──
        errors = self._validate(output)
        if errors:
            self.log_step(trace, "validation_warnings", errors)

        self.log_step(trace, "complete_verification", "Final JSON built and validated.")
        return output

    def _validate(self, output):
        """Run validation checks. Returns list of error strings (empty = all good)."""
        errors = []

        # Schema checks
        assessment = output.get("assessment", {})
        if assessment.get("primary_issue") not in (
            "canceled_order_paid", "unavailable_order_paid",
            "late_delivery_seller", "late_delivery_logistics",
            "valid_split_payment", "unsupported_late_claim",
        ):
            errors.append(f"Invalid primary_issue: {assessment.get('primary_issue')}")

        if assessment.get("case_status") not in ("action_required", "no_action"):
            errors.append(f"Invalid case_status: {assessment.get('case_status')}")

        conf = assessment.get("confidence", 0)
        if not (0.0 <= conf <= 1.0):
            errors.append(f"Confidence out of range: {conf}")

        # Evidence count
        if len(output.get("evidence_ids", [])) > 10:
            errors.append(f"Too many evidence IDs: {len(output['evidence_ids'])}")

        # Entity limits
        entities = output.get("affected_entities", {})
        for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            if len(entities.get(key, [])) > 5:
                errors.append(f"Too many {key}: {len(entities[key])}")

        # Financial sanity
        fin = output.get("financial_resolution", {})
        refund = fin.get("recommended_refund_brl", 0)
        payment = fin.get("payment_total_brl", 0)
        if refund > payment and payment > 0:
            errors.append(f"Refund ({refund}) exceeds payment ({payment})")

        return errors


# ──────────────────────────────────────────────
# CoordinatorAgent — Orchestrator
# ──────────────────────────────────────────────

class CoordinatorAgent(BaseAgent):
    def __init__(self):
        super().__init__("CoordinatorAgent")
        self.order_seller_agent = OrderSellerAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()

    def process_case(self, case_data, db):
        trace = []
        case_id = case_data.get("case_id")
        self.log_step(trace, "start_case", f"Processing case {case_id}")

        claimed_order_id = case_data.get("customer_request", {}).get("claimed_order_id")
        self.log_step(trace, "query_database", f"Querying database for order_id: {claimed_order_id}")

        db_facts = db.get_order_details(claimed_order_id)
        if not db_facts:
            self.log_step(trace, "db_error", f"Order {claimed_order_id} not found in database.")
            db_facts = {
                "order": {"order_id": claimed_order_id, "order_status": "unknown"},
                "customer": None,
                "items": [],
                "payments": [],
                "reviews": [],
            }
            default_proposal = {
                "primary_issue": "unsupported_late_claim",
                "case_status": "no_action",
                "confidence": 1.0,
                "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
                "responsible_party_type": "none",
                "responsible_party_id": None,
                "recommended_refund_brl": 0.0,
                "resolution_action": "reject_late_refund",
                "rationale": "Order not found in database.",
            }
            final_output = self.verifier_agent.verify(case_id, db_facts, default_proposal, trace)
            return final_output, trace

        # ── Step 1: Specialist agent analysis (all deterministic) ──
        self.log_step(trace, "dispatch_agents", "Dispatching specialist agents for analysis.")

        order_seller_report = self.order_seller_agent.analyze(db_facts["order"], db_facts["items"], trace)
        payment_report = self.payment_agent.analyze(db_facts["payments"], db_facts["items"], trace)
        delivery_report = self.delivery_agent.analyze(db_facts["order"], trace)

        # ── Step 2: Policy decision (deterministic + LLM rationale) ──
        self.log_step(trace, "handoff_to_policy", "Handing off analysis reports to PolicyAgent.")

        policy_proposal = self.policy_agent.analyze(
            case_data.get("customer_request"),
            order_seller_report,
            payment_report,
            delivery_report,
            trace,
        )

        # ── Step 3: Verification & output construction (deterministic) ──
        self.log_step(trace, "handoff_to_verifier", "Handing off proposal to VerifierAgent for validation.")

        final_output = self.verifier_agent.verify(case_id, db_facts, policy_proposal, trace)

        self.log_step(trace, "complete_case", f"Completed case {case_id}")
        return final_output, trace
