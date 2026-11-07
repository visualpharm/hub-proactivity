"""Итог прежних ответов переписке — в просьбе разборщику (21.10, d3612).

Разборщик считал свой прежний вердикт свершившейся отправкой: Miguel — «мой вопрос уже доставлен (p3532)», хотя
ответ держала пауза на собеседника; группа — «благодарность отправлена», хотя отправка упала. В просьбе о разборе не
было итога прежних ответов этой переписке. Теперь у каждого пункта — строка с итогом каждого нашего ответа той же
переписке: отправлен (время), держится (почему), не ушёл (причина), итог неизвестен.
"""
import unittest

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика
import engine

TOKEN = {"v": 1, "version": "v1", "manual_followup": False, "edit_version": 0, "held": False, "holder": None}
WA = "wa:whatsapp:1@c.us"


class PriorOutcome(Case):
    def setUp(self):
        super().setUp()
        self.eng.own(self.entry("owner"), {"kind": "settings", "preset": "everyone"}, owner_word=True)
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False, "inbox_guard": True})

    def reply(self, key, text="Buen día! Decime."):
        post = self.incoming(key, sign=True, contact=WA, src="whatsapp", inbox=TOKEN)
        self.advance(engine.SERIES_QUIET + 1)
        self.verdict(post, do="reply", type="ack", text=text, why="рутина", inbox=TOKEN)
        return post

    def ask_next(self, key):
        """Новое сообщение той же переписки уходит на разбор — просьба разборщику."""
        self.io.t += 60
        post = self.incoming(key, sign=True, contact=WA, src="whatsapp", inbox=TOKEN)
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item(key)["status"], "asked")
        text = [t for _, t in self.io.asked if post in t][-1]
        line = [x for x in text.splitlines() if x.startswith("- " + post)][0]
        return text, line

    def test_sent_reply_is_named_sent_with_its_time(self):
        p1 = self.reply("k1")
        rid = self.item("k1")["rid"]
        self.io.t += 120
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": TOKEN, "submitted_inbox": TOKEN,
                    "receipt": {"source": "whatsapp", "id": "m1", "destination": "d"}})
        self.assertEqual(self.item("k1")["status"], "replied")
        sent_at = self.io.local(self.io.t).strftime("%d.%m %H:%M")
        _, line = self.ask_next("k2")
        self.assertIn(f"{p1}: отправлен {sent_at}", line)

    def test_reply_held_by_the_contact_pause_is_named_held_not_sent(self):
        # Miguel, p3492 ушёл, p3532 держала пауза на собеседника — разборщик назвал его «доставленным»
        p1 = self.reply("k1")
        rid = self.item("k1")["rid"]
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": TOKEN, "submitted_inbox": TOKEN,
                    "receipt": {"source": "whatsapp", "id": "m1", "destination": "d"}})
        self.io.t += 60
        p2 = self.reply("k2", text="¿De qué se trata?")
        # второй ответ подряд, собеседник не писал после нашего (сообщение раньше ответа) — пауза держит
        self.assertEqual(self.item("k2")["status"], "draft")
        self.assertTrue(self.item("k2")["v"].get("held_by"))
        _, line = self.ask_next("k3")
        self.assertIn(f"{p1}: отправлен", line)
        self.assertIn(f"{p2}: не отправлен, держится — {self.item('k2')['v']['held_by']}", line)

    def test_failed_and_blocked_replies_are_named_not_sent_and_unknown(self):
        # группа: «благодарность отправлена», хотя отправка упала
        p1 = self.reply("k1", text="¡Gracias!")
        rid1 = self.item("k1")["rid"]
        self.teams({"kind": "send_blocked", "id": "k1", "rid": rid1, "reason": "newer_messages",
                    "error": "A newer message arrived in the chat; reply not sent"})
        self.io.t += 3600
        p2 = self.reply("k2", text="Sí, una vez por semana")
        rid2 = self.item("k2")["rid"]
        self.teams({"kind": "send_failed", "id": "k2", "rid": rid2, "error": "WhatsApp Web: timeout"})
        self.assertEqual(self.item("k2")["status"], "unresolved")
        text, line = self.ask_next("k3")
        self.assertIn(f"{p1}: не ушёл — A newer message arrived in the chat; reply not sent", line)
        self.assertIn(f"{p2}: итог неизвестен", line)
        self.assertNotIn("отправлен 1", line)
        self.assertIn("delivery only", text)   # строка промпта: о доставке — только по этому итогу

    def test_a_scheduled_reply_without_a_receipt_is_not_sent(self):
        p1 = self.reply("k1")
        self.assertEqual(self.item("k1")["status"], "sending")
        _, line = self.ask_next("k2")
        self.assertIn(f"{p1}: ещё не отправлен", line)

    def test_other_conversations_and_items_without_our_reply_stay_out(self):
        self.reply("k1")
        post = self.incoming("x1", contact="wa:other", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        text = [t for _, t in self.io.asked if post in t][-1]
        line = [x for x in text.splitlines() if x.startswith("- " + post)][0]
        self.assertNotIn("прежние ответы", line)


if __name__ == "__main__":
    unittest.main()
