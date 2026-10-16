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
		// The server endpoint needs write permission; a read-only viewer has nothing to preview.
		if (frm.doc.docstatus !== 0 || !(frm.perm[0] && frm.perm[0].write)) return;
		if (frm.doc.payment_type !== 'Pay' || frm.doc.party_type !== 'Supplier') {
			// Switched away from a supplier payment: drop what we added and unlock.
			const rows = frm.doc.cecypo_withholding || [];
			if (rows.length) {
				const accounts = rows.map(function (r) { return r.account; });
				frm.doc.deductions = (frm.doc.deductions || []).filter(function (d) {
					return !(flt(d.amount) < 0 && accounts.indexOf(d.account) >= 0);
				});
				frm.clear_table('cecypo_withholding');
				frm.refresh_fields(['cecypo_withholding', 'deductions']);
			}
			if (frm._wht_locked) lock(frm, false);
			return;
		}
		const seq = (frm._wht_seq = (frm._wht_seq || 0) + 1);
		const held = (frm.doc.cecypo_withholding || []).length > 0;
		CecypoPowerPack.Settings.isEnabled('enable_kenya_withholding', function (enabled) {
			// Feature off: still call when rows are held, so the server clears them.
			if ((enabled || held) && seq === frm._wht_seq) call(frm, seq);
		});
	}

	function call(frm, seq) {
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
					// ERPNext's unallocated/difference maths reads the base amounts.
					frm.doc.base_paid_amount = m.base_paid_amount;
					frm.doc.base_received_amount = m.base_received_amount;
					frm.refresh_field('base_paid_amount');
					frm.refresh_field('base_received_amount');
					frm.events.set_total_allocated_amount(frm);
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
			// "Get Outstanding Invoices" writes allocated_amount with no field event; it ends in
			// allocate_party_amount_against_ref_docs (payment_entry.js ~1099), so recompute after it.
			const orig = frm.events.allocate_party_amount_against_ref_docs;
			if (orig && !orig._wht) {
				frm.events.allocate_party_amount_against_ref_docs = Object.assign(
					async function () {
						const r = await orig.apply(this, arguments);
						debounced(arguments[0]);
						return r;
					},
					{ _wht: true }
				);
			}
			if (frm.doc.docstatus === 0) debounced(frm);
		},
		party: debounced,
		payment_type: debounced,
		party_type: debounced,
		posting_date: debounced,
	});
	frappe.ui.form.on('Payment Entry Reference', {
		allocated_amount: function (frm) { debounced(frm); },
		references_remove: function (frm) { debounced(frm); },
	});
})();
