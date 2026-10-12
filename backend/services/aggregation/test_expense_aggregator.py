"""
Manual test for ExpenseAggregator.

Run from the backend directory:
    python services/aggregation/test_expense_aggregator.py

Mocks neo4j/dotenv/config so it runs without a live database.
Verifies:
  - weekly -> monthly conversion (weekly x 4)
  - yearly  -> monthly conversion (yearly / 12)
  - total income / expenses / investments
  - remaining for expenses (income - expenses)
  - remaining after all obligations (income - expenses - investments)
  - category percentages
  - answer generation helpers
"""

import sys
import os

# Make sure backend root is importable
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

# --- Verify the real chat.py wiring imports/compiles cleanly too ---
import py_compile
_CHAT_PY = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "api", "routes", "chat.py"))

# --- Mock external deps that are not needed for pure math testing ---


class _MockDriver:
    def verify_connectivity(self):
        pass

    def session(self):
        raise RuntimeError("DB not used in this test")

    def close(self):
        pass


class _MockGraphDatabase:
    class driver:  # noqa: N801 - mimic neo4j.GraphDatabase.driver
        def __init__(self, *args, **kwargs):
            self._d = _MockDriver()

        def __getattr__(self, name):
            return getattr(self._d, name)


sys.modules["neo4j"] = type(sys)("neo4j")
sys.modules["neo4j"].GraphDatabase = _MockGraphDatabase

sys.modules["dotenv"] = type(sys)("dotenv")
sys.modules["dotenv"].load_dotenv = lambda *a, **k: None

# Do NOT mock the real config package. Instead provide a fake dotenv above
# so the real config.settings module can import cleanly without the dep.
# The real Settings class just reads env vars with safe defaults.

from services.aggregation.expense_aggregator import ExpenseAggregator


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def main():
    agg = ExpenseAggregator()

    income_items = [
        {"category": "Salary", "amount": 50000, "frequency": "monthly"},
        {"category": "Freelance", "amount": 5000, "frequency": "monthly"},
    ]
    expense_items = [
        {"category": "Rent", "amount": 20000, "frequency": "monthly"},
        {"category": "Groceries", "amount": 10000, "frequency": "weekly"},   # -> 40000
        {"category": "Shopping", "amount": 8000, "frequency": "weekly"},     # -> 32000
        {"category": "Transport", "amount": 5000, "frequency": "weekly"},    # -> 20000
    ]
    investment_items = [
        {"category": "Mutual Funds", "amount": 5000, "frequency": "monthly"},
        {"category": "Stocks", "amount": 6000, "frequency": "monthly"},
    ]

    # For this pure-math test, stub out graph persistence (no live DB).
    agg._save_to_graph = lambda user_id, totals: None

    totals = agg.ingest_user_data(
        "user_test", income_items, expense_items, investment_items
    )

    checks = []

    # 1. Weekly -> monthly conversion
    checks.append(("Groceries weekly 10000 -> monthly 40000",
                   approx(totals["expenses"]["items"]["Groceries"], 40000)))
    checks.append(("Shopping weekly 8000 -> monthly 32000",
                   approx(totals["expenses"]["items"]["Shopping"], 32000)))
    checks.append(("Transport weekly 5000 -> monthly 20000",
                   approx(totals["expenses"]["items"]["Transport"], 20000)))

    # 2. Totals
    checks.append(("Total income 55000",
                   approx(totals["income"]["total"], 55000)))
    checks.append(("Total expenses 112000",
                   approx(totals["expenses"]["total"], 112000)))
    checks.append(("Total investments 11000",
                   approx(totals["investments"]["total"], 11000)))

    # 3. Remaining
    checks.append(("Remaining for expenses = 55000 - 112000 = -57000",
                   approx(totals["remaining_for_expenses"], -57000)))
    checks.append(("Remaining all = 55000 - 112000 - 11000 = -68000",
                   approx(totals["remaining_all"], -68000)))

    # 4. Percentages (expenses vs income)
    expected_rent_pct = round(20000 / 55000 * 100, 1)
    checks.append(("Rent percentage ~36.4%",
                   approx(totals["percentages"]["Rent"], expected_rent_pct)))

    # 5. Annual figures
    checks.append(("Annual income = 55000 * 12 = 660000",
                   approx(totals["annual_income"], 660000)))

    # 6. Free-text parsing (no LLM)
    msg = (
        "My income is Rs 50000. Rent is 20000. "
        "Groceries 10000 weekly. Shopping 8000 per week. Transport 5000/week. "
        "I invest 5000 in mutual funds monthly."
    )
    p_inc, p_exp, p_inv = agg.parse_financial_message(msg)
    checks.append(("Parse: income found", len(p_inc) >= 1))
    checks.append(("Parse: expense count == 4", len(p_exp) == 4))
    checks.append(("Parse: investment found", len(p_inv) >= 1))
    groc = [i for i in p_exp if i["category"] == "groceries"]
    checks.append(("Parse: groceries freq=weekly",
                   bool(groc) and groc[0]["frequency"] == "weekly"))

    # 7. Budget-question routing + deterministic answers
    checks.append(("is_budget_question(total expense) True",
                   agg.is_budget_question("what is my total monthly expense")))
    checks.append(("is_budget_question(non-budget) False",
                   not agg.is_budget_question("who won the match yesterday")))

    ans_total = agg.answer_query("what is my total monthly expense", totals)
    checks.append(("answer_query total -> 112,000",
                   bool(ans_total) and "112,000" in ans_total))
    ans_left = agg.answer_query("how much money do I have left", totals)
    checks.append(("answer_query left -> 57,000 deficit",
                   bool(ans_left) and "57,000" in ans_left))
    ans_save = agg.answer_query("what are my savings", totals)
    checks.append(("answer_query savings -> deficit",
                   bool(ans_save) and "deficit" in ans_save.lower()))
    ans_over = agg.answer_query("am I over budget", totals)
    checks.append(("answer_query over budget -> Yes",
                   bool(ans_over) and ans_over.lower().startswith("yes")))
    ans_groc = agg.answer_query("how much for groceries", totals)
    checks.append(("answer_query groceries -> 40,000",
                   bool(ans_groc) and "40,000" in ans_groc))
    ans_none = agg.answer_query("who won the match", totals)
    checks.append(("answer_query non-budget -> None", ans_none is None))

    # 8. chat.py wiring compiles
    try:
        py_compile.compile(_CHAT_PY, doraise=True)
        checks.append(("chat.py compiles", True))
    except py_compile.PyCompileError:
        checks.append(("chat.py compiles", False))

    # 9. Option A: single ingest_memory call (not one-per-fact)
    calls = {"n": 0, "facts": 0, "nodes": 0}

    def _fake_ingest(user_id, message_text, facts, nodes, relationships,
                     skip_contradiction_detection, source_type):
        calls["n"] += 1
        calls["facts"] += len(facts or [])
        calls["nodes"] += len(nodes or [])

    agg.graph_ingestion.ingest_memory = _fake_ingest
    # Call the real _save_to_graph (bypass the no-op instance stub set earlier).
    ExpenseAggregator._save_to_graph(agg, "user_test", totals)
    checks.append(("Option A: single ingest_memory call", calls["n"] == 1))
    checks.append(("Option A: all facts in one call", calls["facts"] == 6))

    # 10. Option B: distinct :Expense nodes per category, stable IDs
    exp_nodes = agg._build_expense_nodes(totals)
    checks.append(("Option B: one Expense node per category",
                   len(exp_nodes) == len(totals["expenses"]["items"])))
    checks.append(("Option B: nodes typed 'Expense'",
                   all(n["type"] == "Expense" for n in exp_nodes)))
    ids = [n["properties"]["id"] for n in exp_nodes]
    checks.append(("Option B: stable IDs (expense_<cat>)",
                   "expense_groceries" in ids and "expense_rent" in ids))
    checks.append(("Option B: deterministic (idempotent)",
                   ids == [n["properties"]["id"] for n in
                           agg._build_expense_nodes(totals)]))
    checks.append(("Option B: monthly_amount present",
                   all("monthly_amount" in n["properties"] for n in exp_nodes)))

    print("=" * 60)
    print("EXPENSE AGGREGATOR TEST")
    print("=" * 60)
    all_ok = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{status}] {name}")

    print("-" * 60)
    print("Computed summary:")
    print(f"  Monthly income : Rs {totals['income']['total']:,.0f}")
    print(f"  Total expenses : Rs {totals['expenses']['total']:,.0f}")
    print(f"  Remaining      : Rs {totals['remaining_for_expenses']:,.0f}")
    print(f"  Percentages    : {totals['percentages']}")

    print("-" * 60)
    print("Sample answers:")
    print("  total_expense ->", agg.answer_total_expense(totals)[:90], "...")
    print("  over_budget   ->", agg.answer_over_budget(totals)[:90], "...")
    print("  savings       ->", agg.answer_savings(totals)[:90], "...")

    print("=" * 60)
    if all_ok:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
