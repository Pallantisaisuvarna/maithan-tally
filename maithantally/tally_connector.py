import requests
import frappe
from datetime import datetime
from frappe.utils import get_url


def validate_contra_ledgers(ledger_name):
    parent = frappe.db.get_value("Ledger", ledger_name, "parent_ledger")
    allowed = ["Bank Accounts", "Cash-in-Hand"]
    return parent in allowed


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



def create_contra_voucher(doc, method):
    frappe.logger().info(doc.as_dict())
    company, TALLY_URL = get_active_tally_config()
    if not doc.from_ledger:
        frappe.throw("From Ledger is required")
    if not doc.to_ledger:
        frappe.throw("To Ledger is required")
    if not doc.ledger_amount:
        frappe.throw("Amount is required")
    if not doc.voucher_number:
        frappe.throw("Voucher Number is required")
    if not doc.date:
        frappe.throw("Voucher Date is required")
    from_ledger = doc.from_ledger
    to_ledger = doc.to_ledger
    amount = abs(doc.ledger_amount)
    if not validate_contra_ledgers(from_ledger):
        frappe.throw(f"'{from_ledger}' is NOT allowed in Contra (only Cash/Bank allowed).")
    if not validate_contra_ledgers(to_ledger):
        frappe.throw(f"'{to_ledger}' is NOT allowed in Contra (only Cash/Bank allowed).")
    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")
    xml = f"""
    <ENVELOPE>
        <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
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
                        <VOUCHERTYPENAME>Contra</VOUCHERTYPENAME>
                        <DATE>{xml_date}</DATE>
                        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
                        <NARRATION>{doc.narration or ""}</NARRATION>
                        <ALLLEDGERENTRIES.LIST>
                            <LEDGERNAME>{to_ledger}</LEDGERNAME>
                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                            <AMOUNT>{amount}</AMOUNT>
                        </ALLLEDGERENTRIES.LIST>
                        <ALLLEDGERENTRIES.LIST>
                            <LEDGERNAME>{from_ledger}</LEDGERNAME>
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

    frappe.logger().info("Generated XML for Tally:")
    frappe.logger().info(xml)

    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers)

        frappe.logger().info("Tally Response:")
        frappe.logger().info(response.text)

        doc.db_set("tally_response", response.text)
        doc.db_set("voucher_number", doc.voucher_number)

    except Exception as e:
        frappe.logger().error("Tally Error:")
        frappe.logger().error(str(e))
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)

def delete_contra_voucher(doc, method):
    frappe.logger().info(doc.as_dict())
    if not doc.date:
        frappe.throw("Date is required")
    if not doc.voucher_number:
        frappe.throw("Voucher Number is required")
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
                        VCHTYPE="Contra" 
                        ACTION="Delete">
                    </VOUCHER>
                </TALLYMESSAGE>
            </DATA>
        </BODY>
    </ENVELOPE>
    """
    frappe.logger().info("Generated XML for Tally (Delete):")
    frappe.logger().info(xml)
    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers)
        frappe.logger().info("Tally Response:")
        frappe.logger().info(response.text)
        doc.db_set("tally_response", response.text)
    except Exception as e:
        frappe.logger().error("Tally Error:")
        frappe.logger().error(str(e))
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)
