let is_auto_balancing = false;
frappe.ui.form.on("Journal Voucher", {
    validate(frm) {
        auto_balance(frm); 

        let total_debit = 0;
        let total_credit = 0;

        (frm.doc.voucher_ledger_entry || []).forEach(row => {
            if (!row.ledger) frappe.throw("Ledger is mandatory");
            if (!row.entry_type) frappe.throw("Entry Type is mandatory");
            if (!row.ledger_amount || flt(row.ledger_amount) <= 0) {
                frappe.throw("Ledger Amount must be greater than zero");
            }

            if (row.entry_type === "Debit") total_debit += flt(row.ledger_amount);
            else total_credit += flt(row.ledger_amount);
        });

        if (flt(total_debit) !== flt(total_credit)) {
            frappe.throw(`Debit (${total_debit}) and Credit (${total_credit}) must be equal`);
        }
    }
});


frappe.ui.form.on("Voucher Ledger Entry", {
    ledger_amount(frm, cdt, cdn) {
        if (!is_auto_balancing) auto_balance(frm);
    },

    entry_type(frm, cdt, cdn) {
        setTimeout(() => {
            if (!is_auto_balancing) auto_balance(frm);
        }, 10);
    },

    voucher_ledger_entry_add(frm, cdt, cdn) {
        if (!is_auto_balancing) auto_balance(frm);
    },

    voucher_ledger_entry_remove(frm) {
        if (!is_auto_balancing) auto_balance(frm);
    }
});


function auto_balance(frm) {
    if (!frm.doc.voucher_ledger_entry) return;
    is_auto_balancing = true;

    let rows = frm.doc.voucher_ledger_entry;
    let total_debit = 0, total_credit = 0;
    let debit_rows = [], credit_rows = [];

    
    rows.forEach(row => {
        let amt = flt(row.ledger_amount || 0);
        if (row.entry_type === "Debit") {
            total_debit += amt;
            debit_rows.push(row);
        } else if (row.entry_type === "Credit") {
            total_credit += amt;
            credit_rows.push(row);
        }
    });

    let diff = flt(total_debit - total_credit);

   
    if (diff > 0 && credit_rows.length) {
        let empty_credit_row = credit_rows.find(r => !r.ledger_amount || flt(r.ledger_amount) === 0);
        if (empty_credit_row) {
            frappe.model.set_value(empty_credit_row.doctype, empty_credit_row.name, "ledger_amount", diff);
        }
    }

  
    if (diff < 0 && debit_rows.length) {
        let empty_debit_row = debit_rows.find(r => !r.ledger_amount || flt(r.ledger_amount) === 0);
        if (empty_debit_row) {
            frappe.model.set_value(empty_debit_row.doctype, empty_debit_row.name, "ledger_amount", flt(-diff));
        }
    }

    frm.refresh_field("voucher_ledger_entry");
    is_auto_balancing = false;
}
