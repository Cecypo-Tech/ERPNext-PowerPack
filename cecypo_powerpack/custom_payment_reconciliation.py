# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
Custom Payment Reconciliation Controller

Provides zero-allocation reconciliation without affecting standard reconciliation.
"""

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import PaymentReconciliation


def _fixed_update_reference_in_journal_entry(d, journal_entry, do_not_save=False):
    """
    Drop-in replacement for erpnext.accounts.utils.update_reference_in_journal_entry.

    The original uses d["unadjusted_amount"] (the pre-batch outstanding) to compute how
    much of the JE row remains after each allocation. When N invoices are reconciled against
    the same JE row in one batch, iterations 2..N receive the original total as
    unadjusted_amount, causing them to reset the remaining balance to
    (original_total - this_allocation) instead of (running_remaining - this_allocation).
    Result: JE imbalance equal to (original_total - last_allocated_amount).

    Fix: read the actual current balance from jv_detail.get(d["dr_or_cr"]) — the row was
    correctly reduced by the previous iteration, so this value is always current.
    """
    from frappe.utils import cstr
    from erpnext.accounts.utils import get_advance_payment_doctypes

    jv_detail = journal_entry.get("accounts", {"name": d["voucher_detail_no"]})[0]

    rev_dr_or_cr = (
        "debit_in_account_currency"
        if d["dr_or_cr"] == "credit_in_account_currency"
        else "credit_in_account_currency"
    )
    if jv_detail.get(rev_dr_or_cr):
        d["dr_or_cr"] = rev_dr_or_cr
        d["allocated_amount"] = d["allocated_amount"] * -1
        d["unadjusted_amount"] = d["unadjusted_amount"] * -1

    current_balance = flt(jv_detail.get(d["dr_or_cr"]))
    if current_balance - flt(d["allocated_amount"]) != 0:
        amount_in_account_currency = current_balance - flt(d["allocated_amount"])
        amount_in_company_currency = amount_in_account_currency * flt(jv_detail.exchange_rate)
        jv_detail.set(d["dr_or_cr"], amount_in_account_currency)
        jv_detail.set(
            "debit" if d["dr_or_cr"] == "debit_in_account_currency" else "credit",
            amount_in_company_currency,
        )
    else:
        journal_entry.remove(jv_detail)

    new_row = journal_entry.append("accounts")

    [
        new_row.set(field, jv_detail.get(field))
        for field in frappe.get_meta("Journal Entry Account").get_fieldnames_with_value()
    ]

    new_row.set(d["dr_or_cr"], d["allocated_amount"])
    new_row.set(
        "debit" if d["dr_or_cr"] == "debit_in_account_currency" else "credit",
        d["allocated_amount"] * flt(jv_detail.exchange_rate),
    )
    new_row.set(
        "credit_in_account_currency"
        if d["dr_or_cr"] == "debit_in_account_currency"
        else "debit_in_account_currency",
        0,
    )
    new_row.set("credit" if d["dr_or_cr"] == "debit_in_account_currency" else "debit", 0)

    new_row.set("reference_type", d["against_voucher_type"])
    new_row.set("reference_name", d["against_voucher"])

    new_row.against_account = cstr(jv_detail.against_account)
    new_row.is_advance = cstr(jv_detail.is_advance)
    new_row.docstatus = 1

    if jv_detail.get("reference_type") in get_advance_payment_doctypes():
        new_row.advance_voucher_type = jv_detail.get("reference_type")
        new_row.advance_voucher_no = jv_detail.get("reference_name")

    journal_entry.flags.ignore_validate_update_after_submit = True
    journal_entry.flags.ignore_reposting_on_reconciliation = True
    if not do_not_save:
        journal_entry.save(ignore_permissions=True)

    return new_row


class CustomPaymentReconciliation(PaymentReconciliation):
    """
    Extended Payment Reconciliation with zero allocation support via custom method.
    Standard reconciliation is not affected.
    """

    def reconcile_allocations(self, skip_ref_details_update_for_pe=False):
        import erpnext.accounts.utils as erpnext_utils
        erpnext_utils.update_reference_in_journal_entry = _fixed_update_reference_in_journal_entry
        super().reconcile_allocations(skip_ref_details_update_for_pe)

    @frappe.whitelist()
    def zero_reconcile(self):
        """
        Custom reconciliation method for zero allocations.

        This method:
        1. Filters out zero-amount allocations
        2. Bypasses "Payment Entry modified" validation
        3. Performs reconciliation on non-zero allocations

        Does NOT affect standard reconcile() method.
        """
        from cecypo_powerpack.utils import is_feature_enabled

        # Check if feature is enabled
        if not is_feature_enabled('enable_payment_reconciliation_powerup'):
            frappe.throw(_("Zero Allocate feature is not enabled in PowerPack Settings"))

        # Filter out zero allocations
        if self.allocation:
            original_count = len(self.allocation)

            # Keep only non-zero allocations
            non_zero_allocations = [
                alloc for alloc in self.allocation
                if (alloc.allocated_amount or 0) > 0
            ]

            zero_count = original_count - len(non_zero_allocations)

            if zero_count > 0:
                self.allocation = non_zero_allocations
                frappe.msgprint(
                    _("Filtered {0} zero-amount allocation(s). Reconciling {1} allocation(s).").format(
                        zero_count,
                        len(non_zero_allocations)
                    ),
                    indicator='blue',
                    title=_('Zero Allocations Filtered')
                )

        if not self.allocation:
            frappe.throw(_("No non-zero allocations to reconcile"))

        # Validate that no row tries to allocate more than the payment outstanding stored on that row.
        # (Standard reconcile() catches this via validate_allocation; we skip that but must still
        # guard here, otherwise reconcile_dr_cr_note will create an imbalanced JE.)
        for alloc in self.allocation:
            if flt(alloc.allocated_amount) > flt(alloc.amount) + 0.005:
                frappe.throw(
                    _(
                        "Row {0} ({1}): Allocated amount {2} exceeds the payment outstanding {3} "
                        "stored on that row. Open the Allocation table, find the row where "
                        "'Allocated Amount' > 'Amount', and reduce it."
                    ).format(
                        alloc.idx,
                        alloc.reference_name or "",
                        flt(alloc.allocated_amount),
                        flt(alloc.amount),
                    )
                )

        # Perform reconciliation without "modified" check
        self._reconcile_without_validation()

        frappe.msgprint(_("Successfully Reconciled"), indicator="green")

    # NOTE: The process-level monkey-patch in zero_reconcile() is safe under preforked
    # Gunicorn (current bench16 config). Under gevent/gthread it would race across greenlets.
    def _reconcile_without_validation(self):
        """
        Internal method that performs reconciliation without the strict validation.
        Uses ERPNext's reconcile_against_document but skips "Payment Entry modified" check.
        For credit/debit notes (SI/PI with is_return=1), uses reconcile_dr_cr_note instead.
        """
        from erpnext.accounts.utils import reconcile_against_document
        from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import reconcile_dr_cr_note
        import erpnext.accounts.utils

        original_check = erpnext.accounts.utils.check_if_advance_entry_modified
        erpnext.accounts.utils.update_reference_in_journal_entry = _fixed_update_reference_in_journal_entry

        def dummy_check(entry):
            pass

        try:
            erpnext.accounts.utils.check_if_advance_entry_modified = dummy_check

            # Build entry list using parent class logic
            dr_or_cr = "credit_in_account_currency" if self.party_type == "Customer" else "debit_in_account_currency"

            entry_list = []
            dr_or_cr_notes = []

            for row in self.allocation:
                reconciled_entry = frappe._dict({
                    "voucher_type": row.reference_type,
                    "voucher_no": row.reference_name,
                    "voucher_detail_no": row.get("reference_row"),
                    "against_voucher_type": row.invoice_type,
                    "against_voucher": row.invoice_number,
                    "account": self.receivable_payable_account,
                    "party_type": self.party_type,
                    "party": self.party,
                    "is_advance": row.is_advance,
                    "dr_or_cr": dr_or_cr,
                    "unadjusted_amount": row.amount,
                    "allocated_amount": row.allocated_amount,
                    "exchange_rate": row.exchange_rate or 1,
                    "difference_amount": row.difference_amount or 0,
                    "difference_account": row.difference_account,
                    "difference_posting_date": row.get("gain_loss_posting_date"),
                    "currency": row.currency,
                    "cost_center": row.get("cost_center"),
                    "debit_or_credit_note_posting_date": row.get("debit_or_credit_note_posting_date"),
                })

                # Add accounting dimensions
                if self.dimensions:
                    for dimension in self.dimensions:
                        if isinstance(dimension, dict):
                            dimension_field = dimension.get('fieldname')
                        else:
                            dimension_field = dimension

                        if dimension_field:
                            reconciled_entry[dimension_field] = row.get(dimension_field)

                # Categorize entries: credit/debit notes use reconcile_dr_cr_note,
                # payment entries and journal entries use reconcile_against_document
                if row.reference_type in ["Sales Invoice", "Purchase Invoice"]:
                    dr_or_cr_notes.append(reconciled_entry)
                else:
                    entry_list.append(reconciled_entry)

            # Use ERPNext's standard reconciliation with validation disabled
            skip_ref_details_update_for_pe = True

            if entry_list:
                reconcile_against_document(entry_list, skip_ref_details_update_for_pe, self.dimensions)

            # Credit/debit notes require their own reconciliation path that creates a JE
            if dr_or_cr_notes:
                reconcile_dr_cr_note(dr_or_cr_notes, self.company, self.dimensions)

        finally:
            erpnext.accounts.utils.check_if_advance_entry_modified = original_check
