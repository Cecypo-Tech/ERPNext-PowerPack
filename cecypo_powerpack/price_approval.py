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
