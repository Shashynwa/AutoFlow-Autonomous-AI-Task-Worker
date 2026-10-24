import sqlite3
from pathlib import Path
from datetime import date
from decimal import Decimal, InvalidOperation

DB = Path(__file__).resolve().parents[1] / 'data' / 'company.db'

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute('''CREATE TABLE IF NOT EXISTS invoices (invoice_id TEXT PRIMARY KEY, company TEXT NOT NULL, amount REAL NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unpaid')''')
    return connection

def save_invoice(invoice_id, company, amount, invoice_date, due_date):
    try:
        amt = Decimal(str(amount))
        if not amt.is_finite() or amt < 0: raise ValueError('Invalid amount')
        date.fromisoformat(invoice_date); date.fromisoformat(due_date)
        if not invoice_id or not company: raise ValueError('Missing invoice ID or company')
        with connect() as db:
            db.execute('INSERT INTO invoices(invoice_id,company,amount,invoice_date,due_date) VALUES(?,?,?,?,?)', (invoice_id,company,float(amt),invoice_date,due_date))
        return {'status':'success','invoice_id':invoice_id}
    except sqlite3.IntegrityError:
        return {'status':'error','message':'Invoice already exists'}
    except (ValueError, TypeError, InvalidOperation) as exc:
        return {'status':'error','message':str(exc)}

def get_invoice(invoice_id):
    with connect() as db:
        row = db.execute('SELECT * FROM invoices WHERE invoice_id=?',(invoice_id,)).fetchone()
    if row is None: return {'status':'error','message':'Invoice not found'}
    data = dict(row)
    data['payment_status'] = data.pop('status')
    return {'status':'success','data':data}
