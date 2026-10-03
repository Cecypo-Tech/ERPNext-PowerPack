# Plan: "Copy as Message" in the print preview Powerup menu

Approved design (in chat, 2026-10-03): the print preview's Powerup ▾ dropdown gains
the site's "Copy as Message" action, behaving exactly like the form button, by
running the site's own Client Script source against a stub frm — the pattern
klik_pos already uses for held orders, simplified for desk where the real frappe
globals exist.

## Background

- "Copy as Message" is a site-owned Client Script per doctype (seeded as
  `PowerPack - Copy as Message (<doctype>)`), registering a form-only button via
  `frappe.ui.form.on(dt, refresh)` → `frm.add_custom_button('Copy as Message', …,
  'Powerup')`. The print page has no real form (a deep link builds a bare
  `{doctype, docname, doc, meta}` stub), so the button never appears there.
- klik_pos precedent: `klik_pos/api/sales_order.py` finds the script by the
  `add_custom_button('Copy as Message'…)` pattern; its SPA runs the source against
  a shimmed frm (`klik_spa/src/utils/copyAsMessage.ts`).

## Steps

1. **Server endpoint (TDD)** — `cecypo_powerpack/api.py`:
   `get_copy_message_script(doctype)`: enabled Form Client Scripts for the
   doctype, sorted name asc then the seeded `PowerPack - Copy as Message
   (<doctype>)` name first; return the first whose source matches
   `add_custom_button(\s*(?:__\(\s*)?['"]Copy as Message['"]`. Requires read
   permission on the doctype (else None). Write tests first:
   no script → None; seeded name preferred; non-matching/disabled/List-view
   scripts ignored; no-permission user → None.
   Verify: `bench run-tests --app cecypo_powerpack --module <test module>`.

2. **Client** — `cecypo_powerpack/public/js/copy_as_image.js` print-view section:
   - Powerup group created once; two items — Copy as Image (existing) and
     Copy as Message — each with a narrow-screen page-menu fallback, toggled
     independently; group visible if either item is.
   - Per show: fetch the script for `frm.doc.doctype` (`frappe.call`, cached
     promise per doctype). If present, run it with
     `new Function('frappe', 'cur_frm', src)` passing a shim built with
     `Object.create(frappe)` overriding only `ui.form.on` (collects handlers),
     and a stub frm `{doc, doctype, docname, is_new, is_dirty,
     add_custom_button (collects the 'Copy as Message' action),
     remove_custom_button}`. Call the collected `refresh(frm)`; the collected
     action decides visibility (so the script's own guards — cancelled doc
     etc. — apply) and is what the menu items invoke.
   - Guard races: apply results only if the view still shows that doctype.
   - Copy as Message is NOT gated on `enable_copy_as_image` or raw-printing —
     same conditions as the form button (enabled script exists, script's own
     refresh guards pass).
   Verify: `bench build --app cecypo_powerpack` clean.

3. **E2E (browser, dev.localhost)**:
   - SI print preview: Powerup ▾ shows Copy as Image + Copy as Message; message
     click copies/produces the message (alert) including payment details.
   - Customer print preview: no Powerup group at all.
   - Doctype in DOCTYPES with raw format selected: image hidden, message still
     shown (parity with form).

4. **Docs** — README.md + CLAUDE.md one-line updates (print preview Powerup now
   carries the site's Copy as Message too).

5. **Review pass + land** — severity-ranked review; commit on
   `feat/print-preview-copy-as-message`, merge --no-ff to main, push
   `upstream/main`.

## Verification summary

- Python: new test module green + full app suite unaffected.
- `bench build --app cecypo_powerpack` clean.
- Browser e2e as in step 3.
