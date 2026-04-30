import requests
from lxml import etree
import re
import frappe
from datetime import datetime
import xml.sax.saxutils as saxutils

def get_frappe_ledger(tally_name):
    if not tally_name:
        return None
        
    # Standardize spaces
    clean_name = " ".join(tally_name.split()).strip()
    
    # 1. Try direct match
    if frappe.db.exists("Ledger", clean_name):
        return clean_name
        
    # 2. Handle the common '&' character mismatch (e.g., 'Ventures And Industries' vs 'Ventures & Industries')
    if " and " in clean_name.lower():
        test_name = re.sub(r'(?i)\sand\s', ' & ', clean_name)
        if frappe.db.exists("Ledger", test_name):
            return test_name
            
    # 3. Fallback to SQL 'LIKE' for flexible matching
    match = frappe.db.get_value("Ledger", {"name": ["like", f"%{clean_name}%"]}, "name")
    return match if match else clean_name

def sync_contra_vouchers():
    tally_url = "http://v41066.22055.tallyprimecloud.in:9040/"
    
    # CRITICAL: This must match the Tally Title Bar EXACTLY
    company_name = "Dummy Company" 
    
    # CHUNKING: Requesting 1 month only to prevent 'Memory Access Violation'
    start_date = "20260401"
    end_date = "20260430"
    
    tally_payload = f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>VoucherList</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVCURRENTCOMPANY>{saxutils.escape(company_name)}</SVCURRENTCOMPANY>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        <SVFROMDATE>{start_date}</SVFROMDATE>
        <SVTODATE>{end_date}</SVTODATE>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="VoucherList" ISMODIFY="No">
            <TYPE>Voucher</TYPE>
            <FETCH>VOUCHERNUMBER, DATE, VCHTYPE, VOUCHERTYPENAME, NARRATION, ALLLEDGERENTRIES.LIST</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""

    try:
        # Increased timeout for Tally Cloud stability
        response = requests.post(tally_url, data=tally_payload, timeout=60)
        raw_xml = response.content.decode("utf-8", errors="ignore")
        
        if "<VOUCHER" in raw_xml:
            v_count = raw_xml.count("<VOUCHER")
            print(f"SUCCESS: Found {v_count} vouchers. Starting Import...")
        else:
            print("WARNING: No Vouchers found. Ensure the Company is open in Tally.")
            return
    except Exception as e:
        print(f"CONNECTION ERROR: {str(e)}")
        frappe.log_error("Tally Sync Connection Error", str(e))
        return

    def clean_text(text):
        if not text: return ""
        text = re.sub(r'[\x00-\x1f\x7f-\xff]', '', text)
        text = saxutils.unescape(text)
        return " ".join(text.split()).strip()

    def get_val(elem, tag):
        res = elem.xpath(f".//*[local-name()='{tag}']/text()")
        return clean_text(res[0]) if res else ""

    voucher_map = {
        "Contra": "Contra Voucher",
        "Receipt": "Receipt Voucher",
        "Payment": "Payment Voucher",
        "Journal": "Journal Voucher",
    }

    parser = etree.XMLParser(recover=True)
    root = etree.fromstring(raw_xml.encode("utf-8"), parser=parser)
    tally_vouchers_seen = 0

    for voucher in root.xpath("//VOUCHER"):
        try:
            v_num = get_val(voucher, "VOUCHERNUMBER").upper()
            v_type_tally = voucher.get("VCHTYPE") or get_val(voucher, "VOUCHERTYPENAME")
            
            if not v_num or v_type_tally not in voucher_map:
                continue

            v_date_str = get_val(voucher, "DATE")
            v_date = datetime.strptime(v_date_str, "%Y%m%d").date() if v_date_str else None
            v_narration = get_val(voucher, "NARRATION")
            ledger_rows = []

            for entry in voucher.xpath(".//*[local-name()='ALLLEDGERENTRIES.LIST']"):
                raw_lname = get_val(entry, "LEDGERNAME")
                lname = get_frappe_ledger(raw_lname)
                
                amt = float(get_val(entry, "AMOUNT") or 0)
                if not lname or amt == 0: 
                    continue

                ledger_rows.append({
                    "ledger": lname,
                    "entry_type": "Debit" if amt < 0 else "Credit",
                    "ledger_amount": abs(amt)
                })

            if len(ledger_rows) < 2:
                continue

            doctype = voucher_map[v_type_tally]
            existing = frappe.db.exists(doctype, {"voucher_number": v_num, "voucher_type": v_type_tally})
            
            if existing:
                doc = frappe.get_doc(doctype, existing)
                doc.date = v_date
                doc.narration = v_narration
                doc.set("voucher_ledger_entry", [])
                for row in ledger_rows:
                    doc.append("voucher_ledger_entry", row)
                doc.save(ignore_permissions=True)
            else:
                doc = frappe.get_doc({
                    "doctype": doctype,
                    "voucher_number": v_num,
                    "voucher_type": v_type_tally,
                    "date": v_date,
                    "narration": v_narration,
                    "is_pushed_to_tally": 1,
                    "voucher_ledger_entry": ledger_rows
                })
                doc.flags.from_pull = True
                doc.insert(ignore_permissions=True)

            tally_vouchers_seen += 1
            print(f"Synced {v_type_tally} #{v_num}")
            
        except Exception as e:
            print(f"Error processing voucher: {str(e)}")
            continue

    frappe.db.commit()
    print(f"Import Complete. {tally_vouchers_seen} vouchers synced.")