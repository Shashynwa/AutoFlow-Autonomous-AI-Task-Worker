"""Offline agent tests: no Ollama needed. Run: python -m unittest -v."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
from tools import database_tools


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(database_tools, 'DB', Path(self.tmp.name) / 'company.db')
        self.log_patch = patch.object(agent, 'LOG_DIR', Path(self.tmp.name) / 'logs')
        self.db_patch.start(); self.log_patch.start()
        self.addCleanup(self.db_patch.stop); self.addCleanup(self.log_patch.stop)

    def run_decisions(self, task, decisions):
        iterator = iter(decisions)
        return agent.run_agent(task, llm=lambda messages: next(iterator), max_steps=len(decisions))

    def test_latest_invoice_success(self):
        result = self.run_decisions('Find the latest invoice from ABC Company and save it to the database', [
            {'action':'tool','tool_name':'find_latest_invoice','arguments':{'company':'ABC Company'}},
            {'action':'tool','tool_name':'process_invoice','arguments':{'filename':'INV-104.pdf'}},
            {'action':'finish','answer':'Saved and verified INV-104'}])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['verification']['invoice_id'], 'INV-104')
        self.assertTrue(Path(result['log']).exists())

    def test_wrong_invoice_cannot_succeed(self):
        result = self.run_decisions('Find the latest invoice from ABC Company and save it', [
            {'action':'tool','tool_name':'list_files','arguments':{}},
            {'action':'tool','tool_name':'process_invoice','arguments':{'filename':'INV-101.pdf'}},
            {'action':'finish','answer':'Done'}])
        self.assertEqual(result['status'], 'unverified')
        self.assertFalse(result['verification']['verified'])

    def test_premature_finish_cannot_succeed(self):
        result = self.run_decisions('Find the latest invoice from ABC Company and save it', [
            {'action':'finish','answer':'Done'}])
        self.assertEqual(result['status'], 'unverified')

    def test_specific_invoice_preflight_discovery(self):
        result = self.run_decisions('Process INV-104.pdf', [
            {'action':'tool','tool_name':'process_invoice','arguments':{'filename':'INV-104.pdf'}},
            {'action':'finish','answer':'Done'}])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['verification']['invoice_id'], 'INV-104')

    def test_read_only_latest(self):
        result = self.run_decisions('Find the latest invoice from XYZ Company', [
            {'action':'tool','tool_name':'find_latest_invoice','arguments':{'company':'XYZ Company'}},
            {'action':'finish','answer':'INV-102'}])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['verification']['invoice_id'], 'INV-102')

    def test_missing_specific_file_stops_without_llm(self):
        result = agent.run_agent('Process INV-999.pdf', llm=lambda m: self.fail('No LLM needed'))
        self.assertEqual(result['status'], 'unverified')

    def test_paraphrase_goal_parsing(self):
        self.assertEqual(agent.parse_goal("Locate ABC Company's most recent invoice and store its details."),
                         {'kind':'latest', 'company':'ABC Company', 'write':True})
        self.assertEqual(agent.parse_goal('Save the newest invoice for XYZ Company.'),
                         {'kind':'latest', 'company':'XYZ Company', 'write':True})
        self.assertEqual(agent.parse_goal('Find the latest invoice from ABC Company, but do not save anything.'),
                         {'kind':'latest', 'company':'ABC Company', 'write':False})

    def test_readonly_blocks_process_invoice(self):
        result = self.run_decisions('Find the latest invoice from ABC Company, but do not save anything.', [
            {'action':'tool','tool_name':'find_latest_invoice','arguments':{'company':'ABC Company'}},
            {'action':'tool','tool_name':'process_invoice','arguments':{'filename':'INV-104.pdf'}},
            {'action':'finish','answer':'Found INV-104'}])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(database_tools.get_invoice('INV-104')['status'], 'error')

    def test_invalid_arguments_and_recovery(self):
        result = self.run_decisions('Process INV-104.pdf', [
            {'action':'tool','tool_name':'list_files','arguments':{'unexpected': 1}},
            {'action':'tool','tool_name':'list_files','arguments':{}},
            {'action':'execute_flow','tool_name':'process_invoice','arguments':{'filename':'INV-104.pdf'}},
            {'action':'finish','answer':'Done'}])
        self.assertEqual(result['status'], 'completed')

    def test_unsupported_task_not_claimed(self):
        result = agent.run_agent('Send an email to my manager', llm=lambda m: self.fail('Should not call LLM'))
        self.assertEqual(result['status'], 'unsupported')

    def test_repeated_invalid_actions_stop(self):
        result = self.run_decisions('Process INV-104.pdf', [
            {'action':'unknown'}, {'action':'unknown'}, {'action':'unknown'}])
        self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
