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
        if not self.has_value_changed(
            ["credit_ledger", "debit_ledger", "ledger_amount", "date", "narration"]
        ):
            return
        push_to_tally(self, action="Alter")

    def on_trash(self):
        delete_from_tally(self)

    def has_value_changed(self, fields):
        before = self.get_doc_before_save()
        if not before:
            return False
        for field in fields:
            old = before.get(field)
            new = self.get(field)
            if hasattr(old, "strftime"):
                old = old.strftime("%Y-%m-%d")
            if hasattr(new, "strftime"):
                new = new.strftime("%Y-%m-%d")
            if old != new:
                return True
        return False





def validate_contra_ledgers(ledger_name):
    parent = frappe.db.get_value("Ledger", ledger_name, "parent_ledger")
    return parent in ["Bank Accounts", "Cash-in-Hand"]


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





def push_to_tally(doc, action):
    company, TALLY_URL = get_active_tally_config()
    if not doc.debit_ledger:
        frappe.throw("From ledger is required")
    if not doc.credit_ledger:
        frappe.throw("To ledger is required")
    if not doc.ledger_amount:
        frappe.throw("Ledger amount is reqquired")
    if not doc.voucher_number:
        frappe.throw("Voucher number is required")
    if not doc.date:
        frappe.throw("date is required")
    if not validate_contra_ledgers(doc.debit_ledger):
        frappe.throw(f"'{doc.debit_ledger}' is NOT allowed in Contra (only Cash/Bank allowed).")
    if not validate_contra_ledgers(doc.credit_ledger):
        frappe.throw(f"'{doc.credit_ledger}' is NOT allowed in Contra (only Cash/Bank allowed).")

    amount = abs(doc.ledger_amount)

    if action == "Create":
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
                    <VOUCHER VCHTYPE="Contra" ACTION="Create">
                        <DATE>{xml_date}</DATE>
                        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
                        <NARRATION>{doc.narration or ""}</NARRATION>
                        <ALLLEDGERENTRIES.LIST>
                            <LEDGERNAME>{doc.credit_ledger}</LEDGERNAME>
                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                            <AMOUNT>{amount}</AMOUNT>
                        </ALLLEDGERENTRIES.LIST>
                        <ALLLEDGERENTRIES.LIST>
                            <LEDGERNAME>{doc.debit_ledger}</LEDGERNAME>
                            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                            <AMOUNT>-{amount}</AMOUNT>
                        </ALLLEDGERENTRIES.LIST>
                    </VOUCHER>
                </TALLYMESSAGE>
            </REQUESTDATA>
        </IMPORTDATA>
    </BODY>
</ENVELOPE>
"""
    else:
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
                    DATE="{xml_date}"
                    TAGNAME="Voucher Number"
                    TAGVALUE="{doc.voucher_number}"
                    ACTION="{action}"
                    VCHTYPE="Contra">
                    <NARRATION>{doc.narration or ""}</NARRATION>
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{doc.credit_ledger}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <AMOUNT>{amount}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{doc.debit_ledger}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <AMOUNT>-{amount}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
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
                    DATE="{xml_date}"
                    TAGNAME="Voucher Number"
                    TAGVALUE="{doc.voucher_number}"
                    ACTION="Delete"
                    VCHTYPE="Contra">
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>
"""
    try:
        response = requests.post(
            TALLY_URL,
            data=xml.encode("utf-8"),
            headers={"Content-Type": "text/xml"}
        )
        doc.db_set("tally_response", response.text, update_modified=False)
    except Exception as e:
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)
