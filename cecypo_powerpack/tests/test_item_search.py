# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

"""Regression tests for the enhanced item search powerup.

Covers:
  * custom_item_query — multi-word AND matching, `%` wildcards, empty search,
    the feature gate, and the SQL identifier hardening (a searchfield that is
    not a real Item column must be filtered out, never interpolated into SQL).
  * custom_search_link — its signature must stay identical to the upstream
    frappe.desk.search.search_link it overrides.
"""

import inspect

import frappe
from frappe.tests import UnitTestCase

# Distinctive marker so searches don't collide with the (large) real Item table.
MARKER = "zzqppmarker"


class TestCustomItemQuery(UnitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from erpnext.stock.doctype.item.test_item import make_item

		# Deterministic item_codes so reruns reuse the same fixtures (make_item
		# returns the existing doc) instead of accumulating rows. is_stock_item=0
		# keeps them free of warehouse/integration test dependencies.
		cls.grey = make_item("_Test PP RidgeGrey", {"item_name": f"{MARKER} ridge grey", "is_stock_item": 0}).name
		cls.blue = make_item("_Test PP RidgeBlue", {"item_name": f"{MARKER} ridge blue", "is_stock_item": 0}).name
		cls.plain = make_item("_Test PP PlainWhite", {"item_name": f"{MARKER} plain white", "is_stock_item": 0}).name
		cls.created = {cls.grey, cls.blue, cls.plain}
		frappe.db.commit()

	def setUp(self):
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_item_search_powerup = 1
		settings.save()

	def tearDown(self):
		frappe.db.rollback()

	def _names(self, txt, searchfield="name", page_len=50):
		from cecypo_powerpack.api import custom_item_query

		rows = custom_item_query("Item", txt, searchfield, 0, page_len, {}, as_dict=True)
		return {r["name"] for r in rows}

	# ── Core behaviour ────────────────────────────────────────────────────
	def test_single_token_matches_all(self):
		names = self._names(MARKER)
		self.assertTrue(self.created <= names, f"expected all created items, got {names & self.created}")

	def test_multiword_is_and_matching(self):
		# Both tokens must be present → "ridge" excludes the plain-white item.
		names = self._names(f"{MARKER} ridge")
		self.assertIn(self.grey, names)
		self.assertIn(self.blue, names)
		self.assertNotIn(self.plain, names)

	def test_multiword_narrows_to_one(self):
		names = self._names(f"{MARKER} grey")
		self.assertIn(self.grey, names)
		self.assertNotIn(self.blue, names)
		self.assertNotIn(self.plain, names)

	def test_wildcard_token(self):
		# `%` present → treated as a single substring wildcard: marker…grey.
		names = self._names(f"{MARKER}%grey")
		self.assertIn(self.grey, names)
		self.assertNotIn(self.blue, names)

	def test_empty_search_returns_rows(self):
		from cecypo_powerpack.api import custom_item_query

		rows = custom_item_query("Item", "", "name", 0, 5, {}, as_dict=True)
		self.assertIsInstance(rows, list)

	# ── Feature gate ──────────────────────────────────────────────────────
	def test_disabled_falls_back_to_erpnext(self):
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_item_search_powerup = 0
		settings.save()

		from cecypo_powerpack.api import custom_item_query

		# Falls through to erpnext.controllers.queries.item_query without error.
		rows = custom_item_query("Item", MARKER, "name", 0, 5, {}, as_dict=True)
		self.assertIsInstance(rows, list)

	# ── SQL identifier hardening (frappe-sql-format-injection fix) ─────────
	def test_unknown_searchfield_is_filtered_not_injected(self):
		"""A searchfield that isn't a real Item column must be dropped, not
		interpolated into the SQL — otherwise it errors (or, with a crafted
		value, injects). The query should still run over the valid columns."""
		names = self._names(f"{MARKER} ridge", searchfield="totally_not_a_column_xyz")
		# Still matches via the hardcoded valid columns (item_name/item_code/…).
		self.assertIn(self.grey, names)
		self.assertIn(self.blue, names)
		self.assertNotIn(self.plain, names)


class TestCustomSearchLinkSignature(UnitTestCase):
	def test_signature_matches_upstream(self):
		"""Marketplace requirement: an overridden whitelisted method must keep the
		same signature as the original it replaces."""
		from frappe.desk.search import search_link

		from cecypo_powerpack.api import custom_search_link

		ours = inspect.signature(custom_search_link).parameters
		theirs = inspect.signature(search_link).parameters

		self.assertEqual(list(ours), list(theirs), "parameter names/order differ from upstream")
		for name, theirp in theirs.items():
			self.assertEqual(ours[name].kind, theirp.kind, f"kind of {name!r} differs from upstream")
			self.assertEqual(ours[name].default, theirp.default, f"default of {name!r} differs from upstream")
