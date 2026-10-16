# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt, getdate

from cecypo_powerpack.utils import is_feature_enabled


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(
		{
			"Payment Entry": [
				{
					"fieldname": "cecypo_withholding",
					"label": "Withholding Details",
					"fieldtype": "Table",
					"options": "Payment Entry Withholding",
					"insert_after": "deductions",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
		update=True,
	)


def withheld(base, rate):
	"""Whole shillings, rounded up (iTax rounds up). Decimal, never float."""
	return math.ceil(Decimal(str(base)) * Decimal(str(rate)) / 100)


def invoice_withholding(invoice, allocated, supplier, rules, vat_accounts, exempt):
	"""One row per matching rule, in rule order. Pure: no DB."""
	share = Decimal(str(allocated)) / Decimal(str(invoice["total"]))
	rows = []
	for rule in rules:
		is_vat = rule["account"] in vat_accounts
		if (exempt and is_vat) or (rule.get("supplier") or supplier) != supplier:
			continue
		item = rule.get("item")
		lines = [i for i in invoice["items"] if not item or i["item_code"] == item]
		base = (sum(Decimal(str(i["base_net_amount"])) for i in lines) * share).quantize(
			Decimal("0.01"), ROUND_HALF_UP
		)
		amount = withheld(base, rule["rate"])
		if amount:
			rows.append(
				{
					"purchase_invoice": invoice["name"],
					"bill_no": invoice.get("bill_no"),
					"bill_date": invoice.get("bill_date"),
					"base_amount": float(base),
					"rate": rule["rate"],
					"account": rule["account"],
					"amount": amount,
					"is_vat": 1 if is_vat else 0,
				}
			)
	return rows


def vat_due_date(posting_date, holidays):
	"""Posting date + 5 working days (skips Sat/Sun and the given holidays)."""
	d, left = posting_date, 5
	while left:
		d += timedelta(days=1)
		if d.weekday() < 5 and d not in holidays:
			left -= 1
	return d


def income_tax_due_date(posting_date):
	"""20th of the month after posting."""
	y, m = divmod(posting_date.year * 12 + posting_date.month, 12)
	return date(y, m + 1, 20)


def apply_to_payment_entry(doc, method=None):
	"""before_validate on Payment Entry: ERPNext's validate then runs its amount setters on our values."""
	if doc.docstatus == 2 or doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	if not is_feature_enabled("enable_kenya_withholding"):
		return
	settings = frappe.get_single("PowerPack Settings")
	rules = [
		r.as_dict()
		for r in settings.withholding_rules
		if r.account and frappe.get_cached_value("Account", r.account, "company") == doc.company
	]
	if not rules:
		return
	rule_accounts = {r.account for r in rules}
	vat_accounts = {r.account for r in settings.withholding_vat_accounts}
	posting_date = getdate(doc.posting_date)
	exempt = any(
		e.supplier == doc.party and e.valid_until and posting_date <= getdate(e.valid_until)
		for e in settings.withholding_exemptions
	)

	rows = []
	for ref in doc.get("references"):
		if ref.reference_doctype != "Purchase Invoice" or flt(ref.allocated_amount) <= 0:
			continue
		pi = frappe.db.get_value(
			"Purchase Invoice", ref.reference_name,
			["name", "bill_no", "bill_date", "rounded_total", "grand_total"], as_dict=True,
		)
		total = pi and (flt(pi.rounded_total) or flt(pi.grand_total))
		if not total:
			continue
		pi["total"] = total
		pi["items"] = frappe.get_all(
			"Purchase Invoice Item", {"parent": pi.name}, ["item_code", "base_net_amount"], order_by="idx"
		)
		rows += invoice_withholding(pi, ref.allocated_amount, doc.party, rules, vat_accounts, exempt)

	own_deductions = [d for d in doc.get("deductions") if d.account in rule_accounts]
	if not rows and not own_deductions and not doc.get("cecypo_withholding"):
		return

	holidays = _holidays(doc.company)
	for r in rows:
		r["due_date"] = vat_due_date(posting_date, holidays) if r["is_vat"] else income_tax_due_date(posting_date)
	doc.set("cecypo_withholding", rows)

	for d in own_deductions:
		doc.remove(d)
	cost_center = frappe.get_cached_value("Company", doc.company, "cost_center")
	by_account = {}
	for r in rows:
		by_account.setdefault(r["account"], []).append(r)
	for account, acc_rows in by_account.items():
		rates = "/".join(dict.fromkeys(f"{flt(r['rate']):g}" for r in acc_rows))
		doc.append("deductions", {
			"account": account,
			"cost_center": cost_center,
			"amount": -sum(r["amount"] for r in acc_rows),
			"description": f"Withholding {rates}% on {', '.join(dict.fromkeys(r['bill_no'] or r['purchase_invoice'] for r in acc_rows))}",
		})

	if not (flt(doc.source_exchange_rate) and flt(doc.target_exchange_rate)):
		# Same calls ERPNext's validate makes next; needed here for an entry inserted without rates.
		doc.setup_party_account_field()
		doc.set_missing_values()
		doc.set_exchange_rate()

	# ponytail: no unallocated (advance) amount alongside withholding — paid is driven by allocations (spec).
	total_withheld = sum(r["amount"] for r in rows)
	# Rounded per row, as ERPNext's calculate_base_allocated_amount_for_reference does.
	base_allocated = sum(
		flt(flt(r.allocated_amount) * flt(doc.target_exchange_rate), doc.precision("base_paid_amount"))
		for r in doc.get("references")
	)
	# Unrounded on purpose: rounding a foreign-currency paid/received amount to 2dp leaves a difference.
	# Other deductions (bank charges, write-offs) count in ERPNext's difference, so the bank pays them too.
	other_deductions = sum(
		flt(d.amount) for d in doc.get("deductions")
		if d.account not in rule_accounts and not d.is_exchange_gain_loss
	)
	doc.paid_amount = (base_allocated - total_withheld + other_deductions) / flt(doc.source_exchange_rate)
	doc.received_amount = doc.paid_amount * flt(doc.source_exchange_rate) / flt(doc.target_exchange_rate)


def _holidays(company):
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	if not holiday_list:
		return set()
	return {getdate(d) for d in frappe.get_all("Holiday", {"parent": holiday_list}, pluck="holiday_date")}


@frappe.whitelist()
def compute_for_payment_entry(doc):
	"""Run the hook on an unsaved copy, for the form to show before saving."""
	frappe.has_permission("Payment Entry", "write", throw=True)
	pe = frappe.get_doc(frappe.parse_json(doc) if isinstance(doc, str) else doc)
	apply_to_payment_entry(pe)
	return {
		"cecypo_withholding": [r.as_dict() for r in pe.get("cecypo_withholding")],
		"deductions": [d.as_dict() for d in pe.get("deductions")],
		"paid_amount": pe.paid_amount,
		"received_amount": pe.received_amount,
		"base_paid_amount": flt(pe.paid_amount) * flt(pe.source_exchange_rate),
		"base_received_amount": flt(pe.received_amount) * flt(pe.target_exchange_rate),
	}


def prevent_cancel_if_paid_to_kra(doc, method=None):
	paid = [r.kra_journal_entry for r in doc.get("cecypo_withholding") if r.kra_journal_entry]
	if paid:
		frappe.throw(
			_("Withholding on this Payment Entry was paid to KRA by Journal Entry {0}. Cancel that first.").format(
				", ".join(dict.fromkeys(paid))
			)
		)


def merge_vat_rows(rows):
	"""VAT rows merged by (PIN, invoice no), as iTax takes them: base summed, posting date the latest,
	other fields from the first. Income tax rows are dropped. Pure: input dicts are not changed."""
	merged = {}
	for r in rows:
		if not r.get("is_vat"):
			continue
		# Blank PIN / bill no fall back to supplier / invoice so unrelated rows never merge.
		key = (r.get("tax_id") or r.get("supplier"), r.get("bill_no") or r.get("purchase_invoice"))
		m = merged.get(key)
		if not m:
			merged[key] = dict(r)
			continue
		m["base_amount"] = float(Decimal(str(m["base_amount"])) + Decimal(str(r["base_amount"])))
		if r.get("posting_date") and (not m.get("posting_date") or getdate(r["posting_date"]) > getdate(m["posting_date"])):
			m["posting_date"] = r["posting_date"]
	return list(merged.values())


@frappe.whitelist()
def pay_kra(row_names, bank_account: str, posting_date: str, prn: str, reference_date: str) -> str:
	"""One submitted Bank Entry paying the selected withholding rows to KRA. Works with the feature off."""
	frappe.only_for(["Accounts Manager", "Accounts User", "System Manager"])
	row_names = frappe.parse_json(row_names) if isinstance(row_names, str) else row_names
	row_names = list(dict.fromkeys(row_names or []))
	if not row_names:
		frappe.throw(_("Select the withholding rows to pay."))
	if not prn:
		frappe.throw(_("PRN is required."))

	W = frappe.qb.DocType("Payment Entry Withholding")
	PE = frappe.qb.DocType("Payment Entry")
	S = frappe.qb.DocType("Supplier")
	# Locked before the paid check, so two concurrent Pay KRA calls cannot both pass it.
	rows = (
		frappe.qb.from_(W)
		.join(PE).on(W.parent == PE.name)
		.left_join(S).on(S.name == PE.party)
		.select(
			W.name, W.account, W.amount, W.base_amount, W.rate, W.is_vat, W.bill_no, W.purchase_invoice,
			W.kra_journal_entry, PE.name.as_("payment_entry"), PE.company, PE.docstatus,
			PE.posting_date, PE.party.as_("supplier"), S.tax_id,
		)
		.where(W.name.isin(row_names) & (W.parenttype == "Payment Entry"))
		.for_update()
		.run(as_dict=True)
	)
	if len(rows) != len(row_names):
		frappe.throw(_("Some selected withholding rows no longer exist. Refresh the report."))
	if any(r.docstatus != 1 for r in rows):
		frappe.throw(_("Only withholding on submitted Payment Entries can be paid to KRA."))
	paid = list(dict.fromkeys(r.kra_journal_entry for r in rows if r.kra_journal_entry))
	if paid:
		frappe.throw(_("Some selected rows are already paid to KRA by Journal Entry {0}.").format(", ".join(paid)))
	companies = {r.company for r in rows}
	if len(companies) > 1:
		frappe.throw(_("Selected rows belong to more than one company: {0}.").format(", ".join(sorted(companies))))
	company = companies.pop()
	bank = frappe.get_cached_value("Account", bank_account, ["company", "account_type"], as_dict=True)
	if not bank or bank.company != company or bank.account_type not in ("Bank", "Cash"):
		frappe.throw(_("{0} is not a Bank or Cash account of {1}.").format(bank_account, company))

	debits = {}
	for r in rows:
		debits[r.account] = debits.get(r.account, 0) + flt(r.amount)
	# iTax's figure (the PRN): ceil per merged VAT invoice, not the sum of per-payment ceils.
	credit = sum(withheld(m["base_amount"], m["rate"]) for m in merge_vat_rows(rows)) + sum(
		flt(r.amount) for r in rows if not r.is_vat
	)
	accounts = [{"account": a, "debit_in_account_currency": v} for a, v in debits.items()]
	accounts.append({"account": bank_account, "credit_in_account_currency": credit})
	difference = flt(sum(debits.values()) - credit, 2)
	if difference:
		co = frappe.get_cached_value(
			"Company", company, ["round_off_account", "round_off_cost_center", "cost_center"], as_dict=True
		)
		if not co.round_off_account:
			frappe.throw(_("Set a Round Off Account on Company {0}.").format(company))
		accounts.append({
			"account": co.round_off_account,
			"cost_center": co.round_off_cost_center or co.cost_center,
			"credit_in_account_currency" if difference > 0 else "debit_in_account_currency": abs(difference),
		})

	payment_entries = ", ".join(dict.fromkeys(r.payment_entry for r in rows))
	je = frappe.get_doc({
		"doctype": "Journal Entry",
		"voucher_type": "Bank Entry",
		"company": company,
		"posting_date": posting_date,
		"cheque_no": prn,
		"cheque_date": reference_date,
		"user_remark": _("Withholding paid to KRA, PRN {0}. Payment Entries: {1}").format(prn, payment_entries),
		"accounts": accounts,
	})
	je.insert()
	je.submit()
	for r in rows:
		frappe.db.set_value("Payment Entry Withholding", r.name, "kra_journal_entry", je.name)
	return je.name


def allow_cancel_of_kra_payment(doc, method=None):
	"""Journal Entry before_cancel: submitted Payment Entries' withholding rows link here; clear_kra_link drops them."""
	if frappe.db.exists("Payment Entry Withholding", {"kra_journal_entry": doc.name}):
		doc.ignore_linked_doctypes = tuple(getattr(doc, "ignore_linked_doctypes", None) or ()) + ("Payment Entry",)


def clear_kra_link(doc, method=None):
	"""Journal Entry on_cancel: its withholding rows go back to Unpaid."""
	for name in frappe.get_all("Payment Entry Withholding", {"kra_journal_entry": doc.name}, pluck="name"):
		frappe.db.set_value("Payment Entry Withholding", name, "kra_journal_entry", None)
