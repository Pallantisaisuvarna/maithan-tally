frappe.pages['tally-configuration-'].on_page_load = function(wrapper) {
    let page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Tally Configuration Selection',
        single_column: true
    });

    $(wrapper).find('.layout-main-section').html(`
        <div id="tally-config-list" class="mt-4">
            <h3>Tally Configuration</h3>
            <div class="text-muted">Loading...</div>
        </div>
    `);

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Tally Configuration",
            fields: ["name", "company", "url", "is_active","password","username"],
            limit_page_length: 50
        },
        callback: function(r) {
            if (r.message) {
                render_data(r.message);
            } else {
                $("#tally-config-list").html(`<p>No Records Found</p>`);
            }
        }
    });

    function render_data(data) {
        let html = `
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Company</th>
                        <th>URL</th>
                        <th>Is Active</th>
                        <th>Password</th>
                        <th>Username</th>
                    </tr>
                </thead>
                <tbody>
        `;

        data.forEach(row => {
            html += `
                <tr>
                    <td>${row.company || "-"}</td>
                    <td>${row.url || "-"}</td>
                    <td>
                        <input type="checkbox" class="is-active-checkbox" data-name="${row.name}" ${row.is_active ? "checked" : ""}>
                    </td>
                    <td>${row.password || "-"}</td>
                    <td>${row.username || "-"}</td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        $("#tally-config-list").html(html);

        
        $(".is-active-checkbox").on("change", function() {
            let docname = $(this).data("name");
            let value = $(this).is(":checked") ? 1 : 0;

            frappe.call({
                method: "frappe.client.set_value",
                args: {
                    doctype: "Tally Configuration",
                    name: docname,
                    fieldname: "is_active",
                    value: value
                },
                callback: function(r) {
                    frappe.show_alert({ message: 'Updated successfully', indicator: 'green' });
                }
            });
        });
    }
};
