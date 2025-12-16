import requests
from lxml import etree
import re
from datetime import datetime, timedelta, date # Import date and timedelta
import io
import frappe
from frappe.utils import flt, nowdate, getdate # Keep nowdate and getdate

# NOTE: This function MUST be executed using the 'bench execute' command.

def sync_vouchers_from_tally_frappe_orm():
    """
    Fetches Vouchers from Tally using a defined date range, aggregates D/C into a 
    single transaction, and performs CUD operations using Frappe ORM functions.
    """
    
    # ---------------- CONFIGURATION & DATE RANGE ----------------
    tally_url = "http://192.168.1.3:9000/" 

    # --- DATE RANGE FIX: Use standard Python datetime manipulation ---
    # Get today's date using frappe.utils.getdate() or datetime.now().date()
    today = getdate() 
    
    # Define a broad date range (e.g., current day +/- 1 year)
    # This should return a date object, safe for consistency.
    from_date = today - timedelta(days=365) # Go back one year
    to_date = today + timedelta(days=365)   # Go forward one year
    
    # Format dates as YYYYMMDD string for Tally
    tally_from_date = from_date.strftime("%Y%m%d")
    tally_to_date = to_date.strftime("%Y%m%d")


    VCHTYPE_DOCTYPE_MAP = {
        "Payment": "Payment Voucher",
        "Receipt": "Receipt Voucher",
        "Journal": "Journal Voucher",
        "Contra": "Contra Voucher"
    }
    
    # --- Tally Payload (Includes date range variables SVFROMDATE/SVTODATE) ---
    tally_payload = f"""<ENVELOPE>
      <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>VoucherList</ID></HEADER>
      <BODY><DESC><STATICVARIABLES>
            <SVCURRENTCOMPANY>Dummy Company</SVCURRENTCOMPANY>
            <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            <SVFROMDATE>{tally_from_date}</SVFROMDATE>
            <SVTODATE>{tally_to_date}</SVTODATE>
        </STATICVARIABLES>
      <TDL><TDLMESSAGE><COLLECTION NAME="VoucherList" ISMODIFY="No"><TYPE>Voucher"><FETCH>
             VOUCHERNUMBER,DATE,VCHTYPE,VOUCHERTYPENAME,NARRATION,
             ALLLEDGERENTRIES.LIST/LEDGERNAME,ALLLEDGERENTRIES.LIST/AMOUNT
          </FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY>
    </ENVELOPE>"""
    
    # ---------------- HELPER FUNCTIONS (No Changes needed here) ----------------
    def clean_xml_text(text):
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
        text = re.sub(r'&#\d+;', '', text)
        text = text.replace('→', '->').replace('₹', 'Rs.').replace('✓', 'v')
        return text

    def safe_str(s):
        if s is None: return ""
        s = str(s).replace('→', '->').replace('₹', 'Rs.').replace('✓', 'v')
        return str(s).strip() 

    def elem_text(elem, name):
        if elem is None: return None
        res = elem.xpath(f".//*[local-name()='{name}']/text()")
        return res[0].strip() if res else None

    def parse_date(tally_date):
        if not tally_date: return None
        s = str(tally_date).strip()
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try: return datetime.strptime(s, fmt).date()
            except: pass
        return None

    def parse_float(val):
        return flt(str(val).replace(',', '').strip())


    # ---------------- FETCH XML ----------------
    print(f"[TALLY SYNC] Requesting data from {tally_from_date} to {tally_to_date}...")
    try:
        response = requests.post(tally_url, data=tally_payload, timeout=60)
        response.raise_for_status()
        raw_xml = response.content.decode('utf-8', errors='ignore')
        print(f"[TALLY SYNC] XML fetched successfully from {tally_url}")
    except requests.exceptions.RequestException as e:
        frappe.log_error(title="Tally Request Failed", message=f"Could not connect to Tally URL: {tally_url}. Error: {e}")
        print(f"[ERROR] Tally connection failed: {e}")
        return
    
    # --- FRAPPE DB INITIALIZATION & EXISTING DOCS FETCH (Using Frappe ORM) ---
    existing_frappe_docs = {}
    
    for doctype in VCHTYPE_DOCTYPE_MAP.values():
        existing_frappe_docs[doctype] = {}
        docs = frappe.get_all(
            doctype,
            fields=["name", "voucher_number", "voucher_type", "date", "debit_ledger", "credit_ledger", "ledger_amount", "narration"], 
            ignore_permissions=True
        )
        for doc in docs:
            # Unique Key: (Vch No, Vch Type, Date)
            key_tuple = (doc.voucher_number, doc.voucher_type, str(doc.date) if doc.date else "")
            existing_frappe_docs[doctype][key_tuple] = doc # Store the full Frappe doc object

    
    # ---------------- PARSE & SYNC (AGGREGATION - ONE ROW PER VOUCHER) ----------------
    cleaned_xml = clean_xml_text(raw_xml)
    bytes_io = io.BytesIO(cleaned_xml.encode("utf-8"))
    
    # Use a set to track processed documents to handle the deletion logic correctly
    seen_tally_keys = {dt: set() for dt in VCHTYPE_DOCTYPE_MAP.values()}


    try:
        context = etree.iterparse(bytes_io, events=("end",), recover=True)
        for event, elem in context:
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local.upper() != "VOUCHER":
                elem.clear()
                continue

            vchtype_attr = elem.get("VCHTYPE")
            vchtype_child = elem_text(elem, "VOUCHERTYPENAME")
            vchnum_child = elem_text(elem, "VOUCHERNUMBER")
            narration = safe_str(elem_text(elem, "NARRATION"))
            date_val = parse_date(elem_text(elem, "DATE"))

            vch_number = safe_str(vchnum_child or "")
            vch_type = safe_str(vchtype_attr or vchtype_child or "")
            doctype = VCHTYPE_DOCTYPE_MAP.get(vch_type)
            
            if not doctype or not vch_number:
                elem.clear()
                continue

            ledger_nodes = elem.xpath(".//*[local-name()='ALLLEDGERENTRIES.LIST']") or elem.xpath(".//*[local-name()='LEDGERENTRIES.LIST']")

            # --- 1. Aggregate Tally Entries to Single Frappe Row ---
            debit_ledger, credit_ledger = None, None
            debit_amount, credit_amount = 0.0, 0.0
            
            for ledger in ledger_nodes:
                ledger_name = safe_str(elem_text(ledger, "LEDGERNAME"))
                amount_signed = parse_float(elem_text(ledger, "AMOUNT")) 

                # Positive AMOUNT is Credit, Negative AMOUNT is Debit
                if amount_signed > 0:
                    credit_ledger = ledger_name
                    credit_amount = amount_signed
                elif amount_signed < 0:
                    debit_ledger = ledger_name
                    debit_amount = abs(amount_signed)

            # --- 2. Validation & Data Preparation ---
            if not (debit_ledger and credit_ledger and flt(debit_amount) == flt(credit_amount) and debit_amount != 0):
                elem.clear()
                continue
                
            ledger_amount_abs = debit_amount
            
            current_frappe_key = (vch_number, vch_type, str(date_val) if date_val else "")
            seen_tally_keys[doctype].add(current_frappe_key)
            
            doc_data = {
                "doctype": doctype,
                "voucher_number": vch_number,
                "voucher_type": vch_type,
                "date": date_val,
                "narration": narration,
                "credit_ledger": credit_ledger,
                "debit_ledger": debit_ledger,
                "ledger_amount": ledger_amount_abs,
            }

            print(f"--- [AGGREGATED] Vch: {vch_number} ({doctype}) | D: {debit_ledger}, C: {credit_ledger}, Amt: {ledger_amount_abs}")

            existing_doc = existing_frappe_docs[doctype].get(current_frappe_key)
            
            if existing_doc:
                # --- UPDATE EXISTING DOCUMENT ---
                changed = (str(existing_doc.debit_ledger) != str(debit_ledger) or 
                           str(existing_doc.credit_ledger) != str(credit_ledger) or 
                           flt(existing_doc.ledger_amount) != flt(ledger_amount_abs) or 
                           str(existing_doc.narration) != str(narration) or
                           str(existing_doc.date) != str(date_val))

                if changed:
                    doc = frappe.get_doc(doctype, existing_doc.name) 
                    doc.debit_ledger = debit_ledger
                    doc.credit_ledger = credit_ledger
                    doc.ledger_amount = ledger_amount_abs
                    doc.narration = narration
                    doc.date = date_val
                    doc.save(ignore_permissions=True) 
                    print(f"[UPDATE] Updated {doctype} {existing_doc.name} | Vch: {vch_number}")
                else:
                    print(f"[SKIP] No change detected for {doctype} {existing_doc.name} | Vch: {vch_number}")
                
                del existing_frappe_docs[doctype][current_frappe_key]

            else:
                # --- INSERT NEW DOCUMENT ---
                doc = frappe.get_doc(doc_data)
                try:
                    doc.insert(ignore_permissions=True) 
                    print(f"[INSERT] Inserted {doctype} {doc.name} | Vch: {vch_number}")
                except Exception as insert_e:
                    frappe.log_error(title="Tally Insert Failed", message=f"Voucher: {vch_number}. Data: {doc_data}. Error: {str(insert_e)}")
                    print(f"[ERROR] Failed to insert {vch_number}. Check Frappe Error Log.")

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        # ---------------- DELETE OBSOLETE DOCUMENTS ----------------
        documents_to_delete = []
        for doctype in existing_frappe_docs:
            for key_tuple, doc_obj in existing_frappe_docs[doctype].items():
                 documents_to_delete.append((doctype, doc_obj.name))

        for doctype_name, doc_name in documents_to_delete:
            try:
                frappe.delete_doc(doctype_name, doc_name, ignore_permissions=True)
                print(f"[DELETE] Deleted obsolete {doctype_name} {doc_name}")
            except Exception as delete_e:
                frappe.log_error(title="Tally Delete Failed", message=f"Doc: {doc_name} - {str(delete_e)}")
                
        # ---------------- FINAL COMMIT ----------------
        frappe.db.commit()
        print("[INFO] All vouchers synced to Frappe successfully (Frappe ORM Mode)")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Tally Sync General Error", message=f"An error occurred during sync: {e}")
        print(f"[ERROR] Sync process failed. Rolling back database changes. Error: {e}")