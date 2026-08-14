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


def _share_key(doctype: str, docname: str) -> str | None:
    """A public key for this document, minted once and reused afterwards.

    Two things have to be handled here that frappe's own helper does not.
    It looks for an existing key carrying no expiry date, but Document Share
    Key stamps one on insert, so that lookup never matches and every call
    would mint another key - hence the lookup below. And a page render is a
    GET, which frappe rolls back, so a freshly minted key has to be committed
    or the customer is handed a link whose key does not exist.
    """
    existing = frappe.get_all(
        "Document Share Key",
        filters={"reference_doctype": doctype, "reference_docname": docname},
        or_filters=[
            ["expires_on", "is", "not set"],
            ["expires_on", ">=", frappe.utils.today()],
        ],
        fields=["key"],
        order_by="expires_on desc",
        limit=1,
    )
    if existing:
        return existing[0].key

    try:
        key = frappe.get_doc(doctype, docname).get_document_share_key()
        frappe.db.commit()
        return key
    except Exception:
        # Read-only replica, maintenance mode, anything else: better to drop
        # the button than to show one that leads nowhere.
        frappe.log_error(frappe.get_traceback(), "Pay by link: share key")
        return None


def receipt_for(doctype: str, docname: str) -> dict | None:
    """The invoice to show once there is nothing left to pay.

    A paid Sales Order has its receipt on the invoice raised from it, not on
    the order, so follow that through. Anything still owed returns nothing -
    the payer is being asked to pay, not handed a receipt.
    """
    invoice = None

    if doctype == "Sales Invoice":
        row = frappe.db.get_value(
            doctype, docname, ["name", "docstatus", "outstanding_amount"], as_dict=True
        )
        if row and row.docstatus == 1 and flt(row.outstanding_amount) <= 0:
            invoice = row.name

    elif doctype == "Sales Order":
        rows = frappe.get_all(
            "Sales Invoice Item",
            filters={"sales_order": docname, "docstatus": 1},
            fields=["parent"],
            order_by="creation desc",
            limit=1,
        )
        invoice = rows[0].parent if rows else None

    if not invoice:
        return None

    key = _share_key("Sales Invoice", invoice)
    if not key:
        return None

    return {
        "name": invoice,
        "url": f"{frappe.utils.get_url()}/Sales%20Invoice/{invoice}?key={key}",
    }


def payable_gateways(company: str) -> list[dict]:
    """The M-Pesa shortcodes this company can collect through.

    Sourced from Mpesa Settings' own company field. A settings row with no
    shortcode cannot collect, and one without a matching Payment Gateway cannot
    be attached to a request, so both are excluded. Live shortcodes win outright
    when any exist - a sandbox entry alongside them is a test leftover, not a
    choice worth offering a paying customer.
    """
    rows = frappe.get_all(
        "Mpesa Settings",
        filters={"company": company, "business_shortcode": ["is", "set"]},
        fields=["name", "business_shortcode", "sandbox", "paybill_type"],
        order_by="business_shortcode asc",
    )

    usable = [
        row
        for row in rows
        if str(row.business_shortcode).strip()
        and frappe.db.exists("Payment Gateway", f"Mpesa-{row.name}")
    ]
    live = [row for row in usable if not row.sandbox]

    return [
        {
            "gateway": f"Mpesa-{row.name}",
            "shortcode": str(row.business_shortcode).strip(),
            "paybill_type": row.paybill_type,
        }
        for row in (live or usable)
    ]


def _resolve_amount(requested, outstanding: float) -> float:
    """How much to collect now, defaulting to the whole balance.

    Part payments exist so several people can settle one sale between them,
    so anything from a penny up to the balance is allowed. More than the
    balance is refused: an overpayment has no invoice to allocate against and
    becomes a credit somebody has to unpick later.
    """
    if requested in (None, ""):
        return outstanding

    amount = flt(requested)
    if amount <= 0:
        frappe.throw(_("Enter an amount greater than zero."))

    # A penny of rounding either way should not block a payer settling in full.
    if amount - outstanding > 0.005:
        frappe.throw(
            _("That is more than the {0} still owed on this document.").format(
                frappe.utils.fmt_money(outstanding)
            )
        )

    return amount


def _resolve_gateway(company: str, chosen: str | None) -> str:
    """Which shortcode to collect through, honouring the customer's choice."""
    options = payable_gateways(company)

    if not options:
        frappe.log_error(
            f"No usable M-Pesa shortcode for company {company}",
            "Pay by link: no gateway",
        )
        frappe.throw(_("M-Pesa is not available for this document."))

    if chosen:
        # Never take the caller's word for it: only a shortcode this company
        # actually collects through is allowed, or money lands elsewhere.
        if chosen not in {option["gateway"] for option in options}:
            frappe.throw(_("That M-Pesa option is not available for this document."))
        return chosen

    if len(options) == 1:
        return options[0]["gateway"]

    frappe.throw(_("Please choose which M-Pesa number to pay."))


def _reusable_request(doctype: str, docname: str):
    """A draft raised earlier for this document that was never sent.

    Only drafts. A submitted request has already been to Safaricom and carries
    that attempt's outcome, so handing one back does two wrong things: the
    checkout endpoint saves and submits, which a submitted document rejects,
    and the caller polling for a result immediately reads the *previous*
    attempt's terminal status - reporting "Request Cancelled by user" for a
    prompt that was never sent. A new attempt needs a new request.
    """
    rows = frappe.get_all(
        EXPRESS_REQUEST,
        filters=[
            ["reference_doctype", "=", doctype],
            ["reference_name", "=", docname],
            ["docstatus", "=", 0],
            ["status", "=", "In Progress"],
        ],
        fields=["name", "request_id", "base_amount", "payment_gateway"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


@frappe.whitelist(allow_guest=True)
@rate_limit(key="token", limit=10, seconds=60)
def start_mpesa_payment(
    token: str, gateway: str | None = None, amount=None
) -> dict:
    """Hand the customer an M-Pesa checkout page for the linked document."""
    link = _short_link(token)
    payable = get_payable(link.reference_doctype, link.reference_docname)

    if not payable:
        frappe.throw(_("This document is not awaiting payment."))

    gateway = _resolve_gateway(payable["company"], gateway)
    # Never take the client's word for it: the amount is re-checked against
    # what the document actually still owes, on every attempt.
    amount = _resolve_amount(amount, payable["amount"])

    existing = _reusable_request(link.reference_doctype, link.reference_docname)

    # With several people settling one sale, a draft raised for someone else's
    # figure must not be handed over and quietly rewritten.
    if existing and flt(existing.base_amount) != amount:
        existing = None

    if existing:
        # The draft can be stale: the balance may have moved since it was
        # raised, or it may name a shortcode the payer has just moved away from.
        changes = {}
        if existing.payment_gateway != gateway:
            changes["payment_gateway"] = gateway
            changes["settings"] = gateway[6:]
        if changes:
            frappe.db.set_value(EXPRESS_REQUEST, existing.name, changes)
            frappe.db.commit()
        return {
            "request_id": existing.request_id,
            "amount": amount,
            "currency": payable["currency"],
            "redirect_to": f"/mpesa/stkpush?id={existing.request_id}",
        }

    request = frappe.get_doc(
        {
            "doctype": EXPRESS_REQUEST,
            "payment_gateway": gateway,
            "reference_doctype": payable["doctype"],
            "reference_name": payable["docname"],
            "account_reference": payable["docname"],
            "base_amount": amount,
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

    return {
        "request_id": request.request_id,
        "amount": amount,
        "currency": payable["currency"],
        # Kept so the page still works if scripting is unavailable.
        "redirect_to": f"/mpesa/stkpush?id={request.request_id}",
    }
