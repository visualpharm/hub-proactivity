"""Суть входящего в Inbox (владелец 06.11, m4891: «жду summary в Inbox, транскрипт трудно понять»).

1. Просьба разборщику велит класть summary для любого голосового и для текста длиннее ~300 знаков (раньше — от 600).
2. Суть, принятая из вердикта, уходит клиенту в посте kind=item (поле summary, необязательное): клиент берёт разбор
   письма из постов item/verdict/delegated канала плагина, а пост вердикта разборщика может быть отброшен (stale).
"""
import unittest

import engine
from test_proactivity import Case

LONG = "длинное письмо про сроки поставки и оплату " * 20
SUMMARY = "Суть: просит подтвердить поставку до пятницы.\n- оплата после приёмки\n- нужен адрес склада"


class InboxSummary(Case):
    def item_posts(self, key="k1"):
        return [p for p in self.io.posts if p.get("kind") == "item" and p.get("id") == key]

    def test_the_request_asks_a_summary_for_every_voice_message_and_text_over_300(self):
        self.incoming("k1", text=LONG)
        self.eng.tick()
        text = self.io.asked[-1][1]
        rule = next(line for line in text.splitlines() if line.startswith('"summary":'))
        self.assertIn("voice message", rule)
        self.assertIn(str(getattr(engine, "SUMMARY_FROM", 300)), rule)
        self.assertEqual(getattr(engine, "SUMMARY_FROM", 300), 300)
        self.assertNotIn("600", rule)

    def test_the_item_post_carries_the_accepted_summary(self):
        post = self.incoming("k1", text=LONG)
        self.verdict(post, do="escalate", why="нужно решение", ask="подтвердить?", summary=SUMMARY)
        self.assertEqual(self.item_posts()[-1].get("summary"), SUMMARY)

    def test_no_summary_means_no_key_in_the_item_post(self):
        post = self.incoming("k1")
        self.verdict(post, do="escalate", why="нужно решение", ask="подтвердить?")
        self.assertTrue(self.item_posts())
        self.assertNotIn("summary", self.item_posts()[-1])

    def test_a_stale_verdict_does_not_reach_the_client(self):
        post = self.incoming("k1", text=LONG, inbox={"version": 2})
        self.verdict(post, do="escalate", why="нужно решение", ask="подтвердить?", summary="старая суть",
                     inbox={"version": 1})
        self.assertIn(("stale_verdict", {"item": "k1"}), self.io.facts)
        self.assertFalse(any(p.get("summary") for p in self.item_posts()))
        self.verdict(post, do="escalate", why="нужно решение", ask="подтвердить?", summary=SUMMARY,
                     inbox={"version": 2})
        self.assertEqual(self.item_posts()[-1].get("summary"), SUMMARY)


if __name__ == "__main__":
    unittest.main()
