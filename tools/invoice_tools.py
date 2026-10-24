from datetime import date
from decimal import Decimal
from .file_tools import list_files, read_invoice
from .database_tools import save_invoice, get_invoice

FIELDS = ('invoice_id','company','amount','invoice_date','due_date')

def extract_invoice_fields(text):
    raw = {}
    for line in text.splitlines():
        if ':' in line:
            key,value = line.split(':',1)
            raw[key.strip().lower()] = value.strip()
    if any(not raw.get(key) for key in FIELDS):
        raise ValueError('Required invoice fields missing')
    amount = Decimal(raw['amount'])
    if not amount.is_finite() or amount < 0: raise ValueError('Invalid amount')
    date.fromisoformat(raw['invoice_date']); date.fromisoformat(raw['due_date'])
    return {'invoice_id':raw['invoice_id'], 'company':raw['company'], 'amount':float(amount), 'invoice_date':raw['invoice_date'], 'due_date':raw['due_date']}

def matching(stored, source):
    return all(stored[k] == source[k] for k in ('invoice_id','company','invoice_date','due_date')) and abs(stored['amount']-source['amount']) < .005

def find_latest_invoice(company):
    if not isinstance(company,str) or not company.strip(): return {'status':'error','message':'Company required'}
    matches = []
    for filename in list_files()['files']:
        result = read_invoice(filename)
        if result['status'] != 'success': continue
        try: fields = extract_invoice_fields(result['content'])
        except (ValueError, TypeError, ArithmeticError): continue
        if fields['company'].casefold() == company.strip().casefold():
            matches.append({**fields,'filename':filename})
    if not matches: return {'status':'error','message':f'No invoices found for {company}'}
    return {'status':'success','invoice':max(matches,key=lambda item:(item['invoice_date'],item['invoice_id']))}

def process_invoice(filename):
    result = read_invoice(filename)
    if result['status'] != 'success': return result
    try: source = extract_invoice_fields(result['content'])
    except (ValueError, TypeError, ArithmeticError) as exc: return {'status':'error','message':f'Invalid invoice: {exc}'}
    invoice_id = source['invoice_id']
    existing = get_invoice(invoice_id)
    if existing['status'] == 'success':
        ok = matching(existing['data'],source)
        return {'status':'success' if ok else 'error','invoice_id':invoice_id,'verified':ok,'already_exists':True,'message':'Existing record matches PDF' if ok else 'Existing record conflicts with PDF','invoice':source}
    saved = save_invoice(**source)
    if saved['status'] != 'success': return saved
    check = get_invoice(invoice_id)
    ok = check['status'] == 'success' and matching(check['data'],source)
    return {'status':'success' if ok else 'error','invoice_id':invoice_id,'verified':ok,'already_exists':False,'invoice':source,'message':'Saved and verified' if ok else 'Verification failed'}
