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
        push_to_tally(self, action="Alter")
    def on_trash(self):
        if not self.is_pushed_to_tally:
            return
        delete_from_tally(self)




def validate_contra_ledger(ledger):
    parent = frappe.db.get_value("Ledger", ledger, "parent_ledger")
    return parent in ("Cash-in-Hand", "Bank Accounts")


def validate_contra_entries(doc):

    if not doc.voucher_ledger_entry or len(doc.voucher_ledger_entry) < 2:
        frappe.throw("Contra Voucher must have at least two ledger entries")

    total_debit = 0
    total_credit = 0

    for row in doc.voucher_ledger_entry:

        if not row.ledger:
            frappe.throw("Ledger is mandatory")

        if not row.entry_type:
            frappe.throw("Entry Type is mandatory")

        if not row.ledger_amount or row.ledger_amount <= 0:
            frappe.throw("Ledger Amount must be greater than zero")

        if not validate_contra_ledger(row.ledger):
            frappe.throw(f"{row.ledger} is not allowed in Contra Voucher")

        if row.entry_type == "Debit":
            total_debit += row.ledger_amount
        elif row.entry_type == "Credit":
            total_credit += row.ledger_amount
        else:
            frappe.throw("Entry Type must be Debit or Credit")

    if round(total_debit, 2) != round(total_credit, 2):
        frappe.throw(
            f"Debit ({total_debit}) and Credit ({total_credit}) must be equal"
        )




def build_ledger_xml(doc):
    credit_rows = []
    debit_rows = []

    for row in doc.voucher_ledger_entry:
        if row.entry_type == "Credit":
            credit_rows.append(row)
        else:
            debit_rows.append(row)

    ordered_rows = credit_rows + debit_rows
    xml = ""

    for row in ordered_rows:
        amt = abs(row.ledger_amount)

        if row.entry_type == "Credit":
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <AMOUNT>{amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
"""
        else:
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>-{amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
"""

    return xml

def get_active_tally_config():
    config = frappe.db.get_all(
        "Tally Configuration",
        filters={"is_active": 1},
        fields=["company", "url"],
        limit=1
    )

    if not config:
        frappe.throw("No Active Tally Configuration found")
    return config[0].company, config[0].url



def push_to_tally(doc, action):
    company, TALLY_URL = get_active_tally_config()

    validate_contra_entries(doc)
    ledger_xml = build_ledger_xml(doc)

    create_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")
    alter_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    if action == "Create":
        voucher_block = f"""
<VOUCHER VCHTYPE="Contra" ACTION="Create">
    <DATE>{create_date}</DATE>
    <EFFECTIVEDATE>{create_date}</EFFECTIVEDATE>

    <VOUCHERTYPENAME>Contra</VOUCHERTYPENAME>
    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>

    <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
    <NARRATION>{doc.narration or ""}</NARRATION>

    {ledger_xml}
</VOUCHER>
"""
    else:
        voucher_block = f"""
<VOUCHER
    VCHTYPE="Contra"
    ACTION="Alter"
    DATE="{alter_date}"
    TAGNAME="Voucher Number"
    TAGVALUE="{doc.voucher_number}">

    <VOUCHERTYPENAME>Contra</VOUCHERTYPENAME>
    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>

    <NARRATION>{doc.narration or ""}</NARRATION>

    {ledger_xml}
</VOUCHER>
"""

    xml = f"""
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                {voucher_block}
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>
"""

    print(xml)

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )

  
    print(response.text)

    doc.db_set("tally_response", response.text, update_modified=False)




def delete_from_tally(doc):
    

    company, TALLY_URL = get_active_tally_config()
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    xml = f"""
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                <VOUCHER
                    VCHTYPE="Contra"
                    ACTION="Delete"
                    DATE="{xml_date}"
                    TAGNAME="Voucher Number"
                    TAGVALUE="{doc.voucher_number}">
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>
"""

 
    print(xml)

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )

  
    print(response.text)

    doc.db_set("tally_response", response.text, update_modified=False)
