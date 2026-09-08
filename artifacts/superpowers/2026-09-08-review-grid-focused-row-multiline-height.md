# Fix review: focused grid row collapsed instead of expanding for multi-line descriptions

Branch: `fix/grid-focused-row-multiline-height`
File: `cecypo_powerpack/public/css/cecypo_powerpack.css` (+45 lines, CSS only)

## Root cause
Two compact-theme rules, both unscoped by fieldtype:

- `cecypo_powerpack.css:155` `.editable-row .field-area { height: var(--input-height) }`
- `cecypo_powerpack.css:161` `.editable-row .form-control { height: var(--input-height) !important }`

Frappe's `toggle_editable_row(true)` (`grid_row.js:1186`) swaps EVERY cell in the
focused row from `.static-area` to a live control. Those two rules then pin the
Description control (Quill, `Text Editor`) to one line, while `.grid-static-col
{ height: unset !important; max-height: 200px }` (line 95) lets idle rows grow to
content. Hence: idle rows tall, focused row short — the reported inversion.

A second, smaller contributor: Frappe zeroes `.grid-static-col` padding on editable
rows, making the focused cell 16px wider, so the same text wrapped to one line fewer.

## Measured, same row, on dev.localhost
| state | before | after |
|---|---|---|
| row 2 idle | 92px | 92px |
| row 2 focused | **32px** | **92px** |

Baseline captured by checking the file out at HEAD, re-injecting the stylesheet, and
re-measuring in the live page. No console errors. Screenshot confirms all three
description lines visible in the focused row at the same height as the idle row.

## Findings by severity
- **Blocker:** none.
- **Major:** none.
- **Minor:** the `Small Text` / `Text` / `Long Text` / `Code` selectors are reasoned
  from the same mechanism but NOT exercised in the browser — no grid in this app
  currently exposes one of those fieldtypes in list view. `Text Editor` is the
  verified path.
- **Minor:** `Code` renders an editor div, not `.form-control`, so its entry in the
  textarea block is inert. Left in place as harmless defensive coverage; the
  `.field-area` rule is what actually frees its height.
- **Nit:** first block uses 4-space indent, second uses tabs — each matches the
  surrounding lines in that part of the file.

## Scope check
Every rule is prefixed `body.compact-theme .grid-body .editable-row`, so non-compact
sites and every non-grid surface are untouched. No JS, no DocType, no data change.

## Verification commands
```
bench build --app cecypo_powerpack
# then hard-reload the browser (the stylesheet is cached aggressively — a normal
# reload served the stale file during this session)
```

## Deployment
`bench build --app cecypo_powerpack` + `bench clear-cache`, then hard-reload.
No migrate needed.

## Dev-site scaffolding (created then removed)
- Property Setters `Sales Order Item.description` in_list_view/columns — deleted.
- Extra item row on draft `SAL-ORD-2026-00029` — removed.
- NOT reverted: the `description` text on that draft test order's remaining row was
  overwritten with sample multi-line text. It is a `_Test PIP Item` order.
