# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

ROLE = "_MSP Override Role"


def ensure_workflow_state_columns():
	"""Frappe adds `workflow_state` when a Workflow is first saved — DDL, which commits.
	Create it up front (same definition Frappe uses) so tests never trigger it."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	from cecypo_powerpack import price_approval as pa

	pa.setup_custom_fields()
	for dt in pa.APPROVAL_DOCTYPES:
		if not frappe.get_meta(dt).get_field(pa.STATE_FIELD):
			create_custom_field(
				dt,
				{
					"fieldname": pa.STATE_FIELD, "label": "Workflow State", "fieldtype": "Link",
					"options": "Workflow State", "hidden": 1, "allow_on_submit": 1, "no_copy": 1,
				},
				ignore_validate=True,
			)
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
	frappe.db.commit()


class SettingsSnapshot:
	"""Put the site's own PowerPack Settings values back when the class is done.

	FrappeTestCase rolls the database back once per class, and its next class's
	setUpClass commits whatever is still pending — so a test that saves the
	singleton would otherwise overwrite the site's real configuration.
	"""

	SETTINGS_FIELDS = (
		"enable_min_selling_price",
		"min_selling_price_default_basis",
		"min_selling_price_default_percent",
		"min_selling_price_override_role",
		"min_selling_price_skip_if_pricing_rule",
		"min_selling_price_whole_sale",
		"msp_approval_quotation",
		"msp_approval_sales_order",
		"msp_approval_sales_invoice",
		"msp_approval_delivery_note",
	)

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("PowerPack Settings")
		cls._settings_before = {field: settings.get(field) for field in cls.SETTINGS_FIELDS}

	@classmethod
	def tearDownClass(cls):
		# Drop everything the class wrote first: the rollback below the restore is
		# FrappeTestCase's own class cleanup, which runs *after* the commit here and
		# so cannot undo it — without this the commit would persist the test
		# workflows and their workflow_state writes on real documents.
		frappe.db.rollback()
		settings = frappe.get_single("PowerPack Settings")
		for field, value in cls._settings_before.items():
			settings.set(field, value)
		settings.flags.ignore_version = True
		settings.save()
		frappe.db.commit()
		super().tearDownClass()


class TestPriceApprovalFields(FrappeTestCase):
	def test_custom_fields_exist_on_every_approval_doctype(self):
		from cecypo_powerpack import price_approval as pa

		pa.setup_custom_fields()
		for dt in pa.APPROVAL_DOCTYPES:
			meta = frappe.get_meta(dt)
			for fieldname in (pa.BREACH_FIELD, *pa.APPROVAL_FIELDS):
				self.assertTrue(meta.get_field(fieldname), f"{dt} lacks {fieldname}")
		self.assertTrue(frappe.get_meta("Sales Invoice").get_field(pa.SOURCE_ORDER_FIELD))
		self.assertFalse(frappe.get_meta("Sales Order").get_field(pa.SOURCE_ORDER_FIELD))

	def test_source_order_is_data_not_link(self):
		# klik_pos deletes the held Sales Order right after checkout; a Link here
		# would make that delete fail with LinkExistsError.
		from cecypo_powerpack import price_approval as pa

		df = frappe.get_meta("Sales Invoice").get_field(pa.SOURCE_ORDER_FIELD)
		self.assertEqual(df.fieldtype, "Data")

	def test_setup_is_idempotent(self):
		from cecypo_powerpack import price_approval as pa

		pa.setup_custom_fields()
		pa.setup_custom_fields()
		names = frappe.get_all(
			"Custom Field", filters={"dt": "Sales Order", "fieldname": pa.BREACH_FIELD}, pluck="name"
		)
		self.assertEqual(len(names), 1)


class TestPriceApprovalSettings(SettingsSnapshot, FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_workflow_state_columns()

	def tearDown(self):
		frappe.clear_cache(doctype="PowerPack Settings")

	def _settings(self, **values):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.min_selling_price_default_percent = 4
		s.min_selling_price_override_role = None
		for dt_field in ("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note"):
			s.set(dt_field, 0)
		for key, value in values.items():
			s.set(key, value)
		return s

	def test_fields_exist_after_the_diagram(self):
		meta = frappe.get_meta("PowerPack Settings")
		order = [f.fieldname for f in meta.fields]
		for i, fieldname in enumerate(("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note")):
			df = meta.get_field(fieldname)
			self.assertTrue(df, fieldname)
			self.assertEqual(df.fieldtype, "Check")
			self.assertEqual(order.index(fieldname), order.index("min_selling_price_whole_sale_diagram") + 1 + i)

	def test_routing_needs_an_override_role(self):
		s = self._settings(msp_approval_sales_order=1)
		with self.assertRaisesRegex(frappe.ValidationError, "Role Allowed to Override"):
			s.save()

	def test_routing_refuses_a_foreign_active_workflow(self):
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		if frappe.db.exists("Workflow", "_MSP Foreign SO Workflow"):
			frappe.delete_doc("Workflow", "_MSP Foreign SO Workflow", force=True)
		frappe.get_doc({
			"doctype": "Workflow", "workflow_name": "_MSP Foreign SO Workflow", "document_type": "Sales Order",
			"workflow_state_field": "workflow_state", "is_active": 1,
			"states": [{"state": "Draft", "doc_status": "0", "allow_edit": "All"}],
		}).insert()
		try:
			s = self._settings(msp_approval_sales_order=1, min_selling_price_override_role=ROLE)
			with self.assertRaisesRegex(frappe.ValidationError, "_MSP Foreign SO Workflow"):
				s.save()
		finally:
			frappe.clear_cache(doctype="Sales Order")

	def test_routing_off_needs_nothing(self):
		s = self._settings()
		s.save()  # must not raise


class TestWorkflowSync(SettingsSnapshot, FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_workflow_state_columns()

	def tearDown(self):
		from cecypo_powerpack import price_approval as pa

		for dt in pa.APPROVAL_DOCTYPES:
			frappe.clear_cache(doctype=dt)
		frappe.clear_cache(doctype="PowerPack Settings")

	def _configure(self, **flags):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.min_selling_price_default_percent = 4
		s.min_selling_price_override_role = ROLE
		for f in ("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note"):
			s.set(f, flags.get(f, 0))
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		return s

	def test_sync_creates_the_workflow_with_states_transitions_and_roles(self):
		from cecypo_powerpack import price_approval as pa

		self._configure(msp_approval_sales_order=1)
		wf = frappe.get_doc("Workflow", pa.workflow_name_for("Sales Order"))
		self.assertEqual(wf.document_type, "Sales Order")
		self.assertEqual(wf.is_active, 1)
		self.assertEqual(wf.send_email_alert, 1)
		self.assertEqual(
			[(s.state, s.doc_status, s.allow_edit) for s in wf.states],
			[
				(pa.STATE_DRAFT, "0", "All"),
				(pa.STATE_PENDING, "0", ROLE),
				(pa.STATE_APPROVED, "0", "All"),
				(pa.STATE_SUBMITTED, "1", "All"),
				(pa.STATE_CANCELLED, "2", "All"),
			],
		)
		self.assertEqual(
			[(t.state, t.action, t.next_state, t.allowed, t.condition or "") for t in wf.transitions],
			[
				(pa.STATE_DRAFT, pa.ACTION_REQUEST, pa.STATE_PENDING, "All", "doc.powerpack_price_breach"),
				(pa.STATE_DRAFT, pa.ACTION_SUBMIT, pa.STATE_SUBMITTED, "All", "not doc.powerpack_price_breach"),
				(pa.STATE_PENDING, pa.ACTION_APPROVE, pa.STATE_APPROVED, ROLE, ""),
				(pa.STATE_PENDING, pa.ACTION_REJECT, pa.STATE_DRAFT, ROLE, ""),
				(pa.STATE_APPROVED, pa.ACTION_SUBMIT, pa.STATE_SUBMITTED, "All", ""),
				(pa.STATE_APPROVED, pa.ACTION_WITHDRAW, pa.STATE_DRAFT, "All", ""),
				(pa.STATE_SUBMITTED, pa.ACTION_CANCEL, pa.STATE_CANCELLED, "All", ""),
			],
		)
		self.assertFalse(frappe.db.exists("Workflow", pa.workflow_name_for("Quotation")))

	def test_unticking_deactivates_but_keeps_the_workflow(self):
		from cecypo_powerpack import price_approval as pa

		self._configure(msp_approval_sales_order=1)
		self._configure(msp_approval_sales_order=0)
		self.assertEqual(frappe.db.get_value("Workflow", pa.workflow_name_for("Sales Order"), "is_active"), 0)

	def test_role_change_resyncs(self):
		from cecypo_powerpack import price_approval as pa

		other = "_MSP Other Role"
		if not frappe.db.exists("Role", other):
			frappe.get_doc({"doctype": "Role", "role_name": other}).insert()
		self._configure(msp_approval_sales_order=1)
		s = frappe.get_single("PowerPack Settings")
		s.min_selling_price_override_role = other
		s.save()
		wf = frappe.get_doc("Workflow", pa.workflow_name_for("Sales Order"))
		approve = next(t for t in wf.transitions if t.action == pa.ACTION_APPROVE)
		self.assertEqual(approve.allowed, other)

	def test_manual_edit_and_delete_are_refused(self):
		from cecypo_powerpack import price_approval as pa

		self._configure(msp_approval_sales_order=1)
		wf = frappe.get_doc("Workflow", pa.workflow_name_for("Sales Order"))
		wf.send_email_alert = 0
		with self.assertRaisesRegex(frappe.ValidationError, "managed by PowerPack Settings"):
			wf.save()
		with self.assertRaisesRegex(frappe.ValidationError, "managed by PowerPack Settings"):
			frappe.delete_doc("Workflow", wf.name)

	def test_activating_a_foreign_workflow_while_ours_is_on_is_refused(self):
		if frappe.db.exists("Workflow", "_MSP Late Foreign SO Workflow"):
			frappe.delete_doc("Workflow", "_MSP Late Foreign SO Workflow", force=True)
		self._configure(msp_approval_sales_order=1)
		foreign = frappe.get_doc({
			"doctype": "Workflow", "workflow_name": "_MSP Late Foreign SO Workflow", "document_type": "Sales Order",
			"workflow_state_field": "workflow_state", "is_active": 1,
			"states": [{"state": "Draft", "doc_status": "0", "allow_edit": "All"}],
		})
		with self.assertRaisesRegex(frappe.ValidationError, "Turn it off there"):
			foreign.insert()
		# Ours is still the active one.
		from cecypo_powerpack import price_approval as pa

		self.assertEqual(frappe.db.get_value("Workflow", pa.workflow_name_for("Sales Order"), "is_active"), 1)

	def test_an_inactive_foreign_workflow_is_allowed(self):
		if frappe.db.exists("Workflow", "_MSP Idle Foreign SO Workflow"):
			frappe.delete_doc("Workflow", "_MSP Idle Foreign SO Workflow", force=True)
		self._configure(msp_approval_sales_order=1)
		foreign = frappe.get_doc({
			"doctype": "Workflow", "workflow_name": "_MSP Idle Foreign SO Workflow", "document_type": "Sales Order",
			"workflow_state_field": "workflow_state", "is_active": 0,
			"states": [{"state": "Draft", "doc_status": "0", "allow_edit": "All"}],
		})
		foreign.insert()  # must not raise
		self.assertTrue(frappe.db.exists("Workflow", foreign.name))


@contextmanager
def as_requester():
	"""Administrator holds every role, so the override role is always 'held'.
	Present the session as a plain Sales User for the duration; permission
	checks still short-circuit on the Administrator user name."""
	with patch.object(frappe, "get_roles", return_value=["All", "Guest", "Sales User", "System Manager"]):
		yield


class TestRoutedBreach(SettingsSnapshot, FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from cecypo_powerpack.tests.test_min_selling_price import ensure_msp_fixtures

		ensure_msp_fixtures()
		ensure_workflow_state_columns()

	def setUp(self):
		frappe.db.set_single_value("Selling Settings", "validate_selling_price", 0)
		frappe.flags.powerpack_test_min_selling_price = True
		# Frappe sends the workflow action email inline under frappe.in_test
		# (enqueue(..., now=frappe.in_test)) and hands attach_print the very doc
		# object the test holds, which comes back with flags.in_print set — after
		# which Document._save returns without writing anything. Every save after a
		# transition would silently do nothing, in tests only (in a request the job
		# is enqueued after commit and the doc is serialised). The emails are
		# frappe's, not ours.
		emails = patch(
			"frappe.workflow.doctype.workflow_action.workflow_action.send_workflow_action_email",
			new=lambda doc, transitions: None,
		)
		emails.start()
		self.addCleanup(emails.stop)
		self._configure(msp_approval_sales_order=1, msp_approval_sales_invoice=1)

	def tearDown(self):
		from cecypo_powerpack import price_approval as pa

		frappe.flags.powerpack_test_min_selling_price = False
		frappe.set_user("Administrator")
		# Nothing rolls the database back between tests, and submitting a Sales
		# Order creates a Bin for (_MSP Item, _Test Warehouse - _TC) to hold the
		# reserved qty. get_valuation_rate() prefers that Bin over the item master,
		# and its valuation_rate is 0 — which would silently take the floor out of
		# play for every test that runs after a submit. The fixtures are committed,
		# so only what this test wrote goes.
		frappe.db.rollback()
		for dt in pa.APPROVAL_DOCTYPES:
			frappe.clear_cache(doctype=dt)
		frappe.clear_cache(doctype="PowerPack Settings")

	def _configure(self, **flags):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.min_selling_price_default_basis = "Valuation Rate"
		s.min_selling_price_default_percent = 4
		s.min_selling_price_whole_sale = 0
		s.min_selling_price_override_role = ROLE
		s.set("min_selling_price_rules", [])
		for f in ("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note"):
			s.set(f, flags.get(f, 0))
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")

	def _so(self, rate, qty=1):
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		return make_sales_order(item_code="_MSP Item", qty=qty, rate=rate, do_not_save=True)

	def _approved_so(self, rate=90, qty=1):
		"""Breaching draft, requested by a plain user, approved by Administrator."""
		from frappe.model.workflow import apply_workflow

		from cecypo_powerpack import price_approval as pa

		with as_requester():
			so = self._so(rate, qty)
			so.save()
			so = apply_workflow(so, pa.ACTION_REQUEST)
		so = apply_workflow(so, pa.ACTION_APPROVE)
		return frappe.get_doc("Sales Order", so.name)

	# ---- draft saves ----------------------------------------------------------

	def test_breaching_draft_saves_with_the_flag_set(self):
		from cecypo_powerpack import price_approval as pa

		with as_requester():
			so = self._so(90)  # floor is 104
			so.save()
		self.assertEqual(so.get(pa.BREACH_FIELD), 1)
		self.assertEqual(so.get(pa.STATE_FIELD), pa.STATE_DRAFT)

	def test_clean_draft_clears_the_flag(self):
		from cecypo_powerpack import price_approval as pa

		with as_requester():
			so = self._so(120)
			so.save()
		self.assertEqual(so.get(pa.BREACH_FIELD), 0)

	def test_override_role_user_is_not_routed(self):
		# Administrator holds the override role: warning, flag cleared, no request needed.
		from cecypo_powerpack import price_approval as pa

		so = self._so(90)
		so.save()
		self.assertEqual(so.get(pa.BREACH_FIELD), 0)

	def test_routing_off_still_hard_blocks(self):
		self._configure()  # no doctype ticked; workflow deactivated
		with as_requester():
			with self.assertRaisesRegex(frappe.ValidationError, "at least"):
				self._so(90).save()

	# ---- submit gate -----------------------------------------------------------

	def test_submit_without_approval_is_blocked(self):
		with as_requester():
			so = self._so(90)
			so.save()
			with self.assertRaisesRegex(frappe.ValidationError, "Price approval needed"):
				so.submit()

	def test_request_then_approve_stamps_and_allows_submit(self):
		from cecypo_powerpack import price_approval as pa

		so = self._approved_so(rate=90)
		self.assertEqual(so.get(pa.STATE_FIELD), pa.STATE_APPROVED)
		self.assertEqual(so.get(pa.APPROVED_BY_FIELD), "Administrator")
		self.assertTrue(so.get(pa.APPROVED_ON_FIELD))
		rows = pa.load_rows(so.get(pa.APPROVED_ROWS_FIELD))
		self.assertEqual([(r["item_code"], r["qty"], r["base_net_rate"]) for r in rows], [("_MSP Item", 1.0, 90.0)])
		with as_requester():
			so.submit()
		self.assertEqual(so.docstatus, 1)

	def test_requester_cannot_edit_while_pending(self):
		from frappe.model.workflow import apply_workflow

		from cecypo_powerpack import price_approval as pa

		with as_requester():
			so = self._so(90)
			so.save()
			so = apply_workflow(so, pa.ACTION_REQUEST)
			so.items[0].rate = 95
			with self.assertRaises(frappe.ValidationError):
				so.save()

	def test_lowering_an_approved_rate_is_refused(self):
		so = self._approved_so(rate=90)
		with as_requester():
			so.items[0].rate = 85
			with self.assertRaisesRegex(frappe.ValidationError, "approved prices changed"):
				so.save()

	def test_raising_an_approved_qty_is_refused(self):
		so = self._approved_so(rate=90, qty=2)
		with as_requester():
			so.items[0].qty = 3
			with self.assertRaisesRegex(frappe.ValidationError, "approved prices changed"):
				so.save()

	def test_raising_the_rate_after_approval_is_fine(self):
		so = self._approved_so(rate=90)
		with as_requester():
			so.items[0].rate = 95
			so.save()
			so.submit()
		self.assertEqual(so.docstatus, 1)

	def test_reject_and_withdraw_clear_the_stamp(self):
		from frappe.model.workflow import apply_workflow

		from cecypo_powerpack import price_approval as pa

		so = self._approved_so(rate=90)
		with as_requester():
			so = apply_workflow(so, pa.ACTION_WITHDRAW)
		so = frappe.get_doc("Sales Order", so.name)
		self.assertEqual(so.get(pa.STATE_FIELD), pa.STATE_DRAFT)
		self.assertFalse(so.get(pa.APPROVED_ROWS_FIELD))
		self.assertFalse(so.get(pa.APPROVED_BY_FIELD))

		with as_requester():
			so = apply_workflow(so, pa.ACTION_REQUEST)
		so = apply_workflow(so, pa.ACTION_REJECT)
		so = frappe.get_doc("Sales Order", so.name)
		self.assertEqual(so.get(pa.STATE_FIELD), pa.STATE_DRAFT)
		self.assertFalse(so.get(pa.APPROVED_ROWS_FIELD))

	def test_whole_sale_mode_routes_the_sale_breach(self):
		from cecypo_powerpack import price_approval as pa

		s = frappe.get_single("PowerPack Settings")
		s.min_selling_price_whole_sale = 1
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		with as_requester():
			so = self._so(90)  # 90 < 104 sale floor
			so.save()
			self.assertEqual(so.get(pa.BREACH_FIELD), 1)
			with self.assertRaisesRegex(frappe.ValidationError, "Price approval needed"):
				so.submit()
