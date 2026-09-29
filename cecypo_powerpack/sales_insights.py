# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Item insights for the Sales Powerup (Quotation / Sales Order / Sales Invoice / POS Invoice).

One request serves every row of a document. Every money value comes back in company
currency, net of tax, per *stock* UOM; the browser converts to the row's UOM, the
document's currency and, for tax-inclusive documents, the tax-inclusive display basis.
Normalising here is what lets a Box of 12, a USD quotation or a purchase made in cartons
be compared with the Bin valuation rate at all.

Cost data (valuation rate, last purchase) is withheld server-side from anyone without
`sales_visible_to_role`. Checking the role only in the browser, as the old
`get_item_info_for_quotation` did, handed cost prices to every desk user who called the
endpoint directly.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from cecypo_powerpack.utils import get_powerpack_settings

FEATURE_BY_DOCTYPE = {
	"Quotation": "enable_quotation_powerup",
	"Sales Order": "enable_sales_order_powerup",
	"Sales Invoice": "enable_sales_invoice_powerup",
	"POS Invoice": "enable_pos_invoice_powerup",
}
MAX_ITEMS = 500


def can_see_cost(settings) -> bool:
	return (settings.get("sales_visible_to_role") or "System Manager") in frappe.get_roles()


@frappe.whitelist()
def get_sales_item_insights(doctype: str, items: str, customer: str | None = None,
							company: str | None = None) -> dict:
	"""
	Args:
		doctype: the sales document the rows belong to (gates on its enable_* setting)
		items: JSON list of {"item_code", "warehouse"}; warehouse may be empty
		customer: for last-sale-to-customer (omit for a Quotation to a Lead)
		company: scopes history and the cross-warehouse cost fallback, whose base
			currency must match the document's

	Returns:
		{"can_see_cost": bool, "items": [one dict per distinct (item_code, warehouse)]}
	"""
	settings = get_powerpack_settings()
	feature = FEATURE_BY_DOCTYPE.get(doctype)
	if not feature or not cint(settings.get(feature)):
		frappe.throw(_("Sales Powerup is not enabled for {0}").format(doctype), frappe.PermissionError)

	pairs = _parse_items(items)
	show_cost = can_see_cost(settings)
	codes = sorted({code for code, _wh in pairs})
	if not codes:
		return {"can_see_cost": show_cost, "items": []}

	stock_items = set(frappe.get_all("Item", filters={"name": ("in", codes), "is_stock_item": 1}, pluck="name"))
	bins = _bins(codes, company)
	purchases = _last_rates("Purchase Invoice", codes, company) if show_cost else {}
	sales = _last_rates("Sales Invoice", codes, company)
	customer_sales = _last_rates("Sales Invoice", codes, company, customer) if customer else {}

	out = []
	for code, warehouse in pairs:
		row = {"item_code": code, "warehouse": warehouse}
		row.update(_stock(bins.get(code, []), warehouse, code in stock_items))
		if not show_cost:
			row["valuation_rate"] = None
		row.update(_history("last_purchase", purchases.get(code)))
		row.update(_history("last_sale", sales.get(code)))
		row.update(_history("last_sale_to_customer", customer_sales.get(code)))
		out.append(row)

	return {"can_see_cost": show_cost, "items": out}


def _parse_items(items) -> list[tuple[str, str | None]]:
	if isinstance(items, str):
		items = json.loads(items or "[]")
	seen, pairs = set(), []
	for entry in items or []:
		code = (entry or {}).get("item_code")
		if not code:
			continue
		key = (code, (entry.get("warehouse") or None))
		if key not in seen:
			seen.add(key)
			pairs.append(key)
	if len(pairs) > MAX_ITEMS:
		frappe.throw(_("Too many items ({0}); the limit is {1}").format(len(pairs), MAX_ITEMS))
	return pairs


def _bins(codes, company) -> dict[str, list]:
	company_clause = "AND wh.company = %(company)s" if company else ""
	rows = frappe.db.sql(f"""
		SELECT b.item_code, b.warehouse, b.actual_qty, b.reserved_qty, b.projected_qty,
			b.valuation_rate, b.stock_value
		FROM `tabBin` b
		LEFT JOIN `tabWarehouse` wh ON wh.name = b.warehouse
		WHERE b.item_code IN %(codes)s {company_clause}
	""", {"codes": codes, "company": company}, as_dict=True)
	by_code = {}
	for r in rows:
		by_code.setdefault(r.item_code, []).append(r)
	return by_code


def _stock(bins, warehouse, is_stock) -> dict:
	"""Stock for the row's warehouse (or all company warehouses when it has none) and a
	per-stock-UOM cost. A warehouse without a costed Bin falls back to the company-wide
	qty-weighted rate, so an item stocked elsewhere still gets a margin."""
	if not is_stock:
		return {"actual_qty": None, "reserved_qty": None, "available_qty": None, "valuation_rate": None}

	scope = [b for b in bins if b.warehouse == warehouse] if warehouse else bins
	result = {
		"actual_qty": sum(flt(b.actual_qty) for b in scope),
		"reserved_qty": sum(flt(b.reserved_qty) for b in scope),
		"available_qty": sum(flt(b.projected_qty) for b in scope),
	}
	exact = flt(scope[0].valuation_rate) if warehouse and scope else 0
	result["valuation_rate"] = exact if exact > 0 else _weighted_rate(bins)
	return result


def _weighted_rate(bins):
	qty = sum(flt(b.actual_qty) for b in bins if flt(b.actual_qty) > 0)
	if qty > 0:
		return sum(flt(b.stock_value) for b in bins if flt(b.actual_qty) > 0) / qty
	# Nothing in stock anywhere: the last known rate is still the best cost we have.
	rates = [flt(b.valuation_rate) for b in bins if flt(b.valuation_rate) > 0]
	return max(rates) if rates else None


def _last_rates(doctype, codes, company, customer=None) -> dict:
	"""Latest submitted, non-return line per item as base net rate per stock UOM."""
	conditions = ["p.docstatus = 1", "p.is_return = 0", "c.item_code IN %(codes)s"]
	if company:
		conditions.append("p.company = %(company)s")
	if customer:
		conditions.append("p.customer = %(customer)s")
	rows = frappe.db.sql(f"""
		SELECT item_code, rate, posting_date FROM (
			SELECT c.item_code,
				c.base_net_rate / IFNULL(NULLIF(c.conversion_factor, 0), 1) AS rate,
				p.posting_date,
				ROW_NUMBER() OVER (
					PARTITION BY c.item_code
					ORDER BY p.posting_date DESC, p.posting_time DESC, p.creation DESC, c.idx DESC
				) AS rn
			FROM `tab{doctype} Item` c
			INNER JOIN `tab{doctype}` p ON p.name = c.parent
			WHERE {" AND ".join(conditions)}
		) latest
		WHERE rn = 1
	""", {"codes": codes, "company": company, "customer": customer}, as_dict=True)
	return {r.item_code: r for r in rows}


def _history(prefix, row) -> dict:
	return {
		f"{prefix}_rate": flt(row.rate) if row else None,
		f"{prefix}_date": row.posting_date if row else None,
	}
