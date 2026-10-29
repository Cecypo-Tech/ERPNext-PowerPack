"""Naming-series placeholders: company, branch and Stock Entry Type codes, the Payment Entry
direction, and RET / DR on returns and Sales Invoice debit notes. `.CO./.BR/.SI/.#####` names a
Paint Matt sale `OJ/PM/SI/00001`; `.CO./.BR/.SI/.RET/.#####` names its return `OJ/PM/SI/RET/00001`.

Registered through Frappe's naming_series_variables hook, the one ERPNext uses for `.ABBR.`.
Each prefix keeps its own counter, and a matching Document Naming Rule still wins over the
series. A separator written inside a placeholder (`.BR/.`) goes with it when the code is blank,
so a sale with no warehouse is `OJ/SI/00001`, not `OJ//SI/00001`.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELD = "cecypo_naming_code"
SEPARATORS = ("/", "-", "_")
PAYMENT_DIRECTION = {"Receive": "IN", "Pay": "OUT", "Internal Transfer": "TRF"}


def is_enabled():
	# Read from Singles directly: get_single_value throws on a site not yet migrated to this field.
	row = frappe.db.sql(
		"select value from tabSingles where doctype = 'PowerPack Settings' and field = 'enable_branch_naming_codes'"
	)
	return bool(row and int(row[0][0] or 0))


def _code(doctype, name):
	if not name or not frappe.get_meta(doctype).has_field(FIELD):
		return ""
	return (frappe.get_cached_value(doctype, name, FIELD) or "").strip()


def _branch(doc):
	if doc.get("doctype") == "Stock Entry":
		# Both ends of a transfer: HQ to Milimani is HQ-MI.
		codes = dict.fromkeys(filter(None, (_code("Warehouse", doc.get("from_warehouse")), _code("Warehouse", doc.get("to_warehouse")))))
		return "-".join(codes)
	warehouse = None
	if doc.get("is_return") and doc.get("return_against") and doc.get("doctype"):
		# A return is named after the original's branch: a desk return clears the header
		# warehouse, and a Delivery Note return gets the company's sales-return warehouse.
		warehouse = frappe.db.get_value(doc.get("doctype"), doc.get("return_against"), "set_warehouse")
	return _code("Warehouse", warehouse or doc.get("set_warehouse"))


def _value(doc, variable):
	if variable == "CO":
		# No document is the Naming Series screen's preview: show the default company, as .ABBR. does.
		company = doc.get("company") or frappe.db.get_default("company")
		return (_code("Company", company) or frappe.get_cached_value("Company", company, "abbr") or "") if company else ""
	if variable == "BR":
		return _branch(doc)
	if variable == "SET":
		return _code("Stock Entry Type", doc.get("stock_entry_type")) if doc.get("doctype") == "Stock Entry" else ""
	if variable == "PAYDIR":
		return PAYMENT_DIRECTION.get(doc.get("payment_type"), "") if doc.get("doctype") == "Payment Entry" else ""
	if variable == "RET":
		if doc.get("is_return"):
			return "RET"
		return "DR" if doc.get("doctype") == "Sales Invoice" and doc.get("is_debit_note") else ""
	return ""


def parse_variable(doc, variable):
	"""naming_series_variables parser. Off, the part stays literal text, as if PowerPack were not
	installed - a site's existing BR-.YYYY.- series must not change. On, "" when there is no code."""
	if not is_enabled():
		return variable
	doc = doc or frappe._dict()
	separator = variable[-1] if variable[-1] in SEPARATORS else ""
	value = _value(doc, variable.removesuffix(separator) if separator else variable)
	return value + separator if value else ""


def setup_custom_fields():
	"""Idempotent. Run when the setting is turned on, and on migrate while it is on."""
	field = {
		"fieldname": FIELD,
		"label": "Naming Code",
		"fieldtype": "Data",
		"length": 10,
		"description": "Short code for the .CO. / .BR. / .SET. naming-series placeholders (PowerPack Settings > Document Naming).",
	}
	create_custom_fields(
		{
			"Company": [dict(field, insert_after="abbr")],
			"Warehouse": [dict(field, insert_after="warehouse_name")],
			"Stock Entry Type": [dict(field, insert_after="purpose")],
		},
		update=True,
	)


def after_migrate():
	if is_enabled():
		setup_custom_fields()
