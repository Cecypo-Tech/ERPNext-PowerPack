# cecypo_powerpack/cecypo_powerpack/tests/test_price_import_api.py
# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import base64
import csv
import io
import json

import frappe
from frappe.tests import IntegrationTestCase


TEST_ITEM_EXISTS = "_Test PIP Item Exists"
TEST_ITEM_NO_PRICE = "_Test PIP Item No Price"
TEST_PRICE_LIST = "Standard Selling"


def _make_csv_b64(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["item_code", "price_list", "rate"])
    writer.writeheader()
    writer.writerows(rows)
    return base64.b64encode(buf.getvalue().encode()).decode()


def _make_item(item_code, properties=None):
    """Create a minimal Item doc without triggering ERPNext bootstrap."""
    if frappe.db.exists("Item", item_code):
        return frappe.get_doc("Item", item_code)
    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": item_code,
        "item_name": item_code,
        "item_group": "All Item Groups",
        "stock_uom": "Nos",
        "is_stock_item": 0,
        **(properties or {}),
    })
    doc.insert(ignore_permissions=True)
    return doc


class TestPreviewPriceImport(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.item_exists = _make_item(TEST_ITEM_EXISTS, {"is_stock_item": 0}).name
        cls.item_no_price = _make_item(TEST_ITEM_NO_PRICE, {"is_stock_item": 0}).name

        if not frappe.db.exists(
            "Item Price",
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST},
        ):
            frappe.get_doc({
                "doctype": "Item Price",
                "item_code": TEST_ITEM_EXISTS,
                "price_list": TEST_PRICE_LIST,
                "price_list_rate": 100.0,
            }).insert(ignore_permissions=True)
        frappe.db.commit()  # persist class-level fixtures before per-test rollbacks

    def tearDown(self):
        frappe.db.rollback()

    def test_existing_item_with_price_returns_update_status(self):
        from cecypo_powerpack.api import preview_price_import

        content = _make_csv_b64([
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST, "rate": 120.0}
        ])
        result = preview_price_import(content, "test.csv")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "update")
        self.assertEqual(float(result[0]["existing_rate"]), 100.0)
        self.assertIsNotNone(result[0]["item_price_name"])

    def test_missing_item_returns_missing_status(self):
        from cecypo_powerpack.api import preview_price_import

        content = _make_csv_b64([
            {"item_code": "DOES-NOT-EXIST-XYZ-PIP", "price_list": TEST_PRICE_LIST, "rate": 50.0}
        ])
        result = preview_price_import(content, "test.csv")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "missing")
        self.assertIsNone(result[0]["existing_rate"])

    def test_item_with_no_price_for_list_returns_new_status(self):
        from cecypo_powerpack.api import preview_price_import

        content = _make_csv_b64([
            {"item_code": TEST_ITEM_NO_PRICE, "price_list": TEST_PRICE_LIST, "rate": 80.0}
        ])
        result = preview_price_import(content, "test.csv")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "new")
        self.assertIsNone(result[0]["existing_rate"])
        self.assertIsNone(result[0]["item_price_name"])

    def test_mixed_rows_all_returned(self):
        from cecypo_powerpack.api import preview_price_import

        content = _make_csv_b64([
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST, "rate": 120.0},
            {"item_code": TEST_ITEM_NO_PRICE, "price_list": TEST_PRICE_LIST, "rate": 80.0},
            {"item_code": "GHOST-ITEM-PIP", "price_list": TEST_PRICE_LIST, "rate": 50.0},
        ])
        result = preview_price_import(content, "test.csv")

        statuses = {r["item_code"]: r["status"] for r in result}
        self.assertEqual(statuses[TEST_ITEM_EXISTS], "update")
        self.assertEqual(statuses[TEST_ITEM_NO_PRICE], "new")
        self.assertEqual(statuses["GHOST-ITEM-PIP"], "missing")

    def test_empty_file_returns_empty_list(self):
        from cecypo_powerpack.api import preview_price_import

        content = _make_csv_b64([])
        result = preview_price_import(content, "test.csv")
        self.assertEqual(result, [])

    def test_case_insensitive_headers(self):
        from cecypo_powerpack.api import preview_price_import

        buf = io.StringIO()
        buf.write("Item_Code,Price_List,Rate\n")
        buf.write(f"{TEST_ITEM_EXISTS},{TEST_PRICE_LIST},120.0\n")
        content = base64.b64encode(buf.getvalue().encode()).decode()
        result = preview_price_import(content, "test.csv")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["item_code"], TEST_ITEM_EXISTS)


class TestApplyPriceImport(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.item_exists = _make_item(TEST_ITEM_EXISTS, {"is_stock_item": 0}).name
        cls.item_no_price = _make_item(TEST_ITEM_NO_PRICE, {"is_stock_item": 0}).name

        if not frappe.db.exists(
            "Item Price",
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST},
        ):
            frappe.get_doc({
                "doctype": "Item Price",
                "item_code": TEST_ITEM_EXISTS,
                "price_list": TEST_PRICE_LIST,
                "price_list_rate": 100.0,
            }).insert(ignore_permissions=True)
        frappe.db.commit()  # persist class-level fixtures before per-test rollbacks

    def tearDown(self):
        frappe.db.rollback()

    def _get_ip_name(self):
        return frappe.db.get_value(
            "Item Price",
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST},
            "name",
        )

    def test_apply_updates_existing_price(self):
        from cecypo_powerpack.api import apply_price_import

        ip_name = self._get_ip_name()
        rows = [{"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST,
                 "rate": 150.0, "status": "update", "item_price_name": ip_name}]
        result = apply_price_import(json.dumps(rows))

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 0)
        new_rate = frappe.db.get_value("Item Price", ip_name, "price_list_rate")
        self.assertEqual(float(new_rate), 150.0)

    def test_apply_skips_missing_rows(self):
        from cecypo_powerpack.api import apply_price_import

        rows = [{"item_code": "GHOST-PIP", "price_list": TEST_PRICE_LIST,
                 "rate": 50.0, "status": "missing", "item_price_name": None}]
        result = apply_price_import(json.dumps(rows))

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["created"], 0)

    def test_apply_creates_new_price(self):
        from cecypo_powerpack.api import apply_price_import

        rows = [{"item_code": TEST_ITEM_NO_PRICE, "price_list": TEST_PRICE_LIST,
                 "rate": 200.0, "status": "new", "item_price_name": None}]
        result = apply_price_import(json.dumps(rows))

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        new_rate = frappe.db.get_value(
            "Item Price",
            {"item_code": TEST_ITEM_NO_PRICE, "price_list": TEST_PRICE_LIST},
            "price_list_rate",
        )
        self.assertEqual(float(new_rate), 200.0)

    def test_apply_mixed_rows_counts_correctly(self):
        from cecypo_powerpack.api import apply_price_import

        ip_name = self._get_ip_name()
        rows = [
            {"item_code": TEST_ITEM_EXISTS, "price_list": TEST_PRICE_LIST,
             "rate": 110.0, "status": "update", "item_price_name": ip_name},
            {"item_code": TEST_ITEM_NO_PRICE, "price_list": TEST_PRICE_LIST,
             "rate": 55.0, "status": "new", "item_price_name": None},
            {"item_code": "GHOST-PIP", "price_list": TEST_PRICE_LIST,
             "rate": 30.0, "status": "missing", "item_price_name": None},
        ]
        result = apply_price_import(json.dumps(rows))

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 1)
