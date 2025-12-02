frappe.pages['fetching-item-name'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Fetching Item Name',
		single_column: true
	});
	$(wrapper).find('.layout-main-section').html(`
		<div id="fetching-item-container" style="margin-left: 30px; margin-top:20px;">
		<button id="fetch-item-btn" class="btn btn-primary mb-3">Fetch Item</button>
		<div id="item-result" class="mt-4"></div></div>`);
	$(wrapper).find('#fetch-item-btn').on('click',function(){
		$('#item-result').html(`<p>Fetching Item....</p>`);
		frappe.call({
			method: "maithantally.tally_sync_fetch_itemname.fetch_items",
			freeze: true,
			freeze_message:"Fetching Item.....",
			callback: function(r){
				let items=r.message || [];
				if (!Array.isArray(items)) {
					items=[items];
				}
				if(items.length===0) {
					$('#item-result').html(`
						<div class="frappe-card p-3">
						<h4>No new items found.</h4>
						</div>
					`);
					return;
				}
				let htmlRows=items.map(i => `<tr><td>${i}</td></tr>`).join("");
				$('#item-result').html(`
					<div class="frappe-card p-8">
					<h4>Fetched Items List:</h4>
					<table class="table table-bordered">
					<thead>
					<tr>
					<th>Item Name</th></tr></thead>
					<tbody>
					${htmlRows}</tbody>
					</table>
					</div>
				`);

			}
		});
	});
	frappe.router.on("change",()=> {
		$('#ledger-result').html("");
	});
};