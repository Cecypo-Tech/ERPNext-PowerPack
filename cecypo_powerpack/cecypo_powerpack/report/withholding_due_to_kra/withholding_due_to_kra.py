# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
	"""Withholding rows of submitted Payment Entries. Works with the feature off."""
	filters = frappe._dict(filters or {})
	if not filters.company:
		return get_columns(), [], None, None, []

	W = frappe.qb.DocType("Payment Entry Withholding")
	PE = frappe.qb.DocType("Payment Entry")
	S = frappe.qb.DocType("Supplier")
	q = (
		frappe.qb.from_(W)
		.join(PE).on(W.parent == PE.name)
		.left_join(S).on(S.name == PE.party)
		.select(
			W.name.as_("row_name"), PE.party.as_("supplier"), S.tax_id, W.purchase_invoice, W.purchase_order, W.bill_no,
			W.bill_date, PE.name.as_("payment_entry"), PE.posting_date, W.base_amount, W.rate, W.amount,
			W.account, W.is_vat, W.due_date, W.kra_journal_entry,
		)
		.where((W.parenttype == "Payment Entry") & (PE.docstatus == 1) & (PE.company == filters.company))
		.orderby(W.due_date).orderby(PE.posting_date).orderby(PE.name).orderby(W.idx)
	)
	if filters.account:
		q = q.where(W.account == filters.account)
	unpaid = W.kra_journal_entry.isnull() | (W.kra_journal_entry == "")
	status = filters.status or "Unpaid"
	if status == "Unpaid":
		q = q.where(unpaid)
	elif status == "Paid":
		q = q.where(~unpaid)
	if filters.from_date:
		q = q.where(PE.posting_date >= filters.from_date)
	if filters.to_date:
		q = q.where(PE.posting_date <= filters.to_date)

	today = getdate()
	data = q.run(as_dict=True)
	for r in data:
		if r.purchase_order and not r.purchase_invoice:
			r.bill_no = _("Awaiting invoice")
		r.overdue = 1 if not r.kra_journal_entry and r.due_date and getdate(r.due_date) < today else 0
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	return get_columns(), data, None, None, account_cards(data, currency)


def account_cards(data, currency):
	"""One card per account: what is still unpaid among the rows shown, red when any of it is overdue. The
	last card, Selected, is updated in the browser as rows are ticked."""
	due, overdue = {}, set()
	for r in data:
		if r["kra_journal_entry"]:
			continue
		due[r["account"]] = due.get(r["account"], 0) + r["amount"]
		if r["overdue"]:
			overdue.add(r["account"])
	card = {"datatype": "Currency", "currency": currency}
	return [
		{**card, "label": account, "value": value, "indicator": "Red" if account in overdue else "Blue"}
		for account, value in due.items()
	] + [{**card, "label": _("Selected"), "value": 0, "indicator": "Green"}]


def get_columns():
	return [
		{"fieldname": "row_name", "label": _("Row"), "fieldtype": "Data", "hidden": 1},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"fieldname": "tax_id", "label": _("PIN"), "fieldtype": "Data", "width": 120},
		{"fieldname": "purchase_invoice", "label": _("Purchase Invoice"), "fieldtype": "Link",
			"options": "Purchase Invoice", "width": 150},
		{"fieldname": "purchase_order", "label": _("Purchase Order"), "fieldtype": "Link",
			"options": "Purchase Order", "width": 150},
		{"fieldname": "bill_no", "label": _("Invoice No"), "fieldtype": "Data", "width": 110},
		{"fieldname": "bill_date", "label": _("Invoice Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "payment_entry", "label": _("Payment Entry"), "fieldtype": "Link",
			"options": "Payment Entry", "width": 150},
		{"fieldname": "posting_date", "label": _("Payment Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "base_amount", "label": _("Base"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "rate", "label": _("Rate %"), "fieldtype": "Percent", "width": 70},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "account", "label": _("Account"), "fieldtype": "Link", "options": "Account", "width": 160},
		{"fieldname": "is_vat", "label": _("VAT"), "fieldtype": "Check", "width": 50},
		{"fieldname": "due_date", "label": _("Due Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "kra_journal_entry", "label": _("KRA Journal Entry"), "fieldtype": "Link",
			"options": "Journal Entry", "width": 150},
		{"fieldname": "overdue", "label": _("Overdue"), "fieldtype": "Check", "width": 70},
	]
