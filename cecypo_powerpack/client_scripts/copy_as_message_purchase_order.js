// PowerPack - Copy as Message (Purchase Order)
// Adds Powerup > Copy as Message: copies a short message with a public link to the
// order, ready to paste into WhatsApp, SMS or email to the supplier.
//
// This script belongs to your site. Edit it freely: PowerPack created it once and
// will never overwrite it. To switch it off, untick Enabled.
(() => {
	// Extra lines added to the end of every message, such as delivery instructions or
	// what to quote on the invoice. Key by Company name; '*' is used for any company
	// not listed.
	// Example:
	//   '*': `Please deliver to our main store, 8am-4pm, and quote the PO number on your invoice.`,
	const NOTES = {
	};

	frappe.ui.form.on('Purchase Order', {
		refresh(frm) {
			if (frm.is_new() || frm.doc.docstatus === 2) return;
			frm.add_custom_button(__('Copy as Message'), () => copy_message(frm), __('Powerup'));
		},
	});

	async function copy_message(frm) {
		const doc = frm.doc;
		let url;
		try {
			url = await get_public_link(frm);
		} catch (e) {
			frappe.msgprint(__('Failed to generate the public link'));
			return;
		}

		const lines = [
			`${doc.supplier_name || doc.supplier || __('Supplier')},`,
			__('Purchase Order {0} from {1} dated {2}', [
				doc.name, doc.company, frappe.datetime.str_to_user(doc.transaction_date),
			]),
		];
		if (doc.schedule_date) {
			lines.push(__('Required By: {0}', [frappe.datetime.str_to_user(doc.schedule_date)]));
		}
		lines.push(__('Total: {0}', [format_currency(flt(doc.rounded_total || doc.grand_total), doc.currency)]));
		// Only states the supplier must act on; "To Receive and Bill" and the like are ours.
		if (doc.docstatus === 0) {
			lines.push(__('Status: {0}', [__('Draft')]));
		} else if (['On Hold', 'Closed'].includes(doc.status)) {
			lines.push(__('Status: {0}', [__(doc.status)]));
		}
		lines.push(__('View it here: {0}', [url]));

		await copy(lines.join('\n') + notes(doc.company));
	}

	function notes(company) {
		const text = NOTES[company] || NOTES['*'];
		return text ? `\n\n${text.trim()}` : '';
	}

	function get_public_link(frm) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method: 'cecypo_powerpack.api.get_document_public_link',
				args: { doctype: frm.doc.doctype, name: frm.doc.name },
				callback: (r) => (r.message ? resolve(r.message) : reject(new Error('No URL returned'))),
				error: reject,
			});
		});
	}

	async function copy(message) {
		try {
			await navigator.clipboard.writeText(message);
			frappe.show_alert({ message: __('Message copied'), indicator: 'green' });
		} catch (e) {
			frappe.msgprint(__('Failed to copy to clipboard'));
		}
	}
})();
