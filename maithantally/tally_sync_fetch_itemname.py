import frappe
import requests
from lxml import etree
import re
from io import BytesIO
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
    return config[0]["company"], config[0]["url"]






@frappe.whitelist() 
def fetch_items():
    company,TALLY_URL=get_active_tally_config()
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

        inserted_items=[]

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
                    inserted_items.append(name)

        return inserted_items

    except Exception as e:
        frappe.logger().error(f"Error fetching/parsing items: {e}")
        return f"Error: {e}"
