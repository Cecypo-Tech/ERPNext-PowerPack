"""Whitelisted endpoints for Quick Pay. The two flows (cash/bank/card vs
Mpesa) are gated by separate PowerPack Settings flags; both still live in
this single module to keep the imports tidy.
"""

from __future__ import annotations

import json as _json

import frappe
from frappe import _

from cecypo_powerpack.quick_pay import builders, validators
from cecypo_powerpack.utils import get_powerpack_settings


def _user_permitted_mops(user: str) -> list[str] | None:
	perms = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Mode of Payment"},
		fields=["for_value"],
	)
	if not perms:
		return None  # no restriction
	return [p["for_value"] for p in perms]


@frappe.whitelist()
def get_payment_modes(company: str) -> dict:
	"""Categorize enabled Modes of Payment that have an account in `company`."""
	validators.assert_quick_pay_enabled("cash")

	permitted = _user_permitted_mops(frappe.session.user)

	rows = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": company},
		fields=["parent", "default_account"],
	)
	candidates = sorted({r["parent"] for r in rows if r.get("default_account")})

	result = {"cash_modes": [], "bank_modes": [], "card_modes": []}

	for name in candidates:
		if permitted is not None and name not in permitted:
			continue
		mop = frappe.get_cached_doc("Mode of Payment", name)
		if not mop.enabled:
			continue
		mop_type = (mop.type or "").strip()
		lname = name.lower()
		if mop_type == "Phone":
			continue
		if mop_type == "Cash" or lname == "cash":
			result["cash_modes"].append(name)
		elif mop_type == "Bank" or "bank" in lname or "transfer" in lname:
			result["bank_modes"].append(name)
		elif mop_type == "Card" or any(k in lname for k in ("card", "credit", "debit")):
			result["card_modes"].append(name)
	return result


@frappe.whitelist()
def process_quick_pay(
	sales_order: str,
	customer: str,
	payments_json: str,
	outstanding_amount: float,
	create_invoice: int = 0,
	submit_invoice: int = 0,
	idempotency_token: str = "",
) -> dict:
	"""Process Cash/Bank/Card payments against a Sales Order, optionally
	creating + submitting a Sales Invoice afterwards."""
	validators.assert_quick_pay_enabled("cash")
	create_invoice = int(create_invoice or 0)
	submit_invoice = int(submit_invoice or 0)
	validators.assert_can_create_payment_and_invoice(create_invoice, submit_invoice)
	validators.claim_idempotency_token(idempotency_token)

	if not sales_order or not payments_json:
		frappe.throw(_("Missing required parameters"))

	payments = _json.loads(payments_json)
	if not isinstance(payments, list) or not payments:
		frappe.throw(_("No payments provided"))

	so = frappe.get_doc("Sales Order", sales_order)
	settings = get_powerpack_settings()
	update_stock = 1 if settings.get("qp_update_stock_on_invoice") else 0

	if create_invoice:
		issues = validators.preflight_stock_for_so(so)
		if issues:
			frappe.throw(_("Cannot create invoice — fix stock first:\n• ") + "\n• ".join(issues))

	precision = so.precision("grand_total")
	actual_outstanding = validators.compute_outstanding(so.grand_total, so.advance_paid, precision)
	remaining = actual_outstanding

	payment_entries: list[dict] = []
	cash_amount = 0.0
	total_paid = 0.0

	for p in payments:
		p_type = p.get("type")
		p_amount = float(p.get("amount") or 0)
		p_mode = p.get("mode_of_payment") or p_type
		p_ref = p.get("reference") or ""

		if p_amount <= 0:
			continue
		if p_type not in {"Cash", "Bank Transfer", "Card"}:
			continue
		if p_type in {"Bank Transfer", "Card"} and not p_ref:
			frappe.throw(_("Reference number required for {0}").format(p_type))

		if p_type == "Cash":
			cash_amount = p_amount

		allocated = validators.cap_allocation(p_amount, remaining, precision)
		if allocated <= 0:
			continue

		pe = builders.build_payment_entry(
			so_doc=so,
			amount=allocated,
			mode_of_payment=p_mode,
			reference_no=p_ref or None,
			remarks=f"{p_type} payment for {so.name}",
		)
		pe.insert(ignore_permissions=True)
		pe.submit()

		payment_entries.append({
			"name": pe.name,
			"type": p_type,
			"amount": allocated,
		})
		total_paid += allocated
		remaining = validators.normalize_amount(remaining - allocated, precision)

	if not payment_entries:
		frappe.throw(_("No valid payments could be created"))

	non_cash = total_paid - min(cash_amount, actual_outstanding)
	cash_needed = actual_outstanding - non_cash
	change_amount = max(0.0, cash_amount - cash_needed) if cash_amount > 0 else 0.0

	result = {
		"success": True,
		"payment_entries": payment_entries,
		"total_paid": total_paid,
		"change_amount": change_amount,
	}

	if create_invoice and remaining <= 0:
		so.reload()
		si = builders.build_sales_invoice(so, update_stock=update_stock)
		si.insert(ignore_permissions=True)
		if submit_invoice:
			si.submit()
		result["sales_invoice"] = {
			"name": si.name,
			"submitted": si.docstatus == 1,
		}

	return result
