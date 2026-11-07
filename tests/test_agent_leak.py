"""27.10 (d4531): межагентная переписка не попадает в Inbox владельца. teams публикует сообщение агента коллеги видом
agent_msg (клиенты его не рисуют); пункт в proactivity ведётся как агентский (отвечает хаб), и только если разбор
решил, что нужен владелец (escalate/draft), proactivity просит teams показать его постом surface — ровно один раз."""
import unittest

from test_proactivity import Case, msg  # noqa: F401 — общая заглушка ящика


def surfaces(io):
    return [d for d, _ in io.teams_posts if isinstance(d, dict) and d.get("kind") == "surface"]


class AgentLeak(Case):
    def held(self, key="k1", **kw):
        e = self.entry("плагин teams")
        self.eng.teams(e, {**msg(key, **kw), "kind": "agent_msg", "sign": True})
        return e["id"]

    def test_agent_msg_makes_an_agent_item(self):
        self.held("k1", text="Привет\n\n— 🤖 агент hospital, хаб коллеги")
        self.assertTrue(self.item("k1")["agent"])

    def test_escalate_surfaces_once(self):
        post = self.held("k1")
        self.eng.tick()
        self.verdict(post, do="escalate", why="Деньги", ask="Оплатить?")
        self.assertEqual(surfaces(self.io), [{"kind": "surface", "id": "k1"}])
        self.verdict(post, do="escalate", why="Деньги", ask="Оплатить?")
        self.eng.tick()
        self.assertEqual(len(surfaces(self.io)), 1)

    def test_done_and_noise_never_surface(self):
        for do, key in (("done", "k1"), ("noise", "k2"), ("wait", "k3"), ("delegated", "k4")):
            post = self.held(key)
            self.eng.tick()
            self.verdict(post, do=do, why="x", who="relay")
        self.assertEqual(surfaces(self.io), [])

    def test_plain_msg_never_surfaces(self):
        post = self.incoming("k1")
        self.eng.tick()
        self.verdict(post, do="escalate", why="Деньги", ask="Оплатить?")
        self.assertEqual(surfaces(self.io), [])

    def test_signature_list_matches_teams(self):
        from rules import colleague_agent
        for t in ("Готово\n— 🤖 агент hospital, хаб коллеги", "[агент codex] привет", "агент dot, от имени коллеги"):
            self.assertTrue(colleague_agent(t), t)
        self.assertFalse(colleague_agent("Агент недвижимости звонил, перезвони"))

    def test_delegated_agent_msg_stays_out_of_the_owner_digest(self):
        # 30.10 (d4651): сводка «Inbox · сводка» перечисляла в «Поручено» техническое сообщение агента коллеги,
        # которое владелец по правилу выше не видит; человека — по-прежнему перечисляет
        agent, human = self.held("k1"), self.incoming("k2")
        self.eng.tick()
        self.verdict(agent, do="delegated", who="dev-agent", why="Агент: ветка влита, нужен деплой")
        self.verdict(human, do="delegated", who="dev-agent", why="Просит проверить падение сборки")
        self.advance(3 * 3600)
        (_, text, _), = self.io.notes
        self.assertIn("Просит проверить падение сборки", text)
        self.assertNotIn("ветка влита", text)
        self.assertIn("Поручено (1):", text)

    def test_digest_of_agent_msgs_only_is_not_written(self):
        post = self.held("k1")
        self.eng.tick()
        self.verdict(post, do="delegated", who="dev-agent", why="Агент: ветка влита")
        self.advance(3 * 3600)
        self.assertEqual(self.io.notes, [])

    def test_surfaced_agent_msg_delegated_later_is_still_in_the_digest(self):
        # владелец его уже видел (escalate → surface): итог поручения в сводке остаётся
        post = self.held("k1")
        self.eng.tick()
        self.verdict(post, do="escalate", why="Деньги", ask="Оплатить?")
        self.assertEqual(len(surfaces(self.io)), 1)
        self.verdict(post, do="delegated", who="dev-agent", why="Оплату ведёт dev-agent")
        self.assertEqual(self.item("k1")["status"], "delegated")
        self.advance(3 * 3600)
        self.assertIn("Оплату ведёт dev-agent", self.io.notes[-1][1])


if __name__ == "__main__":
    unittest.main()
