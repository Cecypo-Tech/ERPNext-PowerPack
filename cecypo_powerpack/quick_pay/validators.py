"""Pure-ish helpers used by quick_pay/api.py.

Kept side-effect-free so they're easy to unit-test. DB-touching helpers
(stock pre-check, permission gate, idempotency) are below the precision
section and clearly marked.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

# --- Precision -------------------------------------------------------------


def normalize_amount(value, precision: int = 2) -> float:
	"""Round a money amount to currency precision, killing IEEE-754 drift."""
	return flt(value, precision)


def effective_total(so_doc) -> float:
	"""The amount ERPNext actually treats as due on a Sales Order.

	Mirrors the `rounded_total or grand_total` pattern used throughout
	erpnext (e.g. `get_orders_to_be_billed`, `set_grand_total_and_outstanding_amount`
	in payment_entry.py) for computing a voucher's real outstanding ceiling.
	Using `grand_total` alone overstates that ceiling once rounding is
	enabled, since `advance_paid` accumulates against the rounded total —
	allocating the unrounded difference then fails Payment Entry's own
	"Allocated Amount cannot be greater than outstanding amount" check.
	"""
	return flt(so_doc.rounded_total) or flt(so_doc.grand_total)


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


def claim_idempotency_token(token: str, ttl_seconds: int = 15) -> None:
	"""Atomically claim a one-shot token. Raises IdempotencyError if already used.

	Tokens are scoped per user to keep the namespace reasonable.
	TTL is intentionally short (15s) to block double-clicks without locking
	operators out after a genuine server-side failure.
	"""
	if not token or not isinstance(token, str) or len(token) < 8:
		raise IdempotencyError("Missing or invalid idempotency token")

	cache = frappe.cache()
	key = CACHE_PREFIX + frappe.session.user + ":" + token
	if cache.get_value(key) is not None:
		raise IdempotencyError("Duplicate request: this payment has already been processed")
	cache.set_value(key, "1", expires_in_sec=ttl_seconds)


# --- Stock pre-check -------------------------------------------------------


def preflight_stock_for_so(so_doc) -> list[str]:
	"""Return human-readable issues that would cause Sales Invoice (with
	update_stock=1) to fail. Empty list = OK to proceed.

	NOTE: Only catches issues knowable at SO time. If user races against
	another transaction draining the warehouse between this check and the
	invoice insert, that race is unhandled (caught by the SI submit
	validation). Acceptable for v1.

	TESTING TRADE-OFF: Unit tests only cover the trivial "no stock items →
	empty" path. Stock-shortage, batch, and serial cases require real Bin
	records and item configuration — full fixturing is heavyweight and brittle.
	Those cases are deferred to manual verification (Task 19).
	"""
	issues: list[str] = []

	for row in so_doc.items:
		meta = frappe.db.get_value(
			"Item",
			row.item_code,
			["is_stock_item", "has_batch_no", "has_serial_no"],
			as_dict=True,
		)
		if not meta or not meta.is_stock_item:
			continue

		warehouse = getattr(row, "warehouse", None)
		if not warehouse:
			issues.append(f"{row.item_code}: no warehouse set on Sales Order line")
			continue

		actual_qty = (
			frappe.db.get_value(
				"Bin",
				{"item_code": row.item_code, "warehouse": warehouse},
				"actual_qty",
			)
			or 0
		)
		needed = flt(row.qty)
		if flt(actual_qty) < needed:
			issues.append(f"{row.item_code}: only {flt(actual_qty)} available at {warehouse}, need {needed}")

		if meta.has_batch_no and not getattr(row, "batch_no", None):
			issues.append(f"{row.item_code}: requires a batch but none set on Sales Order line")

		if meta.has_serial_no and not getattr(row, "serial_no", None):
			issues.append(f"{row.item_code}: requires serial numbers but none set")

	return issues


# --- Feature toggle / permission gates -------------------------------------

from cecypo_powerpack.utils import is_feature_enabled


def assert_quick_pay_enabled(flow: str) -> None:
	"""flow: 'cash' | 'mpesa'"""
	flag = "enable_quick_pay" if flow == "cash" else "enable_quick_pay_mpesa"
	if not is_feature_enabled(flag):
		frappe.throw(f"Quick Pay ({flow}) is disabled in PowerPack Settings")


def _can_submit_as_owner(doctype: str) -> bool:
	"""Return True if the current user has submit rights on documents they own.

	`frappe.has_permission(..., "submit")` without a doc has no owner context,
	so it returns False for roles where submit is restricted to "if owner".
	We explicitly pass is_owner=True since the user always owns docs they create.
	"""
	from frappe.permissions import get_role_permissions

	perms = get_role_permissions(frappe.get_meta(doctype), is_owner=True)
	return bool(perms.get("submit") or perms.get("if_owner", {}).get("submit"))


def assert_can_process_quick_pay(so_doc, create_invoice: bool, submit_invoice: bool) -> None:
	"""Quick Pay creates (and amends) Payment Entries with ignore_permissions,
	because the Sales role intentionally has no direct Payment Entry access —
	finance keeps that locked down so reps can't browse to the PE list and
	create ad-hoc entries. Checking `frappe.has_permission("Payment Entry", ...)`
	here would therefore always fail by design and isn't the real authorization
	boundary anyway: the boundary is "can this user act on this Sales Order".
	"""
	if not frappe.has_permission("Sales Order", "write", so_doc):
		frappe.throw(_("You do not have permission to record payments against this Sales Order"))
	if create_invoice:
		if not frappe.has_permission("Sales Invoice", "create"):
			frappe.throw(_("You do not have permission to create Sales Invoice"))
		if submit_invoice and not _can_submit_as_owner("Sales Invoice"):
			frappe.throw(_("You do not have permission to submit Sales Invoice"))
