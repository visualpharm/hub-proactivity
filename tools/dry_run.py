#!/usr/bin/env python3
"""Сухой прогон на журнале хаба: что плагин сделал бы с входящими за последние N часов — списком, без отправки и без
записи в ящик ядра (журнал только читается, ящик — заглушка).

    PYTHONPATH=<папка хаба> python3.12 tools/dry_run.py [--hours 24] [--preset everyone] [--journal путь]

Модели нет, поэтому вердиктов тоже нет: видно, что отфильтровано как шум или уже отвечено, что ушло бы разборщику,
какой уровень у сообщения и что закрыло бы отправку независимо от вердикта (нельзя ответить, признаки инструкции)."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import engine  # noqa: E402
import rules  # noqa: E402


class Mute:
    teams_name = "teams"

    def __init__(self):
        self.t = time.time()
        self.asked = []

    def now(self):
        return self.t

    def local(self, ts):
        import datetime
        return datetime.datetime.fromtimestamp(ts)

    def __getattr__(self, name):   # post, post_teams, notify, todo_*, fact — никуда не пишем
        return lambda *a, **k: None

    def ask(self, session, text):
        self.asked.append(text)

    def triager(self, cfg):
        return "hub"

    def triagers(self, cfg):
        return {"hub"}


def blockers(it):
    out = []
    if it.get("reply") is not True:
        out.append("ответить из Inbox нельзя")
    if it.get("sus"):
        out.append("признаки инструкции")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--preset", default="everyone", choices=rules.PRESETS)
    ap.add_argument("--journal", action="append", help="журнал; можно несколько (архив, затем живой)")
    a = ap.parse_args()
    from core.daemon import default_state_dir
    state = default_state_dir()
    archive = os.path.join(state, "journal-archive")
    paths = a.journal or ([os.path.join(archive, n) for n in sorted(os.listdir(archive))
                           if n.endswith(".jsonl")][-1:] if os.path.isdir(archive) else []) + [
        os.path.join(state, "journal.jsonl")]
    engine.FRESH_BACK = a.hours * 3600   # всё окно — «свежее»: ничего не помечать как старое
    io = Mute()
    st = engine.new_state(io.now())
    st["cfg"]["preset"] = a.preset
    eng = engine.Engine(st, io)
    since = io.now() - a.hours * 3600
    seen = 0
    lines = (line for path in paths for line in open(path, "rb"))
    if True:
        for line in lines:
            if b'"ext.post"' not in line or b'"teams"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            d = ev.get("data") or {}
            if ev.get("type") != "ext.post" or d.get("plugin") != "teams" or ev.get("ts", 0) < since:
                continue
            try:
                body = json.loads(d.get("text") or "")
            except ValueError:
                continue
            if d.get("channel") == "plugin" and d.get("sender") == "teams" and isinstance(body, dict):
                if body.get("kind") == "config":
                    eng.teams({"id": f"p{ev['seq']}", "by": "плагин teams", "ts": ev["ts"]}, body)
                    continue
                eng.teams({"id": f"p{ev['seq']}", "by": "плагин teams", "ts": ev["ts"]}, body)
                seen += 1
    pending = {k: it["status"] for k, it in st["items"].items()}
    eng.tick()   # что ушло бы разборщику
    rows = sorted(st["items"].values(), key=lambda it: it.get("at") or "")
    print(f"Окно {a.hours:g} ч, уровень {a.preset}; сообщений канала: {seen}, дел: {len(rows)}")
    for it in rows:
        status = it["status"]
        if pending.get(it["key"]) == "new":
            sender = "colleague" if it.get("sign") else "other"
            lvl = rules.level(a.preset, sender, True)
            stops = blockers(it)
            what = "разборщику; " + (f"рутина ушла бы САМА" if lvl == "send" and not stops else
                                     "рутина — черновик" if lvl == "send" else f"уровень {lvl}")
            if stops:
                what += " (" + ", ".join(stops) + ")"
        else:
            what = {"noise": f"шум: {it.get('noise')}", "answered": "уже отвечено", "ignored": "не показывать",
                    "old": "старое"}.get(status, status)
        print(f"- {it.get('at', '')[:16]} · {it['src']:9} · {it['from'][:28]:28} · {'коллега' if it.get('sign') else 'не коллега':9} · {what}")
    print(f"К разборщику ушло бы просьб: {len(io.asked)}")


if __name__ == "__main__":
    main()
