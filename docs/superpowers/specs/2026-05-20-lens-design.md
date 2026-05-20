# Lens Feature — Design Spec

**Date:** 2026-05-20
**App:** cecypo_powerpack
**Frappe/ERPNext:** v16
**Status:** Approved

---

## Overview

Lens adds a per-item insights dialog to sales and purchase documents. A small magnifying glass icon appears at the end of each item row; clicking it opens a dialog showing sales/purchase history for that item, rates billed to other parties, and all enabled price lists with live margin calculation and optional price editing.

The feature is independent of Sales Powerup and works on all six target doctypes.

---

## Feature Toggle

A single `enable_lens` checkbox is added to **PowerPack Settings** under a new **"Lens"** section. No sub-settings required. The feature is off by default.

---

## Icon

### Placement

A small SVG magnifying glass icon is injected at the far right of each item grid row on all six doctypes:

- **Sales side:** Quotation, Sales Order, Sales Invoice
- **Purchase side:** Purchase Order, Purchase Receipt, Purchase Invoice

The icon is placed in the row's existing action area (alongside the row delete button). It is only rendered when `item_code` is set on the row.

### Style

- SVG path: circle + diagonal line (standard magnifying glass)
- Color: `currentColor` — inherits Frappe's theme text color, adapts to light and dark themes automatically
- Opacity: 55% at rest, 100% on hover
- No border, no background — invisible until hovered

### Injection Timing

Injected via the `form_render` and `grid_row_render` events in `frappe.ui.form.on(...)` for each target doctype. Re-runs on `items_add` and `items_remove` so new rows pick up the icon immediately.

---

## Dialog

Opened by clicking the lens icon on any item row. Data is fetched in a single `frappe.call` to `get_lens_data` on open. The dialog renders after the call resolves.

Built with `frappe.ui.Dialog` (large size). Title: `Lens — <item_name>`.

### Item Header Strip

Shown at the top of every dialog regardless of doctype:

| Element | Detail |
|---------|--------|
| Item name | Bold, 13px |
| Item group | Small badge |
| Stock chip | Total qty across all warehouses |

**Stock chip hover behaviour:**
- If `frappe.model.can_read("Bin")` is `true`: hovering the chip shows a popover listing qty per warehouse (warehouse name + qty). Warehouses with qty ≤ 5 are shown in red. A "Total" row at the bottom matches the chip figure.
- If `false`: chip shows total only; no hover interaction is rendered.
- The per-warehouse data is fetched as part of the main `get_lens_data` call. The server checks `frappe.has_permission("Bin", "read")` and omits the breakdown if the user lacks access.

---

## Sales Doc Dialog (Quotation / Sales Order / Sales Invoice)

### Section 1 — Sales to this customer (last 5)

Queries submitted Sales Invoices and Sales Orders for the combination of `customer` × `item_code`, ordered by `posting_date DESC`.

Columns:

| Column | Source |
|--------|--------|
| Doc | `name` — rendered as a hyperlink opening the document in a new tab |
| Date | `posting_date` formatted as DD-MMM-YY |
| Qty | `qty` from the item line |
| Rate | `rate` from the item line |
| Status | `status` field from the parent document (Paid, Partly Paid, Unpaid, Overdue, etc.) |

Status column only applies to Sales Invoice rows; Sales Order rows show their document status (e.g. "To Deliver and Bill").

Only rendered when a customer is set on the current form. **Note:** Quotation uses `party_name` (not `customer`) and may target a Lead instead of a Customer. The JS must read `frm.doc.party_name || frm.doc.customer` and only pass it to the API when `frm.doc.party_type !== "Lead"` (or when `party_type` is absent, as on SO/SI). If the party is a Lead, this section is skipped.

If no history exists, shows "No previous sales to this customer."

### Section 2 — Sales to other customers (last 5)

Queries submitted Sales Invoices across all customers excluding the current customer, for this `item_code`, ordered by `posting_date DESC`.

Columns:

| Column | Source |
|--------|--------|
| Doc | `name` — hyperlink |
| Customer | `customer` from the parent document |
| Date | `posting_date` formatted as DD-MMM-YY |
| Qty | `qty` |
| Rate | `rate` |

No status column (mixed context, less relevant for pricing decisions).

If no history exists, shows "No sales to other customers found."

### Section 3 — Price Lists

Lists all **enabled selling price lists** that have a price for this item.

Columns:

| Column | Detail |
|--------|--------|
| List | Price list name |
| Current Rate | `price_list_rate` from Item Price |
| Margin % | `(rate - valuation_rate) / rate × 100`, rounded to 1 decimal |
| New Rate | Editable input (see below) |
| New Margin % | Live-calculated as user types |

**Margin calculation** uses the item's `valuation_rate` from `tabBin` (weighted average across all warehouses). If valuation rate is zero or unavailable, margin columns show "—".

**New Rate / New Margin columns** are only rendered if `frappe.model.can_write("Item Price")` returns `true`. If the user lacks write permission, the Current Rate and Margin % columns are still shown (read-only view).

New Margin updates in real-time (on `input` event) as the user edits New Rate.

**"Save Prices" button** at the dialog footer batch-saves all Item Price records where New Rate differs from Current Rate. Uses `frappe.call` to a dedicated `update_item_prices` API method. On success, shows a green alert and refreshes the section. On error, shows the error message without closing the dialog.

---

## Purchase Doc Dialog (Purchase Order / Purchase Receipt / Purchase Invoice)

### Section 1 — Purchase history (last 5)

Queries submitted Purchase Orders, Purchase Receipts, and Purchase Invoices for this `item_code`, across all suppliers, ordered by `posting_date DESC`.

Columns:

| Column | Source |
|--------|--------|
| Doc | `name` — hyperlink |
| Supplier | `supplier` from the parent document |
| Date | `posting_date` formatted as DD-MMM-YY |
| Qty | `qty` |
| Rate | `rate` |

If no history exists, shows "No purchase history found."

### Section 2 — Price Lists

Identical to the sales-side price list section. Showing selling price lists in context of a purchase doc is useful for understanding what margin a given purchase cost yields. Same permission gating applies.

---

## Backend API

### `get_lens_data(item_code, customer, doctype)`

Single `@frappe.whitelist()` function added to `cecypo_powerpack/api.py`.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `item_code` | str | Required |
| `customer` | str | Optional — only used for sales doctypes |
| `doctype` | str | The calling doctype — determines which history sections to fetch |

**Returns a single dict:**

```python
{
    "item_name": str,
    "item_group": str,
    "valuation_rate": float,
    "total_stock": float,
    "stock_by_warehouse": [           # omitted if caller lacks Bin read permission
        {"warehouse": str, "qty": float}, ...
    ],
    "sales_to_customer": [...],       # only for sales doctypes, only if customer set
    "sales_to_others": [...],         # only for sales doctypes
    "purchase_history": [...],        # only for purchase doctypes
    "price_lists": [
        {
            "price_list": str,
            "item_price_name": str,   # name of the Item Price record
            "rate": float,
            "currency": str
        }, ...
    ]
}
```

All history arrays contain at most 5 entries. The server enforces this limit.

### `update_item_prices(updates)`

`@frappe.whitelist()` function in `api.py`. Accepts a JSON list of `{item_price_name, new_rate}` objects. Calls `frappe.db.set_value("Item Price", name, "price_list_rate", rate)` for each. Frappe's built-in permission check enforces write access — no custom gating needed.

---

## New Files

| File | Purpose |
|------|---------|
| `cecypo_powerpack/public/js/lens_powerup.js` | Icon injection, dialog render, price edit logic, warehouse popover |
| `cecypo_powerpack/public/css/lens_powerup.css` | Dialog styles, stock popover, history table, status badges |

Both registered in `hooks.py` under `app_include_js` and `app_include_css`. A new `enable_lens` Check field is added to `powerpack_settings.json`.

---

## PowerPack Settings Changes

| Field | Type | Section |
|-------|------|---------|
| `lens_section` | Section Break | "Lens" |
| `enable_lens` | Check | default 0 |
| `lens_description` | HTML | description blurb |

---

## Out of Scope (v1)

- Lens on POS Invoice (POS UI is structurally different; deferred)
- Quotation / SO history on purchase-side dialog
- Custom "low stock threshold" setting (hardcoded at ≤ 5 for now)
- Trend indicators (↑↓) on history rates
