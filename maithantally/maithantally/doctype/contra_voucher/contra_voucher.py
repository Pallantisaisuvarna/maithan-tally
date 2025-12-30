import requests
import frappe
from frappe.model.document import Document
from datetime import datetime
import xml.sax.saxutils as saxutils


def get_tally_vch_type(doctype):
    mapping = {
        "Contra Voucher": "Contra",
        "Journal Voucher": "Journal",
        "Receipt Voucher": "Receipt",
        "Payment Voucher": "Payment"
    }
    return mapping.get(doctype, "Contra")

class ContraVoucher(Document):
    def after_insert(self):
        if self.flags.from_pull or self.is_pushed_to_tally:
            return
        self.flags.from_insert = True
        push_to_tally(self, action="Create")
        self.db_set("is_pushed_to_tally", 1, update_modified=False)

    def on_update(self):
        if self.flags.from_pull or self.flags.get("from_insert"):
            return
        if not self.is_pushed_to_tally:
            return
        push_to_tally(self, action="Alter")

    def on_trash(self):
        if not self.is_pushed_to_tally:
            return
        delete_from_tally(self)



def validate_entries(doc):
    """General validation for all voucher types"""
    if not doc.voucher_ledger_entry or len(doc.voucher_ledger_entry) < 2:
        frappe.throw("Voucher must have at least two ledger entries")

    total_debit = 0
    total_credit = 0

    for row in doc.voucher_ledger_entry:
        if not row.ledger or not row.entry_type:
            frappe.throw("Ledger and Entry Type are mandatory")
        if not row.ledger_amount or row.ledger_amount <= 0:
            frappe.throw("Ledger Amount must be greater than zero")

        if row.entry_type == "Debit":
            total_debit += row.ledger_amount
        else:
            total_credit += row.ledger_amount

    if round(total_debit, 2) != round(total_credit, 2):
        frappe.throw(f"Debit ({total_debit}) and Credit ({total_credit}) must be equal")

def build_ledger_xml(doc):
    credit_rows = [row for row in doc.voucher_ledger_entry if row.entry_type == "Credit"]
    debit_rows = [row for row in doc.voucher_ledger_entry if row.entry_type == "Debit"]
    
    ordered_rows = credit_rows + debit_rows
    xml = ""

    for row in ordered_rows:
        amt = abs(row.ledger_amount)
        is_deemed_positive = "No" if row.entry_type == "Credit" else "Yes"
        xml_amt = amt if row.entry_type == "Credit" else f"-{amt}"
        
        xml += f"""
        <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>{saxutils.escape(row.ledger)}</LEDGERNAME>
            <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
            <AMOUNT>{xml_amt}</AMOUNT>
        </ALLLEDGERENTRIES.LIST>"""
    return xml

def get_active_tally_config():
    config = frappe.db.get_all("Tally Configuration", 
                              filters={"is_active": 1}, 
                              fields=["company", "url"], limit=1)
    if not config:
        frappe.throw("No Active Tally Configuration found")
    return config[0].company, config[0].url

def push_to_tally(doc, action):
    company, TALLY_URL = get_active_tally_config()
    vch_type = get_tally_vch_type(doc.doctype)
    
    validate_entries(doc)
    ledger_xml = build_ledger_xml(doc)

    create_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")
    alter_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    if action == "Create":
        voucher_block = f"""
        <VOUCHER VCHTYPE="{vch_type}" ACTION="Create">
            <DATE>{create_date}</DATE>
            <EFFECTIVEDATE>{create_date}</EFFECTIVEDATE>
            <VOUCHERTYPENAME>{vch_type}</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
            <NARRATION>{saxutils.escape(doc.narration or "")}</NARRATION>
            {ledger_xml}
        </VOUCHER>"""
    else:
        # Crucial: Specify VCHTYPE to avoid hitting same number in different types
        voucher_block = f"""
        <VOUCHER VCHTYPE="{vch_type}" ACTION="Alter" DATE="{alter_date}" TAGNAME="Voucher Number" TAGVALUE="{doc.voucher_number}">
            <VOUCHERTYPENAME>{vch_type}</VOUCHERTYPENAME>
            <NARRATION>{saxutils.escape(doc.narration or "")}</NARRATION>
            {ledger_xml}
        </VOUCHER>"""

    xml_payload = f"""
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
                <SVCURRENTCOMPANY>{saxutils.escape(company)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                {voucher_block}
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""

    response = requests.post(TALLY_URL, data=xml_payload.encode("utf-8"), headers={"Content-Type": "text/xml"}, timeout=30)
    doc.db_set("tally_response", response.text, update_modified=False)

def delete_from_tally(doc):
    company, TALLY_URL = get_active_tally_config()
    vch_type = get_tally_vch_type(doc.doctype)
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    xml_payload = f"""
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
                <SVCURRENTCOMPANY>{saxutils.escape(company)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                <VOUCHER VCHTYPE="{vch_type}" ACTION="Delete" DATE="{xml_date}" TAGNAME="Voucher Number" TAGVALUE="{doc.voucher_number}">
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""

    response = requests.post(TALLY_URL, data=xml_payload.encode("utf-8"), headers={"Content-Type": "text/xml"}, timeout=30)
    doc.db_set("tally_response", response.text, update_modified=False)