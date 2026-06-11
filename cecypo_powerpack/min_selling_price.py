# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Minimum selling price validation by item group (PowerPack feature)."""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import get_ancestors_of

from cecypo_powerpack.utils import is_feature_enabled

SETTINGS_DOCTYPE = "PowerPack Settings"
TARGET_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "POS Invoice", "Delivery Note")


def compute_floor(basis_rate, percent, precision):
	"""Minimum net rate = basis_rate * (1 + percent/100), rounded to precision."""
	return flt(flt(basis_rate) * (1 + flt(percent) / 100.0), precision)


def pick_rule(group_chain, rules, default_basis, default_percent):
	"""Return (basis, percent) for an item group, or None to defer to native ERPNext.

	group_chain: [item_group, parent, grandparent, ..., root] (most specific first).
	rules: {item_group: (basis, percent)} for configured, non-zero overrides.
	"""
	for group in group_chain:
		if group in rules:
			return rules[group]
	if flt(default_percent):
		return (default_basis, flt(default_percent))
	return None
