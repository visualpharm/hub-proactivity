"""Повторный разбор решённых пунктов (25.10, d4331, hub-core m4211).

Разборщиком был хаб, а он был занят: первая просьба о разборе p4089 (11:39) лежала в его очереди до 13:28. Плагин
считал 15 минут без вердикта от отправки, а не от доставки, и слал ещё три просьбы (11:57, 13:10, 13:24); в 13:29
пришёл вердикт noise, teams отметил answered — а хаб потом разобрал тот же пункт ещё три раза (14:16, 15:23, 15:33).
Так же p4129, p4049, p4169, p4171; p4171 и вовсе ушёл в untriaged за четыре попытки, ни одна из которых до
хаба не дошла. Теперь, пока прежняя просьба лежит недоставленной в очереди разборщика, плагин её не повторяет.
"""
import unittest

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика
import engine
import main


class QueuedAsk(Case):
    def setUp(self):
        super().setUp()
        self.io.pending = {}                       # сессия → посты, о которых просьба ещё в её очереди
        self.io.pending_asks = lambda: self.io.pending

    def test_p880265_one_ask_while_the_first_waits_in_the_hub_queue(self):
        post = self.incoming("wa:g:1", src="whatsapp", where="Mint · группа", contact="wa:g")
        self.eng.tick()
        self.assertEqual(len(self.io.asked), 1)
        self.io.pending = {"hub": {post}}
        for _ in range(7):                         # 11:39 → 13:28: хаб занят, просьба в очереди
            self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(len(self.io.asked), 1)
        self.assertEqual(self.item("wa:g:1")["status"], "asked")
        self.assertEqual(self.item("wa:g:1")["tries"], 1)
        self.io.pending = {}                       # 13:28 хаб взял просьбу
        self.verdict(post, do="noise", why="участники пишут друг другу")
        self.assertEqual(self.item("wa:g:1")["status"], "noise")
        self.teams({"kind": "answered", "id": "wa:g:1"})
        for _ in range(8):
            self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(len(self.io.asked), 1)

    def test_p883089_does_not_go_untriaged_while_no_ask_reached_the_triager(self):
        post = self.incoming()
        self.eng.tick()
        self.io.pending = {"hub": {post}}
        for _ in range(10):                        # 12:19 → 14:43 в очереди
            self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(self.item()["status"], "asked")
        self.assertEqual(len(self.io.asked), 1)

    def test_delivered_but_silent_triager_is_still_asked_again(self):
        post = self.incoming()
        self.eng.tick()
        self.io.pending = {"hub": {"p999"}}        # в очереди чужая просьба — наша дошла
        self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(len(self.io.asked), 2)
        self.assertIn(post, self.io.asked[-1][1])

    def test_ask_queued_at_another_session_does_not_hold_the_current_triager(self):
        post = self.incoming()
        self.eng.tick()
        self.io.pending = {"hub": {post}}
        self.io.target = "inbox"                   # появился свой разборщик — хаб больше не ждём
        self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(self.io.asked[-1][0], "inbox")

    def test_a_stuck_queue_does_not_hold_the_item_forever(self):
        post = self.incoming()
        self.eng.tick()
        self.io.pending = {"hub": {post}}
        self.advance(engine.ASK_TIMEOUT + 1)
        self.assertEqual(len(self.io.asked), 1)
        self.advance(engine.ASK_QUEUED_MAX + 1)
        self.assertEqual(len(self.io.asked), 2)


class PendingAsks(unittest.TestCase):
    """main.IO.pending_asks читает очередь сессий из состояния ядра."""

    def test_reads_undelivered_plugin_asks_from_core_messages(self):
        io = main.IO.__new__(main.IO)
        mine = {"kind": "plugin", "name": main.NAME}
        cmd = lambda posts: (f"Inbox triage ({len(posts)}), plugin proactivity. Read each exact accepted source: "
                             f"`hub feed teams --last 500 | grep -A1 -E '^({'|'.join(posts)}) '`.\n…")
        io._core = {"messages": {
            "m1": {"session": "hub", "state": "queued", "from": mine, "text": cmd(["p4089"])},
            "m2": {"session": "hub", "state": "typing", "from": mine, "text": cmd(["p4169", "p4171"])},
            "m3": {"session": "hub", "state": "delivered", "from": mine, "text": cmd(["p4049"])},
            "m4": {"session": "hub", "state": "queued", "from": {"kind": "owner"}, "text": cmd(["p1"])},
            "m5": {"session": "inbox", "state": "queued", "from": {"kind": "plugin", "name": "teams"},
                   "text": cmd(["p2"])},
        }}
        io._core_at = float("inf")
        self.assertEqual(io.pending_asks(), {"hub": {"p4089", "p4169", "p4171"}})

    def test_the_prompt_command_is_what_pending_asks_parses(self):
        from test_proactivity import IO
        st = engine.new_state(0)
        eng = engine.Engine(st, IO())
        batch = [{"post": "p11", "src": "dm", "key": "a", "where": "Личка", "from": "x", "contact": "c"},
                 {"post": "p12", "src": "dm", "key": "b", "where": "Личка", "from": "y", "contact": "d"}]
        found = main.ASK_POSTS.search(eng.prompt(batch, "draft"))
        self.assertEqual(found.group(1).split("|"), ["p11", "p12"])


if __name__ == "__main__":
    unittest.main()
