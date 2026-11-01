"""Naming-series placeholders: company, branch and Stock Entry Type codes, the Payment Entry
direction, the Sales Invoice sale type (POS / INV), and RET / DR on returns and Sales Invoice debit
notes; `.CO.` is left out when the Company has no Naming Code. `.CO./.BR/.SI/.#####` names a Paint Matt sale `OJ/PM/SI/00001`; `.CO./.BR/.SI/.RET/.#####` names its return `OJ/PM/SI/RET/00001`.

Registered through Frappe's naming_series_variables hook, the one ERPNext uses for `.ABBR.`.
Each prefix keeps its own counter, and a matching Document Naming Rule still wins over the
series. A separator written inside a placeholder (`.BR/.`) goes with it when the code is blank,
so a sale with no warehouse is `OJ/SI/00001`, not `OJ//SI/00001`.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELD = "cecypo_naming_code"
SEPARATORS = ("/", "-", "_")
PAYMENT_DIRECTION = {"Receive": "IN", "Pay": "OUT", "Internal Transfer": "TRF"}
# klik_pos fills Sales Invoice.custom_sale_type before insert (a return copies its original's).
SALE_TYPE = {"Cash": "POS", "Credit": "INV"}
# PowerPack Settings > Apply suggested naming. Each doctype's own letters keep the counters apart.
SUGGESTED_SERIES = {
	"Sales Invoice": ".CO/.BR/.SI/.RET/.#####",
	"Sales Order": ".CO/.BR/.SO/.#####",
	"Quotation": ".CO/.BR/.QT/.#####",
	"Delivery Note": ".CO/.BR/.DN/.RET/.#####",
	"Purchase Order": ".CO/.BR/.PO/.#####",
	"Purchase Receipt": ".CO/.BR/.PR/.RET/.#####",
	"Purchase Invoice": ".CO/.BR/.PI/.RET/.#####",
	"Stock Entry": ".CO/.BR/.STK/.#####",
	"Payment Entry": ".CO/.PAY/.PAYDIR./.#####",
}


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
	if doc.get("is_return") and doc.get("return_against") and doc.get("doctype"):
		# A return is named after the original's branch: a desk return clears the header
		# warehouse, and a Delivery Note return gets the company's sales-return warehouse.
		doctype, name = doc.get("doctype"), doc.get("return_against")
		items = frappe.get_meta(doctype).get_field("items")
		warehouse = frappe.db.get_value(doctype, name, "set_warehouse") or (
			items and frappe.db.get_value(items.options, {"parent": name, "parenttype": doctype, "warehouse": ("is", "set")}, "warehouse", order_by="idx asc")
		)
		if warehouse:
			return _code("Warehouse", warehouse)
	# A POS profile with no warehouse leaves the header blank and sets each row's warehouse:
	# the first row's names the document.
	warehouse = doc.get("set_warehouse") or next((i.get("warehouse") for i in doc.get("items") or [] if i.get("warehouse")), None)
	return _code("Warehouse", warehouse)


def _value(doc, variable):
	if variable == "CO":
		# No document is the Naming Series screen's preview: show the default company, as .ABBR. does.
		# Blank code, the usual single-company site: no company part at all (not the Abbr).
		company = doc.get("company") or frappe.db.get_default("company")
		return _code("Company", company)
	if variable == "BR":
		return _branch(doc)
	if variable == "SET":
		return _code("Stock Entry Type", doc.get("stock_entry_type")) if doc.get("doctype") == "Stock Entry" else ""
	if variable == "PAYDIR":
		return PAYMENT_DIRECTION.get(doc.get("payment_type"), "") if doc.get("doctype") == "Payment Entry" else ""
	if variable == "ST":
		return SALE_TYPE.get(doc.get("custom_sale_type"), "") if doc.get("doctype") == "Sales Invoice" else ""
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


def _series_options(doctype):
	return [o for o in frappe.get_meta(doctype).get_naming_series_options() if o.strip()]


def _last_doc(doctype):
	try:
		return frappe.get_last_doc(doctype)
	except frappe.DoesNotExistError:
		return None


def suggest_code(warehouse_name, warehouse_type, taken):
	"""GIT for a transit warehouse, else the name's initials (Main Store is MS); a code already in
	`taken` gets a number (M, M2), so no two branches share a counter."""
	words = "".join(c if c.isalnum() else " " for c in warehouse_name or "").split()
	base = "GIT" if warehouse_type == "Transit" else "".join(w[0] for w in words).upper() or "W"
	code, n = base, 1
	while code in taken:
		n += 1
		code = f"{base}{n}"
	return code


def _suggested_codes():
	"""A code for each enabled, non-group warehouse that has none. Set codes are never changed."""
	if not frappe.get_meta("Warehouse").has_field(FIELD):
		return []
	warehouses = frappe.get_all(
		"Warehouse", filters={"is_group": 0, "disabled": 0}, fields=["name", "warehouse_name", "warehouse_type", FIELD], order_by="creation asc"
	)
	taken = {(w[FIELD] or "").strip() for w in warehouses} | {
		(c or "").strip() for c in frappe.get_all("Warehouse", filters={"disabled": 1}, pluck=FIELD)
	}
	codes = []
	for w in warehouses:
		if (w[FIELD] or "").strip():
			continue
		code = suggest_code(w.warehouse_name, w.warehouse_type, taken)
		taken.add(code)
		codes.append({"warehouse": w.name, "code": code})
	return codes


@frappe.whitelist()
def get_suggested_series():
	"""The Apply dialog: each doctype's suggested series, its default now, and the next names it
	gives on the latest document (so the preview shows this site's real codes)."""
	from frappe.model.naming import NamingSeries

	frappe.only_for("System Manager")
	rows = []
	for doctype, series in SUGGESTED_SERIES.items():
		options = _series_options(doctype)
		rows.append(
			{
				"doctype": doctype,
				"series": series,
				"current": options[0] if options else "",
				"only": options == [series],
				"preview": NamingSeries(series).get_preview(doc=_last_doc(doctype))[0],
			}
		)
	return {"enabled": is_enabled(), "rows": rows, "codes": _suggested_codes()}


@frappe.whitelist(methods=["POST"])
def apply_suggested_series(company):
	"""Replace each doctype's series list with its suggested series (the default, also for POS).
	Existing documents keep their names; a draft still holding an old series saves, since frappe
	never validates naming_series against its options.
	`company` must be typed exactly as a Company is named: the series are global, so this is a
	confirmation, not a filter. Also fills each blank warehouse Naming Code (`_suggested_codes`).
	Returns the doctypes and codes changed; a second run changes nothing."""
	frappe.only_for("System Manager")
	if not is_enabled():
		frappe.throw(_("Enable Branch Naming Codes and save first, or the placeholders stay literal text."))
	# MariaDB compares names case-insensitively; the confirmation must match the spelling exactly.
	if not company or company not in frappe.get_all("Company", pluck="name"):
		frappe.throw(_("Type the company name exactly as it is spelt to confirm."))

	dns = frappe.get_doc("Document Naming Settings")
	dns.user_must_always_select = 0
	changed = []
	for doctype, series in SUGGESTED_SERIES.items():
		if _series_options(doctype) == [series]:
			continue
		dns.transaction_type = doctype
		dns.naming_series_options = series
		dns.check_duplicate()
		dns.set_series_options_in_meta(doctype, dns.naming_series_options)
		changed.append(doctype)
	codes = _suggested_codes()
	for c in codes:
		frappe.db.set_value("Warehouse", c["warehouse"], FIELD, c["code"])
	return {"series": changed, "codes": codes}
