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


def _build_rules(settings):
	"""{item_group: (basis, percent)} for rows with an item group and non-zero percent."""
	rules = {}
	for row in settings.get("min_selling_price_rules") or []:
		if row.item_group and flt(row.floor_percent):
			rules[row.item_group] = (row.basis or "Valuation Rate", flt(row.floor_percent))
	return rules


def _group_chain(item_group):
	if not item_group:
		return []
	return [item_group] + (get_ancestors_of("Item Group", item_group) or [])


def _basis_rate(item, basis, rate_field):
	conversion_factor = flt(item.get("conversion_factor")) or 1.0
	if basis == "Last Purchase Rate":
		rate = flt(frappe.get_cached_value("Item", item.item_code, "last_purchase_rate"))
	else:  # Valuation Rate
		rate = flt(item.get(rate_field))
		if not rate:
			rate = flt(frappe.get_cached_value("Item", item.item_code, "valuation_rate"))
	return rate * conversion_factor


def validate_min_selling_price(doc, method=None):
	if not is_feature_enabled("enable_min_selling_price"):
		return
	if doc.get("is_return") or doc.get("is_internal_customer"):
		return

	settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	rules = _build_rules(settings)
	default_basis = settings.get("min_selling_price_default_basis") or "Valuation Rate"
	default_percent = flt(settings.get("min_selling_price_default_percent"))
	if not rules and not default_percent:
		return

	override_role = settings.get("min_selling_price_override_role")
	can_override = bool(override_role) and override_role in frappe.get_roles()
	rate_field = "valuation_rate" if doc.doctype in ("Sales Order", "Quotation") else "incoming_rate"

	resolved = {}  # item_group -> (basis, percent) | None
	for item in doc.get("items") or []:
		if not item.item_code or item.get("is_free_item"):
			continue
		item_group = item.get("item_group") or frappe.get_cached_value("Item", item.item_code, "item_group")
		if item_group not in resolved:
			resolved[item_group] = pick_rule(_group_chain(item_group), rules, default_basis, default_percent)
		chosen = resolved[item_group]
		if not chosen:
			continue
		basis, percent = chosen
		basis_rate = _basis_rate(item, basis, rate_field)
		if basis_rate <= 0:
			continue
		floor = compute_floor(basis_rate, percent, item.precision("base_net_rate"))
		if flt(item.base_net_rate) < floor:
			_handle_violation(item, item_group, basis, percent, floor, override_role, can_override)


def _handle_violation(item, item_group, basis, percent, floor, override_role, can_override):
	message = _(
		"Row #{0}: Selling rate for item {1} is below the minimum for item group {2} "
		"({3}, {4}%). Net selling rate should be at least {5}."
	).format(
		item.idx,
		frappe.bold(item.item_name or item.item_code),
		frappe.bold(item_group),
		basis,
		f"{flt(percent):+g}",
		frappe.bold(floor),
	)
	if can_override:
		frappe.msgprint(
			message + " " + _("Allowed because you have the {0} role.").format(frappe.bold(override_role)),
			title=_("Below Minimum Selling Price"),
			indicator="orange",
		)
		return
	if override_role:
		message += "<br><br>" + _("Users with the {0} role can override this.").format(frappe.bold(override_role))
	frappe.throw(message, title=_("Below Minimum Selling Price"))
