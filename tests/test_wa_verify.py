"""1.1.7 (d4851): делегированное/ждущее дело из личного чата WhatsApp не гасится эхом нашего dismiss, пока в чате
нет нашего исходящего позже входящего; нет за час — один раз просим ведущего переписку. И закрытое без ответа дело
помечает чат прочитанным (`send wa-read`), сбой этого вердикт не роняет."""
import unittest

from test_proactivity import IO, Case, msg, T0  # noqa: F401 — общая заглушка ящика
import engine

BOX = "wa:whatsapp:5491100000001@c.us"


class WaIO(IO):
    def __init__(self):
        super().__init__()
        self.out = {}          # цифры → время последнего исходящего (None — прочитать не вышло)
        self.reads, self.marks, self.mark_result = [], [], (True, "")

    def wa_out(self, channel, digits):
        self.reads.append((channel, digits))
        return self.out.get(digits, 0.0)

    def wa_read(self, channel, digits):
        self.marks.append((channel, digits))
        if isinstance(self.mark_result, Exception):
            raise self.mark_result
        return self.mark_result


class WaCase(Case):
    def setUp(self):
        super().setUp()
        self.io = WaIO()
        self.io.t = T0
        self.eng = engine.Engine(self.st, self.io)
        self.io.owners["relay"] = "переписка с людьми"

    def wa(self, key="k1", **kw):
        return self.incoming(key, src="whatsapp", contact=BOX, where="Mint", **kw)

    def delegated(self, key="k1", do="delegated"):
        post = self.wa(key)
        self.eng.tick()
        self.verdict(post, do=do, who="clinic-bookings", why="Закупки")
        self.eng.tick()   # dismiss уходит в teams
        self.assertTrue(self.item(key).get("dismissed"))
        self.teams({"kind": "answered", "id": key})   # эхо dismiss: сборщик закрыл карточку, исходящего нет
        return post


class Held(WaCase):
    def test_echo_of_dismiss_does_not_close_a_delegated_item(self):
        self.delegated()
        self.assertEqual(self.item()["status"], "delegated")
        self.assertIn("wa_hold", self.item())

    def test_echo_of_dismiss_does_not_close_a_waiting_item(self):
        self.delegated(do="wait")
        self.assertEqual(self.item()["status"], "awaiting")

    def test_our_outgoing_after_the_message_closes_it(self):
        self.delegated()
        self.io.out["5491100000001"] = T0 + 120
        self.advance(engine.WA_VERIFY_EVERY + 1)
        self.assertEqual(self.item()["status"], "answered")
        self.assertEqual(self.io.asked[-1][0], "clinic-bookings")   # только поручение; возврата ведущему нет
        self.assertEqual(len(self.io.asked), 2)

    def test_outgoing_before_the_message_does_not_count(self):
        self.delegated()
        self.io.out["5491100000001"] = T0 - 3600
        self.advance(engine.WA_VERIFY_EVERY + 1)
        self.assertEqual(self.item()["status"], "delegated")

    def test_no_outgoing_for_an_hour_goes_back_once(self):
        self.delegated()
        n = len(self.io.asked)
        self.advance(engine.WA_VERIFY - 60)
        self.assertEqual(len(self.io.asked), n)
        self.advance(120)
        self.advance(engine.WA_VERIFY_EVERY + 1)
        back = self.io.asked[n:]
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0][0], "clinic-bookings")   # relay в заглушке пуст — владелец дела
        self.assertIn("[proactivity k1]", back[0][1])
        self.advance(engine.WA_VERIFY_EVERY * 3)
        self.assertEqual(len(self.io.asked), n + 1)
        self.assertEqual(self.item()["status"], "delegated")

    def test_goes_back_to_the_relay_session(self):
        self.st["cfg"]["relay"] = "relay"
        self.delegated()
        n = len(self.io.asked)
        self.advance(engine.WA_VERIFY + engine.WA_VERIFY_EVERY)
        self.assertEqual([a[0] for a in self.io.asked[n:]], ["relay"])

    def test_unreadable_chat_changes_nothing(self):
        self.delegated()
        self.io.out["5491100000001"] = None
        n = len(self.io.asked)
        self.advance(engine.WA_VERIFY + engine.WA_VERIFY_EVERY)
        self.assertEqual((self.item()["status"], len(self.io.asked)), ("delegated", n))

    def test_the_assignee_closing_the_item_ends_the_hold(self):
        post = self.delegated()
        self.verdict(post, by="clinic-bookings", do="done", why="Ответили в чате")
        self.assertEqual(self.item()["status"], "done")
        self.assertNotIn("wa_hold", self.item())

    def test_other_channels_are_closed_as_before(self):
        post = self.incoming("k2", src="dm", contact="teams:chat-1")
        self.eng.tick()
        self.verdict(post, do="delegated", who="clinic-bookings", why="x")
        self.eng.tick()
        self.teams({"kind": "answered", "id": "k2"})
        self.assertEqual(self.item("k2")["status"], "answered")

    def test_a_group_chat_is_closed_as_before(self):
        post = self.incoming("k3", src="whatsapp", contact="wa:whatsapp:120363@g.us")
        self.eng.tick()
        self.verdict(post, do="delegated", who="clinic-bookings", why="x")
        self.eng.tick()
        self.teams({"kind": "answered", "id": "k3"})
        self.assertEqual(self.item("k3")["status"], "answered")

    def test_the_owner_answer_with_proof_closes_it(self):
        self.delegated()
        self.teams({"kind": "answered", "id": "k1", "out": "2027-01-15T08:20:00Z"})
        self.assertEqual(self.item()["status"], "answered")


class MarkRead(WaCase):
    def test_done_info_and_noise_mark_the_chat_read(self):
        for key, do in (("k1", "done"), ("k2", "info"), ("k3", "noise")):
            post = self.wa(key)
            self.eng.tick()
            self.verdict(post, do=do, why="Без ответа")
            self.assertEqual(self.item(key).get("wa_read"), True, do)
        self.assertEqual(self.io.marks, [("whatsapp", "5491100000001")] * 3)

    def test_other_verdicts_do_not_mark_it(self):
        post = self.wa("k1")
        self.eng.tick()
        self.verdict(post, do="delegated", who="clinic-bookings", why="x")
        self.assertEqual(self.io.marks, [])

    def test_non_whatsapp_is_not_marked(self):
        post = self.incoming("k2", src="dm", contact="teams:chat-1")
        self.eng.tick()
        self.verdict(post, do="done", why="x")
        self.assertEqual(self.io.marks, [])

    def test_failure_does_not_break_the_verdict_and_is_logged_once(self):
        self.io.mark_result = (False, "wa-read: нет такой команды")
        post = self.wa("k1")
        self.eng.tick()
        self.verdict(post, do="done", why="x")
        self.assertEqual((self.item()["status"], self.item()["wa_read"]), ("done", False))
        self.assertEqual([f for f, _ in self.io.facts if f == "wa_read_failed"], ["wa_read_failed"])
        self.verdict(post, do="done", why="x")
        self.assertEqual(len(self.io.marks), 1)

    def test_exception_does_not_break_the_verdict(self):
        self.io.mark_result = OSError("нет команды")
        post = self.wa("k1")
        self.eng.tick()
        self.verdict(post, do="noise", why="x")
        self.assertEqual(self.item()["status"], "noise")

    def test_assignee_done_marks_it(self):
        post = self.delegated()
        self.verdict(post, by="clinic-bookings", do="done", why="Ответили")
        self.assertEqual(self.io.marks, [("whatsapp", "5491100000001")])

    def test_switch_off_in_settings(self):
        self.st["cfg"]["wa_read"] = False
        post = self.wa("k1")
        self.eng.tick()
        self.verdict(post, do="done", why="x")
        self.assertEqual(self.io.marks, [])


if __name__ == "__main__":
    unittest.main()
