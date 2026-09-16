# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""One call with everything a salesperson needs about a customer's money position.

The same shape is served by cecypo_frappe_reports' Transaction History page, so
the two dialogs read alike. Figures here are as of today, straight from
submitted Sales Invoices and Payment Entries.
"""

import frappe
from frappe.utils import flt, getdate, today

MAX_CONTACTS = 3


def _allowed_values(doctype):
	"""None when the user has no User Permission rows for doctype, else the allowed names."""
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions

	rows = get_user_permissions().get(doctype)
	return None if not rows else {r.get("doc") for r in rows}


def check_snapshot_access(customer, company=None):
	"""The snapshot shows the customer's full position, so it checks what still matters:
	the user can read this customer, and is not restricted away from this company."""
	frappe.has_permission("Customer", "read", doc=customer, throw=True)
	allowed_companies = _allowed_values("Company")
	if company and allowed_companies is not None and company not in allowed_companies:
		frappe.throw(frappe._("Not permitted for company {0}").format(company), frappe.PermissionError)


def highlight_for(overdue_count, outstanding_total, advances_total):
	if overdue_count > 0:
		return "red"
	if flt(outstanding_total) > 0 or flt(advances_total) > 0:
		return "amber"
	return ""


def _contacts(customer):
	links = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
		fields=["parent"],
		limit=10,
	)
	contacts = []
	for link in links:
		c = frappe.db.get_value(
			"Contact", link.parent,
			["first_name", "last_name", "email_id", "phone", "mobile_no", "is_primary_contact"],
			as_dict=True,
		)
		if c:
			contacts.append(
				{
					"name": " ".join(filter(None, [c.first_name, c.last_name])),
					"email": c.email_id or "",
					"phone": c.mobile_no or c.phone or "",
					"is_primary": int(c.is_primary_contact or 0),
				}
			)
	contacts.sort(key=lambda c: c["is_primary"], reverse=True)
	return contacts[:MAX_CONTACTS]


def build_customer_snapshot(customer, company=None, as_of=None):
	as_of = getdate(as_of or today())

	filters = {"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0.001]}
	if company:
		filters["company"] = company
	invoices = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", "posting_date", "due_date", "grand_total", "rounded_total", "outstanding_amount", "currency", "status"],
		order_by="due_date asc, posting_date asc",
	)
	for inv in invoices:
		due = getdate(inv.due_date or inv.posting_date)
		inv["days_overdue"] = max(0, (as_of - due).days)
		invoiced = flt(inv.rounded_total) or flt(inv.grand_total)
		inv["outstanding_amount"] = flt(inv.outstanding_amount, 2)
		inv["grand_total"] = flt(invoiced, 2)
		inv["paid"] = flt(max(invoiced - flt(inv.outstanding_amount), 0), 2)
		inv.pop("rounded_total", None)
	invoices.sort(key=lambda r: (-r["days_overdue"], str(r["due_date"] or r["posting_date"])))

	pe_filters = {
		"docstatus": 1, "payment_type": "Receive", "party_type": "Customer", "party": customer,
		"unallocated_amount": [">", 0.001],
	}
	if company:
		pe_filters["company"] = company
	advances = frappe.get_all(
		"Payment Entry",
		filters=pe_filters,
		fields=["name", "posting_date", "paid_amount", "unallocated_amount"],
		order_by="posting_date desc",
	)
	for adv in advances:
		adv["paid_amount"] = flt(adv.paid_amount, 2)
		adv["unallocated_amount"] = flt(adv.unallocated_amount, 2)

	outstanding_total = flt(sum(r["outstanding_amount"] for r in invoices), 2)
	overdue = [r for r in invoices if r["days_overdue"] > 0]
	overdue_total = flt(sum(r["outstanding_amount"] for r in overdue), 2)
	advances_total = flt(sum(a["unallocated_amount"] for a in advances), 2)

	doc = frappe.db.get_value(
		"Customer", customer, ["customer_name", "email_id", "mobile_no", "payment_terms"], as_dict=True
	) or {}
	contacts = _contacts(customer)
	primary = next((c for c in contacts if c["email"] or c["phone"]), None)
	if not primary and (doc.get("email_id") or doc.get("mobile_no")):
		primary = {"name": doc.get("customer_name") or customer, "email": doc.get("email_id") or "", "phone": doc.get("mobile_no") or ""}

	credit_limit = None
	if company:
		credit_limit = frappe.db.get_value(
			"Customer Credit Limit", {"parent": customer, "company": company}, "credit_limit"
		)
		credit_limit = flt(credit_limit, 2) if credit_limit is not None else None

	currency = invoices[0].currency if invoices else (
		frappe.get_cached_value("Company", company, "default_currency") if company else None
	)

	return {
		"customer": customer,
		"customer_name": doc.get("customer_name") or customer,
		"company": company,
		"currency": currency,
		"primary_contact": primary,
		"contacts": contacts,
		"credit_limit": credit_limit,
		"payment_terms": doc.get("payment_terms"),
		"outstanding_total": outstanding_total,
		"overdue_total": overdue_total,
		"overdue_count": len(overdue),
		"advances_total": advances_total,
		"net_position": flt(outstanding_total - advances_total, 2),
		"invoices": invoices,
		"advances": advances,
		"highlight": highlight_for(len(overdue), outstanding_total, advances_total),
	}
