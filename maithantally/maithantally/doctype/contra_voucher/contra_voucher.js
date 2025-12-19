let is_auto_balancing = false;

frappe.ui.form.on("Contra Voucher", {
    validate(frm) {
        let total_debit = 0;
        let total_credit = 0;

        (frm.doc.voucher_ledger_entry || []).forEach(row => {
            if (!row.ledger) frappe.throw("Ledger is mandatory");
            if (!row.entry_type) frappe.throw("Entry Type is mandatory");
            if (!row.ledger_amount || row.ledger_amount <= 0) {
                frappe.throw("Ledger Amount must be greater than zero");
            }

            if (row.entry_type === "Debit") {
                total_debit += flt(row.ledger_amount);
            } else if (row.entry_type === "Credit") {
                total_credit += flt(row.ledger_amount);
            }
        });

        if (flt(total_debit) !== flt(total_credit)) {
            frappe.throw(
                `Debit (${total_debit}) and Credit (${total_credit}) must be equal`
            );
        }
    }
});



frappe.ui.form.on("Voucher Ledger Entry", {

    ledger_amount(frm, cdt, cdn) {
        if (!is_auto_balancing) {
            auto_balance(frm, cdt, cdn);
        }
    },

    entry_type(frm, cdt, cdn) {
        if (!is_auto_balancing) {
            auto_balance(frm, cdt, cdn);
        }
    },

    voucher_ledger_entry_remove(frm) {
        if (!is_auto_balancing) {
            auto_balance(frm);
        }
    }
});



function auto_balance(frm, cdt, cdn) {

    is_auto_balancing = true;

    let debit = 0;
    let credit = 0;
    let debit_rows = [];
    let credit_rows = [];

    (frm.doc.voucher_ledger_entry || []).forEach(row => {
        let amt = flt(row.ledger_amount || 0);

        if (row.entry_type === "Debit") {
            debit += amt;
            debit_rows.push(row);
        } else if (row.entry_type === "Credit") {
            credit += amt;
            credit_rows.push(row);
        }
    });


    if (debit > credit && credit_rows.length) {
        let row = credit_rows[credit_rows.length - 1];
        let diff = flt(debit - credit);

        if (!row.ledger_amount || flt(row.ledger_amount) === 0) {
            frappe.model.set_value(
                row.doctype,
                row.name,
                "ledger_amount",
                diff
            );
        }
    }

    if (credit > debit && debit_rows.length) {
        let row = debit_rows[debit_rows.length - 1];
        let diff = flt(credit - debit);

        if (!row.ledger_amount || flt(row.ledger_amount) === 0) {
            frappe.model.set_value(
                row.doctype,
                row.name,
                "ledger_amount",
                diff
            );
        }
    }

    frm.refresh_field("voucher_ledger_entry");

    is_auto_balancing = false;
}
