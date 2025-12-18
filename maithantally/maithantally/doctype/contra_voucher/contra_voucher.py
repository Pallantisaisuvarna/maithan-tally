import requests
import frappe
from frappe.model.document import Document
from datetime import datetime
from frappe.utils import get_url


class ContraVoucher(Document):

    def after_insert(self):
        if self.is_pushed_to_tally:
            return

        self.flags.from_insert = True
        push_to_tally(self, action="Create")
        self.db_set("is_pushed_to_tally", 1, update_modified=False)

    def on_update(self):
        if self.flags.get("from_insert"):
            return

        if not self.is_pushed_to_tally:
            return

        if not self.has_child_value_changed():
            return

        push_to_tally(self, action="Alter")

    def on_trash(self):
        delete_from_tally(self)

    def has_child_value_changed(self):
        before = self.get_doc_before_save()
        if not before:
            return False

        if len(before.voucher_ledger_entry) != len(self.voucher_ledger_entry):
            return True

        for old, new in zip(before.voucher_ledger_entry, self.voucher_ledger_entry):
            if (
                old.ledger != new.ledger
                or old.entry_type != new.entry_type
                or old.ledger_amount != new.ledger_amount
            ):
                return True

        return False
def validate_contra_ledger(ledger):
    parent_ledger = frappe.db.get_value("Ledger", ledger, "parent_ledger")
    return parent_ledger in ("Cash-in-Hand", "Bank Accounts")

def get_active_tally_config():
    config = frappe.db.get_all(
        "Tally Configuration",
        filters={"is_active": 1},
        fields=["company", "url"],
        limit=1
    )
    if not config:
        config_url = get_url("/desk/tally-configuration-")
        frappe.throw(f'No Active Tally Configuration found.<br>'
                     f'<a href="{config_url}" target="_blank"><b>Click here to activate</b></a>')
    return config[0].company, config[0].url

def validate_contra_entries(doc):
    if not doc.voucher_ledger_entry or len(doc.voucher_ledger_entry) < 2:
        frappe.throw("Contra Voucher must have at least two ledger entries")

    total_debit = 0
    total_credit = 0
    has_debit = False
    has_credit = False

    for row in doc.voucher_ledger_entry:

        if not row.ledger:
            frappe.throw("Ledger is mandatory in all rows")

        if not row.entry_type:
            frappe.throw("Entry Type is mandatory (Debit / Credit)")

        if not row.ledger_amount or row.ledger_amount <= 0:
            frappe.throw("Ledger Amount must be greater than zero")

        if not validate_contra_ledger(row.ledger):
            frappe.throw(f"{row.ledger} is not allowed in Contra Voucher")

        if row.entry_type == "Debit":
            total_debit += row.ledger_amount
            has_debit = True

        elif row.entry_type == "Credit":
            total_credit += row.ledger_amount
            has_credit = True

        else:
            frappe.throw("Entry Type must be Debit or Credit")

    if not has_debit or not has_credit:
        frappe.throw("Contra Voucher must contain both Debit and Credit entries")

    if round(total_debit, 2) != round(total_credit, 2):
        frappe.throw(
            f"Debit ({total_debit}) and Credit ({total_credit}) must be equal"
        )
def build_ledger_xml(doc):
    xml = ""

    for row in doc.voucher_ledger_entry:
        amount = abs(row.ledger_amount)

        if row.entry_type == "Debit":
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>-{amount}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
"""

        else:  # Credit
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <AMOUNT>{amount}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
"""

    return xml
def push_to_tally(doc, action):
    company, TALLY_URL = get_active_tally_config()

    if not doc.voucher_number:
        frappe.throw("Voucher number is required")

    if not doc.date:
        frappe.throw("Date is required")

    validate_contra_entries(doc)
    ledger_xml = build_ledger_xml(doc)

    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")

    xml = f"""
<ENVELOPE>
    <HEADER>
        <TALLYREQUEST>Import Data</TALLYREQUEST>
    </HEADER>
    <BODY>
        <IMPORTDATA>
            <REQUESTDESC>
                <REPORTNAME>Vouchers</REPORTNAME>
                <STATICVARIABLES>
                    <SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
                </STATICVARIABLES>
            </REQUESTDESC>
            <REQUESTDATA>
                <TALLYMESSAGE>
                    <VOUCHER VCHTYPE="Contra" ACTION="{action}">
                        <DATE>{xml_date}</DATE>
                        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
                        <NARRATION>{doc.narration or ""}</NARRATION>
                        {ledger_xml}
                    </VOUCHER>
                </TALLYMESSAGE>
            </REQUESTDATA>
        </IMPORTDATA>
    </BODY>
</ENVELOPE>
"""

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )

    doc.db_set("tally_response", response.text, update_modified=False)
def delete_from_tally(doc):
    company, TALLY_URL = get_active_tally_config()
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    xml = f"""
<ENVELOPE>
    <HEADER>
        <TALLYREQUEST>Import Data</TALLYREQUEST>
    </HEADER>
    <BODY>
        <IMPORTDATA>
            <REQUESTDESC>
                <REPORTNAME>Vouchers</REPORTNAME>
                <STATICVARIABLES>
                    <SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
                </STATICVARIABLES>
            </REQUESTDESC>
            <REQUESTDATA>
                <TALLYMESSAGE>
                    <VOUCHER
                        DATE="{xml_date}"
                        VCHTYPE="Contra"
                        ACTION="Delete"
                        VOUCHERNUMBER="{doc.voucher_number}">
                    </VOUCHER>
                </TALLYMESSAGE>
            </REQUESTDATA>
        </IMPORTDATA>
    </BODY>
</ENVELOPE>
"""

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )

    doc.db_set("tally_response", response.text, update_modified=False)
