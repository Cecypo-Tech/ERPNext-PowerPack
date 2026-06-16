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
def get_unallocated_payments(customer: str, company: str) -> list[dict]:
	"""Return submitted Payment Entries for the customer that have unallocated amounts."""
	validators.assert_quick_pay_enabled("cash")
	if not customer or not company:
		return []
	return frappe.get_all(
		"Payment Entry",
		filters={
			"party_type": "Customer",
			"party": customer,
			"docstatus": 1,
			"payment_type": "Receive",
			"unallocated_amount": [">", 0],
			"company": company,
		},
		fields=["name", "posting_date", "mode_of_payment", "paid_amount", "unallocated_amount", "reference_no"],
		order_by="posting_date asc",
	)


def _apply_credit_to_so(pe_name: str, so_doc, amount: float, precision: int) -> dict | None:
	"""Cancel+amend an unallocated Payment Entry to add an allocation to the Sales Order."""
	pe = frappe.get_doc("Payment Entry", pe_name)
	if pe.docstatus != 1:
		frappe.throw(_("Payment Entry {0} is not submitted").format(pe_name))
	if pe.party_type != "Customer" or pe.party != so_doc.customer:
		frappe.throw(_("Payment Entry {0} does not belong to this customer").format(pe_name))

	unalloc = float(pe.unallocated_amount or 0)
	if unalloc <= 0:
		return None

	allocated = validators.cap_allocation(amount, unalloc, precision)
	if allocated <= 0:
		return None

	pe.flags.ignore_permissions = True
	pe.cancel()

	total = validators.effective_total(so_doc)
	amended = frappe.copy_doc(pe)
	amended.docstatus = 0
	amended.amended_from = pe.name
	amended.append(
		"references",
		{
			"reference_doctype": "Sales Order",
			"reference_name": so_doc.name,
			"allocated_amount": allocated,
			"due_date": so_doc.delivery_date or frappe.utils.nowdate(),
			"total_amount": total,
			"outstanding_amount": total - float(so_doc.advance_paid),
		},
	)
	amended.insert(ignore_permissions=True)
	amended.submit()

	return {"original_pe": pe_name, "amended_pe": amended.name, "amount": allocated}


@frappe.whitelist()
def process_quick_pay(
	sales_order: str,
	customer: str,
	payments_json: str,
	outstanding_amount: float,
	create_invoice: int = 0,
	submit_invoice: int = 0,
	idempotency_token: str = "",
	credits_json: str = "",
) -> dict:
	"""Process Cash/Bank/Card payments against a Sales Order, optionally
	creating + submitting a Sales Invoice afterwards."""
	validators.assert_quick_pay_enabled("cash")
	create_invoice = int(create_invoice or 0)
	submit_invoice = int(submit_invoice or 0)
	validators.claim_idempotency_token(idempotency_token)

	if not sales_order or not payments_json:
		frappe.throw(_("Missing required parameters"))

	payments = _json.loads(payments_json)
	if not isinstance(payments, list) or not payments:
		frappe.throw(_("No payments provided"))

	so = frappe.get_doc("Sales Order", sales_order)
	validators.assert_can_process_quick_pay(so, create_invoice, submit_invoice)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not submitted").format(sales_order))
	if so.status in ("Closed", "Cancelled"):
		frappe.throw(_("Cannot process payment for a {0} Sales Order").format(so.status))

	precision = so.precision("grand_total")
	actual_outstanding = validators.compute_outstanding(
		validators.effective_total(so), so.advance_paid, precision
	)
	remaining = actual_outstanding

	payment_entries: list[dict] = []
	credits_applied: list[dict] = []
	cash_tendered = 0.0  # raw amount the customer hands over (may exceed outstanding)
	cash_allocated = 0.0  # portion of cash actually applied to the balance
	total_paid = 0.0

	# Apply unallocated payments (credits) first, before processing new payments.
	if credits_json:
		credits = _json.loads(credits_json)
		for c in credits:
			c_pe = c.get("pe_name")
			c_amt = float(c.get("amount") or 0)
			if not c_pe or c_amt <= 0 or remaining <= 0:
				continue
			result = _apply_credit_to_so(c_pe, so, min(c_amt, remaining), precision)
			if result:
				credits_applied.append(result)
				total_paid += result["amount"]
				remaining = validators.normalize_amount(remaining - result["amount"], precision)
		if credits_applied:
			so.reload()

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

		allocated = validators.cap_allocation(p_amount, remaining, precision)

		if p_type == "Cash":
			cash_tendered += p_amount
			cash_allocated += allocated
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

		payment_entries.append(
			{
				"name": pe.name,
				"type": p_type,
				"amount": allocated,
			}
		)
		total_paid += allocated
		remaining = validators.normalize_amount(remaining - allocated, precision)

	if not payment_entries and not credits_applied:
		frappe.throw(_("No valid payments could be created"))

	change_amount = max(0.0, cash_tendered - cash_allocated)

	result = {
		"success": True,
		"payment_entries": payment_entries,
		"credits_applied": credits_applied,
		"total_paid": total_paid,
		"change_amount": change_amount,
	}

	if create_invoice and remaining <= 0:
		so.reload()
		si = builders.build_sales_invoice(so)
		si.insert()
		builders.sync_so_party_fields(si, so)
		if submit_invoice:
			si.submit()
		result["sales_invoice"] = {
			"name": si.name,
			"submitted": si.docstatus == 1,
		}

	return result


def _phone_mop_for_company(company: str) -> str | None:
	rows = frappe.get_all(
		"Mode of Payment",
		filters={"type": "Phone", "enabled": 1},
		fields=["name"],
	)
	for row in rows:
		if frappe.db.exists("Mode of Payment Account", {"parent": row.name, "company": company}):
			return row.name
	return None


def _mpesa_shortcode_for_company(company: str) -> str | None:
	settings = frappe.get_all(
		"Mpesa Settings",
		filters={"company": company},
		fields=["business_shortcode"],
		limit=1,
	)
	if settings and settings[0].get("business_shortcode"):
		return str(settings[0]["business_shortcode"])
	return None


@frappe.whitelist()
def check_mpesa_available(company: str) -> dict:
	validators.assert_quick_pay_enabled("mpesa")
	return {"available": bool(_phone_mop_for_company(company) and _mpesa_shortcode_for_company(company))}


@frappe.whitelist()
def list_pending_mpesa_payments(company: str, search: str = "") -> dict:
	validators.assert_quick_pay_enabled("mpesa")
	shortcode = _mpesa_shortcode_for_company(company)
	if not shortcode:
		return {"count": 0, "payments": []}

	base_filters = {"docstatus": 0, "businessshortcode": shortcode}
	total_count = frappe.db.count("Mpesa C2B Payment Register", base_filters)

	payments: list[dict] = []
	if len(search) >= 3:
		s = f"%{search}%"
		payments = frappe.get_all(
			"Mpesa C2B Payment Register",
			filters=base_filters,
			or_filters=[
				["full_name", "like", s],
				["transid", "like", s],
				["billrefnumber", "like", s],
				["msisdn", "like", s],
			],
			fields=[
				"name",
				"full_name",
				"transamount",
				"transid",
				"msisdn",
				"posting_date",
				"billrefnumber",
				"creation",
			],
			order_by="creation desc",
			limit_page_length=100,
		)
	return {"count": total_count, "payments": payments}


@frappe.whitelist()
def process_mpesa_quick_pay(
	sales_order: str,
	customer: str,
	mpesa_payments: str,
	outstanding_amount: float,
	create_invoice: int = 0,
	submit_invoice: int = 0,
	idempotency_token: str = "",
) -> dict:
	validators.assert_quick_pay_enabled("mpesa")
	create_invoice = int(create_invoice or 0)
	submit_invoice = int(submit_invoice or 0)
	validators.claim_idempotency_token(idempotency_token)

	mpesa_names = [n.strip() for n in (mpesa_payments or "").split(",") if n.strip()]
	if not mpesa_names:
		frappe.throw(_("No Mpesa payments selected"))

	so = frappe.get_doc("Sales Order", sales_order)
	validators.assert_can_process_quick_pay(so, create_invoice, submit_invoice)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not submitted").format(sales_order))
	if so.status in ("Closed", "Cancelled"):
		frappe.throw(_("Cannot process payment for a {0} Sales Order").format(so.status))

	phone_mop = _phone_mop_for_company(so.company)
	if not phone_mop:
		frappe.throw(_("No Phone-type Mode of Payment configured for {0}").format(so.company))
	shortcode = _mpesa_shortcode_for_company(so.company)
	if not shortcode:
		frappe.throw(_("No Mpesa Settings for {0}").format(so.company))

	precision = so.precision("grand_total")
	remaining = validators.compute_outstanding(validators.effective_total(so), so.advance_paid, precision)

	payment_entries: list[dict] = []
	mpesa_results: list[dict] = []

	for mpesa_name in mpesa_names:
		if remaining <= 0:
			break
		mpesa = frappe.get_doc("Mpesa C2B Payment Register", mpesa_name)
		if mpesa.docstatus != 0:
			continue
		if str(mpesa.businessshortcode or "") != shortcode:
			continue

		mpesa_amt = float(mpesa.transamount or 0)
		if mpesa_amt <= 0:
			continue
		allocated = validators.cap_allocation(mpesa_amt, remaining, precision)

		# Build & submit the PE FIRST.
		pe = builders.build_payment_entry(
			so_doc=so,
			amount=allocated,
			mode_of_payment=phone_mop,
			reference_no=mpesa_name,
			remarks=f"Mpesa payment: {mpesa_name}",
			full_received_amount=mpesa_amt,
		)
		pe.insert(ignore_permissions=True)
		pe.submit()

		# Now mark the Mpesa row as processed and link the PE.
		mpesa.customer = so.customer
		mpesa.company = so.company
		mpesa.mode_of_payment = phone_mop
		mpesa.submit_payment = 0
		mpesa.payment_entry = pe.name
		mpesa.save(ignore_permissions=True)
		mpesa.submit()

		payment_entries.append(
			{
				"name": pe.name,
				"type": "Mpesa",
				"amount": allocated,
				"full_amount": mpesa_amt,
			}
		)
		mpesa_results.append({"name": mpesa.name, "amount": mpesa_amt})
		remaining = validators.normalize_amount(remaining - allocated, precision)

	if not payment_entries:
		frappe.throw(_("No valid Mpesa payments processed"))

	result = {
		"success": True,
		"payment_entries": payment_entries,
		"mpesa_payments": mpesa_results,
		"total_amount": sum(p["amount"] for p in payment_entries),
	}

	if create_invoice and remaining <= 0:
		so.reload()
		si = builders.build_sales_invoice(so)
		si.insert()
		builders.sync_so_party_fields(si, so)
		if submit_invoice:
			si.submit()
		result["sales_invoice"] = {"name": si.name, "submitted": si.docstatus == 1}

	return result


@frappe.whitelist()
def get_customer_phone(customer: str) -> str:
	validators.assert_quick_pay_enabled("mpesa")
	if not customer:
		return ""
	contact = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
		"parent",
	)
	if contact:
		for field in ("mobile_no", "phone"):
			phone = frappe.db.get_value("Contact", contact, field)
			if phone:
				return phone
	return frappe.db.get_value("Customer", customer, "mobile_no") or ""


@frappe.whitelist()
def create_mpesa_payment_request(
	sales_order: str,
	customer: str,
	phone_number: str,
	amount: float,
) -> dict:
	validators.assert_quick_pay_enabled("mpesa")
	if not (sales_order and phone_number and float(amount) > 0):
		frappe.throw(_("Missing required parameters"))

	so = frappe.get_doc("Sales Order", sales_order)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not submitted").format(sales_order))
	if so.status in ("Closed", "Cancelled"):
		frappe.throw(_("Cannot process payment for a {0} Sales Order").format(so.status))

	precision = so.precision("grand_total")
	outstanding = validators.compute_outstanding(validators.effective_total(so), so.advance_paid, precision)
	safe_amount = validators.cap_allocation(float(amount), outstanding, precision)
	if safe_amount <= 0:
		frappe.throw(_("No outstanding amount on this Sales Order"))

	settings = frappe.get_all(
		"Mpesa Settings",
		filters={"company": so.company},
		fields=["name", "payment_gateway_name"],
		limit=1,
	)
	if not settings:
		frappe.throw(_("No Mpesa Settings for {0}").format(so.company))
	gateway_name = settings[0].get("payment_gateway_name") or settings[0].get("name")

	gateway_account = frappe.db.get_value(
		"Payment Gateway Account",
		{"payment_gateway": gateway_name},
		["name", "payment_account", "payment_gateway"],
		as_dict=True,
	)
	if not gateway_account:
		rows = frappe.get_all(
			"Payment Gateway Account",
			filters={"payment_gateway": ["like", "%Mpesa%"]},
			fields=["name", "payment_gateway", "payment_account"],
			limit=1,
		)
		if rows:
			gateway_account = rows[0]
	if not gateway_account:
		frappe.throw(_("No Payment Gateway Account found for Mpesa"))

	pr = frappe.new_doc("Payment Request")
	pr.payment_request_type = "Inward"
	pr.transaction_date = frappe.utils.nowdate()
	pr.phone_number = phone_number
	pr.company = so.company
	pr.party_type = "Customer"
	pr.party = so.customer
	pr.reference_doctype = "Sales Order"
	pr.reference_name = sales_order
	pr.grand_total = safe_amount
	pr.currency = so.currency
	pr.outstanding_amount = safe_amount
	pr.payment_gateway_account = gateway_account.get("name")
	pr.payment_gateway = gateway_account.get("payment_gateway") or gateway_name
	pr.payment_account = gateway_account.get("payment_account")
	pr.payment_channel = "Phone"
	pr.mode_of_payment = _phone_mop_for_company(so.company)
	pr.subject = f"Payment for {sales_order}"
	pr.message = f"Payment for {sales_order}"
	pr.mute_email = 1
	pr.make_sales_invoice = 0
	pr.insert(ignore_permissions=True)
	pr.submit()

	return {"success": True, "payment_request": pr.name}
