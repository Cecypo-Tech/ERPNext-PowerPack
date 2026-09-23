# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Jinja methods (hooks.py ``jinja``). A method is exposed under its function name."""

import frappe

from cecypo_powerpack.api import build_public_link


def get_document_public_link(doctype, name):
	"""Short public link for print formats: ``{{ get_document_public_link(doc.doctype, doc.name) }}``.

	No permission check, unlike the whitelisted API of the same name: a share-key web view
	renders the print format as Guest, and only privileged users author print formats.
	"""
	return build_public_link(frappe.get_doc(doctype, name))
