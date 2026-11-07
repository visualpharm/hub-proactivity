"""link-fade, шаг 2 (28.10): ответ владельца, доказанный сборщиком (`answered` с `out`), гасит черновик под постом и
оставляет след в closes; «Не показывать» (ignore) снимает пункт у владельца — dismiss сборщику; один раз на старте
плагин сверяет слепок с этим. Ключи нейтральные. Запуск: из папки плагина, как весь набор."""
import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_proactivity import Case, T0, engine  # noqa: E402


class LinkFade(Case):
    def setUp(self):
        super().setUp()
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})

    def card(self, key="k1", **kw):
        post = self.incoming(key, **{"contact": "wa:1", "src": "whatsapp", **kw})
        self.eng.tick()
        return post

    def draft(self, post, text="Ok, mañana te confirmo"):
        self.eng.draft_seen(self.entry("hub"), post, text)

    def test_a_proven_reply_removes_the_draft_and_leaves_a_trace(self):
        post = self.card()
        self.draft(post)
        self.assertIn(post, self.st["drafts"])
        self.io.t += 120
        self.teams({"kind": "answered", "id": "k1", "out": "2027-01-15T08:01:30Z"})
        self.assertEqual(self.item()["status"], "answered")
        self.assertNotIn(post, self.st["drafts"])
        self.assertEqual(self.st["drafts_archive"][-1]["post"], post)
        (row,) = self.io.closes
        self.assertEqual((row["item"], row["out"], row["what"]), ("k1", "2027-01-15T08:01:30Z", ["draft"]))

    def test_an_answered_without_out_keeps_the_draft(self):
        # «answered» без исходящего — закрытие карточки не владельцем (удалил собеседник, читалка): черновик не трогаем
        post = self.card()
        self.draft(post)
        self.teams({"kind": "answered", "id": "k1"})
        self.assertIn(post, self.st["drafts"])
        self.assertEqual(self.io.closes, [])

    def test_the_same_reply_twice_is_one_trace(self):
        post = self.card()
        self.draft(post)
        for _ in range(2):
            self.teams({"kind": "answered", "id": "k1", "out": "2027-01-15T08:01:30Z"})
        self.assertEqual(len(self.io.closes), 1)

    def test_no_more_than_twenty_cleanups_a_day(self):
        for n in range(22):
            post = self.card(f"k{n}", contact=f"wa:{n}")
            self.draft(post)
            self.teams({"kind": "answered", "id": f"k{n}", "out": "2027-01-15T08:01:30Z"})
        self.assertEqual(len(self.io.closes), 20)
        self.assertEqual([f for f in self.io.facts if f[0] == "fade_limit"].__len__(), 1)   # тревога одна
        self.assertIn(self.item("k21")["status"], ("answered",))   # статус дела от лимита не зависит

    def test_ignored_card_is_dismissed_at_the_collector(self):
        self.card()
        self.teams({"kind": "ignore", "id": "k1"})
        self.eng.tick()
        self.assertEqual(self.item()["status"], "ignored")
        self.assertIn(({"kind": "dismiss", "id": "k1"}, None), self.io.teams_posts)

    def test_the_dismiss_echo_does_not_turn_ignored_into_answered(self):
        self.card()
        self.teams({"kind": "ignore", "id": "k1"})
        self.eng.tick()
        self.teams({"kind": "answered", "id": "k1"})   # сборщик закрыл по нашему dismiss
        self.assertEqual(self.item()["status"], "ignored")

    def test_start_reconcile_dismisses_old_ignored_once(self):
        post = self.card()
        self.draft(post)
        it = self.item()
        it["status"], it["dismissed"] = "ignored", False   # слепок до правки: ignored не снимали у сборщика
        self.st.pop("fade_v", None)
        self.io.teams_posts.clear()
        self.eng.tick()
        self.assertEqual(self.io.teams_posts.count(({"kind": "dismiss", "id": "k1"}, None)), 1)
        self.assertEqual(self.io.closes[0]["what"], ["dismiss"])
        n = len(self.io.closes)
        self.eng.tick()
        self.assertEqual(len(self.io.closes), n)


if __name__ == "__main__":
    unittest.main()
