# Price Import Tool — Design Spec

**Date:** 2026-05-26  
**Status:** Approved  
**Scope:** cecypo_powerpack

---

## Overview

A bulk price import tool built into PowerPack that lets users upload an Excel or CSV file containing `item_code`, `price_list`, and `rate` columns, review a diff grid before committing, and apply price changes in one click. No PowerPack Setting toggle required. ERPNext role-based permissions are enforced on every write.

---

## Entry Point

Accessible from the **Item Price list view** via the existing **Menu (⋯) dropdown** as "Import Prices (PowerPack)". Implemented via `frappe.listview_settings["Item Price"]` in a new globally-included JS file.

Not gated by any PowerPack Settings toggle — the tool is always available to users with sufficient permissions.

---

## File Format

- Accepts **`.xlsx`** and **`.csv`**
- Required columns (case-insensitive header matching): `item_code`, `price_list`, `rate`
- Extra columns in the file are ignored
- Header row is auto-detected and skipped
- File is sent to the server as a **base64-encoded string** via `frappe.call`

---

## Backend — Two Whitelisted Endpoints (`api.py`)

### `preview_price_import(file_content, file_name)`

1. Checks `frappe.has_permission("Item Price", "read", throw=True)`
2. Decodes base64 → `BytesIO`
3. Parses file:
   - `.xlsx` → `openpyxl` (already in Frappe's environment)
   - `.csv` → Python `csv` module
4. For each row, batch-queries:
   - **Item master** — does `item_code` exist?
   - **Item Price** — does a record exist for `(item_code, price_list)`?
5. Returns a list of enriched row dicts with fields:
   - `item_code`, `price_list`, `rate` (from file)
   - `existing_rate` (null if no existing Item Price)
   - `item_price_name` (the existing Item Price `name`, null if none)
   - `status`: one of `"update"`, `"new"`, `"missing"`
     - `"update"` — item exists, Item Price record exists
     - `"new"` — item exists, no Item Price for this price_list yet
     - `"missing"` — item_code not found in Item master

### `apply_price_import(rows)`

1. Checks `frappe.has_permission("Item Price", "write", throw=True)`
2. Checks `frappe.has_permission("Item Price", "create", throw=True)` if any `"new"` rows present
3. Iterates rows:
   - `"missing"` rows → skipped silently
   - `"update"` rows → `frappe.db.set_value("Item Price", item_price_name, "price_list_rate", rate)`
   - `"new"` rows → `frappe.get_doc({"doctype": "Item Price", "item_code": ..., "price_list": ..., "price_list_rate": ...}).insert(ignore_permissions=False)`
4. Calls `frappe.db.commit()` once after all changes
5. Returns `{"updated": N, "created": M, "skipped": K}`

Rows are passed as a JSON string to work within Frappe's whitelisted method parameter handling.

---

## Frontend (`price_import_powerup.js`)

### List View Hook

```js
frappe.listview_settings["Item Price"] = frappe.listview_settings["Item Price"] || {};
const _orig_onload = frappe.listview_settings["Item Price"].onload;
frappe.listview_settings["Item Price"].onload = function(listview) {
    if (_orig_onload) _orig_onload.call(this, listview);
    listview.page.add_menu_item(__("Import Prices (PowerPack)"), () => open_price_import_dialog());
};
```

### Dialog Structure

A `frappe.ui.Dialog` with `size: "extra-large"` containing:

1. **File field** (`fieldtype: "Attach"` or `<input type="file">`) — accepts `.xlsx,.csv`
2. **HTML field** — renders the review grid after parse; hidden until file is loaded
3. **Primary action** — "Apply N Changes" — disabled until parse completes, re-disabled after apply

### Review Grid

Rendered as an HTML table inside the dialog's HTML field. Structure:

**Summary bar** (above table):
```
[ 48 total ]  [ ✓ 43 updating ]  [ ✦ 3 new prices ]  [ ⚠ 2 not found ]
```

**Table columns:** `item_code` | `price_list` | `existing rate` | `new rate` | `change`

**Row styles by status:**
- `"update"` — standard row; change badge is red/green based on direction, fill intensity scales with `|%|`:
  - `|%| < 5` → light tint background, colored text
  - `5 ≤ |%| < 20` → medium tint
  - `|%| ≥ 20` → solid fill badge with white text
- `"new"` — light blue row background; change cell shows `✦ new price` badge in blue
- `"missing"` — amber row background; item_code in amber bold; change cell shows `⚠ item not found` badge; excluded from apply count

**Change badge format:** `+45.00 (+47.4%)` or `−25.00 (−11.9%)`  
**Zero change:** grey neutral badge `0.00 (0%)`

### Apply Button Label

Shows the count of actionable rows (update + new), not total: `"Apply 46 Changes"`.  
After apply, dialog closes and a success toast appears:  
`"Updated 43 prices, created 3 new. 2 items not found were skipped."`

---

## Files Changed

| File | Change |
|------|--------|
| `cecypo_powerpack/public/js/price_import_powerup.js` | **New** — list view hook, dialog, grid render, apply flow |
| `cecypo_powerpack/api.py` | **Modified** — add `preview_price_import` and `apply_price_import` |
| `cecypo_powerpack/hooks.py` | **Modified** — add `price_import_powerup.js` to `app_include_js` |

No new DocTypes, fixtures, CSS files, or settings fields required.

---

## Permissions Summary

| Action | Permission checked |
|--------|-------------------|
| Parse / preview | `Item Price` — read |
| Apply updates | `Item Price` — write |
| Apply new prices | `Item Price` — create |

All checks use `frappe.has_permission(..., throw=True)` — if the user lacks the role, Frappe returns a permission error automatically.

---

## Edge Cases

- **Duplicate rows in file** (same item_code + price_list appears twice): last row wins (overwrite during apply)
- **rate = 0**: allowed — zero prices are valid in ERPNext
- **Empty file / no data rows**: parse returns empty list; dialog shows "No rows found" message; Apply button stays disabled
- **Malformed file** (wrong columns, unparseable): server returns error message displayed in the dialog; no changes made
- **Large imports (500+ rows)**: no pagination — all rows load in one request; table renders fully (no virtual scroll)
