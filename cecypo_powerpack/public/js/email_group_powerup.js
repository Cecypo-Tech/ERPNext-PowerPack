(function () {

frappe.ui.form.on('Email Group', {
	refresh(frm) {
		frm.add_custom_button(__('Import Subscribers by Item Purchased'), function () {
			show_import_dialog(frm);
		}, __('Powerup'));
	},
});

function show_import_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Import Subscribers by Item Purchased'),
		fields: [
			{
				fieldname: 'filter_type',
				fieldtype: 'Select',
				label: __('Import by'),
				options: 'Item\nItem Group',
				default: 'Item',
				reqd: 1,
				onchange() {
					const type = d.get_value('filter_type');
					d.set_value('filter_value', '');
					d.set_df_property('filter_value', 'label', type === 'Item Group' ? __('Item Group') : __('Item'));
					d.set_df_property('filter_value', 'options', type === 'Item Group' ? 'Item Group' : 'Item');
				},
			},
			{
				fieldname: 'filter_value',
				fieldtype: 'Link',
				label: __('Item'),
				options: 'Item',
				reqd: 1,
			},
		],
		primary_action_label: __('Import'),
		primary_action(values) {
			const $btn = d.get_primary_btn();
			$btn.prop('disabled', true).text(__('Importing…'));

			frappe.call({
				method: 'cecypo_powerpack.api.import_email_group_subscribers_by_item',
				args: {
					email_group: frm.doc.name,
					filter_type: values.filter_type,
					filter_value: values.filter_value,
				},
				callback(r) {
					d.hide();
					if (!r.message) return;
					const added = r.message.added;
					const total = r.message.total;
					if (added > 0) {
						frappe.show_alert({
							message: __('{0} subscriber(s) added ({1} total)', [added, total]),
							indicator: 'green',
						});
					} else {
						frappe.show_alert({
							message: __('No new subscribers found.'),
							indicator: 'blue',
						});
					}
					frm.refresh();
				},
				error() {
					$btn.prop('disabled', false).text(__('Import'));
				},
			});
		},
	});

	d.show();
}

})();
