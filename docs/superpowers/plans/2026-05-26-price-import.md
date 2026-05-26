# Price Import Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Import Prices (PowerPack)" option to the Item Price list's Menu dropdown that lets users upload an xlsx/csv file, review a color-coded diff grid, and apply bulk price updates/creates in one click.

**Architecture:** Two new whitelisted Python endpoints handle parse+enrich and apply separately. A new globally-included JS file adds the list view hook and renders the dialog with review grid. No new DocTypes or settings fields.

**Tech Stack:** Python (openpyxl, csv, base64, io), Frappe whitelist API, frappe.ui.Dialog, FileReader API, HTML table grid.

---

> **⚠ Test runner warning:** The bench-wide test runner is known to crash on ERPNext's BootStrapTestData (Price List duplicate). Always run tests for this module only:
> ```bash
> cd /home/frappeuser/bench16
> bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.cecypo_powerpack.tests.test_price_import_api
> ```
> Never use `bench run-tests --app cecypo_powerpack` without `--module`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `cecypo_powerpack/cecypo_powerpack/tests/test_price_import_api.py` | **Create** | Unit tests for both Python endpoints |
| `cecypo_powerpack/cecypo_powerpack/api.py` | **Modify** (append) | `preview_price_import` + `apply_price_import` |
| `cecypo_powerpack/public/js/price_import_powerup.js` | **Create** | List view hook, dialog, file read, grid render, apply flow |
| `cecypo_powerpack/cecypo_powerpack/hooks.py` | **Modify** | Add `price_import_powerup.js` to `app_include_js` |

---

## Task 1: Test scaffold + preview_price_import (CSV path)

**Files:**
- Create: `cecypo_powerpack/cecypo_powerpack/tests/test_price_import_api.py`
- Modify: `cecypo_powerpack/cecypo_powerpack/api.py` (append to end)

- [ ] **Step 1.1: Create the test file**

```python
# cecypo_powerpack/cecypo_powerpack/tests/test_price_import_api.py
# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import base64
import csv
import io
import json

import frappe
from frappe.tests.utils import FrappeTestCase


TEST_ITEM_EXISTS = "_Test PIP Item Exists"
TEST_ITEM_NO_PRICE = "_Test PIP Item No Price"
TEST_PRICE_LIST = "Standard Selling"


def _make_csv_b64(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["item_code", "price_list", "rate"])
    writer.writeheader()
    writer.writerows(rows)
    return base64.b64encode(buf.getvalue().encode()).decode()


class TestPreviewPriceImport(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from erpnext.stock.doctype.item.test_item import make_item

        cls.item_exists = make_item(TEST_ITEM_EXISTS, {"is_stock_item": 0}).name
        cls.item_no_price = make_item(TEST_ITEM_NO_PRICE, {"is_stock_item": 0}).name

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


class TestApplyPriceImport(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from erpnext.stock.doctype.item.test_item import make_item

        cls.item_exists = make_item(TEST_ITEM_EXISTS, {"is_stock_item": 0}).name
        cls.item_no_price = make_item(TEST_ITEM_NO_PRICE, {"is_stock_item": 0}).name

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
```

- [ ] **Step 1.2: Run test — confirm it fails with ImportError**

```bash
cd /home/frappeuser/bench16
bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.cecypo_powerpack.tests.test_price_import_api
```

Expected: `ImportError: cannot import name 'preview_price_import' from 'cecypo_powerpack.api'`

- [ ] **Step 1.3: Append preview_price_import to api.py (CSV path only)**

Append to end of `cecypo_powerpack/cecypo_powerpack/api.py`:

```python
# ═══════════════════════════════════════════════════════════════════════════════
# PRICE IMPORT
# ═══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def preview_price_import(file_content: str, file_name: str) -> list:
    frappe.has_permission("Item Price", "read", throw=True)

    import base64
    import csv
    import io

    raw = base64.b64decode(file_content)
    rows = _parse_price_file(raw, file_name)

    if not rows:
        return []

    all_item_codes = list({r["item_code"] for r in rows})

    existing_items = set(
        frappe.db.get_all("Item", filters=[["name", "in", all_item_codes]], pluck="name")
    )

    ip_rows = frappe.db.get_all(
        "Item Price",
        filters=[["item_code", "in", all_item_codes]],
        fields=["name", "item_code", "price_list", "price_list_rate"],
    )
    item_price_map = {}
    for ip in ip_rows:
        key = (ip["item_code"], ip["price_list"])
        if key not in item_price_map:
            item_price_map[key] = ip

    enriched = []
    for row in rows:
        item_code = row["item_code"]
        price_list = row["price_list"]
        rate = row["rate"]

        if item_code not in existing_items:
            enriched.append({
                "item_code": item_code,
                "price_list": price_list,
                "rate": rate,
                "existing_rate": None,
                "item_price_name": None,
                "status": "missing",
            })
            continue

        ip = item_price_map.get((item_code, price_list))
        if ip:
            enriched.append({
                "item_code": item_code,
                "price_list": price_list,
                "rate": rate,
                "existing_rate": ip["price_list_rate"],
                "item_price_name": ip["name"],
                "status": "update",
            })
        else:
            enriched.append({
                "item_code": item_code,
                "price_list": price_list,
                "rate": rate,
                "existing_rate": None,
                "item_price_name": None,
                "status": "new",
            })

    return enriched


def _parse_price_file(raw: bytes, file_name: str) -> list:
    import csv
    import io

    name_lower = (file_name or "").lower()
    if name_lower.endswith(".xlsx"):
        return _parse_xlsx(raw)
    if name_lower.endswith(".csv"):
        return _parse_csv(raw)
    frappe.throw(_("Unsupported file type. Please upload a .xlsx or .csv file."))


def _parse_csv(raw: bytes) -> list:
    import csv
    import io

    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    # Normalize headers to lowercase stripped
    rows = []
    for raw_row in reader:
        row = {k.strip().lower(): v for k, v in raw_row.items() if k}
        rows.append(row)
    return _extract_validated_rows(rows)


def _parse_xlsx(raw: bytes) -> list:
    import io
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    headers = None
    rows = []
    for sheet_row in ws.iter_rows(values_only=True):
        if headers is None:
            headers = [str(c).strip().lower() if c is not None else "" for c in sheet_row]
            continue
        if not any(c is not None for c in sheet_row):
            continue
        rows.append(dict(zip(headers, sheet_row)))
    wb.close()
    return _extract_validated_rows(rows)


def _extract_validated_rows(rows: list) -> list:
    result = []
    for row in rows:
        item_code = str(row.get("item_code") or "").strip()
        price_list = str(row.get("price_list") or "").strip()
        rate_raw = row.get("rate")

        if not item_code or not price_list or rate_raw is None or str(rate_raw).strip() == "":
            continue
        try:
            rate = float(str(rate_raw).replace(",", ""))
        except (ValueError, TypeError):
            continue

        result.append({"item_code": item_code, "price_list": price_list, "rate": rate})
    return result
```

- [ ] **Step 1.4: Run CSV tests — confirm they pass**

```bash
cd /home/frappeuser/bench16
bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.cecypo_powerpack.tests.test_price_import_api
```

Expected: `TestPreviewPriceImport` tests pass. `TestApplyPriceImport` still fails with `ImportError`.

- [ ] **Step 1.5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/tests/test_price_import_api.py cecypo_powerpack/api.py
git commit -m "feat(price-import): add preview_price_import endpoint with CSV/xlsx parse"
```

---

## Task 2: apply_price_import endpoint

**Files:**
- Modify: `cecypo_powerpack/cecypo_powerpack/api.py` (append after preview_price_import)

- [ ] **Step 2.1: Append apply_price_import to api.py**

Append directly after the last line of the block added in Task 1:

```python
@frappe.whitelist()
def apply_price_import(rows: str) -> dict:
    frappe.has_permission("Item Price", "write", throw=True)

    rows = frappe.parse_json(rows)

    has_new = any(r.get("status") == "new" for r in rows)
    if has_new:
        frappe.has_permission("Item Price", "create", throw=True)

    updated = 0
    created = 0
    skipped = 0

    for row in rows:
        status = row.get("status")
        if status == "missing":
            skipped += 1
            continue

        item_code = row.get("item_code")
        price_list = row.get("price_list")
        rate = frappe.utils.flt(row.get("rate", 0))

        if status == "update":
            ip_name = row.get("item_price_name")
            if ip_name:
                frappe.db.set_value("Item Price", ip_name, "price_list_rate", rate)
                updated += 1

        elif status == "new":
            frappe.get_doc({
                "doctype": "Item Price",
                "item_code": item_code,
                "price_list": price_list,
                "price_list_rate": rate,
            }).insert()
            created += 1

    frappe.db.commit()
    return {"updated": updated, "created": created, "skipped": skipped}
```

- [ ] **Step 2.2: Run all tests — confirm all pass**

```bash
cd /home/frappeuser/bench16
bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.cecypo_powerpack.tests.test_price_import_api
```

Expected: All tests in both `TestPreviewPriceImport` and `TestApplyPriceImport` pass.

- [ ] **Step 2.3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/api.py
git commit -m "feat(price-import): add apply_price_import endpoint"
```

---

## Task 3: hooks.py — register new JS file

**Files:**
- Modify: `cecypo_powerpack/cecypo_powerpack/hooks.py`

- [ ] **Step 3.1: Add price_import_powerup.js to app_include_js**

In `hooks.py`, the `app_include_js` list currently ends with `lens_powerup.js`. Add the new file after it:

```python
app_include_js = [
    "/assets/cecypo_powerpack/js/cecypo_powerpack.js",
    "/assets/cecypo_powerpack/js/point_of_sale_powerpack.js",
    "/assets/cecypo_powerpack/js/profit_calculator.js",
    "/assets/cecypo_powerpack/js/sales_powerup.js",
    "/assets/cecypo_powerpack/js/bulk_selection.js",
    "/assets/cecypo_powerpack/js/payment_reconciliation_powerup.js",
    "/assets/cecypo_powerpack/js/lens_powerup.js",
    "/assets/cecypo_powerpack/js/price_import_powerup.js",
]
```

- [ ] **Step 3.2: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/hooks.py
git commit -m "feat(price-import): register price_import_powerup.js in hooks"
```

---

## Task 4: Frontend — list view hook + dialog skeleton

**Files:**
- Create: `cecypo_powerpack/public/js/price_import_powerup.js`

- [ ] **Step 4.1: Create the JS file with list view hook and dialog skeleton**

Create `cecypo_powerpack/public/js/price_import_powerup.js`:

```js
(function () {

// ─── List view hook ───────────────────────────────────────────────────────────

frappe.listview_settings["Item Price"] = frappe.listview_settings["Item Price"] || {};
const _orig_onload = frappe.listview_settings["Item Price"].onload;
frappe.listview_settings["Item Price"].onload = function (listview) {
    if (_orig_onload) _orig_onload.call(this, listview);
    listview.page.add_menu_item(__("Import Prices (PowerPack)"), open_price_import_dialog);
};

// ─── State ────────────────────────────────────────────────────────────────────

function make_state() {
    return { rows: [] };
}

// ─── Dialog ───────────────────────────────────────────────────────────────────

function open_price_import_dialog() {
    const state = make_state();

    const dialog = new frappe.ui.Dialog({
        title: __("Import Prices"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "upload_area",
                options: `
                    <div class="pip-upload-area" style="
                        border:2px dashed #d1d5db;border-radius:6px;padding:28px 16px;
                        text-align:center;cursor:pointer;color:#9ca3af;
                        transition:border-color .15s;
                    ">
                        <div style="font-size:28px;margin-bottom:8px;">📄</div>
                        <div style="font-weight:600;color:#374151;margin-bottom:4px;">
                            ${__("Drop .xlsx or .csv here, or click to browse")}
                        </div>
                        <div style="font-size:11px;">
                            ${__("Required columns: item_code, price_list, rate")}
                        </div>
                        <input type="file" accept=".xlsx,.csv" class="pip-file-input" style="display:none;">
                    </div>`,
            },
            { fieldname: "review", fieldtype: "HTML", options: "" },
        ],
        primary_action_label: __("Apply Changes"),
        primary_action() { apply_changes(dialog, state); },
    });

    dialog.get_primary_btn().prop("disabled", true);
    wire_upload(dialog, state);
    dialog.show();
}

// ─── File upload wiring ───────────────────────────────────────────────────────

function wire_upload(dialog, state) {
    dialog.$wrapper.on("click", ".pip-upload-area", function (e) {
        if ($(e.target).is("input")) return;
        dialog.$wrapper.find(".pip-file-input").click();
    });

    dialog.$wrapper.on("change", ".pip-file-input", function (e) {
        const file = e.target.files[0];
        if (file) read_and_preview(file, dialog, state);
    });

    dialog.$wrapper.on("dragover", ".pip-upload-area", function (e) {
        e.preventDefault();
        $(this).css("border-color", "#405BFF");
    });

    dialog.$wrapper.on("dragleave drop", ".pip-upload-area", function (e) {
        e.preventDefault();
        $(this).css("border-color", "#d1d5db");
        if (e.type === "drop") {
            const file = e.originalEvent.dataTransfer.files[0];
            if (file) read_and_preview(file, dialog, state);
        }
    });
}

// ─── File read + server call ──────────────────────────────────────────────────

function read_and_preview(file, dialog, state) {
    const $review = dialog.fields_dict.review.$wrapper;
    $review.html(`<div style="text-align:center;padding:20px;color:var(--text-muted);">${__("Parsing file…")}</div>`);
    dialog.get_primary_btn().prop("disabled", true);

    const reader = new FileReader();
    reader.onload = function (e) {
        const base64 = e.target.result.split(",")[1];
        frappe.call({
            method: "cecypo_powerpack.api.preview_price_import",
            args: { file_content: base64, file_name: file.name },
            freeze: true,
            freeze_message: __("Reading prices…"),
            callback(r) {
                if (r.exc) {
                    $review.html(`<p style="color:#dc2626;padding:12px;">${__("Error reading file. Check format and required columns.")}</p>`);
                    return;
                }
                state.rows = r.message || [];
                render_review(dialog, state);
            },
        });
    };
    reader.readAsDataURL(file);
}

// ─── Review grid ──────────────────────────────────────────────────────────────

function change_badge(row) {
    if (row.status === "missing") {
        return `<span style="background:#fef3c7;color:#92400e;border-radius:3px;padding:2px 7px;font-size:11px;">&#9888; ${__("item not found")}</span>`;
    }
    if (row.status === "new") {
        return `<span style="background:#e0f2fe;color:#0369a1;border-radius:3px;padding:2px 7px;font-size:11px;">&#10022; ${__("new price")}</span>`;
    }
    const existing = parseFloat(row.existing_rate) || 0;
    const diff = flt(row.rate - existing, 2);
    const pct = existing ? flt(((row.rate - existing) / existing) * 100, 1) : 0;

    if (diff === 0) {
        return `<span style="background:#f3f4f6;color:#9ca3af;border-radius:3px;padding:2px 7px;font-size:11px;">0.00 (0%)</span>`;
    }

    const is_up = diff > 0;
    const sign = is_up ? "+" : "−";
    const abs_diff = Math.abs(diff).toFixed(2);
    const abs_pct = Math.abs(pct).toFixed(1);
    const label = `${sign}${abs_diff} (${sign}${abs_pct}%)`;
    const magnitude = Math.abs(pct);

    let bg, color, fw = "600";
    if (magnitude < 5) {
        bg = is_up ? "#fef2f2" : "#f0fdf4";
        color = is_up ? "#dc2626" : "#16a34a";
    } else if (magnitude < 20) {
        bg = is_up ? "#fecaca" : "#bbf7d0";
        color = is_up ? "#b91c1c" : "#15803d";
        fw = "700";
    } else {
        bg = is_up ? "#dc2626" : "#16a34a";
        color = "#fff";
        fw = "700";
    }
    return `<span style="background:${bg};color:${color};font-weight:${fw};border-radius:3px;padding:2px 7px;font-size:11px;">${label}</span>`;
}

function row_bg(status) {
    if (status === "missing") return "background:#fffbeb;";
    if (status === "new") return "background:#f0f9ff;";
    return "";
}

function render_review(dialog, state) {
    const rows = state.rows;
    const $review = dialog.fields_dict.review.$wrapper;

    if (!rows.length) {
        $review.html(`<p style="text-align:center;color:var(--text-muted);padding:16px;">${__("No rows found in file. Check that columns item_code, price_list, and rate are present.")}</p>`);
        dialog.get_primary_btn().prop("disabled", true);
        return;
    }

    const n_update  = rows.filter(r => r.status === "update").length;
    const n_new     = rows.filter(r => r.status === "new").length;
    const n_missing = rows.filter(r => r.status === "missing").length;
    const n_action  = n_update + n_new;

    const summary = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;padding:10px 0 12px;">
            <span style="background:#f3f4f6;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#374151;">${rows.length} ${__("total")}</span>
            ${n_update  ? `<span style="background:#f0fdf4;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#166534;">&#10003; ${n_update} ${__("updating")}</span>` : ""}
            ${n_new     ? `<span style="background:#e0f2fe;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#0369a1;">&#10022; ${n_new} ${__("new prices")}</span>` : ""}
            ${n_missing ? `<span style="background:#fffbeb;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#92400e;">&#9888; ${n_missing} ${__("not found")}</span>` : ""}
        </div>`;

    const tbody = rows.map(row => `
        <tr style="${row_bg(row.status)}">
            <td style="padding:5px 10px;font-family:monospace;font-size:11px;">${frappe.utils.escape_html(row.item_code)}</td>
            <td style="padding:5px 10px;font-size:11px;color:#6b7280;">${frappe.utils.escape_html(row.price_list)}</td>
            <td style="padding:5px 10px;text-align:right;font-size:11px;">
                ${row.existing_rate != null ? format_currency(row.existing_rate) : '<span style="color:#9ca3af;">—</span>'}
            </td>
            <td style="padding:5px 10px;text-align:right;font-size:11px;font-weight:600;">${format_currency(row.rate)}</td>
            <td style="padding:5px 10px;text-align:right;">${change_badge(row)}</td>
        </tr>`).join("");

    $review.html(`
        ${summary}
        <div style="max-height:420px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:4px;">
            <table style="width:100%;border-collapse:collapse;">
                <thead style="position:sticky;top:0;background:#f3f4f6;z-index:1;">
                    <tr>
                        <th style="padding:6px 10px;text-align:left;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("item_code")}</th>
                        <th style="padding:6px 10px;text-align:left;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("price_list")}</th>
                        <th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("existing rate")}</th>
                        <th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("new rate")}</th>
                        <th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("change")}</th>
                    </tr>
                </thead>
                <tbody>${tbody}</tbody>
            </table>
        </div>`);

    dialog.set_primary_action(__("Apply {0} Changes", [n_action]), function () {
        apply_changes(dialog, state);
    });
    dialog.get_primary_btn().prop("disabled", n_action === 0);
}

// ─── Apply ────────────────────────────────────────────────────────────────────

function apply_changes(dialog, state) {
    const n_action = state.rows.filter(r => r.status !== "missing").length;
    if (!n_action) return;

    frappe.call({
        method: "cecypo_powerpack.api.apply_price_import",
        args: { rows: JSON.stringify(state.rows) },
        freeze: true,
        freeze_message: __("Applying price changes…"),
        callback(r) {
            if (r.exc) return;
            const { updated, created, skipped } = r.message;
            dialog.hide();
            const parts = [];
            if (updated) parts.push(__("{0} prices updated", [updated]));
            if (created) parts.push(__("{0} new prices created", [created]));
            if (skipped) parts.push(__("{0} items not found skipped", [skipped]));
            frappe.show_alert({ message: parts.join(", ") + ".", indicator: "green" });
        },
    });
}

})();
```

- [ ] **Step 4.2: Build assets**

```bash
cd /home/frappeuser/bench16
bench build --app cecypo_powerpack
```

Expected: Build completes without errors. Output includes `price_import_powerup.js`.

- [ ] **Step 4.3: Restart bench**

```bash
cd /home/frappeuser/bench16
bench restart
```

- [ ] **Step 4.4: Smoke test in browser**

1. Open `http://site16.local:8002/app/item-price`
2. Click the **⋯ Menu** button (top right of list)
3. Confirm **"Import Prices (PowerPack)"** appears in the dropdown
4. Click it — dialog should open with the upload area
5. Confirm the upload area shows the dashed border and instruction text

- [ ] **Step 4.5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/public/js/price_import_powerup.js
git commit -m "feat(price-import): add list view hook, dialog, file upload, review grid, and apply flow"
```

---

## Task 5: Manual end-to-end verification

- [ ] **Step 5.1: Create a test CSV**

Create a file `test_prices.csv` with content:

```
item_code,price_list,rate
<real-item-from-your-system>,Standard Selling,999.00
<another-real-item>,Standard Selling,1500.00
DOES-NOT-EXIST-XYZ,Standard Selling,50.00
```

Replace the placeholders with two real item codes from your ERPNext instance.

- [ ] **Step 5.2: Test the full flow**

1. Navigate to `http://site16.local:8002/app/item-price`
2. Menu → Import Prices (PowerPack)
3. Upload `test_prices.csv`
4. Confirm the review grid shows:
   - Real items → update rows with existing rate and color-coded change badge
   - `DOES-NOT-EXIST-XYZ` → amber highlighted row with "item not found" badge
   - Summary bar shows correct counts
5. Click "Apply N Changes"
6. Confirm success toast appears
7. Reload the Item Price list and verify the updated rates are correct

- [ ] **Step 5.3: Test xlsx upload**

Save the same data as an `.xlsx` file and repeat the upload — confirm it parses identically.

- [ ] **Step 5.4: Test empty file**

Upload a CSV with only the header row (no data). Confirm the dialog shows "No rows found" and the Apply button stays disabled.

- [ ] **Step 5.5: Test new price creation**

Add a row to the CSV for a real item that has no price in Standard Selling. Confirm it appears as a blue "new price" row and after Apply, a new Item Price record exists.
