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

	// Server rows against local ones, on the server's own fields. Blank, null, 0 and false are alike:
	// a fresh server row holds null where the saved local row holds 0.
	function norm(v) {
		return v === null || v === undefined || v === '' || v === 0 || v === false ? '' : String(v);
	}
	const NUMERIC = ['Currency', 'Float', 'Percent', 'Int'];
	function same_rows(server, local) {
		return server.length === local.length && server.every(function (row, i) {
			return Object.keys(row).every(function (k) {
				if (k.indexOf('__') === 0 || META.indexOf(k) >= 0) return true;
				const df = frappe.meta.get_docfield(row.doctype, k);
				if (df && NUMERIC.indexOf(df.fieldtype) >= 0) {
					// At field precision, as amounts_same: float noise must not re-dirty a saved draft.
					const p = precision(k, local[i]);
					return flt(row[k], p) === flt(local[i][k], p);
				}
				return norm(row[k]) === norm(local[i][k]);
			});
		});
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
				frm.doc.cecypo_total_withheld = 0;
				frm.refresh_fields(['cecypo_withholding', 'deductions', 'cecypo_total_withheld']);
			}
			if (frm._wht_locked) lock(frm, false);
			return;
		}
		const seq = (frm._wht_seq = (frm._wht_seq || 0) + 1);
		const held = (frm.doc.cecypo_withholding || []).length > 0;
		CecypoPowerPack.Settings.isEnabled('enable_kenya_withholding', function (enabled) {
			frm._wht_enabled = enabled;
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
					// The server sends the user's own deductions back under their local names and its
					// withholding deductions with none; local rows it did not send back are ours to replace.
					const local = frm.doc.deductions || [];
					const local_names = local.map(function (d) { return d.name; });
					const kept = m.deductions.map(function (d) { return d.name; }).filter(function (n) {
						return n && local_names.indexOf(n) >= 0;
					});
					const ours = m.deductions.filter(function (d) { return kept.indexOf(d.name) < 0; });
					const held = local.filter(function (d) { return kept.indexOf(d.name) < 0; });
					// Write only what differs: add_child dirties the form (frappe.model.add_child), and a
					// dirty draft never shows Submit, so a saved draft the server already computed stays clean.
					const rows_same = same_rows(m.cecypo_withholding, frm.doc.cecypo_withholding || [])
						&& same_rows(ours, held);
					const amounts_same = ['paid_amount', 'received_amount', 'cecypo_total_withheld'].every(function (f) {
						return flt(m[f], precision(f, frm.doc)) === flt(frm.doc[f], precision(f, frm.doc));
					});
					if (!rows_same) {
						fill(frm, 'cecypo_withholding', m.cecypo_withholding);
						// The user's rows stay the same objects, so a row being edited is not swapped out.
						held.forEach(function (d) { frappe.model.clear_doc(d.doctype, d.name); });
						ours.forEach(function (row) {
							const d = frm.add_child('deductions');
							Object.keys(row).forEach(function (k) {
								if (META.indexOf(k) < 0) d[k] = row[k];
							});
						});
						frm.refresh_field('deductions');
					}
					if (!rows_same || !amounts_same) {
						// Assign, never set_value: that fires ERPNext's re-spread over the references.
						frm.doc.paid_amount = m.paid_amount;
						frm.doc.received_amount = m.received_amount;
						frm.doc.cecypo_total_withheld = m.cecypo_total_withheld;
						frm.refresh_field('cecypo_total_withheld');
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
						// add_child dirties on its own, but clearing (clear_table/clear_doc) and plain
						// assignment do not: a preview that changed the form must mark it unsaved.
						frm.dirty();
					}
				}
				if (has !== !!frm._wht_locked) lock(frm, has);
			},
		});
	}

	const debounced = frappe.utils.debounce(compute, 300);

	frappe.ui.form.on('Payment Entry', {
		refresh: function (frm) {
			if (window.CecypoPowerPack && CecypoPowerPack.addHelp) {
				CecypoPowerPack.Settings.isEnabled('enable_kenya_withholding', function (enabled) {
					if (!enabled) return;
					CecypoPowerPack.addHelp(frm, CecypoPowerPack.WALKTHROUGH_SLUGS.withholding);
					CecypoPowerPack.addHelp(frm, CecypoPowerPack.WALKTHROUGH_SLUGS.withholding_deposits);
				});
			}
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
			// With withholding the paid amount is derived: drop a typed one, so ERPNext allocates each
			// invoice its full outstanding (payment_entry.js fills an empty paid amount from them).
			const fetch = frm.events.get_outstanding_documents;
			if (fetch && !fetch._wht) {
				frm.events.get_outstanding_documents = Object.assign(
					function (frm, filters, get_outstanding_invoices) {
						if (get_outstanding_invoices && filters && filters.allocate_payment_amount && frm.doc.party
							&& frm._wht_enabled && frm.doc.payment_type === 'Pay' && frm.doc.party_type === 'Supplier') {
							frm.doc.paid_amount = frm.doc.received_amount = 0;
							frm.doc.base_paid_amount = frm.doc.base_received_amount = 0;
							frm.refresh_fields(['paid_amount', 'received_amount', 'base_paid_amount', 'base_received_amount']);
						}
						return fetch.apply(this, arguments);
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
		cecypo_skip_withholding: debounced,
	});
	frappe.ui.form.on('Payment Entry Reference', {
		allocated_amount: function (frm) { debounced(frm); },
		references_remove: function (frm) { debounced(frm); },
	});
	// The user's own deductions (bank charges, write-offs) change the paid amount. Our own writes
	// (add_child, plain assignment, clear_doc) fire none of these, so this does not loop.
	frappe.ui.form.on('Payment Entry Deduction', {
		amount: function (frm) { debounced(frm); },
		account: function (frm) { debounced(frm); },
		deductions_add: function (frm) { debounced(frm); },
		deductions_remove: function (frm) { debounced(frm); },
	});
})();
