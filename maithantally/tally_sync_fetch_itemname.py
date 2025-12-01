import frappe
import requests
from lxml import etree
import re
from io import BytesIO

TALLY_URL = "http://192.168.1.41:9000"

@frappe.whitelist() 
def fetch_items():
    xml_request = """<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>EXPORT</TALLYREQUEST>
            <TYPE>COLLECTION</TYPE>
            <ID>ITEMLIST</ID>
        </HEADER>
        <BODY>
            <DESC>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="ITEMLIST" ISINITIALIZE="Yes">
                            <TYPE>StockItem</TYPE>
                            <FETCH>Name</FETCH>
                        </COLLECTION>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""

    try:
        response = requests.post(TALLY_URL, data=xml_request)
        response.raise_for_status()

   
        clean_xml = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", response.text)
        tree = BytesIO(clean_xml.encode("utf-8"))

        item_count = 0

        for event, elem in etree.iterparse(tree, events=("end",), recover=True):
            if elem.tag.upper().endswith("STOCKITEM"):
                name = elem.get("NAME")
                if not name:
                    continue

               
                if not frappe.db.exists("Items", {"item_name": name}):
                    doc = frappe.get_doc({
                        "doctype": "Items",
                        "item_name": name
                    })
                    doc.insert(ignore_permissions=True)
                    frappe.db.commit()
                    item_count += 1

        return item_count     

    except Exception as e:
        frappe.logger().error(f"Error fetching/parsing items: {e}")
        return f"Error: {e}"
