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

    if not doc.date or not doc.credit_ledger or not doc.debit_ledger or not doc.items:
        frappe.throw("All fields (Date, Credit Ledger, Debit Ledger, Items) are required")

    parent_debit = frappe.db.get_value("Ledger", doc.debit_ledger, "parent_ledger")
    parent_credit = frappe.db.get_value("Ledger", doc.credit_ledger, "parent_ledger")

    if parent_debit != "Purchase Accounts":
        frappe.throw("Debit Ledger must be under <b>Purchase Accounts</b>")


    xml_date = datetime.strptime(str(doc.date), "%Y-%m-%d").strftime("%Y%m%d")


    inventory_xml = ""
    total_amount = 0

    for item in doc.items:
        uom = item.uom or ""
        rate_with_uom = f"{item.rate}/{uom}" if uom else f"{item.rate}"

        inventory_xml += f"""
        <ALLINVENTORYENTRIES.LIST>
            <STOCKITEMNAME>{item.item_name}</STOCKITEMNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <ACTUALQTY>{item.actual_quantity} {uom}</ACTUALQTY>
            <BILLEDQTY>{item.billed_quantity} {uom}</BILLEDQTY>
            <RATE>{rate_with_uom}</RATE>
            <AMOUNT>{item.amount}</AMOUNT>

            <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>{doc.debit_ledger}</LEDGERNAME>
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
     <VOUCHER VCHTYPE="Purchase" ACTION="Create" OBJVIEW="Invoice Voucher View">

        <DATE>{xml_date}</DATE>
        <VOUCHERTYPENAME>{doc.voucher_type}</VOUCHERTYPENAME>
        <VOUCHERNUMBER>{doc.voucher_number}</VOUCHERNUMBER>

        <PARTYNAME>{doc.credit_ledger}</PARTYNAME>
        <PARTYLEDGERNAME>{doc.credit_ledger}</PARTYLEDGERNAME>

        <VCHENTRYMODE>Item Invoice</VCHENTRYMODE>
        <NARRATION>{doc.narration}</NARRATION>

        {inventory_xml}

        <!-- CREDIT PARTY -->
        <LEDGERENTRIES.LIST>
            <LEDGERNAME>{doc.credit_ledger}</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
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



def delete_purchase_voucher(doc, method):
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
           VCHTYPE="Purchase"
           ACTION="Delete">
       </VOUCHER>
     </TALLYMESSAGE>
   </DATA>
 </BODY>
</ENVELOPE>
"""

    try:
        headers = {"Content-Type": "text/xml"}
        response = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers)

        doc.db_set("tally_response", response.text)

    except Exception as e:
        doc.db_set("tally_response", f"ERROR: {str(e)}", update_modified=False)
