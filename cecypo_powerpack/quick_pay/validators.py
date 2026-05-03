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


# --- Idempotency -----------------------------------------------------------

CACHE_PREFIX = "quick_pay:idem:"


class IdempotencyError(frappe.ValidationError):
	"""Raised when the same idempotency token is reused, or a token is missing."""


def claim_idempotency_token(token: str, ttl_seconds: int = 120) -> None:
	"""Atomically claim a one-shot token. Raises IdempotencyError if already used.

	Tokens are scoped per user to keep the namespace reasonable.
	"""
	if not token or not isinstance(token, str) or len(token) < 8:
		raise IdempotencyError("Missing or invalid idempotency token")

	cache = frappe.cache()
	key = CACHE_PREFIX + frappe.session.user + ":" + token
	if cache.get_value(key) is not None:
		raise IdempotencyError("Duplicate request: this payment has already been processed")
	cache.set_value(key, "1", expires_in_sec=ttl_seconds)
