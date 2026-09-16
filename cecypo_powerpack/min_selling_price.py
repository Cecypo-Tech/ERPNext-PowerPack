# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Minimum selling price validation by item group (PowerPack feature)."""

import frappe
from frappe import _
from frappe.utils import cint, flt
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


def _basis_rate(doc, item, basis, rate_field):
	conversion_factor = flt(item.get("conversion_factor")) or 1.0
	if basis == "Last Purchase Rate":
		rate = flt(frappe.get_cached_value("Item", item.item_code, "last_purchase_rate"))
	else:  # Valuation Rate
		rate = flt(item.get(rate_field))
		if not rate:
			rate = _current_valuation_rate(doc, item)
	return rate * conversion_factor


def _current_valuation_rate(doc, item):
	"""Cost of the item at the row's warehouse, in stock UOM.

	ERPNext fills the row's ``incoming_rate`` only on Delivery Note and a Sales
	Invoice that updates stock. POS Invoice and a non-stock Sales Invoice reach
	validate with it empty, and the Item master's ``valuation_rate`` is a manual
	default that is blank on almost every item, so falling back to that skipped the
	row silently. Use the same source Quotation / Sales Order get from
	``get_item_details``: the Bin for the warehouse (the moving-average cost of what
	is on hand), then the item master.
	"""
	from erpnext.stock.get_item_details import get_valuation_rate

	return flt(
		(get_valuation_rate(item.item_code, doc.get("company"), item.get("warehouse")) or {}).get(
			"valuation_rate"
		)
	)


def _judged_rows(doc, settings, rules, default_basis, default_percent):
	"""Yield (item, (basis, percent), has_override) for every row a floor applies to.

	Skips rows with no item, free rows, rows exempted by a Pricing Rule, and rows
	whose group has no rule in force. has_override is True when the rule came from
	a per-group row (the group or an ancestor), False when it is the global
	default — whole-sale mode judges only override rows individually.
	"""
	skip_if_pricing_rule = settings.get("min_selling_price_skip_if_pricing_rule")
	resolved = {}  # item_group -> ((basis, percent) | None, has_override)
	for item in doc.get("items") or []:
		if not item.item_code or item.get("is_free_item"):
			continue
		if skip_if_pricing_rule and item.get("pricing_rules"):
			continue
		item_group = item.get("item_group") or frappe.get_cached_value("Item", item.item_code, "item_group")
		if item_group not in resolved:
			chain = _group_chain(item_group)
			resolved[item_group] = (
				pick_rule(chain, rules, default_basis, default_percent),
				any(group in rules for group in chain),
			)
		chosen, has_override = resolved[item_group]
		if not chosen:
			continue
		yield item, chosen, has_override


def judged_items(doc):
	"""The rows the floor applies to under the current settings (for approval snapshots)."""
	settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	rules = _build_rules(settings)
	default_basis = settings.get("min_selling_price_default_basis") or "Valuation Rate"
	default_percent = flt(settings.get("min_selling_price_default_percent"))
	return [item for item, _rule, _override in _judged_rows(doc, settings, rules, default_basis, default_percent)]


def validate_min_selling_price(doc, method=None):
	# Frappe's test-record bootstrap saves sales documents at arbitrary rates; only
	# tests that opt in exercise the floor.
	if frappe.flags.in_test and not frappe.flags.powerpack_test_min_selling_price:
		return
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
	whole_sale = cint(settings.get("min_selling_price_whole_sale"))
	# The sale-level gate needs a global % to gate against; with 0 only the
	# per-row guardrails of override groups apply.
	sale_gate = bool(whole_sale and default_percent)
	rate_field = "valuation_rate" if doc.doctype in ("Sales Order", "Quotation") else "incoming_rate"

	cost_total = 0.0  # sale gate: every judged row's cost under the *global* basis
	net_total = 0.0  # sale gate: the same rows' net amounts
	breaches = []  # (item, floor) for rows below their own floor
	sale_breach = None  # the sale floor, when the sale as a whole is short

	for item, (basis, percent), has_override in _judged_rows(
		doc, settings, rules, default_basis, default_percent
	):
		# Per-row floor: always in per-item mode; in whole-sale mode only for rows
		# whose group has its own override (a guardrail, possibly negative). A row
		# with no cost under its own basis cannot be judged on its own.
		if not whole_sale or has_override:
			basis_rate = _basis_rate(doc, item, basis, rate_field)
			if basis_rate > 0:
				floor = compute_floor(basis_rate, percent, item.precision("base_net_rate"))
				if flt(item.base_net_rate) < floor:
					breaches.append((item, floor))

		# The sale gate is one rule with one basis, so every row is costed the
		# global way for the total — independently of its own basis, or a row
		# never purchased would fall out of the sale (loss and all) just because
		# its override reads Last Purchase Rate.
		if sale_gate:
			global_rate = _basis_rate(doc, item, default_basis, rate_field)
			if global_rate > 0:
				cost_total += global_rate * flt(item.qty)
				net_total += flt(item.base_net_amount)

	if sale_gate and cost_total > 0:
		precision = doc.precision("base_net_total")
		sale_floor = compute_floor(cost_total, default_percent, precision)
		if flt(net_total, precision) < sale_floor:
			sale_breach = sale_floor

	from cecypo_powerpack import price_approval

	if not breaches and sale_breach is None:
		price_approval.set_breach_flag(doc, 0)
		return

	if can_override:
		for item, floor in breaches:
			_handle_violation(item, floor, True)
		if sale_breach is not None:
			_handle_sale_violation(sale_breach, True)
		price_approval.set_breach_flag(doc, 0)
		return

	if not price_approval.routing_applies(doc, settings):
		# An approved held order still covers its checkout invoice when invoice routing
		# is off, so the till needs only the Sales Order switch.
		if price_approval.carry_over_source_approval(doc):
			price_approval.set_breach_flag(doc, 1)
			return
		# Today's hard block: the first breaching row, else the sale.
		if breaches:
			item, floor = breaches[0]
			_handle_violation(item, floor, False)
		_handle_sale_violation(sale_breach, False)

	price_approval.handle_routed_breach(doc, breaches, sale_breach)


def _handle_violation(item, floor, can_override):
	# Deliberately does NOT reveal the basis (valuation/last purchase) or the margin %,
	# so staff cannot back-calculate cost from the message. Only the floor is shown.
	title = _("Powerpack Restrictions")
	item_label = item.get("item_name") or item.item_code
	if can_override:
		frappe.msgprint(
			_("Row #{0} ({1}): Net selling rate is below {2} — allowed by your role.").format(
				item.idx, item_label, frappe.bold(floor)
			),
			title=title,
			indicator="orange",
		)
		return
	frappe.throw(
		_("Row #{0} ({1}): Net selling rate should be at least {2}.").format(
			item.idx, item_label, frappe.bold(floor)
		),
		title=title,
	)


def _handle_sale_violation(floor, can_override):
	# Same rule as _handle_violation: show the floor, never the cost or the margin.
	title = _("Powerpack Restrictions")
	if can_override:
		frappe.msgprint(
			_("Net total of this sale is below {0} — allowed by your role.").format(frappe.bold(floor)),
			title=title,
			indicator="orange",
		)
		return
	frappe.throw(
		_("Net total of this sale should be at least {0}.").format(frappe.bold(floor)),
		title=title,
	)
