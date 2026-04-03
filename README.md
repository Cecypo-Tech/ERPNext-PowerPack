### Cecypo PowerPack

Gives ERPNext Power ups! :facepunch:

### Features

All features are toggled individually via **PowerPack Settings**.

| Feature | Description |
|---|---|
| **Compact Theme** | Reduces line-height and input sizes for a denser layout across the entire desk |
| **POS Powerup** | Compact/thumbnail view toggle, wildcard `%` and multi-word search, keyboard nav, barcode feedback |
| **Sales Powerup** | Inline stock, valuation rate, last purchase price, last sale price and profit margin on Quotation / SO / SI / POS Invoice item lines |
| **Bulk Selection** | Bulk item selector dialog on Quotation, Sales Order, Sales Invoice, Purchase Order, Stock Reconciliation and Stock Entry |
| **Item Search Powerup** | Replaces ERPNext's default item search on all forms with multi-word (space-separated AND) and wildcard (`%`) search |
| **Payment Reconciliation Powerup** | Zero Allocate, Zero Reconcile, 2% Allocate (Kenya VAT withholding), and enhanced doc info on the Payment Reconciliation form |
| **Public Document Links** | Generates short public URLs (`/s/{name}-{token}`) for sharing Quotations, Invoices etc. with customers — includes a branded viewer page and optional Frappe Builder block |
| **Duplicate Tax ID Check** | Warns before saving a Customer or Supplier whose Tax ID is already in use |
| **ETR Invoice Cancellation Guard** | Prevents cancellation of Sales/POS Invoices that have an ETR number set |
| **Warnings** | Future bill-date alert on Purchase Invoice; overdue invoice popup when selecting a customer on sales documents |

##### Centralized Settings to enable/disable features
![](https://i.imgur.com/Y9JD8fX.png)
##### Bulk Price Update
![](https://i.imgur.com/VYu5iaq.png)
##### Compact POS + enhanced search
![](https://i.imgur.com/MlWbhuh.gif)
##### Duplicate customer or supplier soft warning
![](https://i.imgur.com/btf7hCB.png)
##### Power Sales
![](https://i.imgur.com/Hmxel3H.png)
##### Bulk Selection for QT/SO/SI + enhanced search
![](https://i.imgur.com/odv7pO5.gif)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app cecypo_powerpack
```

### API

#### `get_document_public_link(doctype, name)`

Generates a public shareable link for any document (Quotation, Sales Invoice, etc.) that a customer can open to view/print without logging in.

Compatible with both Frappe v15 and v16+.

> **v15 note:** Requires `allow_older_web_view_links` enabled in System Settings.
> **v16+ note:** Uses `DocumentShareKey` with configurable expiry (`document_share_key_expiry` in System Settings, default 90 days).

**JavaScript:**
```javascript
frappe.call({
    method: 'cecypo_powerpack.api.get_document_public_link',
    args: { doctype: frm.doc.doctype, name: frm.doc.name },
    callback(r) {
        // r.message is the shareable URL, e.g.:
        // https://yoursite.com/Quotation/QTN-0001?key=abc123...
    }
});
```

**REST:**
```
GET /api/method/cecypo_powerpack.api.get_document_public_link?doctype=Quotation&name=QTN-0001
```

### License

mit
