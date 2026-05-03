"""Pure-ish helpers used by quick_pay/api.py.

Kept side-effect-free so they're easy to unit-test. DB-touching helpers
(stock pre-check, permission gate, idempotency) are below the precision
section and clearly marked.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


# --- Precision -------------------------------------------------------------

def normalize_amount(value, precision: int = 2) -> float:
	"""Round a money amount to currency precision, killing IEEE-754 drift."""
	return flt(value, precision)


def compute_outstanding(grand_total, advance_paid, precision: int = 2) -> float:
	"""Outstanding for a Sales Order, rounded to currency precision."""
	return flt(flt(grand_total) - flt(advance_paid or 0), precision)


def cap_allocation(amount, outstanding, precision: int = 2) -> float:
	"""Cap an allocation to outstanding so float drift can never push the
	Payment Entry's allocated_amount over outstanding_amount."""
	amount = flt(amount, precision)
	outstanding = flt(outstanding, precision)
	return min(amount, outstanding)
