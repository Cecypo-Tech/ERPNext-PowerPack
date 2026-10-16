// A KRA payment Journal Entry is linked from submitted Payment Entries' withholding rows.
// Without this, desk cancel offers only "Cancel All", which cancels those Payment Entries
// first and is refused. The server clears the links on cancel (kenya_withholding.clear_kra_link).
frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		// ERPNext sets the list in setup; the form object is reused across documents, so toggle.
		const list = (frm.ignore_doctypes_on_cancel_all = frm.ignore_doctypes_on_cancel_all || []);
		const i = list.indexOf("Payment Entry");
		const kra = !!(frm.doc.__onload && frm.doc.__onload.is_kra_payment);
		if (kra && i < 0) list.push("Payment Entry");
		if (!kra && i >= 0) list.splice(i, 1);
	},
});
