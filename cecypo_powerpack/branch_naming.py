"""Naming-series placeholders: company, branch and Stock Entry Type codes, and the Payment Entry
direction. `.CO./.BR/.SI/.#####` names a Paint Matt sale `OJ/PM/SI/00001`.

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
	return bool(frappe.db.get_single_value("PowerPack Settings", "enable_branch_naming_codes"))


def _code(doctype, name):
	return (frappe.db.get_value(doctype, name, FIELD) or "").strip() if name else ""


def _branch(doc):
	if doc.get("doctype") == "Stock Entry":
		# Both ends of a transfer: HQ to Milimani is HQ-MI.
		codes = dict.fromkeys(filter(None, (_code("Warehouse", doc.get("from_warehouse")), _code("Warehouse", doc.get("to_warehouse")))))
		return "-".join(codes)
	return _code("Warehouse", doc.get("set_warehouse"))


def _value(doc, variable):
	if variable == "CO":
		company = doc.get("company")
		return (_code("Company", company) or frappe.db.get_value("Company", company, "abbr") or "") if company else ""
	if variable == "BR":
		return _branch(doc)
	if variable == "SET":
		return _code("Stock Entry Type", doc.get("stock_entry_type")) if doc.get("doctype") == "Stock Entry" else ""
	if variable == "PAYDIR":
		return PAYMENT_DIRECTION.get(doc.get("payment_type"), "") if doc.get("doctype") == "Payment Entry" else ""
	return ""


def parse_variable(doc, variable):
	"""naming_series_variables parser: "" when off, with no document (the Naming Series preview), or with no code."""
	if not doc or not is_enabled():
		return ""
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
