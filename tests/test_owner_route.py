"""Дело по пункту Inbox — сессии, которая ведёт эту переписку, а не хабу (владелец 25.10, m4291: «тебе все эти
приходят в хаб вещи, которые должны в Relay приходить… отправляй туда, где самый подходящий этот тред»).
Разбор (вердикт и черновик) остаётся у быстрого разборщика: черновик должен лежать раньше, чем владелец откроет пункт
(m4251). Поручение (delegated), карточка решения (escalate) и напоминание о зависшем поручении идут сессии из
поля who вердикта; её нет среди живых — хабу, как раньше."""
import unittest

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика
import engine


class OwnerRoute(Case):
    def setUp(self):
        super().setUp()
        self.io.target = "inbox"
        self.io.owners = {"relay": "проактивный ассистент: люди, дом", "procurement": "закупки"}

    def triaged(self, key="k1", **kw):
        post = self.incoming(key, **kw)
        self.eng.tick()
        self.io.asked.clear()
        return post

    def test_triage_request_lists_the_sessions_that_may_own_the_thread(self):
        self.incoming("k1")
        self.eng.tick()
        (to, text), = self.io.asked
        self.assertEqual(to, "inbox")
        self.assertIn("· relay — проактивный ассистент: люди, дом", text)
        self.assertIn("· procurement — закупки", text)
        self.assertIn("do not message it yourself", text)

    def test_delegated_work_goes_to_the_owning_session_not_the_hub(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="delegated", who="relay", why="садовник, дом",
                     next_action="Ответить садовнику про время")
        self.assertEqual(self.item()["status"], "delegated")
        (to, text), = self.io.asked
        self.assertEqual(to, "relay")
        self.assertIn(post, text)
        self.assertIn("Ответить садовнику про время", text)
        self.assertIn('"do":"done"', text.replace(" ", ""))
        self.verdict(post, by="inbox", do="delegated", who="relay", why="повтор")
        self.assertEqual(len(self.io.asked), 1)   # повторный вердикт — второй раз не поручаем

    def test_unknown_owner_falls_back_to_the_hub(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="delegated", who="no-such-session", why="x")
        (to, _), = self.io.asked
        self.assertEqual(to, "hub")
        self.assertEqual(self.item()["v"]["who"], "hub")

    def test_owner_decision_card_goes_to_the_owning_session_and_is_withdrawn_there(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="escalate", who="relay", why="деньги", ask="оплатить садовнику 50 000?",
                     text="Hola, te confirmo mañana")
        self.eng.tick()
        cards = [(to, t) for to, t in self.io.asked if "карточку выбора" in t]
        self.assertEqual([to for to, _ in cards], ["relay"])
        self.io.asked.clear()
        self.teams({"kind": "answered", "id": "k1"})
        self.eng.tick()
        (to, text), = self.io.asked
        self.assertEqual(to, "relay")
        self.assertIn("question withdraw", text)

    def test_escalation_without_an_owner_still_goes_to_the_hub(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="escalate", why="подпись", ask="подписать договор?")
        self.eng.tick()
        self.assertEqual([to for to, t in self.io.asked if "карточку выбора" in t], ["hub"])

    def test_a_stale_delegation_is_asked_of_its_owner(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="delegated", who="relay", why="x")
        self.io.asked.clear()
        self.advance(engine.DELEGATED_STALE + 1)
        (to, text), = self.io.asked
        self.assertEqual(to, "relay")
        self.assertIn(post, text)

    def test_the_conversation_remembers_who_handled_it(self):
        post = self.triaged("k1", contact="wa:1")
        self.verdict(post, by="inbox", do="delegated", who="relay", why="x")
        self.teams({"kind": "answered", "id": "k1"})
        self.io.asked.clear()
        self.incoming("k2", contact="wa:1")
        self.advance(engine.SERIES_QUIET + 1)   # продолжение серии ждёт паузы
        (to, text), = self.io.asked
        self.assertIn("переписку раньше вёл: relay", text)

    def test_a_contact_who_wrote_about_two_subjects_is_not_pinned_to_the_last_session(self):
        """01.11 (d4771): Саша писал сессии проекта про CI, потом про хаб — подсказка «раньше вёл» называла только
        проектную сессию, и реплики про установку хаба ушли ей, а не dev-agent. Подсказка называет всех прежних
        адресатов контакта с числом дел, правило велит выбирать по теме этого сообщения."""
        self.io.owners = {"clinic-bookings": "муниципальные Turnos", "dev-agent": "Hub Developer: код этого хаба"}
        for i, who in enumerate(("dev-agent", "clinic-bookings", "clinic-bookings")):
            post = self.triaged(f"p{i}", contact="teams:sasha")
            self.verdict(post, by="inbox", do="delegated", who=who, why="x")
            self.teams({"kind": "answered", "id": f"p{i}"})
        self.io.asked.clear()
        self.incoming("p9", contact="teams:sasha")
        self.advance(engine.SERIES_QUIET + 1)
        (to, text), = self.io.asked
        self.assertIn("переписку раньше вёл: clinic-bookings (2), dev-agent (1) — выбирай по теме этого сообщения", text)
        self.assertIn("not by the person", text)
        self.assertIn("goes to the session whose description covers hub development", text)

    def test_handover_by_the_owner_is_not_sent_a_second_time(self):
        post = self.triaged()
        self.eng.handover({"id": "m5", "by": "owner", "ts": self.io.t}, {"posts": [post], "to": "relay"})
        self.assertEqual(self.item()["status"], "delegated")
        self.assertEqual(self.io.asked, [])   # слова владельца уже у relay — плагин не дублирует

    def test_verdicts_without_action_never_wake_the_hub(self):
        """27.10 (владелец m4571): хаб-core получал разбор Inbox, хотя Inbox — у inbox. Вердикт без действия
        (done/info/noise/wait) закрывает пункт без единой просьбы кому-либо; поручение живому адресату не идёт хабу."""
        for i, do in enumerate(("done", "info", "noise", "wait")):
            key = f"q{i}"
            post = self.triaged(key)
            self.verdict(post, by="inbox", do=do, why="x")
            self.eng.tick()
            self.assertEqual(self.io.asked, [], do)

    def test_nothing_in_the_triage_cycle_goes_to_the_hub_while_the_triager_lives(self):
        post = self.incoming("k1")
        self.eng.tick()
        self.verdict(post, by="inbox", do="delegated", who="relay", why="садовник")
        self.eng.tick()
        self.advance(engine.DELEGATED_STALE + 1)
        self.assertTrue(self.io.asked)
        self.assertEqual({to for to, _ in self.io.asked} & {"hub", "hub-core"}, set())


class OwnerReplyHandoff(Case):
    """28.10 (владелец: «они уже одно и то же написали, сейчас они вдвоём могут покупку одну и ту же сделать»): разборщик
    дал reply с who=procurement и готовым текстом — плагин сам отправил магазину повтор вопросов, которые procurement уже
    писала. Без сессии переписки (relay ""): ответ в переписке, которую ведёт живая сессия, — её: плагин не шлёт и не
    кладёт черновик, а поручает ей с готовым текстом; хаб (who пусто или неживой) — как раньше. С ней — RelayNoe."""

    TEXT = "Buen día, entonces el Philco lo piden a Springfield?"

    def setUp(self):
        super().setUp()
        self.io.target = "inbox"
        self.io.owners = {"relay": "проактивный ассистент", "procurement": "закупки"}
        self.eng.own(self.entry("owner"), {"kind": "settings", "preset": "everyone"}, owner_word=True)
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})

    def triaged(self, key="k1"):
        post = self.incoming(key, src="whatsapp", contact="wa:shop-" + key)
        self.eng.tick()
        self.io.asked.clear()
        return post

    def sends(self):
        return [d for d, _ in self.io.teams_posts if d.get("kind") == "send"]

    def test_reply_owned_by_a_live_session_is_handed_to_it_not_sent(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="reply", who="procurement", type="answer", text=self.TEXT,
                     why="магазин подтвердил наличие", next_action="Отправить уточнение магазину")
        self.assertEqual(self.sends(), [])
        self.assertEqual(self.io.teams_posts, [])   # и черновик под сообщением не кладём: владелец не отправит дубль
        it = self.item()
        self.assertEqual((it["status"], it.get("handed_to"), it["v"]["do"]), ("delegated", "procurement", "delegated"))
        (to, text), = self.io.asked
        self.assertEqual(to, "procurement")
        self.assertIn(self.TEXT, text)
        self.assertIn(post, text)
        self.assertIn('"do":"done"', text.replace(" ", ""))
        # повтор вердикта (тот же или draft) — идемпотентно: второго поручения и отправки нет
        self.verdict(post, by="inbox", do="reply", who="procurement", type="answer", text=self.TEXT, why="повтор")
        self.verdict(post, by="inbox", do="draft", who="procurement", text=self.TEXT, why="повтор")
        self.assertEqual(len(self.io.asked), 1)
        self.assertEqual(self.sends(), [])
        # сессия сама ответила магазину и закрыла пункт
        self.eng.own(self.entry("procurement"), {"kind": "verdict", "item": post, "do": "done", "why": "отправила",
                                                 "context": "x", "next_action": "Ничего не делать, потому что x"})
        self.assertEqual(self.item()["status"], "done")

    def test_draft_owned_by_a_live_session_is_handed_to_it_not_laid(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="draft", who="relay", text=self.TEXT, why="ответ нужен")
        self.assertEqual(self.io.teams_posts, [])
        self.assertEqual(self.item()["status"], "delegated")
        (to, text), = self.io.asked
        self.assertEqual(to, "relay")
        self.assertIn(self.TEXT, text)

    def test_reply_without_a_live_owner_is_sent_as_before(self):
        for key, who in (("k1", None), ("k2", "no-such-session"), ("k3", "hub")):
            post = self.triaged(key)
            self.verdict(post, by="inbox", do="reply", who=who, type="answer", text=self.TEXT, why="w")
            self.assertEqual(self.item(key)["status"], "sending", who)
            self.assertNotIn("handed_to", self.item(key))
        self.assertEqual(len(self.sends()), 3)
        self.assertEqual(self.io.asked, [])

    def test_an_executor_named_as_owner_hands_to_its_parent(self):
        """Исполнители в owners() не входят (их переписку ведёт родитель): who=исполнитель — поручение родителю."""
        self.io.parents = {"procurement-shop": "procurement", "sub-exec": "procurement-shop"}
        post = self.triaged()
        self.verdict(post, by="inbox", do="reply", who="sub-exec", type="answer", text=self.TEXT, why="w")
        self.assertEqual(self.sends(), [])
        (to, _), = self.io.asked
        self.assertEqual((to, self.item()["handed_to"]), ("procurement", "procurement"))

    def test_triage_rule_says_an_owned_reply_goes_to_its_session(self):
        self.incoming("k1")
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertNotIn("keep reply or draft with text", text)
        self.assertIn("hands it to that session with your text", text)


class RelayNoe(OwnerReplyHandoff):
    """28.10 (владелец m4611): вся переписка с людьми — через relay. reply/draft разборщика плагин не шлёт и эксперту темы
    не отдаёт: поручение relay с черновиком, каналом и экспертом (who); relay нет — черновик в Inbox, без отправки."""

    def setUp(self):
        super().setUp()
        self.st["cfg"]["relay"] = "relay"
        self.io.owners = {"relay": "проактивный ассистент", "procurement": "закупки"}

    def test_reply_goes_to_noe_with_draft_channel_and_expert(self):
        post = self.triaged()
        self.verdict(post, by="inbox", do="reply", who="procurement", type="answer", text=self.TEXT,
                     why="магазин подтвердил наличие")
        self.assertEqual(self.io.teams_posts, [])   # ни отправки, ни черновика под сообщением
        it = self.item()
        self.assertEqual((it["status"], it["handed_to"], it["v"]["who"], it["v"]["expert"]),
                         ("delegated", "relay", "relay", "procurement"))
        (to, text), = self.io.asked
        self.assertEqual(to, "relay")
        for part in (self.TEXT, post, "Эксперт темы: procurement", "whatsapp", "wa:shop-k1"):
            self.assertIn(part, text)
        self.verdict(post, by="inbox", do="reply", who="procurement", type="answer", text=self.TEXT, why="повтор")
        self.verdict(post, by="inbox", do="draft", who="procurement", text=self.TEXT, why="повтор")
        self.assertEqual((len(self.io.asked), self.io.teams_posts), (1, []))
        self.eng.own(self.entry("procurement"), {"kind": "verdict", "item": post, "do": "done", "why": "x",
                                                 "context": "x", "next_action": "Ничего не делать, потому что x"})
        self.assertEqual(self.item()["status"], "delegated")   # закрывает та, кому поручено
        self.eng.own(self.entry("relay"), {"kind": "verdict", "item": post, "do": "done", "why": "отправила",
                                         "context": "x", "next_action": "Ничего не делать, потому что x"})
        self.assertEqual(self.item()["status"], "done")

    def test_reply_or_draft_without_an_expert_goes_to_noe_too(self):
        for key, do, who in (("k1", "reply", None), ("k2", "draft", None), ("k3", "reply", "relay"), ("k4", "reply", "hub")):
            post = self.triaged(key)
            self.verdict(post, by="inbox", do=do, who=who, type="answer", text=self.TEXT, why="w")
            it = self.item(key)
            self.assertEqual((it["status"], it["v"]["who"], it["v"].get("expert")), ("delegated", "relay", None), key)
            (to, text), = self.io.asked   # triaged() чистит список: ровно одно поручение на пункт
            self.assertEqual(to, "relay")
            self.assertNotIn("Эксперт темы", text)
        self.assertEqual(self.sends(), [])
        self.assertEqual([r for _, r in self.io.teams_posts if r], [])   # и черновиков под сообщениями нет

    def test_without_noe_the_reply_stays_a_draft_and_nothing_is_sent(self):
        self.io.owners = {"procurement": "закупки"}
        post = self.triaged()
        self.verdict(post, by="inbox", do="reply", who="procurement", type="answer", text=self.TEXT, why="w")
        self.assertEqual(self.sends(), [])
        self.assertEqual(self.item()["status"], "draft")
        self.assertIn("relay", self.item()["v"]["held_by"])
        (data, reply_to), = self.io.teams_posts
        self.assertEqual(reply_to, post)
        self.assertTrue(data["text"].startswith(self.TEXT))
        self.assertEqual(self.io.asked, [])

    def test_an_executor_named_as_owner_hands_to_its_parent(self):
        self.io.parents = {"procurement-shop": "procurement"}
        post = self.triaged()
        self.verdict(post, by="inbox", do="reply", who="procurement-shop", type="answer", text=self.TEXT, why="w")
        (to, _), = self.io.asked
        self.assertEqual((to, self.item()["v"]["expert"]), ("relay", "procurement"))

    test_reply_owned_by_a_live_session_is_handed_to_it_not_sent = None
    test_draft_owned_by_a_live_session_is_handed_to_it_not_laid = None
    test_reply_without_a_live_owner_is_sent_as_before = None

    def test_triage_rule_says_an_owned_reply_goes_to_its_session(self):
        self.incoming("k1")
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertIn("All correspondence with people goes through the session relay", text)
        self.assertNotIn("hands it to that session with your text", text)

    def test_relay_is_an_owner_setting(self):
        self.assertEqual(engine.clean_settings({"relay": ""}, {"relay": "relay"})["relay"], "")
        self.assertEqual(engine.clean_settings({"relay": "a b;rm"}, {"relay": "relay"})["relay"], "relay")


if __name__ == "__main__":
    unittest.main()
