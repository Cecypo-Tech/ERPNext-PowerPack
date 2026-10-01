# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Rate Price Picker: an item's price on each selling price list, for the Rate dropdown.

Read on the user's behalf - a Sales User cannot read Item Price - and only ever the
prices: whether a price is below the Minimum Selling Price floor comes back as a flag,
never the floor itself, which would reveal cost.
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
):
	"""[{price_list, rate, below_floor}] for every enabled selling list in ``currency``
	that prices the item, ``rate`` per ``uom``.

	``net_factor`` is the row's net rate / rate (inclusive taxes, document discount), so a
	price is judged on the same net, company-currency basis as the floor check on save.
	"""
	if not is_feature_enabled("enable_rate_price_picker"):
		frappe.throw(_("Rate Price Picker is turned off in PowerPack Settings"))
	if doctype not in DOCTYPES:
		frappe.throw(_("Rate Price Picker is not available for {0}").format(_(doctype)))
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	from erpnext.stock.get_item_details import get_price_list_rate_for

	conversion_factor = flt(conversion_factor) or 1.0
	price_lists = frappe.get_all(
		"Price List",
		filters={"enabled": 1, "selling": 1, "currency": currency},
		pluck="name",
		order_by="name asc",
	)
	floor = row_floor(doctype, company, item_code, conversion_factor, warehouse) if company else None
	to_net_company = flt(conversion_rate or 1) * flt(net_factor or 1)

	options = []
	for price_list in price_lists:
		# No price_list_uom_dependant: ERPNext's own price fetch reads that key from
		# get_price_list_details, which never sets it, so it always scales a stock-UOM
		# price by the conversion factor. Passing the Price List flag would disagree with
		# the rate ERPNext puts on the row.
		rate = get_price_list_rate_for(
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
			item_code,
		)
		if rate is None:
			continue
		options.append(
			{
				"price_list": price_list,
				"rate": flt(rate),
				"below_floor": floor is not None and flt(rate) * to_net_company < floor,
			}
		)
	return options
