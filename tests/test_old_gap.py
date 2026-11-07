"""Сообщение, заменённое новым той же серии (old + next), уходит из Inbox вместе с концом цепочки (06.11).

Два письма-уведомления одного отправителя подряд: первое становится old со ссылкой next на второе, второе разобрано
и снято (dismiss), а первое висело в Inbox владельца навсегда — вердикт по old плагин отбрасывает, dismiss давали
только устаревшим черновикам. Теперь old с next снимается, когда конец цепочки той же переписки снят нашим dismiss.
Конец, на который ответил владелец сам, открытый конец или скрытое владельцем сообщение — не повод.
"""
import unittest

from test_proactivity import Case


class OldGap(Case):
    def dismissed(self, key):
        return [d for d, _ in self.io.teams_posts if d.get("kind") == "dismiss" and d.get("id") == key]

    def series(self):
        self.incoming("k1", contact="mail:1", src="email", text="Ваше бронирование подтверждено")
        self.eng.tick()
        post = self.incoming("k2", contact="mail:1", src="email", text="Запрос на особые условия одобрен")
        self.advance(15 * 60)          # серия затихла — второе ушло разборщику
        self.assertEqual((self.item("k1")["status"], self.item("k1").get("next")), ("old", "k2"))
        return post

    def test_a_replaced_message_leaves_with_the_dismissed_end_of_its_chain(self):
        post = self.series()
        self.verdict(post, do="done", why="уведомление")
        self.eng.tick()
        self.assertEqual(len(self.dismissed("k2")), 1)
        self.assertEqual(len(self.dismissed("k1")), 1)     # на старом коде — 0: висит в Inbox
        self.eng.tick()
        self.assertEqual(len(self.dismissed("k1")), 1)     # один раз

    def test_an_open_end_keeps_the_replaced_message(self):
        self.series()
        self.eng.tick()
        self.assertEqual(self.dismissed("k1"), [])

    def test_an_end_the_owner_answered_himself_keeps_it(self):
        self.series()
        self.teams({"kind": "answered", "id": "k2"})
        self.eng.tick()
        self.assertEqual(self.dismissed("k2"), [])
        self.assertEqual(self.dismissed("k1"), [])

    def test_a_hidden_or_too_old_replaced_message_is_left_alone(self):
        post = self.series()
        self.item("k1")["hidden"] = True
        self.verdict(post, do="done", why="уведомление")
        self.eng.tick()
        self.assertEqual(self.dismissed("k1"), [])
        self.item("k1").pop("hidden")
        self.item("k1")["came"] = self.io.t - 4 * 86400
        self.eng.tick()
        self.assertEqual(self.dismissed("k1"), [])

    def test_a_chain_to_another_contact_is_not_followed(self):
        post = self.series()
        self.item("k2")["contact"] = "mail:2"
        self.verdict(post, do="done", why="уведомление")
        self.eng.tick()
        self.assertEqual(self.dismissed("k1"), [])


if __name__ == "__main__":
    unittest.main()
