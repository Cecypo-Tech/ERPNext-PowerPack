// Live preview of Kenya withholding on supplier Payment Entries. The server's
// before_validate hook is the authority; this only shows the result before saving.
(function () {
	const META = ['name', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'parent',
		'parentfield', 'parenttype', 'idx', 'doctype', '__unsaved'];

	function fill(frm, fieldname, rows) {
		frm.clear_table(fieldname);
		rows.forEach(function (row) {
			const d = frm.add_child(fieldname);
			Object.keys(row).forEach(function (k) {
				if (META.indexOf(k) < 0) d[k] = row[k];
			});
		});
		frm.refresh_field(fieldname);
	}

	function lock(frm, locked) {
		['paid_amount', 'received_amount'].forEach(function (f) {
			frm.set_df_property(f, 'read_only', locked ? 1 : 0);
		});
		frm._wht_locked = locked;
	}

	function compute(frm) {
		if (frm.doc.docstatus !== 0 || frm.doc.payment_type !== 'Pay' || frm.doc.party_type !== 'Supplier') return;
		const seq = (frm._wht_seq = (frm._wht_seq || 0) + 1);
		frappe.call({
			method: 'cecypo_powerpack.kenya_withholding.compute_for_payment_entry',
			args: { doc: frm.doc },
			callback: function (r) {
				const m = r.message;
				if (!m || seq !== frm._wht_seq || frm.doc.docstatus !== 0) return;
				const has = m.cecypo_withholding.length > 0;
				if (has || (frm.doc.cecypo_withholding || []).length) {
					fill(frm, 'cecypo_withholding', m.cecypo_withholding);
					fill(frm, 'deductions', m.deductions);
					// Assign, never set_value: that fires ERPNext's re-spread over the references.
					frm.doc.paid_amount = m.paid_amount;
					frm.doc.received_amount = m.received_amount;
					frm.refresh_field('paid_amount');
					frm.refresh_field('received_amount');
					frm.events.set_unallocated_amount(frm);
					frm.events.set_difference_amount(frm);
				}
				if (has !== !!frm._wht_locked) lock(frm, has);
			},
		});
	}

	const debounced = frappe.utils.debounce(compute, 300);

	frappe.ui.form.on('Payment Entry', {
		refresh: function (frm) {
			if (frm.doc.docstatus === 0) debounced(frm);
		},
		party: debounced,
		posting_date: debounced,
	});
	frappe.ui.form.on('Payment Entry Reference', {
		allocated_amount: function (frm) { debounced(frm); },
		references_remove: function (frm) { debounced(frm); },
	});
})();
