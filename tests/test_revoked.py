"""26.10 (d4451): собеседник удалил ждущее сообщение — teams закрывает пункт постом answered с revoked. Это не ответ
владельца: беседа не «живая» (owner_at не ставится), пункт уходит в old без «владелец ответил или закрыл сам»."""
import unittest

from test_proactivity import Case  # noqa: F401 — общая заглушка ящика


class Revoked(Case):
    def test_revoked_closes_without_owner_spoke(self):
        self.incoming("k1", contact="wa:1", src="whatsapp", text="Video note 1")
        self.teams({"kind": "answered", "id": "k1", "revoked": True})
        self.assertEqual(self.item("k1")["status"], "old")
        self.assertTrue(self.item("k1").get("revoked"))
        self.assertFalse(self.item("k1").get("canonical_open"))
        self.assertEqual(self.st.get("owner_at") or {}, {})

    def test_plain_answered_still_means_the_owner(self):
        self.incoming("k1", contact="wa:1", src="whatsapp")
        self.teams({"kind": "answered", "id": "k1"})
        self.assertEqual(self.item("k1")["status"], "answered")
        self.assertTrue(self.st.get("owner_at"))


if __name__ == "__main__":
    unittest.main()
