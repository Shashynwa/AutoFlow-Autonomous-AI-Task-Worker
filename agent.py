import json
import requests
from tools.file_tools import list_files, read_invoice
from tools.database_tools import get_invoice
from tools.invoice_tools import find_latest_invoice, process_invoice

OLLAMA_URL = 'http://localhost:11434/api/chat'
MODEL = 'qwen2.5:3b'
MAX_STEPS = 12
TOOLS = {'list_files':list_files,'read_invoice':read_invoice,'get_invoice':get_invoice,'find_latest_invoice':find_latest_invoice,'process_invoice':process_invoice}
SYSTEM_PROMPT = '''You are AutoFlow, a tool-using office agent. Your task is to execute user requests, not merely explain them.
Tools (call ONE at a time):
list_files {}: list available PDFs.
read_invoice {"filename":"INV-101.pdf"}: read a discovered PDF.
get_invoice {"invoice_id":"INV-101"}: retrieve database record.
find_latest_invoice {"company":"ABC Company"}: find latest PDF by invoice date.
process_invoice {"filename":"INV-101.pdf"}: parse, save and independently verify a discovered PDF.
To process latest company invoice: find_latest_invoice first, then process_invoice with returned filename.
Never invent filenames, amounts, or observations. If an action fails, use feedback to recover.
Reply with exactly one JSON object:
{"action":"tool","tool_name":"find_latest_invoice","arguments":{"company":"ABC Company"}}
OR {"action":"finish","answer":"Summary grounded in observations"}.
Do not claim a save succeeded without verified:true in the tool result.'''

def ask_llm(messages):
    response = requests.post(OLLAMA_URL,json={'model':MODEL,'messages':messages,'stream':False,'format':'json','options':{'temperature':0,'num_ctx':4096}},timeout=240)
    response.raise_for_status()
    return json.loads(response.json()['message']['content'])

def normalize_decision(decision):
    if not isinstance(decision,dict): return {'action':'invalid'}
    action = decision.get('action')
    name = decision.get('tool_name')
    if action in TOOLS: name = action
    elif action not in ('tool','execute_flow','execute','call_tool','finish'): return {'action':'invalid'}
    if action == 'finish': return {'action':'finish','answer':str(decision.get('answer',''))}
    if name not in TOOLS: return {'action':'invalid'}
    return {'action':'tool','tool_name':name,'arguments':decision.get('arguments',{})}

def run_agent(task):
    messages = [{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':task}]
    discovered = set()
    successful = {}
    verified = set()
    observations = []
    # These task types are a narrow demo contract, not general natural-language intent detection.
    requires_write = any(word in task.lower() for word in ('save','process','store','insert','add to the database'))
    for step in range(1,MAX_STEPS+1):
        print(f'\n========== STEP {step} ==========')
        try: decision = normalize_decision(ask_llm(messages))
        except (requests.RequestException,ValueError,KeyError) as exc:
            print('LLM ERROR:',exc); return
        print('AGENT DECISION:',decision)
        messages.append({'role':'assistant','content':json.dumps(decision)})
        if decision['action'] == 'finish':
            if requires_write and not verified:
                # Explicit failure is allowed; never mislabel as completed.
                print('\nTASK NOT VERIFIED:',decision.get('answer',''))
                return
            if not observations:
                messages.append({'role':'user','content':'No tools used. Select a relevant tool first.'})
                continue
            print('\nTASK FINISHED:',decision.get('answer',''))
            if verified: print('INDEPENDENTLY VERIFIED:',sorted(verified))
            return
        if decision['action'] != 'tool':
            observation = {'status':'error','message':'Invalid action; use action=tool and a registered tool_name'}
        else:
            name = decision['tool_name']; args = decision['arguments']
            if not isinstance(args,dict):
                observation = {'status':'error','message':'Arguments must be a JSON object'}
            elif name in ('read_invoice','process_invoice') and args.get('filename') not in discovered:
                observation = {'status':'error','message':'File not discovered; use list_files or find_latest_invoice first'}
            else:
                key = json.dumps([name,args],sort_keys=True)
                if key in successful:
                    observation = {**successful[key],'cached':True}
                else:
                    try: observation = TOOLS[name](**args)
                    except (TypeError,ValueError,OSError) as exc: observation = {'status':'error','message':str(exc)}
                    if observation.get('status') == 'success': successful[key] = observation
                if observation.get('status') == 'success':
                    if name == 'list_files': discovered.update(observation.get('files',[]))
                    if name == 'find_latest_invoice':
                        filename = observation.get('invoice',{}).get('filename')
                        if filename: discovered.add(filename)
                    if name == 'process_invoice' and observation.get('verified') is True:
                        verified.add(observation['invoice_id'])
        print('TOOL OBSERVATION:',observation)
        observations.append(observation)
        messages.append({'role':'user','content':'Tool result: '+json.dumps(observation)+'\nSelect the next action based on this result.'})
    print('\nSTEP LIMIT REACHED. Task completion not established.')

if __name__ == '__main__':
    print('AutoFlow - Autonomous AI Task Worker')
    while True:
        task = input('\nEnter your task (or exit): ').strip()
        if task.lower() == 'exit': break
        if task: run_agent(task)
