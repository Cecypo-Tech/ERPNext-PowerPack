# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


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
