# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""POS minimum selling price = the sale's price list.

On a till whose POS Profile ticks "Enforce minimum selling price to selected pricelist",
a line may not sell below the Item Price of the list it was priced from, unless a
supervisor authorised it with a PIN at the till (pos_supervisor_pin). A till sale on an
unticked till and desk documents keep the cost floor, unchanged.
"""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

ENFORCE_FIELD = "powerpack_enforce_list_floor"
ALLOWANCE_FIELD = "powerpack_list_floor_discount_allowance"
LINE_LIST_FIELD = "powerpack_line_price_list"
PIN_FIELD = "powerpack_pos_supervisor_pin"


def custom_field_definitions():
	line_field = {
		"fieldname": LINE_LIST_FIELD,
		"label": "Priced From List",
		"fieldtype": "Data",
		"insert_after": "price_list_rate",
		"hidden": 1,
		"read_only": 1,
		"print_hide": 1,
	}
	return {
		"POS Profile": [
			{
				"fieldname": ENFORCE_FIELD,
				"label": "Enforce minimum selling price to selected pricelist",
				"fieldtype": "Check",
				"default": "0",  # off on every existing till after an update
				"insert_after": "allow_rate_change",
				"description": "Lines may not sell below the price list they were priced from unless a supervisor authorises it with their PIN.",
			},
			{
				"fieldname": ALLOWANCE_FIELD,
				"label": "Allowed discount below price list (%)",
				"fieldtype": "Percent",
				"default": "0",  # none: the list price itself is the floor
				"insert_after": ENFORCE_FIELD,
				"depends_on": f"eval:doc.{ENFORCE_FIELD}",
				"description": "Cashiers may sell up to this much below the price list without a supervisor. 10 makes the floor 90% of the list price.",
			},
		],
		"Sales Invoice Item": [dict(line_field)],
		"POS Invoice Item": [dict(line_field)],
		"Sales Order Item": [dict(line_field)],
		"User": [
			{
				"fieldname": PIN_FIELD,
				"label": "POS Supervisor PIN",
				"fieldtype": "Password",
				"insert_after": "new_password",
				"description": "4 to 6 digits. Lets you authorise a sale below the minimum selling price at a till.",
			}
		],
	}


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(custom_field_definitions(), ignore_validate=True, update=True)


SETTINGS_DOCTYPE = "PowerPack Settings"
TILL_DOCTYPES = ("Sales Invoice", "POS Invoice")


def is_till_sale(doc):
	return doc.doctype in TILL_DOCTYPES and bool(doc.get("pos_profile"))


def till_enforces(doc):
	profile = doc.get("pos_profile") or doc.get("custom_pos_profile")
	return bool(profile) and bool(cint(frappe.get_cached_value("POS Profile", profile, ENFORCE_FIELD)))


def _may_use(user, price_list):
	"""Enabled selling list the user is not shut out of by Price List User Permissions."""
	flags = frappe.db.get_value("Price List", price_list, ["enabled", "selling"]) if price_list else None
	if not flags or not all(flags):
		return False
	if user == "Administrator":
		return True
	from frappe.permissions import get_user_permissions

	permitted = [p.get("doc") for p in (get_user_permissions(user) or {}).get("Price List") or []]
	return not permitted or price_list in permitted


def _row_list(doc, row, owner):
	"""The list this row is judged against. A list the cashier may not use is never trusted."""
	for candidate in (row.get(LINE_LIST_FIELD), doc.get("selling_price_list")):
		if candidate and _may_use(owner, candidate):
			return candidate
	return frappe.get_cached_value("POS Profile", doc.get("pos_profile") or doc.get("custom_pos_profile"), "selling_price_list")


def _list_price(doc, row, price_list):
	"""Item Price for the row's UOM (or stock UOM x conversion factor), in company currency."""
	from erpnext.stock.get_item_details import get_price_list_rate_for

	ctx = frappe._dict(
		price_list=price_list,
		customer=doc.get("customer"),
		uom=row.get("uom"),
		stock_uom=row.get("stock_uom"),
		conversion_factor=flt(row.get("conversion_factor")) or 1,
		transaction_date=doc.get("posting_date") or doc.get("transaction_date"),
		batch_no=row.get("batch_no"),
		qty=flt(row.get("qty")),
	)
	price = flt(get_price_list_rate_for(ctx, row.item_code))
	list_currency = frappe.get_cached_value("Price List", price_list, "currency")
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	if price and list_currency and company_currency and list_currency != company_currency:
		from erpnext.setup.utils import get_exchange_rate

		price *= flt(get_exchange_rate(list_currency, company_currency, ctx.transaction_date))
	return price


def _promo_price(doc, row, price_list, list_price):
	"""What ERPNext's Pricing Rules would charge for this line, never above list.

	klik_pos clears row.pricing_rules at checkout, so this is recomputed rather than read.
	"""
	from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item

	args = frappe._dict(
		doctype=doc.doctype,
		transaction_type="selling",
		item_code=row.item_code,
		customer=doc.get("customer"),
		company=doc.company,
		currency=doc.get("currency"),
		price_list=price_list,
		price_list_rate=list_price,
		qty=flt(row.qty),
		stock_qty=flt(row.get("stock_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1),
		uom=row.get("uom"),
		stock_uom=row.get("stock_uom"),
		conversion_factor=flt(row.get("conversion_factor")) or 1,
		transaction_date=doc.get("posting_date") or doc.get("transaction_date"),
		conversion_rate=flt(doc.get("conversion_rate")) or 1,
		plc_conversion_rate=1,
	)
	details = get_pricing_rule_for_item(args)
	if not details.get("has_pricing_rule"):
		return list_price
	price = flt(details.get("price_list_rate")) or list_price
	if flt(details.get("discount_amount")):
		price -= flt(details.discount_amount)
	elif flt(details.get("discount_percentage")):
		price *= 1 - flt(details.discount_percentage) / 100
	return min(price, list_price)


def _inclusive_factor(doc, row):
	"""1 + the row's tax fraction already inside the till's prices.

	# ponytail: only "On Net Total" included taxes; add other charge types if a till uses them.
	"""
	item_tax = {}
	if row.get("item_tax_rate"):
		try:
			item_tax = json.loads(row.item_tax_rate) or {}
		except (TypeError, ValueError):
			item_tax = {}
	fraction = 0.0
	for tax in doc.get("taxes") or []:
		if cint(tax.get("included_in_print_rate")) and tax.get("charge_type") == "On Net Total":
			fraction += flt(item_tax.get(tax.account_head, tax.rate)) / 100
	return 1 + fraction


def below_floor_rows(doc):
	"""Every line priced below its list (or its Pricing Rule price), in the till's terms."""
	settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	promos_exempt = cint(settings.get("min_selling_price_skip_if_pricing_rule"))
	owner = doc.get("owner") or frappe.session.user
	profile = doc.get("pos_profile") or doc.get("custom_pos_profile")
	allowance = min(max(flt(frappe.get_cached_value("POS Profile", profile, ALLOWANCE_FIELD)) if profile else 0, 0), 100)
	rows = []
	for row in doc.get("items") or []:
		if not row.get("item_code") or cint(row.get("is_free_item")) or flt(row.get("qty")) <= 0:
			continue
		price_list = _row_list(doc, row, owner)
		if not price_list:
			continue
		minimum = _list_price(doc, row, price_list)
		if minimum <= 0:
			continue
		list_price = minimum
		if promos_exempt:
			minimum = _promo_price(doc, row, price_list, list_price)
		minimum = min(minimum, list_price * (1 - allowance / 100))
		precision = row.precision("base_net_rate") or 2
		factor = _inclusive_factor(doc, row)
		rate = flt(flt(row.base_net_rate) * factor, precision)
		minimum = flt(minimum, precision)
		# Judge the line's net amount against the list taken to net: grossing a rounded net rate
		# back up lands a cent under list on ~7% of prices, and with qty > 1 ERPNext rounds the
		# amount before the rate (2 x 100 incl. 16% -> 172.41 -> 86.20 -> 99.99).
		qty = flt(row.qty)
		net_amount = flt(row.get("base_net_amount")) or flt(row.base_net_rate) * qty
		amount_precision = row.precision("base_net_amount") or 2
		if flt(net_amount, amount_precision) < flt(minimum / factor * qty, amount_precision):
			rows.append(
				{
					"idx": row.idx,
					"item_code": row.item_code,
					"item_name": row.get("item_name") or row.item_code,
					"uom": row.get("uom"),
					"qty": flt(row.qty),
					"rate": rate,
					"minimum": minimum,
					"price_list": price_list,
				}
			)
	return rows


def validate(doc):
	"""Ticked till: every below-list line needs a supervisor's authorisation covering it."""
	from frappe import _
	from frappe.utils import now_datetime

	from cecypo_powerpack import price_approval as pa

	breaches = below_floor_rows(doc)
	if not breaches:
		pa.set_breach_flag(doc, 0)
		return
	by_idx = {row.idx: row for row in doc.items}
	rows = [by_idx[b["idx"]] for b in breaches]

	if not doc.get(pa.APPROVED_ROWS_FIELD):
		pa.carry_over_source_approval(doc)  # a manager's approval of the held order it came from
	approved = pa.load_rows(doc.get(pa.APPROVED_ROWS_FIELD))
	if approved and not pa.uncovered_rows(doc, approved, items=rows):
		pa.set_breach_flag(doc, 1)
		return

	authorisation = doc.flags.get("powerpack_pos_approval")
	if authorisation and not pa.uncovered_rows(doc, authorisation["rows"], items=rows):
		pa.set_breach_flag(doc, 1)
		doc.set(pa.APPROVED_BY_FIELD, authorisation["supervisor"])
		doc.set(pa.APPROVED_ON_FIELD, now_datetime())
		doc.set(pa.APPROVED_ROWS_FIELD, json.dumps(pa.snapshot_rows(doc, items=rows)))
		token_key = authorisation.get("token_key")
		if token_key:  # one sale per PIN: the token is spent once this sale is saved
			frappe.db.after_commit.add(lambda: frappe.cache.delete_value(token_key))
		return

	frappe.throw(
		"<br>".join(
			_("Row {0} ({1}): price should be at least {2}").format(
				b["idx"], b["item_name"], frappe.bold(frappe.format_value(b["minimum"], {"fieldtype": "Currency"}, currency=doc.get("currency")))
			)
			for b in breaches
		),
		title=_(pa.TITLE),
	)


def judge_held_order(doc):
	"""A held order the cashier sent to a manager: flag it when a line is below the list, so
	the price-approval workflow takes it (the till asks with Request Price Approval)."""
	from frappe import _

	from cecypo_powerpack import price_approval as pa

	if not pa.routing_applies(doc, frappe.get_cached_doc(SETTINGS_DOCTYPE)):
		frappe.throw(
			_("Asking a manager needs Sales Order price approval switched on in PowerPack Settings. Ask a supervisor to authorise at the till instead."),
			title=_(pa.TITLE),
		)
	pa.set_breach_flag(doc, 1 if below_floor_rows(doc) else 0)


def till_floor_report(doc):
	"""For the till's checkout preview: does this till enforce the floor, and which lines are below it."""
	from cecypo_powerpack.utils import is_feature_enabled

	if not (is_feature_enabled("enable_min_selling_price") and is_till_sale(doc) and till_enforces(doc)):
		return {"enforced": False, "rows": []}
	if doc.get("is_return") or doc.get("is_internal_customer"):
		return {"enforced": True, "rows": []}
	rows = below_floor_rows(doc)
	# A held order a manager approved: the lines its approval still covers are not blocked.
	from cecypo_powerpack import price_approval as pa

	approval = pa.find_covering_approval(doc) if rows else None
	approved = pa.load_rows(approval.get(pa.APPROVED_ROWS_FIELD)) if approval else []
	if approved:
		by_idx = {row.idx: row for row in doc.items}
		uncovered = set(pa.uncovered_rows(doc, approved, items=[by_idx[r["idx"]] for r in rows]))
		rows = [r for r in rows if r["idx"] in uncovered]
	return {"enforced": True, "rows": rows}
