# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
Custom Payment Reconciliation Controller

Provides zero-allocation reconciliation without affecting standard reconciliation.
"""

import frappe
from frappe import _
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import PaymentReconciliation


class CustomPaymentReconciliation(PaymentReconciliation):
    """
    Extended Payment Reconciliation with zero allocation support via custom method.
    Standard reconciliation is not affected.
    """

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

        # Temporarily replace the validation function
        original_check = erpnext.accounts.utils.check_if_advance_entry_modified

        def dummy_check(entry):
            # Do nothing - skip validation
            pass

        try:
            # Replace validation with dummy
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
            # Always restore original validation function
            erpnext.accounts.utils.check_if_advance_entry_modified = original_check
