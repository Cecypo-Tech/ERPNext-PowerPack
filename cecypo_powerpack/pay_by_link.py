"""Pay-by-link bridge between PowerPack short links and M-Pesa Express.

A short link goes out with an invoice or quotation. Most recipients will never
pay by M-Pesa, so nothing is created until someone actually presses Pay, and a
second press reuses the request already made rather than leaving another row
behind. That keeps one payment request per payer instead of one per email sent.

The short link token is the only thing the caller supplies. It is the capability
the customer was given, and resolving the document through it is what stops an
anonymous caller creating payment requests against arbitrary documents.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import flt

EXPRESS_REQUEST = "Mpesa Express Request"

# A quotation carries no payment state of its own, so a completed request
# against one is what we treat as "already paid".
NO_PAYMENT_STATE = ("Quotation",)

# Statuses that mean the document is no longer collectable.
DEAD_STATUSES = {
    "Sales Order": ("Closed", "Completed"),
    "Quotation": ("Lost", "Expired", "Ordered"),
}


def _short_link(token: str):
    link = frappe.db.get_value(
        "PowerPack Short Link",
        token,
        ["name", "reference_doctype", "reference_docname", "expires_on"],
        as_dict=True,
    )
    if not link:
        frappe.throw(_("This link does not exist."), frappe.PageDoesNotExistError)

    if link.expires_on and str(link.expires_on) < frappe.utils.today():
        frappe.throw(_("This link has expired."), frappe.PageDoesNotExistError)

    if not link.reference_doctype:
        frappe.throw(_("This link does not point at a document."))

    return link


def _settled_by_a_previous_request(doctype: str, docname: str) -> bool:
    return bool(
        frappe.db.exists(
            EXPRESS_REQUEST,
            {
                "reference_doctype": doctype,
                "reference_name": docname,
                "status": "Completed",
            },
        )
    )


def get_payable(doctype: str, docname: str) -> dict | None:
    """What is still owed on this document, or None if nothing is.

    Returns amount in the document's own currency; the Express Request converts
    to KES itself when the gateway is configured for it.
    """
    if doctype not in ("Sales Invoice", "Sales Order", "Quotation"):
        return None

    fields = ["name", "company", "currency", "grand_total", "docstatus", "status"]
    if doctype == "Sales Invoice":
        fields.append("outstanding_amount")
    if doctype == "Sales Order":
        fields.append("advance_paid")

    doc = frappe.db.get_value(doctype, docname, fields, as_dict=True)
    if not doc or doc.docstatus != 1:
        return None

    if doc.status in DEAD_STATUSES.get(doctype, ()):
        return None

    if doctype in NO_PAYMENT_STATE and _settled_by_a_previous_request(doctype, docname):
        return None

    if doctype == "Sales Invoice":
        amount = flt(doc.outstanding_amount)
    elif doctype == "Sales Order":
        amount = flt(doc.grand_total) - flt(doc.advance_paid)
    else:
        amount = flt(doc.grand_total)

    if amount <= 0:
        return None

    return {
        "doctype": doctype,
        "docname": docname,
        "company": doc.company,
        "currency": doc.currency,
        "amount": amount,
    }


def _gateway_for_company(company: str) -> str | None:
    """The M-Pesa gateway collecting for this company, preferring the default."""
    rows = frappe.get_all(
        "Payment Gateway Account",
        filters={"company": company, "payment_gateway": ["like", "Mpesa-%"]},
        fields=["payment_gateway", "is_default"],
        order_by="is_default desc",
        limit=1,
    )
    return rows[0].payment_gateway if rows else None


def _reusable_request(doctype: str, docname: str):
    """An earlier request for this document that the payer can still use.

    A draft has not been sent yet; a failed one can be retried from the same
    page. Either way there is no reason to create a second row.
    """
    rows = frappe.get_all(
        EXPRESS_REQUEST,
        filters=[
            ["reference_doctype", "=", doctype],
            ["reference_name", "=", docname],
            ["docstatus", "<", 2],
            ["status", "in", ["In Progress", "Failed"]],
        ],
        fields=["name", "request_id", "docstatus", "base_amount"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


@frappe.whitelist(allow_guest=True)
@rate_limit(key="token", limit=10, seconds=60)
def start_mpesa_payment(token: str) -> dict:
    """Hand the customer an M-Pesa checkout page for the linked document."""
    link = _short_link(token)
    payable = get_payable(link.reference_doctype, link.reference_docname)

    if not payable:
        frappe.throw(_("This document is not awaiting payment."))

    existing = _reusable_request(link.reference_doctype, link.reference_docname)
    if existing:
        # The balance can have moved since the request was raised.
        if existing.docstatus == 0 and flt(existing.base_amount) != payable["amount"]:
            frappe.db.set_value(
                EXPRESS_REQUEST, existing.name, "base_amount", payable["amount"]
            )
        return {"redirect_to": f"/mpesa/stkpush?id={existing.request_id}"}

    gateway = _gateway_for_company(payable["company"])
    if not gateway:
        frappe.log_error(
            f"No Mpesa Payment Gateway Account for company {payable['company']}",
            "Pay by link: no gateway",
        )
        frappe.throw(_("M-Pesa is not available for this document."))

    request = frappe.get_doc(
        {
            "doctype": EXPRESS_REQUEST,
            "payment_gateway": gateway,
            "reference_doctype": payable["doctype"],
            "reference_name": payable["docname"],
            "account_reference": payable["docname"],
            "base_amount": payable["amount"],
            "currency": payable["currency"],
            "status": "In Progress",
            "transaction_title": f"{payable['doctype']} {payable['docname']}",
        }
    )
    # Left as a draft on purpose: submitting sends a prompt immediately, and at
    # this point nobody has told us which phone to send it to. The checkout page
    # collects that and submits.
    request.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"redirect_to": f"/mpesa/stkpush?id={request.request_id}"}
