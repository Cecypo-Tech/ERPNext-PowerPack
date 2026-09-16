# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Price approval routing for Minimum Selling Price breaches.

A breach by a user without the override role can be routed, per doctype,
through a Frappe Workflow that PowerPack Settings owns. Frappe carries the
request, the emails and the Approve/Reject actions; this module keeps the
enforcement, because a submit from code never goes through a transition
(frappe.model.workflow.validate_workflow only checks a transition when the
state field changes).
"""

import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, now_datetime

APPROVAL_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")
SETTING_FOR_DOCTYPE = {
	"Quotation": "msp_approval_quotation",
	"Sales Order": "msp_approval_sales_order",
	"Sales Invoice": "msp_approval_sales_invoice",
	"Delivery Note": "msp_approval_delivery_note",
}
WORKFLOW_PREFIX = "PowerPack Price Approval - "
STATE_FIELD = "workflow_state"

STATE_DRAFT = "Draft"
STATE_PENDING = "Price Approval Pending"
STATE_APPROVED = "Price Approved"
STATE_SUBMITTED = "Submitted"
STATE_CANCELLED = "Cancelled"
STATE_STYLES = {
	STATE_DRAFT: "",
	STATE_PENDING: "Warning",
	STATE_APPROVED: "Success",
	STATE_SUBMITTED: "Primary",
	STATE_CANCELLED: "Danger",
}

ACTION_REQUEST = "Request Price Approval"
ACTION_APPROVE = "Approve"
ACTION_REJECT = "Reject"
ACTION_SUBMIT = "Submit"
ACTION_WITHDRAW = "Withdraw Approval"
ACTION_CANCEL = "Cancel"
ACTIONS = (ACTION_REQUEST, ACTION_APPROVE, ACTION_REJECT, ACTION_SUBMIT, ACTION_WITHDRAW, ACTION_CANCEL)

ALL_ROLE = "All"

BREACH_FIELD = "powerpack_price_breach"
APPROVED_BY_FIELD = "powerpack_price_approved_by"
APPROVED_ON_FIELD = "powerpack_price_approved_on"
APPROVED_ROWS_FIELD = "powerpack_price_approved_rows"
SOURCE_ORDER_FIELD = "powerpack_source_order"
APPROVAL_FIELDS = (APPROVED_BY_FIELD, APPROVED_ON_FIELD, APPROVED_ROWS_FIELD)

TITLE = "Powerpack Restrictions"


def custom_field_definitions():
	common = [
		{
			"fieldname": BREACH_FIELD,
			"label": "Below Minimum Selling Price",
			"fieldtype": "Check",
			"insert_after": "items",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
		{
			"fieldname": APPROVED_BY_FIELD,
			"label": "Price Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": BREACH_FIELD,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
		{
			"fieldname": APPROVED_ON_FIELD,
			"label": "Price Approved On",
			"fieldtype": "Datetime",
			"insert_after": APPROVED_BY_FIELD,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
		{
			"fieldname": APPROVED_ROWS_FIELD,
			"label": "Price Approved Rows",
			"fieldtype": "Small Text",
			"insert_after": APPROVED_ON_FIELD,
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
	]
	fields = {doctype: [dict(field) for field in common] for doctype in APPROVAL_DOCTYPES}
	# Data, not Link: klik_pos deletes the held order right after checkout and a
	# Link would turn that delete into a LinkExistsError.
	fields["Sales Invoice"].append(
		{
			"fieldname": SOURCE_ORDER_FIELD,
			"label": "Price Approval Source Order",
			"fieldtype": "Data",
			"insert_after": APPROVED_ROWS_FIELD,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		}
	)
	return fields


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(custom_field_definitions(), ignore_validate=True, update=True)


def routing_enabled(settings, doctype):
	field = SETTING_FOR_DOCTYPE.get(doctype)
	return bool(field and cint(settings.get(field)))


def workflow_name_for(doctype):
	return WORKFLOW_PREFIX + doctype


def validate_price_approval_settings(settings):
	"""PowerPackSettings.validate: routing needs an approver role and a free doctype."""
	wanted = [doctype for doctype in APPROVAL_DOCTYPES if routing_enabled(settings, doctype)]
	if not wanted:
		return
	if not settings.get("min_selling_price_override_role"):
		frappe.throw(_("Set a Role Allowed to Override first — it is the approver role."))
	for doctype in wanted:
		foreign = frappe.db.get_value(
			"Workflow",
			{"document_type": doctype, "is_active": 1, "name": ["not like", WORKFLOW_PREFIX + "%"]},
			"name",
		)
		if foreign:
			frappe.throw(
				_(
					"{0} already has an active workflow '{1}'. Deactivate it or leave price approval off for {0}."
				).format(doctype, foreign)
			)


def workflow_states(role):
	return [
		(STATE_DRAFT, "0", ALL_ROLE),
		(STATE_PENDING, "0", role),  # the requester cannot edit while pending
		(STATE_APPROVED, "0", ALL_ROLE),
		(STATE_SUBMITTED, "1", ALL_ROLE),
		(STATE_CANCELLED, "2", ALL_ROLE),
	]


def workflow_transitions(role):
	return [
		(STATE_DRAFT, ACTION_REQUEST, STATE_PENDING, ALL_ROLE, f"doc.{BREACH_FIELD}"),
		(STATE_DRAFT, ACTION_SUBMIT, STATE_SUBMITTED, ALL_ROLE, f"not doc.{BREACH_FIELD}"),
		(STATE_PENDING, ACTION_APPROVE, STATE_APPROVED, role, ""),
		(STATE_PENDING, ACTION_REJECT, STATE_DRAFT, role, ""),
		(STATE_APPROVED, ACTION_SUBMIT, STATE_SUBMITTED, ALL_ROLE, ""),
		(STATE_APPROVED, ACTION_WITHDRAW, STATE_DRAFT, ALL_ROLE, ""),
		(STATE_SUBMITTED, ACTION_CANCEL, STATE_CANCELLED, ALL_ROLE, ""),
	]


def _ensure_workflow_masters():
	for state, style in STATE_STYLES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(
				ignore_permissions=True
			)
	for action in ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)


def sync_price_approval_workflows(settings):
	"""PowerPackSettings.on_update: the settings are the only source of these workflows."""
	role = settings.get("min_selling_price_override_role")
	frappe.flags.powerpack_workflow_sync = True
	try:
		for doctype in APPROVAL_DOCTYPES:
			name = workflow_name_for(doctype)
			exists = frappe.db.exists("Workflow", name)
			if routing_enabled(settings, doctype):
				_ensure_workflow_masters()
				workflow = frappe.get_doc("Workflow", name) if exists else frappe.new_doc("Workflow")
				workflow.update(
					{
						"workflow_name": name,
						"document_type": doctype,
						"workflow_state_field": STATE_FIELD,
						"is_active": 1,
						"send_email_alert": 1,
						"override_status": 0,
					}
				)
				workflow.set("states", [])
				for state, doc_status, allow_edit in workflow_states(role):
					workflow.append("states", {"state": state, "doc_status": doc_status, "allow_edit": allow_edit})
				workflow.set("transitions", [])
				for state, action, next_state, allowed, condition in workflow_transitions(role):
					workflow.append(
						"transitions",
						{
							"state": state,
							"action": action,
							"next_state": next_state,
							"allowed": allowed,
							"allow_self_approval": 0,
							"condition": condition,
						},
					)
				workflow.save(ignore_permissions=True)
			elif exists and frappe.db.get_value("Workflow", name, "is_active"):
				# Deactivate, never delete: Workflow Action history stays readable.
				frappe.db.set_value("Workflow", name, "is_active", 0)
				frappe.clear_cache(doctype=doctype)
	finally:
		frappe.flags.powerpack_workflow_sync = False


def guard_managed_workflow(doc, method=None):
	"""doc_events on Workflow (before_validate, validate, on_trash).

	Ours may only be touched by the settings sync. And nobody may activate another
	workflow on a doctype whose PowerPack workflow is active: frappe's
	Workflow.set_active() would deactivate ours with a raw UPDATE, silently, while
	the settings still say price approval is on. Checked in before_validate so it
	runs before that UPDATE.
	"""
	name = doc.name or doc.get("workflow_name") or ""
	if name.startswith(WORKFLOW_PREFIX):
		if not frappe.flags.powerpack_workflow_sync:
			frappe.throw(_("This workflow is managed by PowerPack Settings → Pricing. Change it there."))
		return
	if method != "before_validate" or not cint(doc.get("is_active")):
		return
	doctype = doc.get("document_type")
	if doctype not in APPROVAL_DOCTYPES:
		return
	ours = workflow_name_for(doctype)
	if frappe.db.get_value("Workflow", ours, "is_active"):
		frappe.throw(
			_(
				"Price approval for {0} is on in PowerPack Settings → Pricing, which runs the workflow '{1}'. Turn it off there before activating another workflow on {0}."
			).format(doctype, ours)
		)


def _meta(doc):
	return getattr(doc, "meta", None)


def set_breach_flag(doc, value):
	meta = _meta(doc)
	if meta and meta.has_field(BREACH_FIELD):
		doc.set(BREACH_FIELD, cint(value))


def routing_applies(doc, settings):
	meta = _meta(doc)
	return bool(meta and meta.has_field(BREACH_FIELD) and routing_enabled(settings, doc.doctype))


def load_rows(raw):
	if not raw:
		return []
	try:
		rows = json.loads(raw)
	except (TypeError, ValueError):
		return []
	return rows if isinstance(rows, list) else []


def snapshot_rows(doc):
	from cecypo_powerpack.min_selling_price import judged_items

	return [
		{
			"item_code": item.item_code,
			"uom": item.get("uom") or None,
			"qty": flt(item.qty),
			"base_net_rate": flt(item.base_net_rate),
		}
		for item in judged_items(doc)
	]


def uncovered_rows(doc, approved_rows):
	"""idx of judged rows no approved row covers: same item and UOM, rate at or
	above the approved rate, quantity at or below the approved quantity."""
	from cecypo_powerpack.min_selling_price import judged_items

	missing = []
	for item in judged_items(doc):
		covered = any(
			row.get("item_code") == item.item_code
			and (row.get("uom") or None) == (item.get("uom") or None)
			and flt(item.base_net_rate) >= flt(row.get("base_net_rate"))
			and flt(item.qty) <= flt(row.get("qty"))
			for row in approved_rows
		)
		if not covered:
			missing.append(item.idx)
	return missing


def find_covering_approval(doc):
	"""The document's own stamp, else (Sales Invoice) the source order's. None when nothing covers."""
	own = load_rows(doc.get(APPROVED_ROWS_FIELD))
	if own:
		return doc if not uncovered_rows(doc, own) else None
	if doc.doctype != "Sales Invoice" or not doc.get(SOURCE_ORDER_FIELD):
		return None
	if not (frappe.db.has_column("Sales Order", STATE_FIELD) and frappe.db.has_column("Sales Order", APPROVED_ROWS_FIELD)):
		return None
	order = frappe.db.get_value(
		"Sales Order",
		doc.get(SOURCE_ORDER_FIELD),
		["name", "docstatus", "customer", STATE_FIELD, *APPROVAL_FIELDS],
		as_dict=True,
	)
	if not order or cint(order.docstatus) != 0 or order.get(STATE_FIELD) != STATE_APPROVED:
		return None
	if order.customer != doc.get("customer"):
		return None
	if uncovered_rows(doc, load_rows(order.get(APPROVED_ROWS_FIELD))):
		return None
	return order


def copy_approval_from_order(doc, order):
	"""The held order is deleted right after checkout; carry its approval and say so."""
	for field in APPROVAL_FIELDS:
		doc.set(field, order.get(field))
	doc.flags.powerpack_approval_comment = _("Price approved by {0} on {1} at {2}").format(
		order.get(APPROVED_BY_FIELD), order.name, order.get(APPROVED_ON_FIELD)
	)


def handle_routed_breach(doc, breaches, sale_breach):
	"""A breach the user may not override, on a doctype with routing on."""
	rows = ", ".join(str(item.idx) for item, _floor in breaches) or _("the sale total")

	if doc.get("_action") == "submit":
		approval = find_covering_approval(doc)
		if approval is None:
			frappe.throw(
				_("Price approval needed for row(s) {0}. Save as draft and use <b>Request Price Approval</b>.").format(rows),
				title=_(TITLE),
			)
		if approval is not doc:
			copy_approval_from_order(doc, approval)
		return

	set_breach_flag(doc, 1)
	approved = load_rows(doc.get(APPROVED_ROWS_FIELD))
	if approved and uncovered_rows(doc, approved):
		frappe.throw(
			_("The approved prices changed (row {0}). Restore them, or use <b>Withdraw Approval</b> and request again.").format(
				", ".join(str(idx) for idx in uncovered_rows(doc, approved))
			),
			title=_(TITLE),
		)
	if doc.get(STATE_FIELD) in (None, "", STATE_DRAFT):
		frappe.msgprint(
			_("Row(s) {0} are below the minimum selling price. Use <b>Request Price Approval</b> before submitting.").format(rows),
			title=_(TITLE),
			indicator="blue",
		)


def stamp_price_approval(doc, method=None):
	"""on_update of the four doctypes: stamp on entering Price Approved, clear on leaving it as a draft."""
	meta = _meta(doc)
	if not (meta and meta.has_field(APPROVED_ROWS_FIELD)):
		return
	comment = doc.flags.pop("powerpack_approval_comment", None)
	if comment:
		doc.add_comment("Comment", comment)
	before = doc.get_doc_before_save()
	previous = before.get(STATE_FIELD) if before else None
	current = doc.get(STATE_FIELD)
	if current == previous:
		return
	if current == STATE_APPROVED:
		values = {
			APPROVED_BY_FIELD: frappe.session.user,
			APPROVED_ON_FIELD: now_datetime(),
			APPROVED_ROWS_FIELD: json.dumps(snapshot_rows(doc)),
		}
	elif previous == STATE_APPROVED and cint(doc.docstatus) == 0:
		values = dict.fromkeys(APPROVAL_FIELDS, None)
	else:
		return
	doc.db_set(values, update_modified=False)


def guard_pending_edit(doc, method=None):
	"""before_validate on the four doctypes: hold a pending document still.

	A workflow state's ``allow_edit`` is enforced only by the desk form
	(frappe/public/js/frappe/model/workflow.js, ``is_read_only``) — frappe never
	checks it on the server. Without this, a requester could still lower a rate
	through the API after the approver had looked at the document, and the
	approval would then stamp the lowered price. Only a save that *leaves* the
	document pending is refused: Request (Draft to Pending) and Approve / Reject
	(Pending to something else) both change the state and pass through.
	"""
	if doc.get(STATE_FIELD) != STATE_PENDING:
		return
	before = doc.get_doc_before_save()
	if not before or before.get(STATE_FIELD) != STATE_PENDING:
		return
	settings = frappe.get_cached_doc("PowerPack Settings")
	if not routing_applies(doc, settings):
		return
	role = settings.get("min_selling_price_override_role")
	if role and role in frappe.get_roles():
		return
	frappe.throw(
		_("This document is waiting for price approval and cannot be changed. Ask an approver to approve or reject it first."),
		title=_(TITLE),
	)
