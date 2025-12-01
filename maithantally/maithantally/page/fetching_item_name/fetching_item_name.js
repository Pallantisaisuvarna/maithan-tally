frappe.pages['fetching-item-name'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Fetching Item Name',
		single_column: true
	});
	page.add_inner_button("Fetch Item", ()=> {
		frappe.call({
			method: "maithantally.tally_sync_fetch_itemname.fetch_items",
			freeze: true,
			freeze_message:"Fteching Item Name.....",
			callback: function(r) {
				frappe.msgprint({
					title:"Sucess",
					message:`Response fetched sucessfully.<br><br>
					<b>Imported Itemnames:<b>${r.message}`,
					indicator:"green"
					
				});

			}
		});
	});
}