"""Crowded canonical triage and authority/attention cases, synthetic IO only."""
import json
from test_proactivity import Case
import engine


class Management(Case):
    def test_actual_triager_prompt_keeps_ownership_receipts_and_useful_work_separate(self):
        self.manage(); self.incoming('owned-work'); self.eng.tick()
        text = self.io.asked[-1][1]
        for clause in (
            'what can usefully advance an existing outcome now',
            'Preserve the accepted',
            'separate observer',
            'A successful command or queued message establishes dispatch only',
            'triage done verdict does not prove the requested external effect',
            'advance useful independent authorized work',
            'unchanged facts suppress repeated checks or reports',
            'Keep a lesson narrow',
            "Never answer the owner's pending card on his behalf",
            'active AND cancelled occurrence evidence',
        ):
            with self.subTest(clause=clause): self.assertIn(clause, text)
        self.assertNotIn('perform no calendar mutation', text)   # 22.10: стоп «только подготовка» снят
        self.assertIn('it needs no owner approval', text)
        self.assertFalse(self.io.teams_posts)

    def test_management_triager_receives_exact_occurrence_cancellation_contract(self):
        self.manage()
        self.incoming('cancelled-meeting')
        self.eng.tick()
        prompt = self.io.asked[-1][1]
        for clause in (
            'Established meeting cancellation',
            'without another owner approval',
            'proposal alone does not cancel',
            'optional attendee declining a group meeting',
            'account, calendar, event UID/provider ID',
            'recurrence key and current event/source versions',
            'only that exact occurrence, never the series',
            'reconfirmation or accepted reschedule',
            'Serialize the occurrence claim',
            'duplicates, concurrent workers and restart',
            'read back the exact occurrence before retrying',
            'authoritative calendar readback',
            'existing scheduling owner',
            'no supported cancellation adapter',
            'Deferred-message cancel is not a calendar operation',
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, prompt)
        self.assertFalse(self.io.teams_posts)

    def test_cancellation_management_policy_is_not_enabled_by_default(self):
        self.incoming('meeting')
        self.eng.tick()
        self.assertNotIn('Established meeting cancellation', self.io.asked[-1][1])

    def test_verified_cancellation_needs_no_owner_approval(self):
        """22.10 (владелец m3889 «сам сам все сам»): «только подготовка до отдельного гейта» записали агенты без его слова —
        отмена встречи контрагентом уходит владельцу расписания без одобрения; условия точного вхождения остаются."""
        self.manage()
        self.incoming('pending-cancellation')
        self.eng.tick()
        prompt = self.io.asked[-1][1]
        for clause in (
            "verified cancellation needs no owner approval",
            'without another owner approval',
            'already-completed occurrence must not be acted on again',
            'it is not an owner decision',
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, prompt)
        for clause in ('PREPARATION ONLY', 'separate applicable cancellation gate', 'prepare only',
                       'perform no calendar mutation', 'Do not accept a permission card via Hub'):
            with self.subTest(gone=clause):
                self.assertNotIn(clause, prompt)
        self.assertFalse(self.io.teams_posts)

    def test_oversized_proposal_is_not_truncated_into_invalid_send_or_partial_action(self):
        self.manage()
        token={'v':1,'version':'v1','edit_version':0,'held':False}
        p=self.incoming('a',inbox=token)
        self.verdict(p,do='reply',type='answer',text='"'*1100,inbox=token)
        self.assertEqual(self.item('a')['status'],'blocked')
        self.assertEqual(self.io.teams_posts,[])
        self.assertEqual(self.st['sent'],[])

    def test_exact_guidance_chunks_are_required_and_old_guidance_verdict_is_rejected(self):
        import hashlib
        self.manage()
        guidance='  Exact owner guidance\n No invented deadlines.  '
        ident=hashlib.sha256(guidance.encode()).hexdigest()
        self.teams({'kind':'triage_config','triage':'proactivity','inbox_guard':True,
                    'guidance_id':ident,'guidance_parts':2})
        p=self.incoming('a',inbox={'v':1,'version':'v','edit_version':0,'held':False})
        self.teams({'kind':'triage_prompt','guidance_id':ident,'of':2,'part':1,'text':guidance[12:]})
        self.assertFalse(self.st['caps']['guidance_ready'])
        self.teams({'kind':'triage_prompt','guidance_id':ident,'of':2,'part':0,'text':guidance[:12]})
        self.assertEqual(self.st['caps']['prompt'],guidance)
        self.assertTrue(self.st['caps']['guidance_ready'])
        self.eng.tick()
        self.assertIn(json.dumps(guidance),self.io.asked[-1][1])
        self.verdict(p,do='done',type='info',why='Verified complete',guidance_id='older',inbox=self.item('a')['inbox'])
        self.assertNotEqual(self.item('a')['status'],'done')
    def test_whole_inventory_revives_only_current_retained_untriaged_work(self):
        self.manage()
        old=self.incoming('current')
        self.item('current')['status']='old'
        closed=self.incoming('closed')
        self.item('closed')['status']='answered'
        self.teams({'kind':'inbox_item','id':'current','post':old})
        self.teams({'kind':'inbox_item','id':'closed','post':closed})
        self.assertEqual(self.item('current')['status'],'new')
        self.assertEqual(self.item('closed')['status'],'answered')

    def manage(self):
        self.eng.own(self.entry('owner'),{'kind':'settings','management':True},owner_word=True)
        self.teams({'kind':'config','triage':'proactivity','inbox_guard':True})

    def decision(self,key,consequence='normal',deadline=None):
        post=self.incoming(key)
        self.verdict(post,do='escalate',type='decision',owner_only=True,
                     why='Owner-only decision',ask='Approve the established choice',
                     consequence=consequence,deadline=deadline)
        return post

    def test_thirty_routine_drafts_do_not_bury_two_owner_decisions(self):
        self.manage()
        for n in range(30):
            p=self.incoming(f'r{n}')
            self.verdict(p,do='draft',type='answer',why='Routine proposal',text='Verified reply')
        self.decision('decision-a','high'); self.decision('decision-b')
        self.eng.tick()
        self.assertEqual(len(self.io.notes),2)
        self.assertEqual(set(self.eng.attention()),{'decision-a','decision-b'})
        self.assertEqual(len(self.st['items']),32)
        self.assertEqual(self.st['cfg']['preset'],'everyone')
        self.assertEqual(len(self.io.teams_posts),30)
        self.assertTrue(all('Context:' in p['text'] and 'Next action:' in p['text'] for p,_ in self.io.teams_posts))

    def test_owner_only_and_private_editor_holds_never_dispatch_as_routine(self):
        self.manage()
        token={'v':1,'version':'v1','edit_version':1,'held':True,'holder':'client-a'}
        p=self.incoming('held',inbox=token)
        self.verdict(p,do='reply',type='answer',text='Owner text',inbox=token)
        self.assertFalse(self.io.teams_posts)
        self.assertEqual(self.item('held')['status'],'draft')
        p=self.incoming('decision')
        self.verdict(p,do='reply',type='answer',text='Approve',owner_only=True)
        self.assertFalse(any(p.get('kind')=='send' for p,_ in self.io.teams_posts))

    def test_drafts_held_only_for_the_missing_guard_go_back_to_triage_when_it_is_on(self):
        # 16.10 (слово владельца m2240 «разговаривай сам и всё делай сам, не давай мне вычитывать»): автоотправка Inbox
        # стояла выключенной — ответы оседали черновиками «Private editor hold or shared editor protection unavailable»
        self.eng.own(self.entry('owner'),{'kind':'settings','preset':'everyone'},owner_word=True)
        self.teams({'kind':'config','triage':'proactivity'})
        token={'v':1,'version':'v1','edit_version':0,'held':False,'holder':None}
        p=self.incoming('a',inbox=token)
        self.verdict(p,do='reply',type='answer',text='Готово',inbox=token)
        self.assertEqual(self.item('a')['status'],'draft')
        held={'v':1,'version':'v1','edit_version':1,'held':True,'holder':'client-a'}
        q=self.incoming('b',inbox=held)
        self.verdict(q,do='reply',type='answer',text='Его текст',inbox=held)
        self.teams({'kind':'config','triage':'proactivity','inbox_guard':True})
        self.assertEqual((self.item('a')['status'],self.item('a')['tries']),('new',0))
        self.assertEqual(self.item('b')['status'],'draft')            # держит редактор владельца — не трогаем

    def test_done_without_source_backed_reason_does_not_archive(self):
        self.manage(); p=self.incoming('unresolved')
        self.verdict(p,do='done',type='info')
        self.eng.tick()
        self.assertNotEqual(self.item('unresolved')['status'],'done')
        self.assertFalse(any(p.get('kind')=='dismiss' for p,_ in self.io.teams_posts))

    def test_five_real_blockers_retained_three_visible_and_deadline_reprioritizes(self):
        self.manage()
        for n in range(5): self.decision(f'd{n}','high' if n<3 else 'normal')
        self.eng.tick()
        self.assertEqual(self.eng.attention(),['d0','d1','d2'])
        self.assertEqual(len([i for i in self.st['items'].values() if i['status']=='escalated']),5)
        self.st['items']['d4']['v']['deadline']=engine.iso(self.io.t+60)
        self.eng.tick()
        self.assertIn('d4',self.eng.attention())
        self.assertEqual(len(self.eng.attention()),3)
        self.assertEqual(len([i for i in self.st['items'].values() if i.get('card')]),3)

    def test_technical_blocker_stays_agent_owned_and_other_work_continues(self):
        self.manage(); p=self.incoming('technical')
        self.verdict(p,do='blocked',type='other',owner_only=False,why='Source reader unavailable')
        self.decision('owner')
        self.eng.tick()
        self.assertEqual(self.eng.attention(),['owner'])
        self.assertEqual(self.item('technical')['status'],'blocked')
        self.assertTrue(any('technical' in str(x) or p in str(x) for x in self.io.asked))

    def test_stale_verdict_cannot_reuse_current_token_or_overwrite_private_hold(self):
        self.manage()
        token={'v':1,'version':'v1','edit_version':0,'held':False}
        p=self.incoming('a',inbox=token)
        self.teams({'kind':'draft_state','id':'a','inbox':{**token,'edit_version':1,'held':True}})
        self.verdict(p,do='reply',type='answer',text='Old reply',inbox=token)
        self.assertFalse(any(d.get('kind')=='send' for d,_ in self.io.teams_posts))
        self.assertTrue(self.item('a')['inbox']['held'])

    def test_uncertain_delivery_never_retries_or_requests_another_channel_send(self):
        self.st['cfg']['preset']='everyone'; self.st['caps']['triage']=True
        p=self.incoming('a'); self.verdict(p,do='reply',type='answer',text='Confirmed fact')
        rid=self.item('a')['rid']
        self.teams({'kind':'send_uncertain','id':'a','rid':rid})
        before=len(self.io.teams_posts)
        self.advance(3600)
        self.assertEqual(len(self.io.teams_posts),before)
        self.assertEqual(self.item('a')['status'],'unresolved')
        self.assertIn('reconcile',self.io.asked[-1][1].lower())
        self.assertEqual(self.io.notes,[])

    def test_prompt_respects_source_holds_and_private_context_not_as_outgoing(self):
        self.manage(); self.incoming('a')
        self.eng.tick(); text=self.io.asked[-1][1]
        self.assertNotIn('без --cached: он сам откроет чат',text)
        self.assertIn('Context:',text); self.assertIn('Next action:',text)
        self.assertIn('owner_only',text)
