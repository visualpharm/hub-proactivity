"""Данные владельца в черновиках (26.10, d4491).

Черновик ответа продавцу, просившему данные для накладной, написал «El DNI te lo mando en un momento» и «Missing: DNI»,
хотя DNI был в той же переписке днём раньше (поле context пункта несёт лишь несколько последних реплик). Теперь в
просьбе разборщику — правило «данные владельца подставлять, не обещать прислать позже» и справочник владельца из
локального файла в папке настроек хаба (значения в репо не лежат).
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика
import engine

FACTS = {"name": "Owner Example", "dni": "00.000.001", "address": "Example 1, Town, CP 0000", "email": "owner@example.org"}


class OwnerFactsInPrompt(Case):
    def setUp(self):
        super().setUp()
        self.eng.own(self.entry("owner"), {"kind": "settings", "preset": "everyone"}, owner_word=True)
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False, "inbox_guard": True})

    def ask(self):
        post = self.incoming("k1", src="whatsapp", text="pasame tus datos para armar el remito: nombre, DNI, domicilio")
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item("k1")["status"], "asked")
        return [t for _, t in self.io.asked if post in t][-1]

    def test_rule_and_reference_go_into_the_request(self):
        self.io.owner_facts = lambda: dict(FACTS)
        text = self.ask()
        self.assertIn(engine.OWNER_FACTS_RULE, text)
        self.assertIn("Owner reference (trusted", text)
        self.assertIn(json.dumps(FACTS, ensure_ascii=False), text)

    def test_without_reference_the_rule_stays_and_points_to_the_thread(self):
        text = self.ask()   # заглушка ящика без owner_facts — как хаб без файла
        self.assertIn(engine.OWNER_FACTS_RULE, text)
        self.assertIn("Owner reference: none on this hub", text)


class OwnerFactsFile(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        self.dir = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"HUB_CONFIG_DIR": self.dir})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.io = main.IO.__new__(main.IO)

    def write(self, body):
        with open(os.path.join(self.dir, engine.OWNER_FACTS_FILE), "w", encoding="utf-8") as f:
            f.write(body)

    def test_reads_scalar_fields_from_the_hub_config_folder(self):
        self.write(json.dumps({**FACTS, "nested": {"x": 1}, "list": [1]}))
        self.assertEqual(self.io.owner_facts(), FACTS)

    def test_missing_or_broken_file_is_no_reference(self):
        self.assertIsNone(self.io.owner_facts())
        self.write("{not json")
        self.assertIsNone(self.io.owner_facts())
        self.write("[1, 2]")
        self.assertIsNone(self.io.owner_facts())


if __name__ == "__main__":
    unittest.main()
