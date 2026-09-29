# Review: Copy as Message for Purchase Order

Branch: feat/copy-as-message-po

## Change
- `client_scripts/copy_as_message_purchase_order.js`: Powerup > Copy as Message on
  Purchase Order. Message to the supplier: name, PO number, our company, date, Required
  By, total, public link; status only when Draft / On Hold / Closed (internal fulfilment
  statuses mean nothing to a supplier). Per-company `NOTES` block (shipped empty) instead
  of `PAYMENT_DETAILS`.
- `copy_as_message.py`: registered in `SCRIPTS` — seeded when missing, then site-owned.
- Tests and README.

## Verification
- `test_copy_as_message` OK; full `bench run-tests --app cecypo_powerpack` OK
  (1 pre-existing Quick Pay skip).
- Browser, PUR-ORD-2026-00004: Powerup ▾ shows Copy as Message; clipboard:
  "Supplier A, / Purchase Order PUR-ORD-2026-00004 from Dev Co dated 07-07-2026 /
  Required By: 08-07-2026 / Total: Sh 464.00 / View it here: https://dev.cecypo.tech/s/…"
- Short link opens for a guest (200, PowerPack landing page, no Pay button — pay-by-link
  is limited to SI/SO/QT).

## Findings (subagent review: ready to merge)
- Blocker/Major: none.
- Minor, fixed: On Hold/Closed status line; dropped "Items: N" (row count, not quantity);
  company named in the PO line; test names/asserts tightened; README covers banner and
  header, not only footer.
- Note for the site: dev's Public Link footer HTML says "PAY SECURELY — Processed by
  Safaricom M-Pesa". It is site data shown on every document link, including POs.
