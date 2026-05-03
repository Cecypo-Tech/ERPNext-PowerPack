"""Whitelisted endpoints for Quick Pay. The two flows (cash/bank/card vs
Mpesa) are gated by separate PowerPack Settings flags; both still live in
this single module to keep the imports tidy.
"""

from __future__ import annotations

import frappe
from frappe import _

from cecypo_powerpack.quick_pay import validators


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
