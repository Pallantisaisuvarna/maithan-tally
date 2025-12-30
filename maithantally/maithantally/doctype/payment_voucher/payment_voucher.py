import requests
import frappe
import xml.sax.saxutils as saxutils
from frappe.model.document import Document
from datetime import datetime
from frappe.utils import get_url

class PaymentVoucher(Document):
    def after_insert(self):
        if self.flags.from_pull or self.is_pushed_to_tally:
            return
            
        self.flags.from_insert = True
        push_to_tally(self, action="Create")
        self.db_set("is_pushed_to_tally", 1, update_modified=False)

    def on_update(self):
        if self.flags.from_pull:
            return
            
        if self.flags.get("from_insert"):
            return
            
        if not self.is_pushed_to_tally:
            return
            
        push_to_tally(self, action="Alter")

    def on_trash(self):
        if not self.is_pushed_to_tally:
            return
        delete_from_tally(self)

def escape_xml(data):
    if data is None:
        return ""
    return saxutils.escape(str(data))

def validate_payment_entries(doc):
    has_cash_or_bank = False
    for row in doc.voucher_ledger_entry:
        parent_ledger = frappe.db.get_value(
            "Ledger",
            row.ledger,
            "parent_ledger"
        )
        if parent_ledger in ("Cash-in-Hand", "Bank Accounts"):
            has_cash_or_bank = True
            break
    if not has_cash_or_bank:
        frappe.throw(
            "Payment Voucher must contain at least one "
            "<b>Cash-in-Hand</b> or <b>Bank Accounts</b> ledger"
        )

def get_active_tally_config():
    config = frappe.db.get_all(
        "Tally Configuration",
        filters={"is_active": 1},
        fields=["company", "url"],
        limit=1
    )
    if not config:
        config_url = get_url("/desk/tally-configuration-")
        frappe.throw(
            f'No Active Tally Configuration found.<br>'
            f'<a href="{config_url}" target="_blank"><b>Click here to activate</b></a>'
        )
    return config[0].company, config[0].url

def build_payment_ledger_xml(doc):
    xml = ""
    for row in doc.voucher_ledger_entry:
        amt = abs(row.ledger_amount)
        safe_ledger = escape_xml(row.ledger)
        if row.entry_type == "Debit":
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{safe_ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>-{amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>"""
        else:
            xml += f"""
<ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>{safe_ledger}</LEDGERNAME>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <AMOUNT>{amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>"""
    return xml

def push_to_tally(doc, action):
    company, TALLY_URL = get_active_tally_config()
    validate_payment_entries(doc)

    if not doc.date or not doc.voucher_ledger_entry:
        frappe.throw("Date and Ledger Entries are mandatory")

    ledger_xml = build_payment_ledger_xml(doc)
    safe_company = escape_xml(company)
    safe_narration = escape_xml(doc.narration)
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")
    vch_type = "Payment"

    if action == "Create":
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
                    <SVCURRENTCOMPANY>{safe_company}</SVCURRENTCOMPANY>
                </STATICVARIABLES>
            </REQUESTDESC>
            <REQUESTDATA>
                <TALLYMESSAGE xmlns:UDF="TallyUDF">
                    <VOUCHER VCHTYPE="{vch_type}" ACTION="Create">
                        <VOUCHERTYPENAME>{vch_type}</VOUCHERTYPENAME>
                        <DATE>{xml_date}</DATE>
                        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
                        <NARRATION>{safe_narration}</NARRATION>
                        {ledger_xml}
                    </VOUCHER>
                </TALLYMESSAGE>
            </REQUESTDATA>
        </IMPORTDATA>
    </BODY>
</ENVELOPE>"""
    else:
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
                <SVCURRENTCOMPANY>{safe_company}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER
                    DATE="{xml_date}"
                    TAGNAME="Voucher Number"
                    TAGVALUE="{doc.voucher_number}"
                    ACTION="Alter"
                    VCHTYPE="{vch_type}">
                    <NARRATION>{safe_narration}</NARRATION>
                    {ledger_xml}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )
    doc.db_set("tally_response", response.text, update_modified=False)

def delete_from_tally(doc):
    company, TALLY_URL = get_active_tally_config()
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")
    safe_company = escape_xml(company)

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
                <SVCURRENTCOMPANY>{safe_company}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER
                    DATE="{xml_date}"
                    TAGNAME="Voucher Number"
                    TAGVALUE="{doc.voucher_number}"
                    ACTION="Delete"
                    VCHTYPE="Payment">
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""

    response = requests.post(
        TALLY_URL,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "text/xml"}
    )
    doc.db_set("tally_response", response.text, update_modified=False)