# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""PowerPack must not require the M-Pesa app to be installed.

PowerPack names Mpesa Settings, Mpesa C2B Payment Register and Mpesa Express
Request as strings rather than importing them, so on a site without
``frappe_mpsa_payments`` nothing would stop a query reaching a table that does
not exist. These tests pin the guards that keep that from happening.

Each test that expects a guard to fire stubs the database call it protects with
a raiser, so a passing test proves the query was never reached - not merely
that the return value happened to look right.
"""

import unittest
from unittest.mock import patch

import frappe

from cecypo_powerpack.pay_by_link import (
    _settled_by_a_previous_request,
    document_status,
    payable_gateways,
)
from cecypo_powerpack.quick_pay.api import _mpesa_shortcode_for_company
from cecypo_powerpack.utils import MPESA_APP, mpesa_app_installed

OTHER_APPS = ["frappe", "erpnext", "cecypo_powerpack"]
WITH_MPESA = [*OTHER_APPS, MPESA_APP]


def _boom(*args, **kwargs):
    raise AssertionError("the M-Pesa doctype was queried on a site without the app")


def _without_mpesa():
    return patch("frappe.get_installed_apps", return_value=OTHER_APPS)


def _with_mpesa():
    return patch("frappe.get_installed_apps", return_value=WITH_MPESA)


class TestMpesaAppInstalled(unittest.TestCase):
    def test_reports_installed_when_present(self):
        with _with_mpesa():
            self.assertTrue(mpesa_app_installed())

    def test_reports_absent_when_missing(self):
        with _without_mpesa():
            self.assertFalse(mpesa_app_installed())

    def test_this_site_actually_has_it(self):
        """Guards against the helper silently reporting False everywhere."""
        self.assertTrue(mpesa_app_installed())


class TestPayByLinkWithoutMpesa(unittest.TestCase):
    def test_settled_lookup_short_circuits(self):
        with _without_mpesa(), patch("frappe.db.exists", _boom):
            self.assertFalse(_settled_by_a_previous_request("Quotation", "Q-1"))

    def test_no_gateways_are_offered(self):
        with _without_mpesa(), patch("frappe.get_all", _boom):
            self.assertEqual(payable_gateways("Some Co"), [])

    def test_a_quotation_page_still_renders_its_status(self):
        """The crash this guard exists to prevent: document_status on a
        Quotation consults the Express Request table."""
        row = frappe._dict({"status": "Open", "docstatus": 1})
        with _without_mpesa(), patch("frappe.db.get_value", return_value=row), patch(
            "frappe.db.exists", _boom
        ):
            self.assertEqual(document_status("Quotation", "Q-1"), {"label": "Open", "tone": "open"})

    def test_the_settled_lookup_is_used_when_the_app_is_there(self):
        """The guard must not disable the feature on a site that has the app."""
        with _with_mpesa(), patch("frappe.db.exists", return_value="MEXP-1") as exists:
            self.assertTrue(_settled_by_a_previous_request("Quotation", "Q-1"))
        exists.assert_called_once()


class TestQuickPayWithoutMpesa(unittest.TestCase):
    def test_no_shortcode_resolves(self):
        with _without_mpesa(), patch("frappe.get_all", _boom):
            self.assertIsNone(_mpesa_shortcode_for_company("Some Co"))

    def test_the_settings_lookup_runs_when_the_app_is_there(self):
        rows = [{"business_shortcode": "898102"}]
        with _with_mpesa(), patch("frappe.get_all", return_value=rows) as get_all:
            self.assertEqual(_mpesa_shortcode_for_company("Some Co"), "898102")
        get_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()
