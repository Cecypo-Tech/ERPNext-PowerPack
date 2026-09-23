// PowerPack - Copy as Message (Quotation)
// Adds Powerup > Copy as Message: copies a short message with a public link to the
// quotation, ready to paste into WhatsApp, SMS or email.
//
// This script belongs to your site. Edit it freely: PowerPack created it once and
// will never overwrite it. To switch it off, untick Enabled.
(() => {
	// Payment details added to the message. Key by Company name; '*' is used for
	// any company not listed.
	// Example:
	//   'My Company Ltd': `======= PAYMENT DETAILS =======
	// BANK: ...
	// A/C: ...
	// PAYBILL: ...`,
	const PAYMENT_DETAILS = {
	};

	frappe.ui.form.on('Quotation', {
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
			`${doc.customer_name || doc.party_name || __('Customer')},`,
			__('Quotation {0} dated {1}', [doc.name, frappe.datetime.str_to_user(doc.transaction_date)]),
		];
		if (doc.valid_till) {
			lines.push(__('Valid Till: {0}', [frappe.datetime.str_to_user(doc.valid_till)]));
		}
		lines.push(__('Total: {0}', [format_currency(doc.rounded_total || doc.grand_total, doc.currency)]));
		lines.push(__('View it here: {0}', [url]));

		await copy(lines.join('\n') + payment_details(doc.company));
	}

	function payment_details(company) {
		const details = PAYMENT_DETAILS[company] || PAYMENT_DETAILS['*'];
		return details ? `\n\n${details.trim()}` : '';
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
