# Finish: Copy as Image

Landed: `feat/copy-as-image` merged to `main` (1273d46) and pushed to `upstream/main`.

## What shipped
- Powerup > Copy as Image on QT / SO / SI / PO forms (default format + letterhead).
- Copy as Image button on the print preview of those doctypes (selected format, letterhead,
  language and sidebar print settings).
- Server: `cecypo_powerpack.copy_as_image.get_print_image` - print PDF -> pypdfium2 150 DPI
  -> pages stacked (max 10), trailing blank pages/space trimmed; raw formats refused;
  Print permission; PowerPack Settings > Enable Copy as Image (patch turns it on).

## Verification
- `bench --site dev.localhost run-tests --app cecypo_powerpack`: 63 + 10 + 223 + 63 tests,
  all OK (1 pre-existing skip), on a quiet site.
- Headless Chromium e2e at 1400px and 375px: clipboard receives image/png from both entry
  points; one button + one menu item; hidden for User and raw formats; triple click -> one
  request; unsaved-form and raw-default messages shown; no page errors.

## Deploy on other sites
`bench migrate` (field + patch) and `bench build --app cecypo_powerpack`.
`pypdfium2` is now a declared dependency (already installed wherever erpnext's pdfplumber is).

## Follow-ups
- dev's Sales Invoice default print format is `Calibration Grid - ESC/P` (raw), so the SI
  form button there explains to pick another format; use the print preview, or change the
  default.
- Sidebar print-settings toggles are not rendered on dev's print page, so that path is
  covered by a unit test rather than a browser toggle.
