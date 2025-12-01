import requests
import frappe
from datetime import datetime
from frappe.utils import get_url



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



def send_to_tally(doc, method):
    frappe.logger().info(doc.as_dict())
    company,TALLY_URL=get_active_tally_config()

    if not doc.date:
        frappe.throw("Date is required")

    if not doc.from_ledger:
        frappe.throw("From Ledger is required")

    if not doc.to_ledger:
        frappe.throw("To Ledger is required")

    if not doc.ledger_amount:
        frappe.throw("Amount is required")

    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%d-%b-%Y")

   
    from_ledger = doc.from_ledger
    to_ledger = doc.to_ledger
    amount = doc.ledger_amount

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
        <VOUCHER VCHTYPE="Journal" ACTION="Create">

        <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
        <DATE>{xml_date}</DATE>
        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
        <NARRATION>{doc.narration or ""}</NARRATION>
        <PARTYLEDGERNAME>{to_ledger}</PARTYLEDGERNAME>

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

    frappe.logger().info(xml)

    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml, headers=headers)
        doc.db_set("tally_response", response.text)

    except Exception as e:
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)


def delete_journal_voucher(doc, method):
    frappe.logger().info(doc.as_dict())


    if not doc.date:
        frappe.throw("Date is required")
    if not doc.voucher_number:
        frappe.throw("Voucher Number is required")
    company,TALLY_URL=get_active_tally_config()

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
                        VCHTYPE="Journal" 
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
