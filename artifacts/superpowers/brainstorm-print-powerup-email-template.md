# Brainstorm: Print preview Powerup dropdown + Email Template auto-select

Date: 2026-10-03
Classification: **bounded** (both changes modify flows that already exist in this repo / frappe's composer; short in-chat design, no spec file).

## Goal

1. The print preview toolbar should carry the same **Powerup ▾** dropdown as the
   document form, with **Copy as Image** as an item — replacing the current
   standalone "Copy as Image" button — so the two surfaces look and behave alike.
2. When the Email dialog (`frappe.views.CommunicationComposer`) opens from a form
   and no template is picked, auto-select the **Email Template whose name equals
   the doctype** (e.g. an Email Template named "Sales Invoice" for a Sales Invoice).

## Constraints / facts found in code

- Document view uses `frm.add_custom_button(label, fn, __('Powerup'))` — an inner
  group dropdown.
- Print preview currently uses `view.page.add_button(...)`
  (`copy_as_image.js:134`), which lands in `.custom-actions` — a container that is
  `hidden-xs hidden-md`, which is why the code also keeps a page-menu item for
  narrow screens.
- `page.add_custom_button_group(label)` + `page.add_custom_menu_item(group, ...)`
  is the established pattern (Permission Manager uses it) and renders the same
  "Label ▾" dropdown as the form's custom button groups. It does NOT auto-create
  a narrow-screen menu item, so the existing menu fallback must be kept explicitly.
- Frappe's composer already auto-selects `frm.meta.default_email_template` on the
  first email for a document (`communication.js:554-557`), but that needs per-
  doctype configuration via Customize Form. Selecting a template does **not**
  apply it — the user still clicks "Add Template"; our auto-select will behave
  identically (select + reveal the section, not auto-insert).
- Client-side `frappe.db.exists` permission-checks Email Template, which many
  roles can't read — same class of problem as the PowerPack Settings
  `frappe.client.get` trap documented in CLAUDE.md. Existence must be answered by
  a whitelisted app endpoint.

## Design

### 1. Print preview Powerup dropdown (`public/js/copy_as_image.js`)

In `setup_print_view_button`:
- `const group = view.page.add_custom_button_group(__('Powerup'))`
- `view.page.add_custom_menu_item(group, __('Copy as Image'), click, true)`
- Keep a plain `view.page.add_menu_item(__('Copy as Image'), click, true)` for
  xs/md screens where `.custom-actions` is hidden (replaces the current
  label-matching hack that fishes the auto-added item out of the menu).
- `view._pp_copy_image` becomes the jQuery set {group's `.custom-btn-group`,
  menu `<li>`}; `update_print_view_button` toggles it exactly as today
  (feature flag + doctype allow-list + raw-printing check unchanged).

### 2. Email Template auto-select

- **Setting:** new checkbox `enable_email_template_autoselect` in PowerPack
  Settings (follows the one-checkbox-per-feature pattern; default off).
- **Server:** `get_doctype_email_template(doctype)` in `api.py` —
  returns the template name when the feature is enabled, an **enabled** Email
  Template named exactly `doctype` exists; else `None`. Read via `frappe.db.exists`
  / `get_value` with no user-permission walk (it reveals only that a template with
  that name exists — configuration, not data).
- **Client:** new `public/js/email_template_autoselect.js` imported by the bundle.
  Patch `frappe.views.CommunicationComposer.prototype.set_values` (class is in the
  desk bundle, loaded before app bundles): after the original resolves, when
  `this.frm && !this.is_a_reply && !this.content_set &&
  !this.dialog.get_value("email_template")`, call the endpoint and, on a hit,
  `await this.dialog.set_value("email_template", name)` +
  `this.toggle_more_options(true)` so the selection is visible. Frappe's own
  `meta.default_email_template` (if configured) wins because it is set before we
  look and we only fill an empty field.

### Testing

- Python: tests for `get_doctype_email_template` — feature off → None; no
  template → None; disabled template → None; match → name.
- Manual/e2e in browser on dev.localhost: print preview shows Powerup ▾ with
  Copy as Image (and still hides for raw printing / disabled setting); Email
  dialog on a doctype with a matching template pre-selects it; a doctype
  without one is untouched; reply emails untouched.
- Deploy needs `bench build --app cecypo_powerpack` + `bench migrate`
  (settings field).

### Out of scope

- Auto-inserting the template body (clicking "Add Template" for the user) —
  mirrors frappe's native default-template behavior instead. Can be a follow-up
  if wanted.
