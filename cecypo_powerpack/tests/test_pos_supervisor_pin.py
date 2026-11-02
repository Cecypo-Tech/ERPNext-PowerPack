# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Supervisor PIN at the till: who may authorise, lockout, and the token bound to the rows."""

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.tests.test_pos_list_floor import CASHIER, TILL, ensure_plf_fixtures, make_invoice

ROLE = "_PLF Supervisor"
SUP1 = "_plf_sup1@example.com"
SUP2 = "_plf_sup2@example.com"
NO_PIN = "_plf_sup_nopin@example.com"
PIN1, PIN2 = "1234", "567890"


def ensure_supervisors():
	from cecypo_powerpack.pos_list_floor import PIN_FIELD

	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(ignore_permissions=True)
	for email, pin in ((SUP1, PIN1), (SUP2, PIN2), (NO_PIN, None)):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
				 "roles": [{"role": ROLE}]}
			).insert(ignore_permissions=True)
		if pin:
			user = frappe.get_doc("User", email)
			user.set(PIN_FIELD, pin)
			user.save(ignore_permissions=True)
	frappe.db.commit()


class TestPosSupervisorPin(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_plf_fixtures()
		ensure_supervisors()

	def setUp(self):
		self.saved_role = frappe.db.get_single_value("PowerPack Settings", "min_selling_price_override_role")
		frappe.db.set_single_value("PowerPack Settings", "min_selling_price_override_role", ROLE)
		frappe.clear_cache(doctype="PowerPack Settings")
		for user in (SUP1, SUP2):
			frappe.cache.delete_value(f"powerpack_pin_fail:{user}")
		frappe.set_user(CASHIER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("PowerPack Settings", "min_selling_price_override_role", self.saved_role)
		frappe.clear_cache(doctype="PowerPack Settings")
		super().tearDown()

	def test_supervisor_list_has_only_role_holders_with_pin(self):
		from cecypo_powerpack.pos_supervisor_pin import get_pos_supervisors

		names = [s["name"] for s in get_pos_supervisors()]
		self.assertIn(SUP1, names)
		self.assertIn(SUP2, names)
		self.assertNotIn(NO_PIN, names)
		self.assertNotIn(CASHIER, names)

	def test_right_pin_gives_token_bound_to_rows(self):
		from cecypo_powerpack.pos_supervisor_pin import apply_authorisation, authorise

		doc = make_invoice(420, owner=CASHIER)
		result = authorise(doc, SUP1, PIN1)
		self.assertTrue(result["ok"])
		later = make_invoice(420, owner=CASHIER)
		apply_authorisation(later, result["token"])
		approval = later.flags.powerpack_pos_approval
		self.assertEqual(approval["supervisor"], SUP1)
		self.assertEqual([(r["item_code"], r["base_net_rate"]) for r in approval["rows"]], [("_PLF Item", 420)])

	def test_wrong_pin_counts_and_locks_after_5(self):
		from cecypo_powerpack.pos_supervisor_pin import authorise

		doc = make_invoice(420, owner=CASHIER)
		for _ in range(5):
			self.assertFalse(authorise(doc, SUP1, "0000")["ok"])
		with self.assertRaisesRegex(frappe.ValidationError, "Try again in 15 minutes"):
			authorise(doc, SUP1, PIN1)
		self.assertTrue(authorise(doc, SUP2, PIN2)["ok"])

	def test_right_pin_resets_the_count(self):
		from cecypo_powerpack.pos_supervisor_pin import authorise

		doc = make_invoice(420, owner=CASHIER)
		for _ in range(4):
			authorise(doc, SUP1, "0000")
		self.assertTrue(authorise(doc, SUP1, PIN1)["ok"])
		for _ in range(4):
			authorise(doc, SUP1, "0000")
		self.assertTrue(authorise(doc, SUP1, PIN1)["ok"])

	def test_cashier_without_role_cannot_authorise(self):
		from cecypo_powerpack.pos_list_floor import PIN_FIELD
		from cecypo_powerpack.pos_supervisor_pin import authorise

		frappe.set_user("Administrator")
		cashier = frappe.get_doc("User", CASHIER)
		cashier.set(PIN_FIELD, "4321")
		cashier.save(ignore_permissions=True)
		frappe.set_user(CASHIER)
		self.assertFalse(authorise(make_invoice(420, owner=CASHIER), CASHIER, "4321")["ok"])

	def test_token_from_another_cashier_refused(self):
		from cecypo_powerpack.pos_supervisor_pin import apply_authorisation, authorise

		token = authorise(make_invoice(420, owner=CASHIER), SUP1, PIN1)["token"]
		frappe.set_user(SUP2)
		with self.assertRaisesRegex(frappe.ValidationError, "expired"):
			apply_authorisation(make_invoice(420, owner=SUP2), token)

	def test_unknown_token_refused(self):
		from cecypo_powerpack.pos_supervisor_pin import apply_authorisation

		with self.assertRaisesRegex(frappe.ValidationError, "expired"):
			apply_authorisation(make_invoice(420, owner=CASHIER), "nope")

	def test_attempts_logged_without_the_pin(self):
		from cecypo_powerpack.pos_supervisor_pin import authorise

		authorise(make_invoice(420, owner=CASHIER), SUP1, "9999")
		authorise(make_invoice(420, owner=CASHIER), SUP1, PIN1)
		frappe.set_user("Administrator")
		logs = frappe.get_all(
			"Activity Log",
			{"timeline_doctype": "User", "timeline_name": SUP1},
			["status", "subject", "content", "user"],
			order_by="creation desc",
			limit=2,
		)
		self.assertEqual([log.status for log in logs], ["Success", "Failed"])
		for log in logs:
			self.assertEqual(log.user, CASHIER)
			self.assertIn(TILL, log.subject)
			self.assertNotIn(PIN1, (log.subject or "") + (log.content or ""))
			self.assertNotIn("9999", (log.subject or "") + (log.content or ""))
