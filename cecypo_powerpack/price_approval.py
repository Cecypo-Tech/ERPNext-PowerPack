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
	"""doc_events on Workflow (validate, on_trash): only the settings sync may touch ours."""
	name = doc.name or doc.get("workflow_name") or ""
	if name.startswith(WORKFLOW_PREFIX) and not frappe.flags.powerpack_workflow_sync:
		frappe.throw(_("This workflow is managed by PowerPack Settings → Pricing. Change it there."))
