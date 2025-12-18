import requests
from lxml import etree
import re
import frappe
from datetime import datetime
import io


def sync_contra_vouchers():
    tally_url = "http://192.168.1.40:9000/"

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

        debit_ledger = None
        credit_ledger = None
        amount = 0.0

        ledger_entries = voucher.xpath(".//*[local-name()='ALLLEDGERENTRIES.LIST']")

        for entry in ledger_entries:
            ledger_name = elem_text(entry, "LEDGERNAME")
            amt = parse_amount(elem_text(entry, "AMOUNT"))

            if vch_type in ("Journal", "Contra"):
                if amt < 0:
                    debit_ledger = ledger_name
                    amount = abs(amt)
                elif amt > 0:
                    credit_ledger = ledger_name
                    amount = amt

            elif vch_type == "Payment":
                if amt < 0:
                    debit_ledger = ledger_name
                    amount = abs(amt)
                elif amt > 0:
                    credit_ledger = ledger_name
                    amount = amt

            elif vch_type == "Receipt":
                if amt < 0:
                    debit_ledger = ledger_name
                    amount = abs(amt)
                elif amt > 0:
                    credit_ledger = ledger_name
                    amount = amt

        if not debit_ledger or not credit_ledger:
            voucher.clear()
            continue

        doctype = voucher_map[vch_type]
        tally_vouchers_seen.add(voucher_number)

        existing = frappe.db.exists(doctype, {"voucher_number": voucher_number})

        if existing:
            doc = frappe.get_doc(doctype, existing)
            doc.date = voucher_date
            doc.narration = narration
            doc.debit_ledger = debit_ledger
            doc.credit_ledger = credit_ledger
            doc.ledger_amount = amount
            doc.flags.from_pull = True
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc({
                "doctype": doctype,
                "voucher_number": voucher_number,
                "voucher_type": vch_type,
                "date": voucher_date,
                "narration": narration,
                "debit_ledger": debit_ledger,
                "credit_ledger": credit_ledger,
                "ledger_amount": amount,
                "is_pushed_to_tally": 1
            })
            doc.flags.from_pull = True
            doc.insert(ignore_permissions=True)

        voucher.clear()

    for doctype in voucher_map.values():
        for d in frappe.get_all(doctype, ["name", "voucher_number"]):
            if d.voucher_number not in tally_vouchers_seen:
                frappe.delete_doc(doctype, d.name, ignore_permissions=True)

    frappe.db.commit()
