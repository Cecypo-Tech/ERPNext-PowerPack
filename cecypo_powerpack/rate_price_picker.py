# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Rate Price Picker: an item's price on each selling price list, for the Rate dropdown.

Read on the user's behalf - a Sales User cannot read Item Price - for an item the user
can read. Whether a price is below the Minimum Selling Price floor comes back as a flag
rather than the floor; the flag is advisory (saving runs the real check), and a failed
save states the floor anyway.
"""

import frappe
from frappe import _
from frappe.utils import flt

from cecypo_powerpack.min_selling_price import row_floor
from cecypo_powerpack.utils import is_feature_enabled

DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")


@frappe.whitelist()
def get_rate_options(
	doctype,
	item_code,
	uom,
	stock_uom,
	conversion_factor,
	currency,
	customer=None,
	company=None,
	transaction_date=None,
	conversion_rate=1,
	net_factor=1,
	warehouse=None,
	qty=1,
	has_pricing_rule=0,
):
	"""{options: [{price_list, rate, below_floor}], set_list_price} for every enabled
	selling list in ``currency`` that prices the item, ``rate`` per ``uom``.

	``net_factor`` is the row's net rate / rate (inclusive taxes, document discount), so a
	price is judged on the same net, company-currency basis as the floor check on save.
	``set_list_price`` False tells the client to set only the rate on a pick: see
	``_list_price_writes_back``.
	"""
	if not is_feature_enabled("enable_rate_price_picker"):
		# Not an error: a browser still holding the old setting would get a dialog on
		# every Rate focus.
		return {"options": [], "set_list_price": True}
	if doctype not in DOCTYPES:
		frappe.throw(_("Rate Price Picker is not available for {0}").format(_(doctype)))
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	# As ERPNext's own get_item_details: User Permissions on Item / Item Group apply.
	frappe.has_permission("Item", "read", doc=item_code, throw=True)

	from erpnext.stock.get_item_details import get_price_list_rate_for

	conversion_factor = flt(conversion_factor) or 1.0
	price_lists = frappe.get_all(
		"Price List",
		filters={"enabled": 1, "selling": 1, "currency": currency},
		pluck="name",
		order_by="name asc",
	)
	floor = (
		row_floor(doctype, company, item_code, conversion_factor, warehouse, has_pricing_rule=has_pricing_rule)
		if company
		else None
	)
	template = frappe.get_cached_value("Item", item_code, "variant_of")
	to_net_company = flt(conversion_rate or 1) * flt(net_factor or 1)

	def price_for(code, price_list):
		# No price_list_uom_dependant: ERPNext's own price fetch reads that key from
		# get_price_list_details, which never sets it, so it always scales a stock-UOM
		# price by the conversion factor. Passing the Price List flag would disagree with
		# the rate ERPNext puts on the row.
		return get_price_list_rate_for(
			frappe._dict(
				price_list=price_list,
				customer=customer,
				uom=uom,
				stock_uom=stock_uom,
				conversion_factor=conversion_factor,
				transaction_date=transaction_date,
				# Needed: without a qty, get_price_list_rate_for drops a price it found for
				# the row's own UOM (it gates that match on the packing-unit check).
				qty=flt(qty) or 1,
			),
			code,
		)

	options = []
	for price_list in price_lists:
		rate = price_for(item_code, price_list)
		if rate is None and template:
			# As ERPNext: a variant without its own price takes its template's.
			rate = price_for(template, price_list)
		if rate is None:
			continue
		options.append(
			{
				"price_list": price_list,
				"rate": flt(rate),
				"below_floor": floor is not None and flt(rate) * to_net_company < floor,
			}
		)
	return {"options": options, "set_list_price": not _list_price_writes_back()}


def _list_price_writes_back():
	"""Whether saving would copy the row's Price List Rate into the document's price list.

	With Stock Settings inserting/updating Item Prices from transactions on the "Price List
	Rate" basis, ERPNext writes the row's list price back to the document's own list on
	save (get_item_details.insert_item_price). A pick from another list must then set the
	rate only - as typing it would - or picking Retail would rewrite Standard Selling.
	"""
	stock_settings = frappe.get_cached_doc("Stock Settings")
	return bool(
		stock_settings.auto_insert_price_list_rate_if_missing
		and stock_settings.update_price_list_based_on == "Price List Rate"
		and frappe.has_permission("Item Price", "write")
	)
