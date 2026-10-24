# AutoFlow — Autonomous AI Task Worker (v0.2)

A small, **real-execution** office agent. A local Ollama LLM selects tools, while Python reads synthetic invoice PDFs, writes to SQLite, and **independently verifies the user's requested outcome**. No company credentials or third-party data.

## Requirements
- Python 3.10+
- Ollama installed and running; `ollama pull qwen2.5:3b`

## Setup (Windows CMD)
```cmd
py -3.10 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen2.5:3b
python generate_invoices.py
python setup_database.py
python -m unittest -v
python agent.py
```

**Example tasks**
- `Find the latest invoice from ABC Company and save it to the database. Verify that it was saved correctly.`
- `Find the latest invoice from XYZ Company.`
- `Process INV-104.pdf.`

## Architecture

`User request → restricted goal parser → Ollama Qwen 2.5 3B → tool decision → strict argument validation + source discovery + goal safeguards → real PDF/SQLite tools → observation → next decision → independent goal verifier → status and JSONL audit trail`

- The LLM selects the next action, but cannot authorize its own success.
- `find_latest_invoice` searches the actual synthetic PDFs by company and date.
- `process_invoice` validates PDF fields, handles duplicate/conflicting records, saves to SQLite, and checks the stored values.
- The **goal verifier** independently re-reads the latest matching source invoice and its database record. Processing the wrong invoice cannot complete a latest-invoice request.
- Tool calls are checked for exact argument names and types. Undiscovered filenames are blocked. Repeated failed actions stop safely.
- Task decisions, observations, and final status are saved as JSONL under `logs/` (ignored by Git).

## Tests

`python -m unittest -v` runs the original invoice tool tests and eight offline agent/controller tests. The latter inject predetermined LLM decisions, allowing tests to run without Ollama. **These tests do not measure real-model task success rate**; run the agent manually with Ollama and record actual results separately.

## Known limitations

- Deliberately supports a **narrow invoice task contract**: latest invoice for a company (read or save) and explicit invoice PDF processing. Other tasks are rejected rather than falsely marked complete.
- Goal interpretation uses simple pattern matching, not general natural-language understanding. Some paraphrases may be rejected or misinterpreted; the current verifier is specific to invoices.
- `process_invoice` is a high-level tool that bundles parsing, saving, and verification; the model autonomously chooses tools, not every internal substep.
- No browser automation, human approval for sensitive actions, multi-user security, persistent cross-task memory, or general task planning.
- Local demo SQLite uses floating-point amounts; production financial systems should store integer minor units or decimals.
- Local model output may still be unreliable; the controller prevents false success for the supported goals but cannot guarantee that Qwen finishes every task.
- The test invoices are synthetic; do not use real financial data.

## Design choices / next steps

A narrow, auditable, CPU-friendly implementation was prioritized over mocked breadth. Next: model-level evaluation over varied phrasings, user clarification/approval, stronger goal parsing, more workflows, and optionally browser/API integrations. No external API keys are required. Tools: Python, Ollama `qwen2.5:3b`, PyMuPDF, SQLite, requests, ReportLab (sample PDF generation).

## Demo evidence

For a live demo, start Ollama, run `python agent.py`, enter a supported request, and show (1) tool decisions, (2) real PDF and database operations, (3) `INDEPENDENTLY VERIFIED`, and (4) the corresponding `logs/<task_id>.jsonl` trace. A screen recording can be linked here before submission.

## Live Ollama evaluation (optional)

With Ollama running and `qwen2.5:3b` available, run:

```bash
python evaluate_agent.py --repeats 1
```

This runs 12 natural-language scenarios, including known paraphrase limitations. It
creates an isolated temporary SQLite database for each scenario and **does not
modify your `data/company.db`**. Results and full agent transcripts are saved to
`evaluation_results/eval_<timestamp>.json`. Some paraphrase tests are expected
to expose weaknesses in v0.2; don't present the evaluation as 100% passing
without running it. For repeated-run measurements use `--repeats 2` (24 runs).
Each Ollama request can take time on CPU. The evaluation's pass rate includes
expected rejections; it is not a measure of unrestricted generalization.
