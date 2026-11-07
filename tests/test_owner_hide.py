"""Скрытие пункта Inbox владельцем (20.10, d3452): клиент пишет в канал teams пост {"kind":"hide","ids":[…]}; сборщик
teams его не разбирает (скрытое помнит только клиент), а proactivity читала из канала лишь посты сборщика — владелец убрал
пункт Miguel (p3332), а разбор положил под него черновик и держал пункт открытым (draft)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_proactivity import Case, engine, msg  # noqa: E402


class OwnerHide(Case):
    def setUp(self):
        super().setUp()
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})

    def hide(self, *ids, by="owner", kind="hide"):
        self.eng.teams(self.entry(by), {"kind": kind, "ids": list(ids)})

    def test_hidden_item_is_closed_and_a_later_verdict_does_not_reopen_it(self):
        post = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item("k1")["status"], "asked")
        self.hide("k1")
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.verdict(post, do="draft", why="ответить", text="Dale")
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.assertEqual(self.io.teams_posts, [])

    def test_repost_of_the_same_message_does_not_reopen_a_hidden_item(self):
        # p3372: сборщик дочитал текст и перепостил тот же id — пункт снова пошёл в разбор и стал draft
        self.incoming("k1", contact="wa:1", src="whatsapp", inbox={"version": 1})
        self.hide("k1")
        self.incoming("k1", contact="wa:1", src="whatsapp", text="дочитанный текст", inbox={"version": 2})
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.assertEqual(self.io.asked, [])

    def test_repost_after_the_item_was_pruned_stays_hidden(self):
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.hide("k1")
        del self.st["items"]["k1"]
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.assertEqual(self.io.asked, [])

    def test_a_new_message_of_the_same_chat_surfaces_as_usual(self):
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.hide("k1")
        self.io.t += engine.SERIES + 1
        post = self.incoming("k2", contact="wa:1", src="whatsapp", text="¿Qué necesitás?")
        self.advance(engine.SERIES_QUIET + 1)
        self.assertEqual(self.item("k2")["status"], "asked")
        self.assertIn(post, self.io.asked[-1][1])

    def test_a_draft_of_the_hidden_item_does_not_move_to_the_new_message(self):
        post = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        self.verdict(post, do="draft", why="ответить", text="Dale, probemos")
        self.assertEqual(self.item("k1")["status"], "draft")
        self.hide("k1")
        self.assertEqual(self.item("k1")["status"], "ignored")
        sent = len(self.io.teams_posts)
        self.teams({"kind": "answered", "id": "k1", "newer": "k2"})
        self.incoming("k2", contact="wa:1", src="whatsapp", text="otra cosa")
        self.assertEqual(self.io.teams_posts[sent:], [])
        self.assertEqual(self.item("k1")["status"], "ignored")

    def test_teams_closing_a_hidden_card_is_not_the_owner_speaking(self):
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.hide("k1")
        self.teams({"kind": "answered", "id": "k1"})
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.assertNotIn("wa:1", self.st.get("owner_at") or {})

    def test_hiding_an_autoreply_being_sent_cancels_it_in_teams(self):
        post = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        it = self.item("k1")
        it["status"], it["rid"] = "sending", "r1"
        self.st["rids"]["r1"] = "k1"
        self.hide("k1")
        self.assertIn(({"kind": "dismiss", "id": "k1"}, None), self.io.teams_posts)
        self.teams({"kind": "canceled", "id": "k1", "rid": "r1"})
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.assertTrue(post)

    def test_only_the_owner_hides(self):
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.hide("k1", by="inbox-sess")
        self.hide("k1", by="плагин teams")
        self.assertEqual(self.item("k1")["status"], "new")

    def test_hidden_mark_reaches_an_item_that_was_open_before_the_fix(self):
        # живое состояние: пункт уже draft, скрытие записано в hidden (правка состояния) — такт сам закрывает его
        post = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.advance(engine.SERIES_QUIET + 1)
        self.verdict(post, do="draft", why="ответить", text="Dale")
        self.st.setdefault("hidden", {})["k1"] = self.io.t
        self.eng.tick()
        self.assertEqual(self.item("k1")["status"], "ignored")

    def test_unhide_drops_the_mark_without_reopening(self):
        self.incoming("k1", contact="wa:1", src="whatsapp", inbox={"version": 1})
        self.hide("k1")
        self.hide("k1", kind="unhide")
        self.assertNotIn("k1", self.st.get("hidden") or {})
        self.assertEqual(self.item("k1")["status"], "ignored")
        self.incoming("k1", contact="wa:1", src="whatsapp", inbox={"version": 2})
        self.assertEqual(self.item("k1")["status"], "new")


if __name__ == "__main__":
    unittest.main()
