"""Payment Entry and Sales Invoice builders for Quick Pay.

Both builders return *unsaved* documents — caller decides when to insert/submit.
This makes test isolation easier and lets the API layer wrap insert/submit
inside its idempotency / pre-flight logic.
"""

from __future__ import annotations

import frappe
from erpnext.accounts.party import get_party_account
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from frappe.utils import flt, nowdate

from cecypo_powerpack.quick_pay.validators import (
	cap_allocation,
	compute_outstanding,
)


def build_payment_entry(
	so_doc,
	amount: float,
	mode_of_payment: str,
	reference_no: str | None = None,
	remarks: str | None = None,
	*,
	full_received_amount: float | None = None,
):
	"""Build (but don't save) a Payment Entry against a Sales Order.

	`amount` is what to allocate to the SO. `full_received_amount` (Mpesa-only)
	is the total received when it exceeds the SO outstanding — the PE records
	the full amount but only allocates `amount` to this SO. If None, defaults
	to `amount` (cash/bank/card path).
	"""
	company = so_doc.company
	customer = so_doc.customer

	if full_received_amount is None:
		full_received_amount = amount

	paid_to = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not paid_to:
		frappe.throw(f"No account for Mode of Payment {mode_of_payment} in {company}")

	paid_from = get_party_account("Customer", customer, company)

	company_currency = frappe.db.get_value("Company", company, "default_currency")
	paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency
	paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency

	precision = so_doc.precision("grand_total")
	outstanding = compute_outstanding(so_doc.grand_total, so_doc.advance_paid, precision)
	allocated = cap_allocation(amount, outstanding, precision)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive"
	pe.mode_of_payment = mode_of_payment
	pe.party_type = "Customer"
	pe.party = customer
	pe.party_name = so_doc.customer_name or customer
	pe.company = company
	pe.posting_date = nowdate()
	pe.paid_from = paid_from
	pe.paid_to = paid_to
	pe.paid_from_account_currency = paid_from_currency
	pe.paid_to_account_currency = paid_to_currency
	pe.paid_amount = flt(full_received_amount, precision)
	pe.received_amount = flt(full_received_amount, precision)
	pe.reference_no = reference_no or so_doc.name
	pe.reference_date = nowdate()
	pe.remarks = remarks or f"Payment for {so_doc.name}"

	pe.append(
		"references",
		{
			"reference_doctype": "Sales Order",
			"reference_name": so_doc.name,
			"due_date": so_doc.delivery_date or nowdate(),
			"total_amount": flt(so_doc.grand_total, precision),
			"outstanding_amount": outstanding,
			"allocated_amount": allocated,
		},
	)

	return pe


def build_sales_invoice(so_doc, *, update_stock: int = 0):
	"""Build (but don't save) a Sales Invoice from a Sales Order using the
	official ERPNext mapper. Caller is responsible for insert/submit.
	"""
	si = make_sales_invoice(so_doc.name, ignore_permissions=True)
	si.update_stock = 1 if update_stock else 0
	si.allocate_advances_automatically = 1
	return si
