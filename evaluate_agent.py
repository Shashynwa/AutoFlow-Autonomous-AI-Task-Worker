"""Live Ollama evaluation for AutoFlow v0.2. Run: python evaluate_agent.py --repeats 2

Runs against an isolated temporary SQLite database. Does not alter data/company.db.
"""
import argparse
import contextlib
from contextlib import closing
import io
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import agent
from tools import database_tools

CASES = [
    {'name':'abc_write', 'task':'Find the latest invoice from ABC Company and save it to the database. Verify that it was saved correctly.', 'expected':'completed', 'invoice':'INV-104'},
    {'name':'xyz_write', 'task':'Find the latest invoice from XYZ Company and save it to the database.', 'expected':'completed', 'invoice':'INV-102'},
    {'name':'abc_read', 'task':'Find the latest invoice from ABC Company and tell me its amount and due date.', 'expected':'completed', 'invoice':'INV-104'},
    {'name':'xyz_read', 'task':'What is the latest invoice from XYZ Company?', 'expected':'completed', 'invoice':'INV-102'},
    {'name':'specific_invoice', 'task':'Process INV-103.pdf and verify that it was saved.', 'expected':'completed', 'invoice':'INV-103'},
    {'name':'missing_file', 'task':'Process INV-999.pdf.', 'expected':'unverified'},
    {'name':'missing_company', 'task':'Find the latest invoice from NoSuchCompany and save it.', 'expected':'unverified'},
    {'name':'unsupported_email', 'task':'Send an email to ABC Company confirming their payment.', 'expected':'unsupported'},
    {'name':'unsupported_payment', 'task':'Mark invoice INV-104 as paid.', 'expected':'unsupported'},
    {'name':'paraphrase_recent', 'task':"Locate ABC Company's most recent invoice and store its details.", 'expected':'completed', 'invoice':'INV-104', 'known_gap':True},
    {'name':'paraphrase_newest', 'task':'Save the newest invoice for XYZ Company.', 'expected':'completed', 'invoice':'INV-102', 'known_gap':True},
    {'name':'paraphrase_dont_save', 'task':'Find the latest invoice from ABC Company, but do not save anything.', 'expected':'completed', 'invoice':'INV-104', 'read_only':True, 'known_gap':True},
]


def evaluate(repeats, timeout_note=True):
    records = []
    original_db = database_tools.DB
    original_log_dir = agent.LOG_DIR
    with tempfile.TemporaryDirectory(prefix='autoflow-eval-') as folder:
        base = Path(folder)
        database_tools.DB = base / 'company.db'
        agent.LOG_DIR = base / 'logs'
        try:
            for repetition in range(1, repeats + 1):
                for case in CASES:
                    # Fresh database per case: a previous case cannot make a write appear successful.
                    database_tools.DB = base / f'db_{repetition}_{case["name"]}.sqlite3'
                    started = time.monotonic()
                    stdout = io.StringIO()
                    try:
                        with contextlib.redirect_stdout(stdout):
                            result = agent.run_agent(case['task'])
                    except Exception as exc:
                        result = {'status':'crashed', 'reason':f'{type(exc).__name__}: {exc}', 'verification':{}}
                    elapsed = round(time.monotonic() - started, 2)
                    verified_id = (result.get('verification') or {}).get('invoice_id')
                    status_ok = result.get('status') == case['expected']
                    invoice_ok = (case.get('invoice') is None or verified_id == case['invoice'])
                    # For read-only tasks, make sure no DB row was created.
                    rows = 0
                    if database_tools.DB.exists():
                        with closing(database_tools.connect()) as conn:
                            rows = conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0]
                    readonly_ok = not case.get('read_only') or rows == 0
                    false_completion = result.get('status') == 'completed' and not (status_ok and invoice_ok and readonly_ok)
                    passed = status_ok and invoice_ok and readonly_ok
                    entry = {'case':case['name'], 'run':repetition, 'task':case['task'],
                             'expected_status':case['expected'], 'actual_status':result.get('status'),
                             'expected_invoice':case.get('invoice'), 'verified_invoice':verified_id,
                             'duration_seconds':elapsed, 'database_rows':rows,
                             'passed':passed, 'false_completion':false_completion,
                             'known_gap':case.get('known_gap',False), 'reason':result.get('reason'),
                             'agent_output':stdout.getvalue()}
                    records.append(entry)
                    verdict = 'PASS' if passed else 'FAIL'
                    print(f'[{verdict}] run={repetition} {case["name"]}: {result.get("status")} ({elapsed}s)', flush=True)
        finally:
            database_tools.DB = original_db
            agent.LOG_DIR = original_log_dir

    total = len(records)
    passes = sum(r['passed'] for r in records)
    false_completions = sum(r['false_completion'] for r in records)
    summary = {'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'model':agent.MODEL,
               'runs':total, 'passed':passes, 'pass_rate':round(passes/total,4),
               'false_completions':false_completions,
               'false_completion_rate':round(false_completions/total,4),
               'note':'Pass rate includes unsupported/failure cases; not a general agent benchmark.'}
    output_dir = Path(__file__).resolve().parent / 'evaluation_results'
    output_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = output_dir / f'eval_{stamp}.json'
    path.write_text(json.dumps({'summary':summary,'cases':records},indent=2),encoding='utf-8')
    print('\nSUMMARY:',json.dumps(summary,indent=2))
    print('Full report:',path)
    return 0 if passes == total else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=1, help='Number of runs per test case')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('--repeats must be between 1 and 10')
    raise SystemExit(evaluate(args.repeats))
