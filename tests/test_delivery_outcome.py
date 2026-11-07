"""Итог автоответа (20.10, d3412; хвосты inbox-predraft m3212).

1. Teams-ответы Саше и коллегау (p2772, p2852, p2892) ушли — teams прислал `sent` с квитанцией Graph, — а пункты
   висели в sending: квитанция несёт версию Inbox уже после отправки (`inbox`), версия, на которую слали, — в
   `submitted_inbox`; плагин сверял первую и отбрасывал квитанцию.
2. Восемь автоответов teams отклонил до отправки (send_blocked) — пункты ушли в blocked, текста владелец не видел. Отказ
   до транспорта значит «не ушло»: текст ложится черновиком под сообщение с причиной, владелец отправляет кнопкой.
3. Итога нет вовсе (или он неизвестен) — пункт не висит в sending: после срока он unresolved, текст — черновиком с
   пометкой «доставка не подтверждена»; повторной отправки нет.
"""
import unittest

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика
import engine

TOKEN = {"v": 1, "version": "v1", "manual_followup": False, "edit_version": 0, "held": False, "holder": None}
AFTER = {**TOKEN, "version": "v2", "manual_followup": True}
TEXT = "Получил, посмотрю до вечера"


class Outcome(Case):
    def setUp(self):
        super().setUp()
        self.eng.own(self.entry("owner"), {"kind": "settings", "preset": "everyone"}, owner_word=True)
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False, "inbox_guard": True})

    def send(self, key="k1", **kw):
        post = self.incoming(key, sign=True, **kw)
        self.eng.tick()
        self.verdict(post, do="reply", type="ack", text=TEXT, why="Саша прислал релиз",
                     **({"inbox": kw["inbox"]} if kw.get("inbox") else {}))
        self.assertEqual(self.item(key)["status"], "sending")
        return post, self.io.teams_posts[-1][0]["rid"]

    def sends(self):
        return [d for d, _ in self.io.teams_posts if d.get("kind") == "send"]

    def drafts(self):
        return [(d["text"], to) for d, to in self.io.teams_posts if "kind" not in d]

    # --- 1. квитанция ----------------------------------------------------------------------------------------------
    def test_a_teams_receipt_for_the_submitted_version_closes_the_item_as_replied(self):
        _, rid = self.send(inbox=TOKEN)
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": AFTER, "submitted_inbox": TOKEN,
                    "receipt": {"source": "teams", "id": "1792506959419", "destination": "d"}})
        self.assertEqual(self.item()["status"], "replied")
        self.assertEqual(self.item()["inbox"], AFTER)   # дальше — версия после отправки

    def test_a_receipt_for_another_version_or_without_a_message_id_is_not_trusted(self):
        _, rid = self.send(inbox=TOKEN)
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": AFTER, "submitted_inbox": {**TOKEN, "version": "v0"},
                    "receipt": {"source": "teams", "id": "1", "destination": "d"}})
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": AFTER, "submitted_inbox": TOKEN, "receipt": {}})
        self.assertEqual(self.item()["status"], "sending")
        self.assertEqual([w for w, _ in self.io.facts].count("unverified_or_stale_receipt"), 2)

    def test_a_receipt_is_matched_to_the_version_that_was_sent_even_if_the_draft_moved_since(self):
        _, rid = self.send(inbox=TOKEN)
        self.teams({"kind": "draft_state", "id": "k1", "inbox": {**TOKEN, "version": "v1b", "edit_version": 1}})
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": AFTER, "submitted_inbox": TOKEN,
                    "receipt": {"source": "teams", "id": "1", "destination": "d"}})
        self.assertEqual(self.item()["status"], "replied")

    def test_a_mismatched_submitted_version_is_not_rescued_by_the_post_send_version(self):
        _, rid = self.send(inbox=TOKEN)
        self.teams({"kind": "sent", "id": "k1", "rid": rid, "inbox": TOKEN, "submitted_inbox": {**TOKEN, "version": "v0"},
                    "receipt": {"source": "teams", "id": "1", "destination": "d"}})
        self.assertEqual(self.item()["status"], "sending")

    # --- 2. отказ до отправки -------------------------------------------------------------------------------------
    def test_a_blocked_autoreply_becomes_a_draft_under_the_message_with_the_reason(self):
        post, rid = self.send(src="whatsapp")
        self.teams({"kind": "send_blocked", "id": "k1", "rid": rid, "reason": "newer_messages",
                    "error": "A newer message arrived in the chat; reply not sent. Review it and send again"})
        self.assertEqual(self.item()["status"], "draft")
        (text, to), = self.drafts()
        self.assertEqual(to, post)
        reply, _, private = text.partition("\n---\n")
        self.assertEqual(reply, TEXT)                       # без подписи «от лица»: отправит владелец, подпишет клиент
        self.assertIn("A newer message arrived", private)
        self.assertEqual(len(self.sends()), 1)              # сам не повторяет
        self.teams({"kind": "send_blocked", "id": "k1", "rid": rid, "error": "x"})   # teams повторил ответ на rid
        self.assertEqual(len(self.drafts()), 1)

    def test_a_block_after_a_newer_message_lays_the_draft_under_the_open_card(self):
        self.send(contact="wa:1", src="whatsapp")
        rid = self.item()["rid"]
        self.teams({"kind": "answered", "id": "k1", "newer": "k2"})
        b = self.incoming("k2", contact="wa:1", src="whatsapp")
        self.teams({"kind": "send_blocked", "id": "k1", "rid": rid, "error": "The canonical source item is no longer open"})
        self.assertEqual([to for _, to in self.drafts()], [b])
        self.assertEqual(self.item()["status"], "old")
        self.assertEqual(len(self.sends()), 1)

    def test_a_block_after_the_owner_closed_the_card_himself_stays_closed(self):
        # p2932: владелец ответил Саше сам в 14:24, отказ teams пришёл в 14:25 — черновик уже не нужен
        _, rid = self.send()
        self.teams({"kind": "answered", "id": "k1"})
        self.teams({"kind": "send_blocked", "id": "k1", "rid": rid, "error": "The canonical source item is no longer open"})
        self.assertEqual(self.item()["status"], "answered")
        self.assertEqual(self.drafts(), [])
        self.assertEqual((self.io.notes, self.io.todos), ([], []))

    def test_a_held_duplicate_is_a_block_too(self):
        # 19.10 08:00, p2480/p2520: teams на повтор rid ответил send_duplicate state=held — не ушло
        post, rid = self.send(inbox=TOKEN)
        self.teams({"kind": "send_duplicate", "id": "k1", "rid": rid, "state": "held", "version": "v1"})
        self.assertEqual(self.item()["status"], "draft")
        self.assertEqual([to for _, to in self.drafts()], [post])

    # --- 3. итога нет или он неизвестен -----------------------------------------------------------------------------
    def test_no_outcome_after_the_deadline_is_unresolved_and_shown_as_an_unconfirmed_draft(self):
        post, rid = self.send()
        self.advance(engine.SEND_WAIT - 60)
        self.assertEqual(self.item()["status"], "sending")
        self.advance(3600)
        self.assertEqual(self.item()["status"], "unresolved")
        (text, to), = self.drafts()
        self.assertEqual(to, post)
        self.assertIn("доставка не подтверждена", text.partition("\n---\n")[2])
        self.assertEqual(len(self.sends()), 1)
        self.assertEqual((self.io.notes, self.io.todos), ([], []))
        self.advance(3600)
        self.assertEqual(len(self.drafts()), 1)             # один раз
        self.teams({"kind": "sent", "id": "k1", "rid": rid})   # итог пришёл позже — ушло
        self.assertEqual(self.item()["status"], "replied")

    def test_a_send_scheduled_for_later_is_not_timed_out_before_its_time(self):
        _, rid = self.send()
        self.teams({"kind": "scheduled", "id": "k1", "rid": rid, "at": engine.iso(self.io.t + 10 * 3600), "held": "hours"})
        self.advance(9 * 3600)
        self.assertEqual(self.item()["status"], "sending")
        self.advance(3600 + engine.SEND_WAIT + 60)
        self.assertEqual(self.item()["status"], "unresolved")

    def test_an_uncertain_outcome_is_unresolved_draft_without_retry(self):
        post, rid = self.send()
        self.teams({"kind": "send_uncertain", "id": "k1", "rid": rid,
                    "error": "Delivery outcome needs reconciliation; no automatic retry"})
        self.assertEqual(self.item()["status"], "unresolved")
        (text, to), = self.drafts()
        self.assertEqual(to, post)
        self.assertIn("доставка не подтверждена", text)
        self.advance(3 * 3600)
        self.assertEqual(len(self.sends()), 1)
        self.assertEqual((self.io.notes, self.io.todos), ([], []))


if __name__ == "__main__":
    unittest.main()
