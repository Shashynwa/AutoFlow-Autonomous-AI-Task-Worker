from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
INVOICE_DIR = ROOT / 'data' / 'invoices'

def list_files():
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    return {'status':'success','files': sorted(p.name for p in INVOICE_DIR.glob('*.pdf') if p.is_file())}

def read_invoice(filename):
    if not isinstance(filename,str) or Path(filename).name != filename or not filename.lower().endswith('.pdf') or filename in ('.','..'):
        return {'status':'error','message':'Invalid filename'}
    path = INVOICE_DIR / filename
    if not path.is_file() or path.is_symlink():
        return {'status':'error','message':'Invoice file not found'}
    try:
        with pymupdf.open(path) as doc:
            content = '\n'.join(page.get_text() for page in doc)
        return {'status':'success','filename':filename,'content':content[:20000]}
    except Exception as exc:
        return {'status':'error','message':f'Unable to read PDF: {type(exc).__name__}'}
