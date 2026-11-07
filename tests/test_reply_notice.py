from test_proactivity import Case
import engine

class ReplyNotices(Case):
    def test_done_stop_needs_no_owner_review_or_draft(self):
        p=self.incoming('stop')
        self.verdict(p,do='done',type='info',why='Owner confirmed stop; past operation unknown')
        self.eng.tick()
        self.assertEqual(self.item('stop')['status'],'done')
        self.assertFalse(self.io.notes);self.assertFalse(self.io.notices)
        self.assertTrue(all(p.get("kind")=="dismiss" for p,_ in self.io.teams_posts))
    def test_reply_closes_matching_owner_notification_once(self):
        p=self.incoming('old')
        self.verdict(p,do='draft',type='ack',text='Ready',why='Needs reply')
        self.eng.tick()
        nid=self.item('old')['owner_notice'];self.assertTrue(nid)
        self.teams({'kind':'answered','id':'old','receipt':{'source':'telegram','id':'102'}})
        self.eng.tick();self.eng.tick()
        self.assertEqual(self.io.resolved_notices,[nid])
        self.assertEqual(self.item('old')['status'],'answered')
        self.verdict(p,do='draft',type='ack',text='Late old draft');self.eng.tick()
        self.assertEqual(self.item('old')['status'],'answered')
        self.assertEqual(self.io.resolved_notices,[nid])
    def test_new_incoming_and_separate_commitment_survive_old_reply(self):
        p=self.incoming('old');self.verdict(p,do='draft',type='ack',text='Ready');self.eng.tick()
        old=self.item('old')['owner_notice']
        p=self.incoming('new',contact='new-conversation');self.verdict(p,do='escalate',type='decision',ask='Choose?',why='Real separate commitment');self.eng.tick()
        self.teams({'kind':'answered','id':'old'});self.eng.tick()
        self.assertIn(old,self.io.resolved_notices)
        self.assertEqual(self.item('new')['status'],'escalated')
        self.assertNotIn(self.item('new')['owner_notice'],self.io.resolved_notices)
    def test_failed_or_pending_send_does_not_resolve_draft(self):
        p=self.incoming('old');self.verdict(p,do='draft',type='ack',text='Ready');self.eng.tick()
        self.teams({'kind':'scheduled','id':'old','rid':'r'});self.eng.tick()
        self.teams({'kind':'send_failed','id':'old','rid':'r','error':'unknown'});self.eng.tick()
        self.assertFalse(self.io.resolved_notices)


class NoticeNeeds(Case):
    """30.10 (d4691): запись колокола несёт needs — что ждёт владелец: reply (ответить), decision (решить), fyi (к сведению)."""

    def needs(self, key, **verdict):
        p = self.incoming(key)
        self.verdict(p, do='escalate', why='Контекст', **verdict)
        self.eng.tick()
        self.eng.tick()
        on = [n for n in self.io.notices if n['id'] == key and n['active']]
        self.assertEqual(len(on), 1)
        return on[0].get('needs')

    def test_decision_when_the_verdict_asks_for_a_choice(self):
        self.assertEqual(self.needs('n1', type='decision', ask='Согласовать скидку?'), 'decision')
        self.assertEqual(self.needs('n2', type='task', ask='Оплатить счёт в Inbox', owner_only=True), 'decision')

    def test_reply_when_the_sender_waits_for_words(self):
        self.assertEqual(self.needs('n3', type='answer', text='Готов'), 'reply')

    def test_fyi_when_it_is_only_information(self):
        self.assertEqual(self.needs('n4', type='info'), 'fyi')


class NoticeCard(Case):
    """31.10 (d4731): запись колокола «решить» знает карточку хаба — qN возвращает сессия, которую просили её поставить;
    пока номера нет, запись несёт, кого и когда просили (запасная привязка в todo-own)."""

    def escalate(self, key='c1'):
        p = self.incoming(key)
        self.verdict(p, do='escalate', type='decision', ask='Согласовать?', why='Контекст')
        self.eng.tick()
        self.eng.tick()
        return self.item(key)

    def last(self, key='c1'):
        return [n for n in self.io.notices if n['id'] == key and n['active']][-1]

    def card_post(self, key, card, by=None, ts=None):
        self.eng.own(self.entry(by or self.item(key)['card_to'], ts), {'kind': 'card', 'item': key, 'card': card})

    def test_request_asks_the_session_to_report_the_card_number(self):
        it = self.escalate()
        text = self.io.asked[-1][1]
        self.assertIn('"kind":"card"', text)
        self.assertIn(f'"item":"{it["key"]}"', text)

    def test_notice_names_who_was_asked_until_the_number_comes(self):
        it = self.escalate()
        n = self.last()
        self.assertEqual((n['card_session'], n['card_asked']), (it['card_to'], it['card_asked']))
        self.assertNotIn('card', n)

    def test_number_from_the_asked_session_lands_in_the_notice(self):
        it = self.escalate()
        self.card_post('c1', 'q777')
        self.assertEqual(self.last()['card'], 'q777')
        self.assertEqual(it['card_id'], 'q777')

    def test_number_from_another_session_or_malformed_is_ignored(self):
        it = self.escalate()
        self.card_post('c1', 'q777', by='stranger')
        self.card_post('c1', 'not-a-card')
        self.eng.own(self.entry('hub'), {'kind': 'card', 'item': 'nothing', 'card': 'q5'})
        self.assertNotIn('card_id', it)
        self.assertNotIn('card', self.last())

    def test_a_new_card_request_drops_the_old_number(self):
        it = self.escalate()
        self.card_post('c1', 'q777')
        self.io.t += 60
        self.eng._ask_card(it)
        self.assertNotIn('card', self.last())
        self.assertEqual(self.last()['card_asked'], it['card_asked'])
