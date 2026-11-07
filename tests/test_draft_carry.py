"""Черновик идёт за перепиской (20.10, d3292; владелец m3252: «I requested to draft and it's still not here»).
Мигель: ✨ на p3012 в 18:25, hub-core положил черновик под p3012 в 18:26, в 18:27 Мигель дописал — teams закрыл
p3012 (answered, newer) и открыл p3092; черновик разбора 18:43 лёг под p3092, закрытый за 16 с до того новым
p3172. Клиенты показывают черновик только под постом открытой карточки — оба пропали. Черновик (сессии или разбора),
положенный под пункт, который заменило новое сообщение той же переписки, переносится на открытый пункт; наружу
ничего не уходит."""
import json
import os
import tempfile
import time
import unittest

from test_proactivity import Case, msg  # noqa: F401 — общая заглушка ящика
import engine
import main


class DraftCarry(Case):
    def setUp(self):
        super().setUp()
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})

    def draft(self, post, text, by="hub-core"):
        self.eng.draft_seen(self.entry(by), post, text)

    def supersede(self, old, new, **kw):
        self.teams({"kind": "answered", "id": old, "newer": new})
        return self.incoming(new, contact="wa:1", src="whatsapp", **kw)

    def carried(self):
        return [(d.get("text") if isinstance(d, dict) else d, to) for d, to in self.io.teams_posts
                if not (isinstance(d, dict) and d.get("kind"))]

    def test_a_session_draft_follows_the_newer_message_of_the_same_conversation(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp", text="¿Cuántos kWh tiene la batería?")
        self.draft(a, "Unos 29,6 kWh.\n---\nContext: ficha del Shark")
        self.io.t += 60
        b = self.supersede("k1", "k2", text="¿Cuántos kWh tiene la batería? · Para cargarla de 0 a 100%")
        got = self.carried()
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0][1], b)
        self.assertTrue(got[0][0].startswith("Unos 29,6 kWh.\n---\n"))
        self.assertIn(a, got[0][0])   # откуда перенесён — в приватной части, под «---»
        self.assertNotIn("send", [d.get("kind") for d, _ in self.io.teams_posts if isinstance(d, dict)])

    def test_a_draft_that_lands_after_the_card_was_replaced_goes_to_the_open_card(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.io.t += 60
        b = self.supersede("k1", "k2")
        self.draft(a, "Unos 29,6 kWh.")
        self.assertEqual([to for _, to in self.carried()], [b])

    def test_the_chain_ends_at_the_open_card_and_carries_once(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Borrador 1")
        b = self.supersede("k1", "k2")
        c = self.supersede("k2", "k3")
        got = self.carried()
        self.assertEqual([to for t, to in got if t.startswith("Borrador 1")], [b])   # копия одна — под b
        self.assertEqual(self.st["drafts"][c].get("shown"), b)   # у c клиенты покажут её по цепочке замен
        self.assertIn(("draft_carry_shown", {"from": a, "under": b, "to": c, "item": "k3"}), self.io.facts)

    def test_only_the_freshest_draft_of_the_replaced_cards_is_carried(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Borrador 1")
        self.io.t += 60
        b = self.supersede("k1", "k2")
        self.io.t += 60
        self.draft(b, "Borrador 2", by="плагин proactivity")
        self.io.t += 60
        c = self.supersede("k2", "k3")
        to_c = [t for t, to in self.carried() if to == c]
        self.assertEqual(len(to_c), 1, to_c)
        self.assertTrue(to_c[0].startswith("Borrador 2"))

    def test_a_triage_verdict_for_a_replaced_card_is_laid_under_the_open_card_and_not_sent(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.eng.tick()
        b = self.supersede("k1", "k2")
        self.verdict(a, do="reply", type="answer", text="Unos 29,6 kWh.", why="pregunta la batería")
        got = self.carried()
        self.assertEqual([to for _, to in got], [b])
        self.assertTrue(got[0][0].startswith("Unos 29,6 kWh.\n---\n"))
        self.assertNotIn("send", [d.get("kind") for d, _ in self.io.teams_posts if isinstance(d, dict)])
        self.assertEqual(self.item("k1")["status"], "old")

    def test_the_open_card_with_its_own_draft_keeps_it(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        b = self.supersede("k1", "k2")
        self.draft(b, "Gracias Miguel, sí, son unos 29 kWh.", by="плагин proactivity")
        self.draft(a, "Unos 29,6 kWh.")
        self.assertEqual(self.carried(), [])

    def test_a_late_verdict_does_not_cover_the_open_cards_own_triage_draft(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        b = self.supersede("k1", "k2")
        self.advance(engine.SERIES_QUIET + 1)
        self.verdict(b, do="draft", type="answer", text="Gracias Miguel, sí, son unos 29 kWh.", why="nuevo")
        self.verdict(a, do="draft", type="answer", text="Unos 29,6 kWh.", why="viejo")   # эхо черновика b ещё в пути
        self.assertEqual([to for _, to in self.carried()], [b])
        self.assertTrue(self.carried()[0][0].startswith("Gracias"))

    def test_a_newer_draft_still_reaches_a_card_that_shows_an_older_copy_by_the_chain(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Borrador 1")
        b = self.supersede("k1", "k2")
        self.io.t += 60
        c = self.supersede("k2", "k3")
        self.io.t += 60
        self.verdict(b, do="draft", type="answer", text="Borrador 2", why="tarde")   # вердикт к заменённому b
        to_c = [t for t, to in self.carried() if to == c]
        self.assertEqual(len(to_c), 1, to_c)
        self.assertTrue(to_c[0].startswith("Borrador 2"))

    def test_a_replacement_teams_did_not_confirm_still_gets_its_own_copy(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Borrador 1")
        b = self.supersede("k1", "k2")
        self.teams({"kind": "answered", "id": "k2", "newer": "k3"})
        self.item("k2").pop("replaced_by")   # замена из состояния до 21.10: клиенты могли её не знать
        c = self.incoming("k3", contact="wa:1", src="whatsapp")
        self.assertEqual([to for _, to in self.carried()], [b, c])

    def test_a_stale_draft_is_not_carried(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Viejo")
        self.io.t += engine.DRAFT_STALE + 60
        self.supersede("k1", "k2")
        self.assertEqual(self.carried(), [])

    def test_an_owner_answer_is_not_a_replacement(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Unos 29,6 kWh.")
        self.teams({"kind": "answered", "id": "k1"})   # владелец ответил сам — переносить некуда и незачем
        self.incoming("k2", contact="wa:1", src="whatsapp")
        self.assertEqual(self.carried(), [])

    def test_another_contact_does_not_get_the_draft(self):
        a = self.incoming("k1", contact="wa:1", src="whatsapp")
        self.draft(a, "Unos 29,6 kWh.")
        self.teams({"kind": "answered", "id": "k1", "newer": "k2"})
        self.incoming("k9", contact="wa:9", src="whatsapp")   # новое сообщение другого человека
        self.assertEqual(self.carried(), [])


class CarryReplay(Case):
    """Реплей 21.10 13:19–13:28 (d3809, журнал journal-1-2): разбор положил черновик под p3652 (Alex,
    Telegram); через 4 мин она дописала — teams закрыл p3652 (newer) и открыл p3732, черновик перенесён под него;
    ещё через 134 с — p3769, и тот же черновик лёг второй раз («Перенесён из p3652»): две одинаковые строки в ленте.
    Клиенты показывают у открытой карточки черновик заменённого сообщения по цепочке — копия нужна одна."""

    TEXT = "Jajaja no le des bola a los chunks 😄"

    def setUp(self):
        super().setUp()
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})

    def at(self, seq, ts, body):
        self.io.t = ts
        self.eng.teams({"id": f"p{seq}", "by": "плагин teams", "ts": ts}, body)
        self.echo()

    def echo(self):
        """Свои посты плагин читает из журнала следующим тактом (main.Journal → draft_seen)."""
        for data, to in self.io.teams_posts[self.seen:]:
            self.n += 1
            if to and not (isinstance(data, dict) and data.get("kind")):
                text = data["text"] if isinstance(data, dict) else data
                self.eng.draft_seen({"id": f"p{self.n}", "by": "плагин proactivity", "ts": self.io.t}, to, text)
        self.seen = len(self.io.teams_posts)

    def tg(self, key, text, at):
        return {"kind": "msg", "id": key, "answered": False, "reply": True, "sign": False, "contact": "tg:100200300",
                "src": "telegram", "where": "Telegram", "from": "Alex", "text": text, "at": at,
                "link": "tg://user?id=100200300", "mention": False, "tier": "B"}

    def test_the_draft_is_carried_once_along_the_series(self):
        self.seen = 0
        self.at(3652, 1792599565.552, self.tg("tg:100200300:169336", "Recibir este chunk me confundió todo",
                                                "2026-10-21T16:18:30Z"))
        self.io.t = 1792599731.583
        self.eng.draft_seen({"id": "p3692", "by": "плагин proactivity", "ts": self.io.t}, "p3652",
                            self.TEXT + "\n---\nПочему: живая переписка, только черновик.")
        self.at(690725, 1792599976.191, {"kind": "answered", "id": "tg:100200300:169336",
                                         "newer": "tg:100200300:169353"})
        self.at(3732, 1792599976.269, self.tg("tg:100200300:169353", "I’m sure you’ll find the way.",
                                                "2026-10-21T16:24:42Z"))
        self.at(690762, 1792600109.832, {"kind": "answered", "id": "tg:100200300:169353",
                                         "newer": "tg:100200300:169361"})
        self.at(3769, 1792600109.862, self.tg("tg:100200300:169361", "I’m sure you’ll find the way. · Ignora "
                                                "100% auriculares", "2026-10-21T16:27:30Z"))
        lines = [(d, to) for d, to in self.io.teams_posts if not (isinstance(d, dict) and d.get("kind"))]
        chunks = [to for d, to in lines if (d["text"] if isinstance(d, dict) else d).startswith(self.TEXT)]
        self.assertEqual(chunks, ["p3732"])   # одна строка черновика в ленте — перенос под p3732
        self.assertIn(f"\n---\n{engine.CARRY_NOTE} p3652:", lines[0][0]["text"])
        self.assertEqual(self.st["drafts"]["p3769"].get("shown"), "p3732")
        self.assertNotIn("send", [d.get("kind") for d, _ in self.io.teams_posts if isinstance(d, dict)])


class DraftReading(unittest.TestCase):
    """Черновик в канале teams — простой текст с reply_to от сессии или плагина: разбор его видит."""

    def setUp(self):
        self.f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.addCleanup(os.unlink, self.f.name)
        self.n = 0
        self.jr = main.Journal(self.f.name)

    def add(self, **data):
        self.n += 1
        with open(self.f.name, "a", encoding="utf-8") as g:
            g.write(json.dumps({"seq": self.n, "ts": 1000 + self.n, "type": "ext.post", "entity": None, "data": data},
                               ensure_ascii=False) + "\n")
        return self.n

    def test_raw_reply_drafts_are_read_but_not_from_the_owner_or_teams(self):
        a = self.add(plugin="teams", text="Unos 29,6 kWh.", reply_to="p7", channel="session", owner=False, sender="hub-core")
        b = self.add(plugin="teams", text="Borrador", reply_to="p7", channel="plugin", owner=False, sender="ext:proactivity")
        self.add(plugin="teams", text="Mío", reply_to="p7", channel="web", owner=True)
        self.add(plugin="teams", text="x", reply_to="p7", channel="plugin", owner=False, sender="ext:teams")
        self.add(plugin="teams", text="sin destino", channel="session", owner=False, sender="hub-core")
        now = time.time()
        self.jr.read(now=now)
        got = [(x["entry"]["id"], x["entry"]["by"], x["plugin"], x["body"]) for x in self.jr.read(now=now + 10)]
        self.assertEqual(got, [(f"p{a}", "hub-core", main.DRAFT, {"reply_to": "p7", "text": "Unos 29,6 kWh."}),
                               (f"p{b}", "плагин proactivity", main.DRAFT, {"reply_to": "p7", "text": "Borrador"})])

    def test_step_hands_drafts_to_the_engine(self):
        seen = []

        class Eng:
            st = {"teams_seq": 0}

            def draft_seen(self, entry, post, text):
                seen.append((entry["id"], post, text))

            def tick(self):
                pass

        class Jr:
            def read(self, now):
                return [{"entry": {"id": "p5", "by": "hub-core", "ts": 1}, "plugin": main.DRAFT,
                         "body": {"reply_to": "p3", "text": "Hola"}}]

        class Io:
            def now(self):
                return 1

        main.step(Eng(), Io(), Jr())
        self.assertEqual(seen, [("p5", "p3", "Hola")])


if __name__ == "__main__":
    unittest.main()
