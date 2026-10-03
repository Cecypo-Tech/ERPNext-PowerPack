# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Copy as Message: Client Scripts that PowerPack creates once and then leaves to the site.

These are deliberately not fixtures. ``sync_fixtures`` imports with ``force=True`` on
every ``bench migrate``, which would overwrite a site's edits (its bank details live in
the script) and re-enable a script the site switched off. So they are created only when
missing - on install and after every migrate, which makes deleting a script the way to
reset it to the shipped version - and carry no module, which keeps the ``Client Script``
fixture filter in hooks.py (``module = Cecypo PowerPack``) from exporting them.
"""

import os
import re

import frappe

# Client Script name -> (DocType, source file under client_scripts/)
SCRIPTS = {
	"PowerPack - Copy as Message (Quotation)": ("Quotation", "copy_as_message_quotation.js"),
	"PowerPack - Copy as Message (Sales Order)": ("Sales Order", "copy_as_message_sales_order.js"),
	"PowerPack - Copy as Message (Sales Invoice)": ("Sales Invoice", "copy_as_message_sales_invoice.js"),
	"PowerPack - Copy as Message (Purchase Order)": ("Purchase Order", "copy_as_message_purchase_order.js"),
}

# Hand-made site scripts the above replace, by the DocType they cover. Disabled - never
# deleted, since they may hold the site's bank details, which have to be copied into the
# new script by hand - and only when the replacement is created, so a site that turns one
# back on is not overruled on every migrate.
LEGACY_SCRIPTS = {"SI - Copy to Clipboard": "Sales Invoice"}


def script_source(name):
	_, filename = SCRIPTS[name]
	with open(os.path.join(os.path.dirname(__file__), "client_scripts", filename)) as f:
		return f.read()


def seed_client_scripts():
	"""Idempotent. Wired to after_install and after_migrate."""
	for name, (doctype, _) in SCRIPTS.items():
		if frappe.db.exists("Client Script", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": name,
				"dt": doctype,
				"view": "Form",
				"enabled": 1,
				"script": script_source(name),
			}
		).insert(ignore_permissions=True, set_name=name)

		for legacy, legacy_doctype in LEGACY_SCRIPTS.items():
			if legacy_doctype == doctype and frappe.db.get_value("Client Script", legacy, "enabled"):
				frappe.db.set_value("Client Script", legacy, "enabled", 0)


# The button the script adds, as written in its source: __('Copy as Message') or the bare
# string. The same pattern klik_pos uses to find the script for held orders.
COPY_MESSAGE_BUTTON = re.compile(r"add_custom_button\(\s*(?:__\(\s*)?['\"]Copy as Message['\"]")


@frappe.whitelist()
def get_copy_message_script(doctype: str):
	"""Source of the site's enabled "Copy as Message" Client Script for ``doctype``, or None.

	The print preview runs it against a stub frm so its Powerup menu offers the same
	action as the form's. The site may have renamed or rewritten the script, so it is
	found by what it does (the button it adds), with the seeded name preferred when
	several match. Form Client Scripts are served to every desk user who opens the form,
	so read permission on the doctype is the right gate.
	"""
	if not frappe.has_permission(doctype, "read"):
		return None
	rows = frappe.get_all(
		"Client Script",
		filters={"dt": doctype, "enabled": 1, "view": "Form"},
		fields=["name", "script"],
		order_by="name asc",
	)
	rows.sort(key=lambda row: row.name != f"PowerPack - Copy as Message ({doctype})")
	return next((row.script for row in rows if COPY_MESSAGE_BUTTON.search(row.script or "")), None)
