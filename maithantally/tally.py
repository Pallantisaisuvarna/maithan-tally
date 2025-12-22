import requests
from lxml import etree
import re
import frappe
from datetime import datetime
import io

def is_same_voucher(doc, voucher_date, narration, ledger_rows):
    if doc.date != voucher_date:
        return False
    if (doc.narration or "") != (narration or ""):
        return False
    existing_rows = [
        {
            "ledger": r.ledger,
            "entry_type": r.entry_type,
            "ledger_amount": float(r.ledger_amount)
        }
        for r in doc.voucher_ledger_entry
    ]
    if len(existing_rows) != len(ledger_rows):
        return False
    def normalize(rows):
        return sorted(
            rows,
            key=lambda x: (x["ledger"], x["entry_type"], x["ledger_amount"])
        )
    return normalize(existing_rows) == normalize(ledger_rows)

def sync_contra_vouchers():
    tally_url = "http://192.168.1.61:9000"
    tally_payload = """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>VoucherList</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVCURRENTCOMPANY>Dummy Company</SVCURRENTCOMPANY>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="VoucherList" ISMODIFY="No">
            <TYPE>Voucher</TYPE>
            <FETCH>
              VOUCHERNUMBER,
              DATE,
              VCHTYPE,
              VOUCHERTYPENAME,
              NARRATION,
              ALLLEDGERENTRIES.LIST
            </FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""

    response = requests.post(tally_url, data=tally_payload)
    raw_xml = response.content.decode("utf-8", errors="ignore")

    def clean_xml(text):
        return re.sub(r'[\x00-\x1f]', '', text)

    def elem_text(elem, name):
        res = elem.xpath(".//*[local-name()=$n]/text()", n=name)
        return res[0].strip() if res else ""

    def parse_date(val):
        try:
            return datetime.strptime(val, "%Y%m%d").date()
        except:
            return None

    def parse_amount(val):
        try:
            return float(val)
        except:
            return 0.0

    voucher_map = {
        "Contra": "Contra Voucher",
        "Receipt": "Receipt Voucher",
        "Payment": "Payment Voucher",
        "Journal": "Journal Voucher",
    }

    xml = io.BytesIO(clean_xml(raw_xml).encode("utf-8"))
    tally_vouchers_seen = set()

    for _, voucher in etree.iterparse(xml, events=("end",), tag="VOUCHER", recover=True):
        voucher_number = elem_text(voucher, "VOUCHERNUMBER")
        vch_type = voucher.get("VCHTYPE") or elem_text(voucher, "VOUCHERTYPENAME")

        if not voucher_number or vch_type not in voucher_map:
            voucher.clear()
            continue

        voucher_date = parse_date(elem_text(voucher, "DATE"))
        narration = elem_text(voucher, "NARRATION")
        ledger_rows = []

        ledger_entries = voucher.xpath(".//*[local-name()='ALLLEDGERENTRIES.LIST']")
        for entry in ledger_entries:
            ledger_name = elem_text(entry, "LEDGERNAME")
            amt = parse_amount(elem_text(entry, "AMOUNT"))

            if not ledger_name or amt == 0:
                continue

            if amt < 0:
                ledger_rows.append({
                    "ledger": ledger_name,
                    "entry_type": "Debit",
                    "ledger_amount": abs(amt)
                })
            else:
                ledger_rows.append({
                    "ledger": ledger_name,
                    "entry_type": "Credit",
                    "ledger_amount": amt
                })

        if len(ledger_rows) < 2:
            voucher.clear()
            continue

        doctype = voucher_map[vch_type]
        tally_vouchers_seen.add((voucher_number or "").strip().upper())

        existing = frappe.db.exists(doctype, {"voucher_number": voucher_number})
        if existing:
            doc = frappe.get_doc(doctype, existing)
            if not is_same_voucher(doc, voucher_date, narration, ledger_rows):
                doc.date = voucher_date
                doc.narration = narration
                doc.set("voucher_ledger_entry", [])
                for row in ledger_rows:
                    doc.append("voucher_ledger_entry", row)
                doc.flags.from_pull = True
                doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc({
                "doctype": doctype,
                "voucher_number": voucher_number,
                "voucher_type": vch_type,
                "date": voucher_date,
                "narration": narration,
                "is_pushed_to_tally": 1,
                "voucher_ledger_entry": ledger_rows
            })
            doc.flags.from_pull = True
            doc.insert(ignore_permissions=True)

        voucher.clear()

    frappe.db.commit()

    def normalize_voucher_number(vn):
        return (vn or "").strip().upper()

    tally_vouchers_seen_normalized = {normalize_voucher_number(vn) for vn in tally_vouchers_seen}

    for doctype in voucher_map.values():
        for d in frappe.get_all(doctype, ["name", "voucher_number"]):
            if normalize_voucher_number(d.voucher_number) not in tally_vouchers_seen_normalized:
                frappe.delete_doc(doctype, d.name, ignore_permissions=True)

    frappe.db.commit()
    return None
