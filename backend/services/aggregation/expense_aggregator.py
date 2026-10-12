"""
Expense Aggregator - Compute totals from financial data.
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from services.graph.ingestion import GraphIngestion

# In-process cache of the latest computed totals per user.
# Lets the chat QUESTION path answer budget questions deterministically
# without a DB round-trip. Populated on every ingest_from_text().
_LATEST_TOTALS: Dict[str, Dict[str, Any]] = {}


class ExpenseAggregator:
    WEEKLY_TO_MONTHLY = 4.0
    MONTHS_PER_YEAR = 12

    def __init__(self):
        self.graph_ingestion = GraphIngestion()

    # ------------------------------------------------------------------
    # Free-text parsing (chat integration)
    # ------------------------------------------------------------------

    _INCOME_WORDS = (
        "income", "salary", "earn", "earns", "earned", "paycheck", "pay",
        "wage", "stipend", "revenue", "freelance",
    )
    _INVESTMENT_WORDS = (
        "invest", "invests", "investment", "investments", "sip", "mutual fund",
        "mutualfund", "stock", "stocks", "shares", "ppf", "fd", "fixed deposit",
        "crypto", "gold", "nps", "elss", "etf", "bonds",
    )
    _EXPENSE_WORDS = (
        "rent", "groceries", "grocery", "food", "shopping", "transport",
        "travel", "utilities", "utility", "bill", "bills", "emi", "loan",
        "insurance", "health", "medical", "education", "fees", "fuel",
        "electricity", "internet", "phone", "mobile", "subscription",
        "entertainment", "dining", "expense", "expenses", "spend", "spent",
    )
    _FREQ_WORDS = {
        "weekly": ("weekly", "week", "/wk", "per week", "a week"),
        "yearly": ("yearly", "annual", "annually", "/yr", "per year", "a year"),
        "daily": ("daily", "day", "/day", "per day", "a day"),
    }
    _AMOUNT_RE = re.compile(
        r"(?:₹|rs\.?|inr|\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
        r"|([0-9][0-9,]*(?:\.[0-9]+)?)",
        re.IGNORECASE,
    )

    def parse_financial_message(self, text):
        """
        Extract (income_items, expense_items, investment_items) from free text.
        Deterministic; no LLM involved.
        """
        if not text:
            return [], [], []

        clauses = re.split(r"[.;\n]| and | also |, ", text, flags=re.IGNORECASE)

        income_items, expense_items, investment_items = [], [], []

        for clause in clauses:
            low = clause.lower()
            amounts = self._extract_amounts(clause)
            if not amounts:
                continue
            freq = self._detect_frequency(low)
            kind = self._classify(low)
            if kind is None:
                continue
            category = self._extract_category(low, kind)
            item = {"category": category, "amount": amounts[0], "frequency": freq}
            if kind == "income":
                income_items.append(item)
            elif kind == "expense":
                expense_items.append(item)
            else:
                investment_items.append(item)

        return income_items, expense_items, investment_items

    def _extract_amounts(self, clause):
        """Return numeric amounts in a clause (largest first)."""
        vals = []
        for m in self._AMOUNT_RE.finditer(clause):
            raw = m.group(1) or m.group(2)
            if not raw:
                continue
            try:
                vals.append(float(raw.replace(",", "")))
            except ValueError:
                continue
        vals = [v for v in vals if v >= 1]
        vals.sort(reverse=True)
        return vals

    def _detect_frequency(self, low):
        for freq, words in self._FREQ_WORDS.items():
            if any(w in low for w in words):
                return freq
        return "monthly"

    def _classify(self, low):
        if any(w in low for w in self._INVESTMENT_WORDS):
            return "investment"
        if any(w in low for w in self._INCOME_WORDS):
            return "income"
        if any(w in low for w in self._EXPENSE_WORDS):
            return "expense"
        return None

    def _extract_category(self, low, kind):
        known = list(self._INCOME_WORDS) + list(self._EXPENSE_WORDS) + \
            list(self._INVESTMENT_WORDS)
        for word in known:
            if word in low:
                return self.normalize_category(word)
        return kind

    def ingest_from_text(self, user_id, text):
        """
        Parse free text, compute totals, persist to graph, cache totals.
        Returns totals dict, or None if nothing financial was found.
        """
        income_items, expense_items, investment_items = \
            self.parse_financial_message(text)
        if not income_items and not expense_items and not investment_items:
            return None
        totals = self.ingest_user_data(
            user_id, income_items, expense_items, investment_items
        )
        _LATEST_TOTALS[user_id] = totals
        return totals

    @staticmethod
    def get_cached_totals(user_id):
        """Return the most recently computed totals for a user, if any."""
        return _LATEST_TOTALS.get(user_id)

    def ingest_user_data(self, user_id, income_items, expense_items, investment_items=None):
        monthly_income = self._to_monthly(income_items)
        monthly_expenses = self._to_monthly(expense_items)
        monthly_investments = self._to_monthly(investment_items or [])

        total_income = sum(monthly_income.values())
        total_expenses = sum(monthly_expenses.values())
        total_investments = sum(monthly_investments.values())

        remaining_for_expenses = total_income - total_expenses
        remaining_all = total_income - (total_expenses + total_investments)

        result = {
            "user_id": user_id,
            "income": {"items": monthly_income, "total": total_income},
            "expenses": {"items": monthly_expenses, "total": total_expenses},
            "investments": {"items": monthly_investments, "total": total_investments},
            "remaining_for_expenses": remaining_for_expenses,
            "remaining_all": remaining_all,
            "percentages": self._compute_percentages(monthly_expenses, total_income),
            "annual_income": total_income * self.MONTHS_PER_YEAR,
            "annual_expenses": total_expenses * self.MONTHS_PER_YEAR,
            "annual_investments": total_investments * self.MONTHS_PER_YEAR,
        }
        self._save_to_graph(user_id, result)
        return result

    def _to_monthly(self, items):
        monthly = {}
        for item in items:
            category = item.get("category", "unknown")
            amount = float(item.get("amount", 0))
            freq = str(item.get("frequency", "monthly")).lower()
            if freq == "weekly":
                monthly_amt = amount * self.WEEKLY_TO_MONTHLY
            elif freq == "yearly":
                monthly_amt = amount / self.MONTHS_PER_YEAR
            else:
                monthly_amt = amount
            monthly[category] = monthly.get(category, 0.0) + monthly_amt
        return monthly

    def _compute_percentages(self, expenses, total_income):
        if total_income <= 0:
            return {}
        return {k: round(v / total_income * 100, 1) for k, v in expenses.items()}

    def _save_to_graph(self, user_id, totals):
        """Persist computed totals to the graph in a SINGLE ingestion call.

        Option A: one Message node + all computed Facts (instead of one
        Message per fact). Option B: distinct :Expense nodes per category so
        expenses stand out in the Mindmap. Facts auto-link to the Expense
        nodes by name (RELATES_TO) via the ingestion fallback.
        """
        facts = self._build_facts(user_id, totals)
        expense_nodes = self._build_expense_nodes(totals)

        self.graph_ingestion.ingest_memory(
            user_id=user_id,
            message_text="Computed monthly budget summary",
            facts=facts,
            nodes=expense_nodes,
            relationships=[],
            skip_contradiction_detection=True,
            source_type="chat",
        )

    def _build_expense_nodes(self, totals):
        """Build distinct :Expense nodes (one per category) with stable IDs.

        Deterministic IDs (expense_<category>) mean repeated aggregation for
        the same category updates the node instead of creating duplicates.
        """
        nodes = []
        for cat, amt in totals["expenses"]["items"].items():
            cat_lower = str(cat).lower().strip()
            nodes.append({
                "type": "Expense",
                "properties": {
                    "id": f"expense_{cat_lower}",
                    "name": str(cat),
                    "monthly_amount": round(float(amt), 2),
                    "currency": "INR",
                },
            })
        return nodes

    def _build_facts(self, user_id, totals):
        facts = []
        # Income
        facts.append({
            "text": f"Computed: Monthly Income = Rs {totals['income']['total']:,.0f}, Annual Income = Rs {totals['annual_income']:,.0f}",
            "confidence": 1.0, "type": "computed",
        })
        # Expenses breakdown + total
        exp_parts = " + ".join(
            f"{cat} Rs {amt:,.0f}" for cat, amt in totals["expenses"]["items"].items()
        )
        facts.append({
            "text": f"Computed: Monthly Expenses = Rs {totals['expenses']['total']:,.0f} ({exp_parts})",
            "confidence": 1.0, "type": "computed",
        })
        # Investments
        inv_parts = " + ".join(
            f"{cat} Rs {amt:,.0f}" for cat, amt in totals["investments"]["items"].items()
        )
        facts.append({
            "text": f"Computed: Monthly Investments = Rs {totals['investments']['total']:,.0f} ({inv_parts})",
            "confidence": 1.0, "type": "computed",
        })
        # Remaining (expenses only)
        facts.append({
            "text": f"Computed: Remaining for Expenses = Rs {totals['remaining_for_expenses']:,.0f}",
            "confidence": 1.0, "type": "computed",
        })
        # Remaining (all obligations)
        facts.append({
            "text": f"Computed: Remaining after all obligations = Rs {totals['remaining_all']:,.0f}",
            "confidence": 1.0, "type": "computed",
        })
        # Percentages
        pct_parts = ", ".join(f"{cat}: {pct}%" for cat, pct in totals["percentages"].items())
        facts.append({
            "text": f"Computed: Expense Percentages = {pct_parts}",
            "confidence": 1.0, "type": "computed",
        })
        return facts

    def is_budget_question(self, query):
        """Heuristic: does this query ask for an aggregated budget figure?"""
        q = query.lower()
        triggers = (
            "total expense", "total expenses", "total spend", "total spending",
            "how much do i spend", "how much did i spend", "monthly expense",
            "how much left", "money left", "left after", "remaining",
            "savings", "saving", "over budget", "under budget", "budget",
            "breakdown", "how much for", "how much on", "expense breakdown",
            "how much do i have", "do i have left", "income minus", "groceries",
            "grocery",
        )
        return any(t in q for t in triggers)

    def answer_query(self, query, totals):
        """
        Deterministically answer a budget question from computed totals.
        Returns None if not a recognized budget question (caller falls back
        to the normal RAG/LLM path).
        """
        if not totals:
            return None
        q = query.lower()

        if "grocer" in q:
            return self.answer_groceries(totals)
        if "breakdown" in q or "categor" in q or "percent" in q or "percentage" in q:
            return self.answer_breakdown(totals)
        if "budget" in q:
            return self.answer_over_budget(totals)
        if "saving" in q or "savings" in q:
            return self.answer_savings(totals)
        if any(k in q for k in ("left", "remaining", "do i have", "balance")):
            return self.answer_remaining(totals)
        if any(k in q for k in (
            "total expense", "total expenses", "total spend", "total spending",
            "how much do i spend", "how much did i spend", "monthly expense",
        )):
            return self.answer_total_expense(totals)
        return None

    def answer_total_expense(self, totals):
        parts = " + ".join(f"{cat} Rs {amt:,.0f}" for cat, amt in sorted(totals["expenses"]["items"].items()))
        items = {k.lower(): v for k, v in totals["expenses"]["items"].items()}
        return (
            f"Your total monthly expenses are Rs {totals['expenses']['total']:,.0f}. "
            f"Breakdown: Rent Rs {items.get('rent', 0):,.0f}, "
            f"Groceries Rs {items.get('groceries', 0):,.0f}, "
            f"Shopping Rs {items.get('shopping', 0):,.0f}, "
            f"Transport Rs {items.get('transport', 0):,.0f}. "
            f"Calculated as: {parts} = Rs {totals['expenses']['total']:,.0f}."
        )

    def answer_remaining(self, totals):
        if totals["remaining_for_expenses"] >= 0:
            return (
                f"You have Rs {totals['remaining_for_expenses']:,.0f} left after expenses. "
                f"Monthly income is Rs {totals['income']['total']:,.0f} "
                f"and total monthly expenses are Rs {totals['expenses']['total']:,.0f}."
            )
        else:
            deficit = abs(totals["remaining_for_expenses"])
            return (
                f"You are Rs {deficit:,.0f} over budget. "
                f"Monthly income Rs {totals['income']['total']:,.0f}, "
                f"total expenses Rs {totals['expenses']['total']:,.0f}. "
                f"Deficit amount: Rs {deficit:,.0f}."
            )

    def answer_breakdown(self, totals):
        items = {k.lower(): v for k, v in totals["expenses"]["items"].items()}
        pct = totals["percentages"]
        pct_lower = {k.lower(): v for k, v in pct.items()}
        parts = []
        for cat in ["rent", "groceries", "shopping", "transport"]:
            if cat in items:
                amt = items[cat]
                p = pct_lower.get(cat, 0)
                parts.append(f"{cat.title()}: Rs {amt:,.0f} ({p}%)")
        pct_parts = ", ".join(f"{cat}: {pct}%" for cat, pct in sorted(pct.items()))
        return f"Expense breakdown:\n" + "\n".join(f"  - {p}" for p in parts) + f"\nPercentages of income: {pct_parts}"

    def answer_over_budget(self, totals):
        if totals["remaining_for_expenses"] < 0:
            deficit = abs(totals["remaining_for_expenses"])
            return (
                f"Yes, you are over budget by Rs {deficit:,.0f}. "
                f"Income: Rs {totals['income']['total']:,.0f}, "
                f"Expenses: Rs {totals['expenses']['total']:,.0f}. "
                f"Deficit: Rs {deficit:,.0f}."
            )
        else:
            surplus = totals["remaining_for_expenses"]
            return (
                f"No, you are within budget by Rs {surplus:,.0f}. "
                f"Income: Rs {totals['income']['total']:,.0f}, "
                f"Expenses: Rs {totals['expenses']['total']:,.0f}. "
                f"Remaining: Rs {surplus:,.0f}."
            )

    def answer_savings(self, totals):
        remaining = totals["remaining_for_expenses"]
        if remaining >= 0:
            return (
                f"You are saving Rs {remaining:,.0f} this month. "
                f"Total income: Rs {totals['income']['total']:,.0f}, "
                f"total expenses: Rs {totals['expenses']['total']:,.0f}."
            )
        else:
            deficit = abs(remaining)
            return (
                f"You have a deficit of Rs {deficit:,.0f} this month. "
                f"You need Rs {deficit:,.0f} more than your Rs {totals['income']['total']:,.0f} income "
                f"to cover your Rs {totals['expenses']['total']:,.0f} in expenses."
            )

    def answer_groceries(self, totals):
        items = {k.lower(): v for k, v in totals["expenses"]["items"].items()}
        monthly = items.get("groceries", 0)
        weekly = monthly / self.WEEKLY_TO_MONTHLY
        return f"You spend Rs {monthly:,.0f} per month on groceries (Rs {weekly:,.0f} per week, 4 weeks/month)."

    @staticmethod
    def normalize_category(category, lowercase=True):
        if lowercase:
            category = category.lower().strip()
        mapping = {
            "rent": "rent", "groceries": "groceries", "grocery": "groceries",
            "shopping": "shopping", "transport": "transport", "travel": "transport",
            "food": "groceries", "utilities": "rent",
        }
        return mapping.get(category, category)

