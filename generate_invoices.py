from pathlib import Path
from reportlab.pdfgen import canvas
ROOT = Path(__file__).resolve().parent
DEST = ROOT/'data'/'invoices'; DEST.mkdir(parents=True,exist_ok=True)
invoices = [
 {'invoice_id':'INV-101','company':'ABC Company','amount':12000,'invoice_date':'2026-10-01','due_date':'2026-10-20'},
 {'invoice_id':'INV-102','company':'XYZ Company','amount':18000,'invoice_date':'2026-10-05','due_date':'2026-10-25'},
 {'invoice_id':'INV-103','company':'ABC Company','amount':25000,'invoice_date':'2026-10-15','due_date':'2026-11-05'},
 {'invoice_id':'INV-104','company':'ABC Company','amount':32000,'invoice_date':'2026-10-18','due_date':'2026-11-10'},
]
for invoice in invoices:
    path = DEST/f"{invoice['invoice_id']}.pdf"
    pdf = canvas.Canvas(str(path)); pdf.setFont('Helvetica-Bold',18); pdf.drawString(100,750,'COMPANY INVOICE'); pdf.setFont('Helvetica',12)
    for i,(key,value) in enumerate(invoice.items()): pdf.drawString(100,690-i*35,f'{key}: {value}')
    pdf.save(); print('Created:',path)
