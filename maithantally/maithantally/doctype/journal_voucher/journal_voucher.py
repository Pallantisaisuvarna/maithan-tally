import requests
import frappe
from frappe.model.document import Document
from datetime import datetime


class JournalVoucher(Document):

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
def validate_journal_entries(doc):

    if not doc.voucher_ledger_entry or len(doc.voucher_ledger_entry) < 2:
        frappe.throw("Journal Voucher must have at least two ledger entries")

    total_debit = 0
    total_credit = 0

    for row in doc.voucher_ledger_entry:

        if not row.ledger:
            frappe.throw("Ledger is mandatory")

        if row.entry_type not in ("Debit", "Credit"):
            frappe.throw("Entry Type must be Debit or Credit")

        if not row.ledger_amount or row.ledger_amount <= 0:
            frappe.throw("Ledger Amount must be greater than zero")

        if row.entry_type == "Debit":
            total_debit += row.ledger_amount
        else:
            total_credit += row.ledger_amount

    if round(total_debit, 2) != round(total_credit, 2):
        frappe.throw(
            f"Debit ({total_debit}) and Credit ({total_credit}) must be equal"
        )
def build_ledger_xml(doc):
    xml = ""

    for row in doc.voucher_ledger_entry:
        amt = abs(row.ledger_amount)

        if row.entry_type == "Debit":
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>-{amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
"""
        else:  # Credit
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{row.ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <AMOUNT>{amt}</AMOUNT>
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

    validate_journal_entries(doc)
    ledger_xml = build_ledger_xml(doc)

    create_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")
    alter_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

    if action == "Create":
        voucher_block = f"""
<VOUCHER VCHTYPE="Journal" ACTION="Create">
    <DATE>{create_date}</DATE>
    <EFFECTIVEDATE>{create_date}</EFFECTIVEDATE>
    <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
    <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
    <NARRATION>{doc.narration or ""}</NARRATION>
    {ledger_xml}
</VOUCHER>
"""
    else:
        voucher_block = f"""
<VOUCHER VCHTYPE="Journal"
         ACTION="Alter"
         DATE="{alter_date}"
         TAGNAME="Voucher Number"
         TAGVALUE="{doc.voucher_number}">
    <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
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
    <VOUCHER VCHTYPE="Journal"
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

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )

    doc.db_set("tally_response", response.text, update_modified=False)
