from tools.invoice_tools import find_latest_invoice,process_invoice
from tools.database_tools import get_invoice
latest = find_latest_invoice('ABC Company')
print('Latest:',latest)
assert latest['invoice']['invoice_id']=='INV-104'
first = process_invoice('INV-104.pdf')
print('Process:',first)
assert first['verified'] is True
again = process_invoice('INV-104.pdf')
print('Duplicate:',again)
assert again['verified'] is True and again['already_exists'] is True
missing = process_invoice('INV-999.pdf')
print('Missing:',missing)
assert missing['status']=='error'
assert get_invoice('INV-999')['status']=='error'
print('ALL TESTS PASSED')
