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
        frappe.throw(
            f'No Active Tally Configuration found.<br>'
            f'<a href="{config_url}" target="_blank"><b>Click here to activate</b></a>'
        )
    return config[0].company, config[0].url

def send_to_tally(doc, method):
    company, TALLY_URL = get_active_tally_config()

    if not doc.date or not doc.from_ledger or not doc.to_ledger or not doc.items:
        frappe.throw("All fields (Date, From Ledger, To Ledger, Items) are required")

    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")

  
    inventory_xml = ""
    total_amount = 0
    for item in doc.items:
        uom = item.uom or ""
        inventory_xml += f"""
        <ALLINVENTORYENTRIES.LIST>
            <STOCKITEMNAME>{item.item_name}</STOCKITEMNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <ACTUALQTY>{item.actual_quantity} {uom}</ACTUALQTY>
            <BILLEDQTY>{item.billed_quantity} {uom}</BILLEDQTY>
            <RATE>{item.rate}</RATE>
            <AMOUNT>{item.amount}</AMOUNT>
            <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>{doc.to_ledger}</LEDGERNAME>
                <AMOUNT>{item.amount}</AMOUNT>
            </ACCOUNTINGALLOCATIONS.LIST>
        </ALLINVENTORYENTRIES.LIST>
        """
        total_amount += float(item.amount)


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
     <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
        <DATE>{xml_date}</DATE>
        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>
        <PARTYNAME>{doc.from_ledger}</PARTYNAME>
        <PARTYLEDGERNAME>{doc.from_ledger}</PARTYLEDGERNAME>
        <VCHENTRYMODE>Item Invoice</VCHENTRYMODE>

        {inventory_xml}

        <LEDGERENTRIES.LIST>
            <LEDGERNAME>{doc.from_ledger}</LEDGERNAME>
            <AMOUNT>-{total_amount}</AMOUNT>
        </LEDGERENTRIES.LIST>
     </VOUCHER>
    </TALLYMESSAGE>
   </REQUESTDATA>
  </IMPORTDATA>
 </BODY>
</ENVELOPE>
"""

    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers)
        doc.db_set("tally_response", response.text)
    except Exception as e:
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)






def delete_sales_voucher(doc, method):
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
                        VCHTYPE="Sales" 
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
