# Review: PowerPack Settings - fewer, wider sections on Items and System tabs

Branch: feat/settings-layout

## Change (powerpack_settings.json, layout fields only)
- Items: one section "Item Powerups", 2 columns (Item Search | Item List).
  `item_list_powerup_section` Section Break -> Column Break.
- System:
  - "Powerups" (was "Payment Reconciliation Powerup"), 3 columns:
    Payment Reconciliation | Warnings | Email Group. `warnings_section` and
    `email_group_section` -> Column Breaks, moved up with their fields.
  - Validation & Checks, 2 columns: new `column_break_validation_1`.
  - Public Document Links, 2 columns: new `column_break_public_link_0`.
  - Banner & Footer unchanged.
- No data field changed (checked by diffing every non-layout field definition).
  One description line now stores its em-dash as — (same parsed text) - the file
  had mixed escaping.

## Verification (dev.localhost, 1440px viewport)
- `bench migrate` (first run hit an unrelated race: another session was mid-edit on
  cecypo_qz_extension's after_migrate; second run clean).
- Tab heights: Items 258 -> 173px, System 978 -> 691px. Screenshots checked.
- Saved the form once: all 59 tabSingles values identical apart from `modified`.
- Full app suite (site otherwise idle): 316 tests OK.

## Findings
- Blocker / Major: none.
- Minor: the Warnings description is long and sets the height of the Powerups row.
- Nit: section/column fieldnames keep their old names (e.g. `warnings_section` is now a
  Column Break) so the diff stays small and nothing referencing them breaks.
