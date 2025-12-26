import requests
from lxml import etree
import re
import frappe
from datetime import datetime
import io
import xml.sax.saxutils as saxutils

def get_frappe_ledger(tally_name):
    
    if not tally_name:
        return None
        
    if frappe.db.exists("Ledger", tally_name):
        return tally_name
    words = tally_name.split()
    if len(words) > 1:
        test_name = f"{words[0]} & {' '.join(words[1:])}"
        if frappe.db.exists("Ledger", test_name):
            return test_name
        test_name_2 = tally_name.replace(" ", " & ")
        if frappe.db.exists("Ledger", test_name_2):
            return test_name_2

    return tally_name

def sync_contra_vouchers():
    tally_url = "http://192.168.1.48:9000"
    company_name = "Dummy Company" 
    
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
        response = requests.post(tally_url, data=tally_payload, timeout=30)
        raw_xml = response.content.decode("utf-8", errors="ignore")
    except Exception as e:
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
    
    tally_vouchers_seen = set()

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
                if not lname or amt == 0: continue

                ledger_rows.append({
                    "ledger": lname,
                    "entry_type": "Debit" if amt < 0 else "Credit",
                    "ledger_amount": abs(amt)
                })

            if len(ledger_rows) < 2: continue

            doctype = voucher_map[v_type_tally]
            tally_vouchers_seen.add((v_num, v_type_tally))

            existing = frappe.db.exists(doctype, {"voucher_number": v_num, "voucher_type": v_type_tally})
            
            if existing:
                doc = frappe.get_doc(doctype, existing)
                doc.date = v_date
                doc.narration = v_narration
                doc.set("voucher_ledger_entry", [])
                for row in ledger_rows:
                    doc.append("voucher_ledger_entry", row)
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
            doc.save(ignore_permissions=True)
            
        except Exception as e:
            frappe.log_error(f"Tally Sync Error: Voucher {v_num}", str(e))
            continue

    
    for v_tally_name, doctype_frappe in voucher_map.items():
        local_docs = frappe.get_all(doctype_frappe, 
                                   filters={"is_pushed_to_tally": 1, "voucher_type": v_tally_name}, 
                                   fields=["name", "voucher_number"])
        for d in local_docs:
            if (d.voucher_number.upper(), v_tally_name) not in tally_vouchers_seen:
                frappe.delete_doc(doctype_frappe, d.name, ignore_permissions=True)

    frappe.db.commit()