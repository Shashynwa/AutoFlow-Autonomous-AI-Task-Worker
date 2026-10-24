# AutoFlow — updated local prototype

Python 3.10, Ollama `qwen2.5:3b`. Uses local PDF invoices and SQLite. No company credentials.

## Setup (Windows CMD)

```cmd
py -3.10 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
ollama list
python generate_invoices.py
python setup_database.py
python test_invoice_tools.py
python agent.py
```

Example task: `Find the latest invoice from ABC Company and save it to the database. Verify that it was saved correctly.`

The model chooses tools. The controller normalizes common action variants, restricts processing to discovered files, caches successful calls, and relies on deterministic PDF parsing and database verification. A `finish` message is not proof of successful writing; look for `INDEPENDENTLY VERIFIED`.

**Limitations:** invoice schema is fixed; the LLM can still choose the wrong task/filename; task intent detection is keyword-based; no general-purpose objective verifier, browser automation, approval gate, or persisted audit log yet. This is a restricted prototype, not production software.
