"""Actual plugin controls with an isolated Hub, no collector or permission changes."""
import json, os, unittest
from pathlib import Path
from unittest import mock
from tests.test_web_e2e import PageInChrome

# cdp.mjs ядра flagman не знает шага tapSelector (был в форке) — неизвестный шаг молча пропускается и клика нет.
# Тот же «тап»: элемент виден, включён и попадает под точку в своём центре, затем click() по нему.
def tap(sel):
    return {"eval": f"""(()=>{{const n=document.querySelector({json.dumps(sel)});if(!n||n.disabled)return false;
n.scrollIntoView({{block:'center'}});const r=n.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;
if(!(r.width&&r.height&&n.contains(document.elementFromPoint(x,y))))return false;n.click();return true}})()"""}

class SettingsRefusal(PageInChrome):
    def tap(self,sel):
        self.assertTrue(self.page(tap(sel))[-1]["eval"],f"не нажимается: {sel}")

    def test_refused_preset_keeps_last_accepted_value_and_allows_retry(self):
        cfg=Path(self.state)/"settings.json"
        cfg.write_text(json.dumps({"extensions":{"proactivity":{"path":str(Path(__file__).resolve().parents[1]),"web":"main.js"}}}))
        env=mock.patch.dict(os.environ,{"HUB_CONFIG":str(cfg)});env.start();self.addCleanup(env.stop)
        self.ev("session.requested","hub",session_id="settings-audit",kind="hub",owner=True)
        self.ev("session.started","hub",session_id="settings-audit")
        self.ev("ext.post",None,plugin="proactivity",channel="plugin",sender="proactivity",text=json.dumps({"kind":"config","preset":"draft","digest_h":3}))
        self.page({"go":f"http://127.0.0.1:{self.port}/#/settings"},{"until":"[...document.querySelectorAll('[role=tab]')].some(n=>n.textContent==='Proactivity')"},{"click":"Proactivity"},
            {"until":"document.querySelectorAll('.pa-box input').length===4"},
            {"eval":"window.__originalFetch=window.fetch;window.__attempts=0;window.fetch=(url,opts)=>String(url).includes('/api/feed/post')?(window.__attempts++,Promise.resolve(new Response(JSON.stringify({error:'Synthetic refusal'}),{status:403}))):window.__originalFetch(url,opts);true"})
        before=self.page({"eval":"document.querySelector('.pa-box input:checked').closest('label').textContent"})[-1]["eval"]
        self.tap(".pa-box .pa-row:nth-child(3) input");self.page({"wait":"Synthetic refusal"})
        got=self.page({"eval":"({selected:document.querySelector('.pa-box input:checked').closest('label').textContent,attempts:window.__attempts,disabled:document.querySelector('.pa-box input').disabled})"})[-1]["eval"]
        self.assertEqual(got["selected"],before,got)
        self.assertFalse(got["disabled"],got)
        if os.environ.get("HUB_PLUGIN_SCREENSHOTS"):
            out=Path(os.environ["HUB_PLUGIN_SCREENSHOTS"]);out.mkdir(parents=True,exist_ok=True)
            for width in (390,1240):   # шага media у cdp.mjs flagman нет — тема страницы как есть
                self.page({"shot":str(out/f"proactivity-refusal-{width}.png"),"width":width,"height":844})
        self.tap(".pa-box .pa-row:nth-child(3) input")
        self.assertEqual(self.page({"eval":"window.__attempts"})[-1]["eval"],2)
        self.assertFalse([e for e in self.spooled() if e["type"]=="ext.post"])

def load_tests(loader,suite,pattern):
    return unittest.TestSuite(SettingsRefusal(n) for n in SettingsRefusal.__dict__ if n.startswith("test_"))
