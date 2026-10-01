# Plan: Copy as Image (QT / SO / SI / PO)

Approved design (chat, 2026-10-01): one click puts a PNG of the document's print on the
clipboard for pasting into messaging apps. Form Powerup menu + print preview toolbar,
all pages stitched, QT/SO/SI/PO only, gated by a new PowerPack setting (default on).

## Steps
1. Branch `feat/copy-as-image`.
2. Setting: add `copy_as_image_section` + `enable_copy_as_image` (Check, default 1) to
   PowerPack Settings (Sales & POS tab, after Lens). `bench migrate`.
   Verify: field exists on dev.localhost.
3. TDD - `tests/test_copy_as_image.py` (red first):
   - `stitch_pages` on synthetic PIL pages: height = sum of pages, trailing white trimmed
     on the last page only, `MAX_PAGES` cap honoured.
   - `get_print_image`: returns PNG bytes as a binary response for a real Sales Invoice
     (or any of the four); refuses other doctypes; refuses a user without print
     permission; refuses when `enable_copy_as_image` is off.
4. Implement `cecypo_powerpack/copy_as_image.py`:
   - `render_png(doc, print_format, letterhead, no_letterhead, lang)`:
     `frappe.get_print(..., as_pdf=True)` -> pypdfium2 pages at 150 DPI -> `stitch_pages`.
   - `get_print_image(...)` whitelisted GET: gate, doctype allow-list, print permission,
     response type `binary` / `image/png`.
   Verify: tests green.
5. Client `public/js/copy_as_image.js` imported in the bundle:
   - Form refresh handlers for the four doctypes: Powerup > Copy as Image (saved,
     not cancelled).
   - Print view: patch `frappe.ui.form.PrintView.prototype.setup_toolbar` / `show` to add a
     toolbar button visible only for the four doctypes, using selected format, letterhead,
     language.
   - `ClipboardItem({'image/png': fetchPromise})` called synchronously in the click
     handler; fallback downloads `<name>.png`.
   `bench build --app cecypo_powerpack`. Verify bundle builds.
6. Manual/endpoint verification: render a real SI to PNG via the endpoint and inspect it.
   Browser check if Playwright is available; otherwise hand the paste check to the user.
7. README section. Full app test suite. Review (`artifacts/superpowers/review-copy-as-image.md`).
8. Merge to main, push `upstream/main`.

## Risks
- Print permission vs read: use `frappe.has_permission(doctype, "print", doc)` as frappe's
  own PDF download does.
- Huge prints: cap at MAX_PAGES (10).
- Safari user activation: ClipboardItem must be created in the click handler with a promise.
- Clipboard image unsupported: download fallback.
