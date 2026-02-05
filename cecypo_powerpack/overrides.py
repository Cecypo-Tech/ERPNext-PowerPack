# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
Payment Reconciliation Overrides

Custom validation and reconciliation logic to support zero-amount allocations.
"""

import frappe
from frappe import _
import json


def validate_allocation_with_zero_support(doc, method=None):
    """
    Enhanced validation that allows zero-amount allocations when the feature is enabled.

    Standard ERPNext validation may throw errors for zero allocations.
    This override warns if ALL allocations are zero.
    The actual filtering happens in the custom controller's reconcile_allocations method.

    Args:
        doc: Payment Reconciliation document
        method: Hook method name (unused)
    """
    from cecypo_powerpack.utils import is_feature_enabled

    # Only apply custom logic if feature is enabled
    if not is_feature_enabled('enable_payment_reconciliation_zero_allocate'):
        return

    if not doc.allocation:
        return

    # Check if all allocations are zero
    non_zero_count = 0
    zero_count = 0

    for allocation in doc.allocation:
        allocated_amount = allocation.get('allocated_amount') or 0

        if allocated_amount > 0:
            non_zero_count += 1
        else:
            zero_count += 1

    # Warn if all allocations are zero (but don't prevent saving/reconciling)
    if zero_count > 0 and non_zero_count == 0:
        frappe.msgprint(
            _("All allocation amounts are zero. Please set amounts before reconciling."),
            indicator='orange',
            title=_('Zero Allocations')
        )


def get_payment_amount(doc, allocation):
    """
    Get the payment amount for an allocation row.

    Args:
        doc: Payment Reconciliation document
        allocation: Allocation row

    Returns:
        float: Payment amount
    """
    reference_name = allocation.get('reference_name')

    if not reference_name or not doc.payments:
        return 0

    for payment in doc.payments:
        if payment.get('reference_name') == reference_name:
            return payment.get('amount') or 0

    return 0


def get_invoice_outstanding(doc, allocation):
    """
    Get the outstanding amount for an invoice in an allocation row.

    Args:
        doc: Payment Reconciliation document
        allocation: Allocation row

    Returns:
        float: Invoice outstanding amount
    """
    voucher_no = allocation.get('voucher_no')

    if not voucher_no or not doc.invoices:
        return 0

    for invoice in doc.invoices:
        if invoice.get('voucher_no') == voucher_no:
            return invoice.get('outstanding_amount') or 0

    return 0


@frappe.whitelist()
def reconcile_wrapper(doc):
    """
    Wrapper for Payment Reconciliation reconcile method.

    This wrapper filters out zero-amount allocations before calling
    the standard ERPNext reconcile method.

    Args:
        doc: Payment Reconciliation document (JSON string or dict)

    Returns:
        Result from standard reconcile method
    """
    from cecypo_powerpack.utils import is_feature_enabled

    # Parse doc if it's a JSON string
    if isinstance(doc, str):
        doc = json.loads(doc)

    # Create document object
    reconciliation_doc = frappe.get_doc(doc)

    # Check if feature is enabled
    if is_feature_enabled('enable_payment_reconciliation_zero_allocate'):
        if reconciliation_doc.allocation:
            # Filter out zero-amount allocations
            original_count = len(reconciliation_doc.allocation)
            non_zero_allocations = [
                alloc for alloc in reconciliation_doc.allocation
                if (alloc.get('allocated_amount') or 0) > 0
            ]

            zero_count = original_count - len(non_zero_allocations)

            if zero_count > 0:
                # Replace allocation table with non-zero entries only
                reconciliation_doc.allocation = non_zero_allocations

                frappe.msgprint(
                    _("Skipped {0} zero-amount allocation rows. Reconciling {1} non-zero rows.").format(
                        zero_count,
                        len(non_zero_allocations)
                    ),
                    indicator='blue',
                    title=_('Zero Allocations Skipped')
                )

    # Call the original reconcile method
    from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import reconcile
    return reconcile(reconciliation_doc.as_dict())
