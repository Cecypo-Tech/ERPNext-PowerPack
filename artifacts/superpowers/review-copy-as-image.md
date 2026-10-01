# Review: Copy as Image (feat/copy-as-image)

Scope: `copy_as_image.py`, `public/js/copy_as_image.js`, PowerPack Settings
`enable_copy_as_image` (+ default patch), tests, README/CLAUDE.md.

## Verification
- `bench --site dev.localhost run-tests --module cecypo_powerpack.tests.test_copy_as_image` - 10/10 OK
  (stitch/trim on synthetic pages, real wkhtmltopdf PDF -> PNG incl. 10-page cap,
  endpoint: inline PNG response, args passed through, print permission, doctype allow-list, gate).
- Real renders via the endpoint: SI X-POS-00021, PO LPO/26/10/DBG1 (slash in name ->
  `LPO-26-10-DBG1.png`), QT SAL-QTN-2026-00002. ~3.5-4 s each, 86-142 KB, 1240 px wide.
- Headless Chromium (python playwright, throwaway user, deleted after):
  form Powerup > Copy as Image on the PO puts a 187 KB image/png on the clipboard and shows
  "Image copied"; print preview button on the QT puts a 174 KB PNG on the clipboard and the
  image matches the preview (letterhead, item image); button hidden on /app/print/User/...,
  shown again on a Sales Invoice in the same PrintView instance; no page errors.
- Full app suite: two runs collided with another session's klik_pos tests on the same site
  (TimestampMismatchError on PowerPack/System Settings, deadlocks - failing classes ran
  before test_copy_as_image). Rerun on a quiet site: see finish notes.

## Findings
### Blocker
- none
### Major
- none
### Minor
- Prints longer than MAX_PAGES (10) are cut silently; README says "up to 10 pages".
- `print_format_builder_beta` (weasyprint) formats are rendered through get_print/wkhtmltopdf,
  not weasyprint, so they may differ from that format's own PDF. No such formats on dev.
- Users with Read but not Print can download frappe's PDF (frappe accepts read OR print)
  but cannot Copy as Image - intentional, stricter.
- Mobile (hidden-xl) menu item toggling is not browser-tested; it relies on
  `add_menu_item` returning the item `add_button` already created (same label).
### Nit
- The trim stops at the print's own footer ("Page 1 of 1"), so a short document keeps
  the blank band above its footer. Faithful to the print; not cropped further on purpose.

## Deploy
`bench migrate` (new Check field + patch that turns it on) and
`bench build --app cecypo_powerpack` (new bundle import).
