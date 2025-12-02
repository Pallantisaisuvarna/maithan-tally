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
def fetch_ledgers():
    company,TALLY_URL=get_active_tally_config()
    xml_request = """<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>EXPORT</TALLYREQUEST>
            <TYPE>COLLECTION</TYPE>
            <ID>LEDGERLIST</ID>
        </HEADER>
        <BODY>
            <DESC>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="LEDGERLIST" ISINITIALIZE="Yes">
                            <TYPE>Ledger</TYPE>
                            <FETCH>Name</FETCH>
                            <FETCH>Parent</FETCH>
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

        inserted_ledgers = []   

        for event, ledger in etree.iterparse(tree, events=("end",), recover=True):
            if ledger.tag.upper().endswith("LEDGER"):
                name = ledger.get("NAME")
                parent_elem = ledger.find(".//PARENT")
                parent = parent_elem.text.strip() if parent_elem is not None else None

                if not name:
                    continue

                if not frappe.db.exists("Ledger", {"ledger_name": name, "parent_ledger": parent}):
                    doc = frappe.get_doc({
                        "doctype": "Ledger",
                        "ledger_name": name,
                        "parent_ledger": parent
                    })
                    doc.insert(ignore_permissions=True)
                    frappe.db.commit()

                    inserted_ledgers.append(name)  

        return inserted_ledgers  

    except Exception as e:
        frappe.logger().error(f"Error fetching/parsing ledgers: {e}")
        return {"error": str(e)}
