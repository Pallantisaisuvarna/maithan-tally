import frappe
from datetime import datetime
from frappe.utils import get_url
import requests


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


def send_to_tally(doc, method=None):

    company, TALLY_URL = get_active_tally_config()

    required_fields = ["date", "credit_ledger", "debit_ledger", "items", "order_due_date"]
    for field in required_fields:
        if not getattr(doc, field, None):
            frappe.throw(f"Field '{field}' is required")

    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")
    credit_ledger = doc.credit_ledger
    debit_ledger = doc.debit_ledger

    parent_from = frappe.db.get_value("Ledger", credit_ledger, "parent_ledger")
    parent_to=frappe.db.get_value("Ledger",debit_ledger,"parent_ledger")
    if parent_to != "Purchase Accounts":
        frappe.throw("Debit Ledger must be under 'Purchase Account'")

    total_amount = 0
    inventory_xml = ""
    order_due_date_str = datetime.strptime(str(doc.order_due_date), '%Y-%m-%d').strftime('%Y%m%d')

    for item in doc.items:
        uom = item.uom or ""
        item_rate = float(item.rate)
        item_amount = float(item.amount)

        inventory_xml += f"""
        <ALLINVENTORYENTRIES.LIST>
            <STOCKITEMNAME>{item.item_name}</STOCKITEMNAME>
            <RATE>{item_rate:.2f}</RATE>
            <AMOUNT>{item_amount:.2f}</AMOUNT>
            <ACTUALQTY>{item.actual_quantity} {uom}</ACTUALQTY>
            <BILLEDQTY>{item.billed_quantity} {uom}</BILLEDQTY>
            <ORDERDUEDATE>{order_due_date_str}</ORDERDUEDATE>
            <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>{credit_ledger}</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>{item_amount:.2f}</AMOUNT>
            </ACCOUNTINGALLOCATIONS.LIST>
        </ALLINVENTORYENTRIES.LIST>
        """

        total_amount += item_amount

    voucher_number = str(doc.voucher_number)
    reference = doc.order_no
    customer_amount_positive = f"{total_amount:.2f}"

    xml_data = f"""
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
                    <TALLYMESSAGE xmlns:UDF="TallyUDF">
                        <VOUCHER VCHTYPE="Purchase Order" ACTION="Create">
                            <DATE>{xml_date}</DATE>
                            <VOUCHERTYPENAME>Purchase Order</VOUCHERTYPENAME>
                            <VOUCHERNUMBER>{voucher_number}</VOUCHERNUMBER>
                            <PARTYNAME>{debit_ledger}</PARTYNAME>
                            <PARTYLEDGERNAME>{debit_ledger}</PARTYLEDGERNAME>
                            <REFERENCE>{reference}</REFERENCE>
                            <NARRATION>{doc.narration}</NARRATION>
                            <ORDERNO>{doc.order_no}</ORDERNO>

                            {inventory_xml}

                            <LEDGERENTRIES.LIST>
                                <LEDGERNAME>{debit_ledger}</LEDGERNAME>
                                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                                <AMOUNT>{customer_amount_positive}</AMOUNT>
                            </LEDGERENTRIES.LIST>

                        </VOUCHER>
                    </TALLYMESSAGE>
                </REQUESTDATA>
            </IMPORTDATA>
        </BODY>
    </ENVELOPE>
    """

    xml = xml_data

    frappe.logger().info("Generated XML for Tally (Purchase Order):")
    frappe.logger().info(xml)

    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers, timeout=10)

        frappe.logger().info("Tally Response:")
        frappe.logger().info(response.text)

        doc.db_set("tally_response", response.text)

        return response.text

    except requests.exceptions.RequestException as e:
        frappe.logger().error("Tally Error:")
        frappe.logger().error(str(e))
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)
        frappe.throw(f"Error sending data to Tally: {e}")



def delete_purchase_order(doc, method):
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
                        VCHTYPE="Purchase Order" 
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
