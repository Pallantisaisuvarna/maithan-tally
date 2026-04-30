import frappe
import requests
from lxml import etree
import re
from io import BytesIO
from frappe.utils import get_url
import xml.sax.saxutils as saxutils

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
    company, TALLY_URL = get_active_tally_config()
    
    # CRITICAL CLOUD FIX: Added <STATICVARIABLES> block to provide Company Context
    xml_request = f"""<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>EXPORT</TALLYREQUEST>
            <TYPE>COLLECTION</TYPE>
            <ID>LEDGERLIST</ID>
        </HEADER>
        <BODY>
            <DESC>
                <STATICVARIABLES>
                    <SVCURRENTCOMPANY>{saxutils.escape(company)}</SVCURRENTCOMPANY>
                    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                </STATICVARIABLES>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="LEDGERLIST" ISINITIALIZE="Yes">
                            <TYPE>Ledger</TYPE>
                            <FETCH>Name, Parent</FETCH>
                        </COLLECTION>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""

    try:
        # Increased timeout to 60 for Cloud latency
        response = requests.post(TALLY_URL, data=xml_request, timeout=60)
        response.raise_for_status()

        clean_xml = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", response.text)
        tree = BytesIO(clean_xml.encode("utf-8"))

        inserted_ledgers = [] 
        
        # PERFORMANCE FIX: Load existing names into a set to avoid thousands of DB queries
        existing_ledgers = set(frappe.db.get_all("Ledger", pluck="ledger_name"))

        for event, ledger in etree.iterparse(tree, events=("end",), recover=True):
            if ledger.tag.upper().endswith("LEDGER"):
                # Use findtext to avoid errors if tags are missing
                name = ledger.get("NAME") or ledger.findtext("NAME")
                parent = ledger.findtext("PARENT") or ""

                if not name or name in existing_ledgers:
                    continue

                doc = frappe.get_doc({
                    "doctype": "Ledger",
                    "ledger_name": name,
                    "parent_ledger": parent
                })
                doc.insert(ignore_permissions=True)
                inserted_ledgers.append(name)
                
                # Update local set to prevent duplicate processing in same loop
                existing_ledgers.add(name)

        # BATCH FIX: Commit only once after the loop finishes
        if inserted_ledgers:
            frappe.db.commit()

        return inserted_ledgers  

    except Exception as e:
        frappe.logger().error(f"Error fetching/parsing ledgers: {e}")
        return {"error": str(e)}