"""AutoFlow v0.2: restricted, auditable local invoice agent."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from tools.file_tools import list_files, read_invoice
from tools.database_tools import get_invoice
from tools.invoice_tools import find_latest_invoice, process_invoice, matching, extract_invoice_fields

OLLAMA_URL = 'http://localhost:11434/api/chat'
MODEL = 'qwen2.5:3b'
MAX_STEPS = 12
LOG_DIR = Path(__file__).resolve().parent / 'logs'
TOOLS = {'list_files': list_files, 'read_invoice': read_invoice, 'get_invoice': get_invoice,
         'find_latest_invoice': find_latest_invoice, 'process_invoice': process_invoice}
ARGUMENTS = {'list_files': {}, 'read_invoice': {'filename': str},
             'get_invoice': {'invoice_id': str}, 'find_latest_invoice': {'company': str},
             'process_invoice': {'filename': str}}
SYSTEM_PROMPT = '''You are AutoFlow, a local tool-using office agent. Execute the user's task.
Use one tool per response. Never invent file names or claim actions succeeded without tool evidence.
Tools: list_files {}; read_invoice {"filename":"..."}; get_invoice {"invoice_id":"..."};
find_latest_invoice {"company":"..."}; process_invoice {"filename":"..."}.
For latest invoice requests, ALWAYS call find_latest_invoice(company) before process_invoice(filename).
Reply with exactly one JSON object, either
{"action":"tool","tool_name":"find_latest_invoice","arguments":{"company":"ABC Company"}}
or {"action":"finish","answer":"A concise evidence-based summary"}.
Do not treat a tool's success as proof that the original user goal is complete.
If the tool reports an error, choose a recovery action or finish with an honest failure summary.'''


def ask_llm(messages):
    response = requests.post(OLLAMA_URL, json={'model': MODEL, 'messages': messages,
        'stream': False, 'format': 'json', 'options': {'temperature': 0, 'num_ctx': 4096}}, timeout=120)
    response.raise_for_status()
    return json.loads(response.json()['message']['content'])


def normalize_decision(decision):
    if not isinstance(decision, dict):
        return {'action': 'invalid', 'message': 'Response is not an object'}
    action = decision.get('action')
    if action == 'finish':
        return {'action': 'finish', 'answer': str(decision.get('answer', ''))}
    name = action if action in TOOLS else decision.get('tool_name')
    if action not in TOOLS and action not in ('tool', 'execute_flow', 'execute', 'call_tool'):
        return {'action': 'invalid', 'message': 'Unrecognized action'}
    if name not in TOOLS:
        return {'action': 'invalid', 'message': 'Unknown tool'}
    return {'action': 'tool', 'tool_name': name, 'arguments': decision.get('arguments', {})}


def validate_args(name, args):
    expected = ARGUMENTS[name]
    if not isinstance(args, dict) or set(args) != set(expected):
        return ('Tool ' + name + ' accepts no arguments' if not expected else 'Arguments must contain exactly: ' + ', '.join(expected))
    for key, kind in expected.items():
        if not isinstance(args[key], kind) or not args[key].strip():
            return f'{key} must be a nonempty string'
    return None


def parse_goal(task):
    """Parse supported invoice intents and prioritize explicit no-write constraints."""
    text = task.strip()
    lower = text.casefold()
    # Negative instructions override positive verbs such as "save".
    no_write = bool(re.search(r"\b(?:do\s+not|don't|dont|never|without)\s+(?:\w+\s+){0,3}?(?:save|store|insert|process|write|modify|update)\b", lower))
    write = bool(re.search(r'\b(save|process|store|insert|record)\b', lower)) and not no_write
    latest = bool(re.search(r'\b(?:latest|newest|most\s+recent)\b', lower))
    # Specific filename takes precedence; never turn it into an unrelated company search.
    file_match = re.search(r'\b(INV-[A-Za-z0-9_-]+\.pdf)\b', text, re.I)
    if file_match and not latest and write:
        return {'kind': 'specific', 'filename': file_match.group(1), 'write': True}
    if latest:
        # Company possessive: "ABC Company's most recent invoice"
        possessive = re.search(r"\b([A-Za-z0-9][A-Za-z0-9 .&-]*?\s+Company)\s*['’]s\b", text, re.I)
        company = possessive.group(1).strip() if possessive else None
        if company:
            company = re.sub(r'^(?:locate|find|show|give|retrieve|identify)\s+', '', company, flags=re.I)
        if not company:
            # "from ABC Company", "for XYZ Company", or "for NoSuchCompany"
            match = re.search(r'\b(?:from|for)\s+([\w .&-]+?)(?=\s+(?:and|invoice|to|into|in the|with|then|please|but|$)|[.,!?]|$)', text, re.I)
            if match:
                company = match.group(1).strip()
        if company:
            return {'kind': 'latest', 'company': company, 'write': write}
    return {'kind': 'unsupported', 'write': write}


def verify_goal(goal, state):
    """Re-read trusted source and DB, independent of the LLM's finish message."""
    if goal['kind'] == 'unsupported':
        return {'verified': False, 'reason': 'Task outside supported invoice workflows'}
    if goal['kind'] == 'latest':
        result = find_latest_invoice(goal['company'])
        if result['status'] != 'success':
            return {'verified': False, 'reason': result.get('message', 'Latest invoice unavailable')}
        expected = result['invoice']
        if not goal['write']:
            seen = state.get('latest_seen')
            ok = not state['processed_files'] and bool(seen and seen.get('invoice_id') == expected['invoice_id'] and
                      seen.get('company', '').casefold() == goal['company'].casefold())
            return {'verified': ok, 'reason': 'Latest invoice confirmed' if ok else 'Latest invoice not discovered',
                    'invoice_id': expected['invoice_id'] if ok else None}
        filename = expected['filename']
    else:
        filename = goal['filename']
        source_result = read_invoice(filename)
        if source_result['status'] != 'success':
            return {'verified': False, 'reason': 'Requested source file unavailable'}
        try:
            expected = extract_invoice_fields(source_result['content'])
        except (ValueError, TypeError, ArithmeticError):
            return {'verified': False, 'reason': 'Requested source file invalid'}
    if filename not in state['processed_files']:
        return {'verified': False, 'reason': 'Correct source invoice was not processed'}
    db_result = get_invoice(expected['invoice_id'])
    ok = db_result['status'] == 'success' and matching(db_result['data'], expected)
    return {'verified': ok, 'reason': 'Goal and database independently verified' if ok else 'Database does not match goal invoice',
            'invoice_id': expected['invoice_id']}


def run_agent(task, llm=ask_llm, max_steps=MAX_STEPS):
    task_id = str(uuid.uuid4())[:8]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f'{task_id}.jsonl'
    goal = parse_goal(task)
    state = {'discovered': set(), 'processed_files': set(), 'latest_seen': None,
             'failures': {}, 'steps': 0}
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': task + '\nSupported task contract: ' + json.dumps(goal)}]

    def record(event, **details):
        with log_path.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                                  'task_id': task_id, 'event': event, **details}, default=str) + '\n')

    def end(status, reason, verification=None):
        result = {'task_id': task_id, 'status': status, 'reason': reason,
                  'verification': verification or {'verified': False}, 'log': str(log_path)}
        record('end', result=result)
        print('\nTASK', status.upper() + ':', reason)
        if verification and verification.get('verified'):
            print('INDEPENDENTLY VERIFIED:', verification['invoice_id'])
        print('AUDIT LOG:', log_path)
        return result

    record('start', task=task, goal=goal)
    if goal['kind'] == 'unsupported':
        return end('unsupported', 'This version supports latest-company invoice lookup/processing and explicit invoice processing only')

    # Deterministic source discovery for exact filenames. This is a real tool call,
    # recorded in the audit trail, and avoids LLM hallucinations during recovery.
    if goal['kind'] == 'specific':
        discovery = list_files()
        record('preflight_discovery', observation=discovery)
        if discovery.get('status') != 'success':
            return end('unverified', 'Unable to list invoice files')
        state['discovered'].update(discovery['files'])
        if goal['filename'] not in state['discovered']:
            return end('unverified', f"Requested invoice file not found: {goal['filename']}")
        messages.append({'role': 'user', 'content': 'Verified file discovery: ' + json.dumps(discovery) + '. The requested filename exists. Process only the requested filename.'})

    for step in range(1, max_steps + 1):
        state['steps'] = step
        print(f'\n========== STEP {step} ==========')
        try:
            decision = normalize_decision(llm(messages))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            record('model_error', error=type(exc).__name__, detail=str(exc))
            return end('failed', 'Model response failed: ' + type(exc).__name__)
        print('AGENT DECISION:', decision)
        record('decision', step=step, decision=decision)
        messages.append({'role': 'assistant', 'content': json.dumps(decision)})
        if decision['action'] == 'finish':
            verification = verify_goal(goal, state)
            if verification['verified']:
                invoice_id = verification['invoice_id']
                if not goal['write']:
                    summary = f'Located and verified {invoice_id}; no database changes made'
                else:
                    summary = f'Processed and independently verified {invoice_id} in the database'
                return end('completed', summary, verification)
            # Never allow an LLM's finish statement to override the verifier.
            return end('unverified', verification['reason'], verification)

        if decision['action'] != 'tool':
            observation = {'status': 'error', 'message': decision.get('message', 'Invalid action')}
            key = 'invalid'
        else:
            name, args = decision['tool_name'], decision['arguments']

            # Recover missing filename for an explicit invoice-processing task.
            # Only use the filename extracted from the original user request.
            if (
                name == 'process_invoice'
                and goal['kind'] == 'specific'
                and goal['write']
                and isinstance(args, dict)
                and 'filename' not in args
                and goal['filename'] in state['discovered']
            ):
                args = {'filename': goal['filename']}

                # Keep the corrected decision in the audit log.
                record(
                    'argument_recovery',
                    step=step,
                    tool=name,
                    recovered_arguments=args,
                    reason='Filename recovered from verified user request'
                )

                print('RECOVERED ARGUMENTS:', args)

            key = json.dumps([name, args], sort_keys=True, default=str)
            validation = validate_args(name, args)
            if validation:
                observation = {'status': 'error', 'message': validation}
            elif name == 'process_invoice' and not goal['write']:
                observation = {'status': 'error', 'message': 'Read-only task: database writes are prohibited'}
            elif name == 'process_invoice' and goal['kind'] == 'specific' and args['filename'] != goal['filename']:
                observation = {'status': 'error', 'message': 'Filename differs from requested invoice'}
            elif name == 'find_latest_invoice' and goal['kind'] == 'specific':
                observation = {'status': 'error', 'message': 'Specific invoice task: use the requested filename, not a latest-company lookup'}
            elif name in ('read_invoice', 'process_invoice') and args['filename'] not in state['discovered']:
                observation = {'status': 'error', 'message': 'File not discovered; call list_files or find_latest_invoice first'}
            elif name == 'process_invoice' and goal['kind'] == 'latest' and (
                    not state['latest_seen'] or args['filename'] != state['latest_seen'].get('filename')):
                observation = {'status': 'error', 'message': 'Must process filename returned by latest-invoice lookup'}
            elif name == 'find_latest_invoice' and goal['kind'] == 'latest' and args['company'].casefold() != goal['company'].casefold():
                observation = {'status': 'error', 'message': 'Company differs from requested company'}
            else:
                try:
                    observation = TOOLS[name](**args)
                except (TypeError, ValueError, OSError) as exc:
                    observation = {'status': 'error', 'message': type(exc).__name__ + ': ' + str(exc)}
                if not isinstance(observation, dict):
                    observation = {'status': 'error', 'message': 'Tool returned invalid response'}
                if observation.get('status') == 'success':
                    if name == 'list_files':
                        state['discovered'].update(observation.get('files', []))
                    elif name == 'find_latest_invoice':
                        found = observation.get('invoice', {})
                        if found.get('filename'):
                            state['discovered'].add(found['filename'])
                            if goal['kind'] == 'latest' and args['company'].casefold() == goal['company'].casefold():
                                state['latest_seen'] = found
                    elif name == 'process_invoice' and observation.get('verified') is True:
                        state['processed_files'].add(args['filename'])
        if observation['status'] == 'error':
            state['failures'][key] = state['failures'].get(key, 0) + 1
            if state['failures'][key] >= 3:
                record('observation', step=step, observation=observation)
                return end('failed', 'Repeated failed action; stopped safely')
        print('TOOL OBSERVATION:', observation)
        record('observation', step=step, observation=observation)
        messages.append({'role': 'user', 'content': 'Tool result: ' + json.dumps(observation) + '\nChoose next action. Only finish if the requested goal is complete.'})
    return end('failed', 'Step limit reached without verified completion')


if __name__ == '__main__':
    print('AutoFlow v0.2 - Autonomous AI Task Worker')
    while True:
        task = input('\nEnter your task (or exit): ').strip()
        if task.lower() == 'exit':
            break
        if task:
            run_agent(task)
