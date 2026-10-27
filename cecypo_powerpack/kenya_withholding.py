# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import csv
import io
import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import flt, getdate

from cecypo_powerpack.utils import is_feature_enabled


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(
		{
			"Payment Entry": [
				# Per payment, what a VAT WHT exemption does per supplier: VAT rules skipped, income tax rules kept.
				{
					"fieldname": "cecypo_skip_withholding",
					"label": "Skip Withholding",
					"fieldtype": "Check",
					"insert_after": "apply_tds",
					"depends_on": "eval:doc.payment_type=='Pay' && doc.party_type=='Supplier'",
					"description": "",  # blank, not omitted: update=True leaves an omitted key as it was on migrated sites
					"no_copy": 1,
					"print_hide": 1,
				},
				{
					"fieldname": "cecypo_withholding",
					"label": "Withholding Details",
					"fieldtype": "Table",
					"options": "Payment Entry Withholding",
					"insert_after": "deductions",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				},
				# Shown beside the paid amount while picking invoices: allocated = paid + withheld (+ other deductions).
				{
					"fieldname": "cecypo_total_withheld",
					"label": "Withheld",
					"fieldtype": "Currency",
					"options": "Company:company:default_currency",
					"insert_after": "column_break_21",
					"depends_on": "eval:doc.cecypo_total_withheld",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				},
			],
			# Set by pay_kra. Copied on Amend (frappe copies no_copy fields then), which refuse_kra_amend refuses.
			"Journal Entry": [
				{
					"fieldname": "cecypo_kra_payment",
					"label": "KRA Withholding Payment",
					"fieldtype": "Check",
					"insert_after": "cheque_date",
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				}
			],
		},
		ignore_validate=True,
		update=True,
	)
	# Entries withheld before cecypo_total_withheld existed. Idempotent; only touches entries with rows.
	frappe.db.sql("""
		update `tabPayment Entry` pe
		join (select parent, sum(amount) total from `tabPayment Entry Withholding`
			where parenttype = 'Payment Entry' group by parent) w on w.parent = pe.name
		set pe.cecypo_total_withheld = w.total
		where ifnull(pe.cecypo_total_withheld, 0) != w.total""")
	# Every Payment Entry, not only withholding ones: ERPNext hides References (and Get Outstanding Invoices)
	# until a paid amount is typed. Left empty, Get Outstanding fills it from the invoices (payment_entry.js).
	make_property_setter(
		"Payment Entry", "section_break_14", "depends_on",
		"eval:(doc.party && doc.paid_from && doc.paid_to)", "Code", validate_fields_for_doctype=False,
	)


def withheld(base, rate):
	"""Whole shillings, rounded up (iTax rounds up). Decimal, never float."""
	return math.ceil(Decimal(str(base)) * Decimal(str(rate)) / 100)


def invoice_withholding(invoice, allocated, supplier, rules, vat_accounts, exempt, field="purchase_invoice"):
	"""One row per matching rule, in rule order. Pure: no DB. `field` names the link the row carries; a
	Purchase Order (a deposit) has no bill, and its row records the allocation it covers."""
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
			row = {field: invoice["name"]}
			if field == "purchase_invoice":
				row.update(bill_no=invoice.get("bill_no"), bill_date=invoice.get("bill_date"))
			else:
				row["allocated_amount"] = float(allocated)
			rows.append(
				{
					**row,
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


REFERENCE_FIELDS = {"Purchase Invoice": "purchase_invoice", "Purchase Order": "purchase_order"}


def _reference_allocations(doc):
	"""Allocated amount per (doctype, name) of Purchase Invoice / Purchase Order, summed over its reference rows
	(one per payment term)."""
	allocated = {}
	for ref in doc.get("references"):
		if ref.reference_doctype in REFERENCE_FIELDS and flt(ref.allocated_amount) > 0:
			key = (ref.reference_doctype, ref.reference_name)
			allocated[key] = allocated.get(key, Decimal(0)) + Decimal(str(flt(ref.allocated_amount)))
	return allocated


def _whole(x, places=0):
	return Decimal(x).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)


def split_row(row, allocated):
	"""Carve `allocated` of the row's allocated_amount into a new row; the source keeps the remainder, so the
	parts always sum to the original. Taking it all returns the source itself. Pure: dicts only."""
	total, a = Decimal(str(row["allocated_amount"])), Decimal(str(allocated))
	if a >= total:
		return row
	part = dict(row)
	part["amount"] = int(_whole(Decimal(str(row["amount"])) * a / total))
	part["base_amount"] = float(_whole(Decimal(str(row["base_amount"])) * a / total, 2))
	part["allocated_amount"] = float(a)
	row["amount"] -= part["amount"]
	row["base_amount"] = float(Decimal(str(row["base_amount"])) - Decimal(str(part["base_amount"])))
	row["allocated_amount"] = float(total - a)
	return part


def _covered_by_deposit(doc):
	"""Allocated amount per (Purchase Invoice, the Purchase Order it was set from or '') on a Payment Entry."""
	out = {}
	for ref in doc.get("references"):
		if ref.reference_doctype == "Purchase Invoice" and flt(ref.allocated_amount) > 0:
			po = ref.advance_voucher_no if ref.advance_voucher_type == "Purchase Order" else ""
			key = (ref.reference_name, po or "")
			out[key] = out.get(key, Decimal(0)) + Decimal(str(flt(ref.allocated_amount)))
	return out


def link_deposit_rows(doc, method=None):
	"""before_update_after_submit: ERPNext set a deposit against a Purchase Invoice (it reduces the PO reference
	and appends one for the invoice). Move the covered share of the waiting deposit rows onto that invoice."""
	before = doc.get_doc_before_save()
	waiting = [r for r in doc.get("cecypo_withholding") or [] if r.purchase_order and not r.purchase_invoice and not r.kra_journal_entry]
	if not before or not waiting:
		return
	was, now = _covered_by_deposit(before), _covered_by_deposit(doc)
	for (name, from_po), total in now.items():
		left = total - was.get((name, from_po), Decimal(0))
		if left <= 0:
			continue
		pi = frappe.db.get_value("Purchase Invoice", name, ["bill_no", "bill_date"], as_dict=True)
		# The PO the new allocation came from; with none (unallocated amount) the PI's own POs, then any.
		preferred = [from_po] if from_po else []
		preferred += frappe.get_all("Purchase Invoice Item", {"parent": name}, pluck="purchase_order", order_by="idx")
		for po in dict.fromkeys(preferred + [r.purchase_order for r in waiting]):
			rows = [r for r in waiting if r.purchase_order == po and not r.purchase_invoice]
			if left <= 0:
				break
			if not rows:
				continue
			# All rule rows of a PO share allocated_amount: they are created and split together.
			take = min(left, max(Decimal(str(r.allocated_amount)) for r in rows))
			for r in rows:
				d = r.as_dict(no_default_fields=True)
				part = split_row(d, take)
				part.update(purchase_invoice=name, bill_no=pi.bill_no, bill_date=pi.bill_date)
				if part is d:
					r.update(part)
				else:
					r.update(d)
					doc.append("cecypo_withholding", part)
			left -= take


def refuse_cancel_if_deposit_paid_to_kra(doc, method=None):
	"""Purchase Invoice before_cancel: stop before ERPNext unlinks the deposit if its withholding went to KRA."""
	for r in frappe.get_all(
		"Payment Entry Withholding",
		{"purchase_invoice": doc.name, "purchase_order": ["is", "set"], "kra_journal_entry": ["is", "set"]},
		["parent", "kra_journal_entry"],
	):
		frappe.throw(
			_("Withholding on deposit {0} for this invoice was paid to KRA by {1}. Cancel that first.").format(
				r.parent, r.kra_journal_entry
			)
		)


def unlink_deposit_rows(doc, method=None):
	"""Purchase Invoice on_cancel: ERPNext released the deposit without saving the Payment Entry, so its linked
	withholding rows go back to waiting by db writes, merged into the waiting row of the same order and account."""
	rows = frappe.get_all(
		"Payment Entry Withholding",
		{"purchase_invoice": doc.name, "purchase_order": ["is", "set"], "kra_journal_entry": ["is", "not set"]},
		["name", "parent", "purchase_order", "account", "amount", "base_amount", "allocated_amount"],
	)
	for r in rows:
		waiting = frappe.db.get_value(
			"Payment Entry Withholding",
			{"parent": r.parent, "purchase_order": r.purchase_order, "account": r.account,
				"purchase_invoice": ["is", "not set"], "kra_journal_entry": ["is", "not set"]},
			["name", "amount", "base_amount", "allocated_amount"], as_dict=True,
		)
		if waiting:
			frappe.db.set_value("Payment Entry Withholding", waiting.name, {
				"amount": waiting.amount + r.amount,
				"base_amount": flt(waiting.base_amount + r.base_amount, 2),
				"allocated_amount": flt(waiting.allocated_amount + r.allocated_amount, 2),
			})
			frappe.db.delete("Payment Entry Withholding", r.name)
		else:
			frappe.db.set_value("Payment Entry Withholding", r.name,
				{"purchase_invoice": None, "bill_no": None, "bill_date": None})


def apply_to_payment_entry(doc, method=None, preview=False):
	"""before_validate on Payment Entry, so it also runs at submit with the rules then in force. ERPNext's
	validate then runs its amount setters on our values. When the entry no longer qualifies (feature off, no
	rules for the company, not a supplier payment), rows it already holds are cleared, not submitted."""
	if doc.docstatus == 2:
		return
	held = doc.get("cecypo_withholding") or []
	rules = []
	if doc.payment_type == "Pay" and doc.party_type == "Supplier" and is_feature_enabled("enable_kenya_withholding"):
		settings = frappe.get_single("PowerPack Settings")
		rules = [
			r.as_dict()
			for r in settings.withholding_rules
			if r.account and frappe.get_cached_value("Account", r.account, "company") == doc.company
		]
	if not rules and not held:
		return
	# Accounts of the rows held before too, so a cleared or re-pointed rule leaves no stale deduction.
	rule_accounts = {r["account"] for r in rules} | {r.account for r in held}
	posting_date = getdate(doc.posting_date)

	rows = []
	if rules:
		vat_accounts = {r.account for r in settings.withholding_vat_accounts}
		exempt = doc.get("cecypo_skip_withholding") or any(
			e.supplier == doc.party and e.valid_until and posting_date <= getdate(e.valid_until)
			for e in settings.withholding_exemptions
		)
		for (dt, name), allocated in _reference_allocations(doc).items():
			fields = ["name", "rounded_total", "grand_total"]
			if dt == "Purchase Invoice":
				fields += ["bill_no", "bill_date"]
			pi = frappe.db.get_value(dt, name, fields, as_dict=True)
			total = pi and (flt(pi.rounded_total) or flt(pi.grand_total))
			if not total:
				continue
			pi["total"] = total
			pi["items"] = frappe.get_all(
				f"{dt} Item", {"parent": pi.name}, ["item_code", "base_net_amount"], order_by="idx"
			)
			rows += invoice_withholding(pi, allocated, doc.party, rules, vat_accounts, exempt, REFERENCE_FIELDS[dt])

	# Nothing withheld now or before: a deduction on a rule account is the user's own; leave it.
	if not rows and not held:
		return
	own_deductions = [d for d in doc.get("deductions") if d.account in rule_accounts]

	holidays = _holidays(doc.company)
	for r in rows:
		r["due_date"] = vat_due_date(posting_date, holidays) if r["is_vat"] else income_tax_due_date(posting_date)
	doc.set("cecypo_withholding", rows)
	doc.cecypo_total_withheld = sum(r["amount"] for r in rows)

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
			"description": f"Withholding {rates}% on {', '.join(dict.fromkeys(r.get('bill_no') or r.get('purchase_invoice') or r['purchase_order'] for r in acc_rows))}",
		})

	if doc.payment_type != "Pay" or doc.party_type != "Supplier":
		# ponytail: switched away from a supplier payment; amounts are ERPNext's/the user's again.
		return

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
	# Not in the preview: it runs while an allocation is still being typed. Save and submit refuse it.
	if rows and not preview and flt(doc.paid_amount, doc.precision("paid_amount")) <= 0:
		frappe.throw(_("Withholding of {0} leaves nothing to pay. Check the allocated amounts.").format(total_withheld))


def _holidays(company):
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	if not holiday_list:
		return set()
	return {getdate(d) for d in frappe.get_all("Holiday", {"parent": holiday_list}, pluck="holiday_date")}


@frappe.whitelist()
def compute_for_payment_entry(doc):
	"""Run the hook on an unsaved copy, for the form to show before saving."""
	frappe.has_permission("Payment Entry", "write", throw=True)
	doc = frappe.parse_json(doc) if isinstance(doc, str) else doc
	if doc.get("doctype") != "Payment Entry":
		frappe.throw(_("Expected a Payment Entry."))
	pe = frappe.get_doc(doc)
	for dt, name in _reference_allocations(pe):
		frappe.has_permission(dt, "read", name, throw=True)
	apply_to_payment_entry(pe, preview=True)
	return {
		"cecypo_withholding": [r.as_dict() for r in pe.get("cecypo_withholding")],
		"deductions": [d.as_dict() for d in pe.get("deductions")],
		"paid_amount": pe.paid_amount,
		"cecypo_total_withheld": pe.cecypo_total_withheld,
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
		# iTax takes one row per (PIN, invoice), so two rates on one key cannot be filed.
		if flt(m["rate"]) != flt(r["rate"]):
			frappe.throw(_("Invoice {0} has VAT withholding at different rates ({1}% and {2}%). Pay or export those rows separately.").format(
				key[1], flt(m["rate"]), flt(r["rate"])
			))
		m["base_amount"] = float(Decimal(str(m["base_amount"])) + Decimal(str(r["base_amount"])))
		if r.get("posting_date") and (not m.get("posting_date") or getdate(r["posting_date"]) > getdate(m["posting_date"])):
			m["posting_date"] = r["posting_date"]
	return list(merged.values())


def _load_rows(row_names, lock=False):
	"""Withholding rows of submitted Payment Entries by name, with the supplier PIN and Purchase Invoice
	dates. Throws on an empty, stale or non-submitted selection."""
	row_names = frappe.parse_json(row_names) if isinstance(row_names, str) else row_names
	row_names = list(dict.fromkeys(row_names or []))
	if not row_names:
		frappe.throw(_("Select the withholding rows."))
	W = frappe.qb.DocType("Payment Entry Withholding")
	PE = frappe.qb.DocType("Payment Entry")
	S = frappe.qb.DocType("Supplier")
	PI = frappe.qb.DocType("Purchase Invoice")
	q = (
		frappe.qb.from_(W)
		.join(PE).on(W.parent == PE.name)
		.left_join(S).on(S.name == PE.party)
		.left_join(PI).on(PI.name == W.purchase_invoice)
		.select(
			W.name, W.account, W.amount, W.base_amount, W.rate, W.is_vat, W.bill_no, W.bill_date,
			W.purchase_invoice, W.kra_journal_entry, PE.name.as_("payment_entry"), PE.company, PE.docstatus,
			PE.posting_date, PE.party.as_("supplier"), S.tax_id, PI.posting_date.as_("invoice_posting_date"),
		)
		.where(W.name.isin(row_names) & (W.parenttype == "Payment Entry"))
	)
	# Locked before the paid check, so two concurrent Pay KRA calls cannot both pass it.
	rows = (q.for_update() if lock else q).run(as_dict=True)
	for r in rows:
		r.tax_id = (r.tax_id or "").strip()
	if len(rows) != len(row_names):
		frappe.throw(_("Some selected withholding rows no longer exist. Refresh the report."))
	if any(r.docstatus != 1 for r in rows):
		frappe.throw(_("Only withholding on submitted Payment Entries can be paid to KRA."))
	return rows


def itax_csv_rows(rows):
	"""iTax Withholding VAT import lines: PIN, invoice no, invoice date, amount, payment date. VAT rows
	only, merged by merge_vat_rows. Invoice no / date fall back to the Purchase Invoice name / posting date."""
	fmt = lambda d: getdate(d).strftime("%d/%m/%Y")
	return [
		[
			m["tax_id"], m.get("bill_no") or m["purchase_invoice"],
			fmt(m.get("bill_date") or m["invoice_posting_date"]), f"{m['base_amount']:.2f}", fmt(m["posting_date"]),
		]
		for m in merge_vat_rows(rows)
	]


def _itax_rows(row_names):
	"""The selection's VAT rows, refused when there are none or a supplier has no PIN."""
	frappe.only_for(["Accounts Manager", "Accounts User", "System Manager"])
	rows = [r for r in _load_rows(row_names) if r.is_vat]
	if not rows:
		frappe.throw(_("No VAT withholding rows in the selection."))
	missing = sorted({r.supplier for r in rows if not r.tax_id})
	if missing:
		frappe.throw(_("Set the Tax ID (PIN) on supplier {0} before exporting.").format(", ".join(missing)))
	return rows


@frappe.whitelist(methods=["POST"])
def check_itax_export(row_names):
	"""export_itax_csv's refusals, run by frappe.call first: the download is a form POST into a new tab
	(open_url_post), where a refusal renders as a bare error page instead of a message on the report."""
	_itax_rows(row_names)


@frappe.whitelist(methods=["POST"])
def export_itax_csv(row_names):
	"""Download the iTax Withholding VAT upload for the selected rows. Works with the feature off."""
	rows = _itax_rows(row_names)
	out = io.StringIO()
	csv.writer(out, lineterminator="\r\n").writerows(itax_csv_rows(rows))
	frappe.response["filename"] = f"WHT-VAT-{getdate().strftime('%d-%m-%Y')}.csv"
	frappe.response["filecontent"] = out.getvalue().encode()
	frappe.response["type"] = "download"


def _payable_rows(row_names, lock=False):
	"""Selected rows, refused if any is paid, they span companies, or they mix VAT and income tax."""
	rows = _load_rows(row_names, lock=lock)
	paid = list(dict.fromkeys(r.kra_journal_entry for r in rows if r.kra_journal_entry))
	if paid:
		frappe.throw(_("Some selected rows are already paid to KRA by Journal Entry {0}.").format(", ".join(paid)))
	companies = {r.company for r in rows}
	if len(companies) > 1:
		frappe.throw(_("Selected rows belong to more than one company: {0}.").format(", ".join(sorted(companies))))
	# VAT and income tax are separate iTax returns, so separate PRNs.
	if len({bool(r.is_vat) for r in rows}) > 1:
		frappe.throw(_("Pay VAT withholding and income tax withholding separately: they have separate PRNs."))
	return rows


def _bank_figure(rows):
	"""iTax's figure (the PRN): ceil per merged VAT invoice, not the sum of per-payment ceils."""
	return sum(withheld(m["base_amount"], m["rate"]) for m in merge_vat_rows(rows)) + sum(
		flt(r.amount) for r in rows if not r.is_vat
	)


@frappe.whitelist()
def pay_kra_preview(row_names) -> dict:
	"""What Pay KRA would post for the selection: the bank figure and the sum withheld."""
	frappe.only_for(["Accounts Manager", "Accounts User", "System Manager"])
	rows = _payable_rows(row_names)
	return {"bank": _bank_figure(rows), "withheld": sum(flt(r.amount) for r in rows)}


@frappe.whitelist(methods=["POST"])
def pay_kra(row_names, bank_account: str, posting_date: str, prn: str, reference_date: str) -> str:
	"""One submitted Bank Entry paying the selected withholding rows to KRA. Works with the feature off."""
	frappe.only_for(["Accounts Manager", "Accounts User", "System Manager"])
	if not prn:
		frappe.throw(_("PRN is required."))
	rows = _payable_rows(row_names, lock=True)
	company = rows[0].company
	bank = frappe.get_cached_value("Account", bank_account, ["company", "account_type"], as_dict=True)
	if not bank or bank.company != company or bank.account_type not in ("Bank", "Cash"):
		frappe.throw(_("{0} is not a Bank or Cash account of {1}.").format(bank_account, company))

	debits = {}
	for r in rows:
		debits[r.account] = debits.get(r.account, 0) + flt(r.amount)
	credit = _bank_figure(rows)
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
		"cecypo_kra_payment": 1,
		"user_remark": _("Withholding paid to KRA, PRN {0}. Payment Entries: {1}").format(prn, payment_entries),
		"accounts": accounts,
	})
	je.insert()
	je.submit()
	for r in rows:
		frappe.db.set_value("Payment Entry Withholding", r.name, "kra_journal_entry", je.name)
	return je.name


def flag_kra_payment(doc, method=None):
	"""Journal Entry onload: tells the form (kenya_withholding_journal_entry.js) to skip Payment Entry in Cancel All."""
	if doc.docstatus == 1 and doc.get("cecypo_kra_payment"):
		doc.set_onload("is_kra_payment", 1)


def refuse_kra_amend(doc, method=None):
	"""Journal Entry before_insert: an amended KRA payment would leave its rows Unpaid, so payable twice."""
	if doc.amended_from and frappe.db.get_value("Journal Entry", doc.amended_from, "cecypo_kra_payment"):
		frappe.throw(_(
			"Journal Entry {0} paid withholding to KRA and cannot be amended. Its rows are Unpaid again: "
			"run Pay KRA from the Withholding Due to KRA report."
		).format(doc.amended_from))


def allow_cancel_of_kra_payment(doc, method=None):
	"""Journal Entry before_cancel: submitted Payment Entries' withholding rows link here; clear_kra_link drops them."""
	if doc.get("cecypo_kra_payment"):
		doc.ignore_linked_doctypes = tuple(getattr(doc, "ignore_linked_doctypes", None) or ()) + ("Payment Entry",)


def clear_kra_link(doc, method=None):
	"""Journal Entry on_cancel: its withholding rows go back to Unpaid."""
	for name in frappe.get_all("Payment Entry Withholding", {"kra_journal_entry": doc.name}, pluck="name"):
		frappe.db.set_value("Payment Entry Withholding", name, "kra_journal_entry", None)
