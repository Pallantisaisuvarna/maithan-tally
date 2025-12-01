frappe.pages['fetching-ledger-'].on_page_load = function (wrapper) {

    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Fetching Ledger',
        single_column: true
    });

    $(wrapper).find('.layout-main-section').html(`
        <div id="fetch-ledger-container" style="margin-left: 30px; margin-top: 20px;">
            <button id="fetch-ledger-btn" class="btn btn-primary mb-3">
                Fetch Ledger
            </button>
            <div id="ledger-result" class="mt-4"></div>
        </div>
    `);

    $(wrapper).find('#fetch-ledger-btn').on('click', function () {
        $('#ledger-result').html(`<p>Fetching Ledger...</p>`);

        frappe.call({
            method: "maithantally.tally_sync_fetch_ledgers.fetch_ledgers",
            freeze: true,
            freeze_message: "Fetching Ledger...",
            callback: function (r) {

                let ledgers = r.message || [];

                if (!Array.isArray(ledgers)) {
                    ledgers = [ledgers];
                }

                if (ledgers.length === 0) {
                    $('#ledger-result').html(`
                        <div class="frappe-card p-3">
                            <h4>No new ledgers found.</h4>
                        </div>
                    `);
                    return;
                }

                
                let htmlRows = ledgers.map(l => `<tr><td>${l}</td></tr>`).join("");

                $('#ledger-result').html(`
                    <div class="frappe-card p-3">
                        <h4>Fetched Ledgers List:</h4>
                        <table class="table table-bordered">
                            <thead>
                                <tr>
                                    <th>Ledger Name</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${htmlRows}
                            </tbody>
                        </table>
                    </div>
                `);
            }
        });
    });

    frappe.router.on("change", () => {
        $('#ledger-result').html("");
    });
};
