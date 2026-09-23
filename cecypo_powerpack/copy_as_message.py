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

import frappe

# Client Script name -> (DocType, source file under client_scripts/)
SCRIPTS = {
	"PowerPack - Copy as Message (Quotation)": ("Quotation", "copy_as_message_quotation.js"),
	"PowerPack - Copy as Message (Sales Order)": ("Sales Order", "copy_as_message_sales_order.js"),
	"PowerPack - Copy as Message (Sales Invoice)": ("Sales Invoice", "copy_as_message_sales_invoice.js"),
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
