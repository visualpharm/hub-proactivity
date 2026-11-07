"""Спам режется на входе (06.11, d4931: «Inbox застрял, и со спамом и казино»).

Группа Telegram с игорной рекламой слала одно и то же 12 раз за полтора часа; каждое сообщение уходило разборщику и
висело в Inbox владельца, пока ядро было медленным. Теперь игорная реклама (два признака и больше) и письмо со строкой
отписки — шум на входе: разборщик их не видит, из Inbox они уходят сами (dismiss), в сводке строкой «спам ×N».
Один признак — не спам: живой человек может написать «ходили в казино» или «бонус к зарплате».
"""
import unittest

import rules
from test_proactivity import Case

CASINO = ("IRIS: 👑 ELITE CASINO CHAT 👑 Добро пожаловать в наш закрытый игровой клуб! Мы ценим своих игроков, поэтому "
          "дарим новичкам Приветственный Пакет 350% на старте. Это твой шанс испытать удачу.")
COLD = ("make your handbook truly accessible Hi the owner, thought this could help your team. "
        "If you don't want to hear from me again, just let me know.")


class SpamCut(Case):
    def dismissed(self, key):
        return [d for d, _ in self.io.teams_posts if d.get("kind") == "dismiss" and d.get("id") == key]

    def test_a_casino_group_is_noise_on_arrival_and_leaves_the_inbox(self):
        self.incoming("k1", src="telegram", where="Telegram · группа", text=CASINO, **{"from": "Сладость победы"})
        self.eng.tick()
        self.assertEqual(self.io.asked, [])                    # разборщику не ушло
        self.assertEqual(self.item()["status"], "noise")
        self.assertEqual(self.item()["noise"], "спам")
        self.assertEqual(len(self.dismissed("k1")), 1)          # из Inbox владельца уходит само

    def test_a_cold_email_with_an_opt_out_line_is_a_newsletter(self):
        self.incoming("k1", src="email", where="Почта", text=COLD, **{"from": "Liam Benjamin"})
        self.eng.tick()
        self.assertEqual(self.io.asked, [])
        self.assertEqual((self.item()["status"], self.item()["noise"]), ("noise", "рассылка"))
        self.assertEqual(len(self.dismissed("k1")), 1)

    def test_spam_is_counted_in_the_digest(self):
        self.incoming("k1", src="telegram", text=CASINO)
        self.incoming("k2", src="email", text=COLD)
        self.eng.tick()
        self.advance(3 * 3600 + 1)
        (title, text, _), = self.io.notes
        self.assertIn("спам ×1", text)
        self.assertIn("рассылка ×1", text)

    def test_one_marker_from_a_real_person_still_goes_to_triage(self):
        self.incoming("k1", src="whatsapp", text="Вчера ходили в казино в Мар-дель-Плате, было весело")
        self.incoming("k2", src="dm", text="Бонус к зарплате за ноябрь пришлю в пятницу")
        self.incoming("k3", src="whatsapp", text="Promo de Telecentro: 300 megas a mitad de precio por 6 meses")
        self.eng.tick()
        self.assertEqual([self.item(k)["status"] for k in ("k1", "k2", "k3")], ["asked"] * 3)


class SpamRules(unittest.TestCase):
    def test_unsubscribe_only_counts_in_email(self):
        self.assertIsNone(rules.noise_reason({"src": "whatsapp", "from": "Хорхе", "text": "как unsubscribe сделать?"}))
        self.assertEqual(rules.noise_reason({"src": "email", "from": "Shop", "text": "Deals. Unsubscribe here"}),
                         "рассылка")

    def test_words_inside_other_words_do_not_count(self):
        # «pin-up» и «1win» — только отдельным словом; «opt out» ловит отписку, но не «adopt outcomes»
        self.assertIsNone(rules.spam_reason({"src": "email", "text": "we adopt outcomes-based pricing; win1win"}))
        self.assertIsNone(rules.spam_reason({"src": "dm", "text": "казино-рояль пересмотрим?"}))


if __name__ == "__main__":
    unittest.main()
