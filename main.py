"""Процесс плагина «Proactivity»: разбирает входящие Inbox (канал плагина teams) и ведёт их в чат хаба.

Модели здесь нет: процесс читает журнал, держит автомат дел (engine.py), отдаёт сообщения разборщику — сессии — и пишет
в ящик ядра только факты: пост в свой канал (в т.ч. {kind: notification} — колокол), сообщение сессии, owner.notify
(чат) и, когда владелец разрешил и гейты пускают, пост `send` в канал teams. Пункт To-do плагин не кладёт (решение
владельца — карточкой хаба, 16.10; во flagman событий owner.todo_* нет): todo_done лишь снимает пункт прежних версий. Правила и гейты — rules.py; состояние дел — в файле
рядом и постами `item` в канале плагина.

Журнал читаем сами, как teams: построчно с места остановки, только посты двух каналов и слова владельца хабу; пост,
который ядро отклонило (следом core.rejected с of = его seq), не считается. Сессии и их имена — core.journal.load_state.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.dont_write_bytecode = True   # без __pycache__ в папке расширения: страница следит за mtime файлов плагина

from core import journal, spool  # noqa: E402
from core.daemon import default_state_dir  # noqa: E402
from core.tools import from_owner  # noqa: E402

import engine  # noqa: E402
import media  # noqa: E402

NAME = os.environ.get("HUB_EXTENSION", engine.NAME).split(":")[-1]
TEAMS = "teams"            # откуда входящие; канал плагина Inbox
STATE = default_state_dir()
OWN = os.path.join(STATE, "ext-" + NAME)
STATE_PATH = os.path.join(OWN, "state.json")
EVERY = 5                  # с между проходами
POST_MAX = 2000
HOLD = 3                   # с: пост ждёт, не отклонит ли его ядро (core.rejected идёт следом)
WORD_TTL = 24 * 3600       # слово владельца хабу, на которое можно сослаться (`for: mN`), — сутки, как в ядре
# ссылка клиента на сообщение Inbox в словах владельца (задача): натив — «… — пост в
# `hub feed teams`», веб плагина teams (inboxRef) — «Пост (до него) в `hub feed teams`.»
POST_REF = re.compile(r"[Пп]ост (p\d+)(?: \(до него ((?:p\d+(?:, )?)+)\))? в `hub feed teams`")
DRAFT = "draft"            # черновик сессии или плагина под постом сообщения (текст с reply_to) — за перепиской
WORD = "word"              # слово владельца с такой ссылкой — в очередь Journal.read, как посты каналов
RELEVANT = re.compile(rb'"ext\.post"|"core\.rejected"|"message\.received"|"permission\.answered"|"owner\.todo_added"')


# команда чтения в просьбе разборщику (engine.prompt): «grep -A1 -E '^(p1|p2) '»
ASK_POSTS = re.compile(r"grep -A1 -E '\^\((p\d+(?:\|p\d+)*)\) '")


def post_refs(text):
    out = []
    for m in POST_REF.finditer(text or ""):
        out += [m[1]] + re.findall(r"p\d+", m[2] or "")
    return list(dict.fromkeys(out))


def load(now):
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) and st.get("v") == 1 else engine.new_state(now)
    except (OSError, ValueError):
        return engine.new_state(now)


def save(st):
    os.makedirs(OWN, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def plugin_name(sender):
    """Имя плагина из подписи отправителя: с Sync 20.10 ядро подписывает процесс плагина само — `ext:<имя>`
    (`ext:<аккаунт>:<имя>` у плагина из каталога), прежние факты — голым именем."""
    name = str(sender)
    return (name[4:] if name.startswith("ext:") else name).split(":")[-1]


def author(d):
    """Кто написал пост — как в ядре (_ext_post): сессия, плагин или владелец; иначе None."""
    if d.get("channel") == "session":
        return d.get("sender") or ""
    if d.get("channel") == "plugin" and d.get("sender"):
        return f"плагин {plugin_name(d['sender'])}"
    return "owner" if from_owner(d) else None


class Journal:
    """Журнал ядра с места остановки. read() отдаёт по порядку: посты каналов {"entry", "plugin", "body"}, слова
    владельца хабу (запоминаются в words) и пункты To-do плагина (todo_ids: название → id)."""

    def __init__(self, path):
        self.path, self.offset, self.ino = path, 0, None
        self.hold = []         # [(first_seen, seq, plugin, entry, body)]
        self.words = {}        # "mN" → (ts, кому): слова владельца
        self.todo_ids = {}     # title → "t:<seq>" — пункты To-do, которые положил этот плагин

    def read(self, now=None):
        now = now or time.time()
        try:
            ino = os.stat(self.path).st_ino
            if ino != self.ino:   # журнал начат заново (journal.rotate) — с начала
                self.ino, self.offset = ino, 0
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith(b"\n"):   # строка дописывается — дочитаем в следующий раз
                        break
                    self.offset += len(line)
                    if RELEVANT.search(line):
                        self._line(line, now)
        except OSError:
            pass
        out = [h for h in self.hold if now - h[0] >= HOLD]
        self.hold = [h for h in self.hold if now - h[0] < HOLD]
        return [{"entry": h[3], "plugin": h[2], "body": h[4]} for h in out]

    def _line(self, line, now):
        try:
            ev = json.loads(line)
        except ValueError:
            return
        d, kind = ev.get("data") or {}, ev.get("type")
        if kind == "core.rejected":
            self.hold = [h for h in self.hold if h[1] != d.get("of")]
        elif kind == "message.received" and from_owner(d) and not d.get("for"):
            self.words[f"m{ev.get('seq')}"] = (ev.get("ts") or 0, str(d.get("to") or "").strip().lower())
            for k in list(self.words)[:-300]:
                del self.words[k]
            refs = post_refs(str(d.get("quote") or ""))   # ссылку кладёт клиент цитатой; в тексте — его слова
            if refs:   # передал сообщение Inbox в работу: ждёт, как пост, не отклонит ли его ядро
                entry = {"id": f"m{ev.get('seq')}", "by": "owner", "ts": ev.get("ts") or now}
                self.hold.append((now, ev.get("seq"), WORD, entry,
                                  {"kind": "handover", "posts": refs, "to": str(d.get("to") or "").strip()}))
        elif kind == "permission.answered" and from_owner(d) and ev.get("entity"):
            # ответ владельца на карточку сессии: слово ей (ядро отдаёт его сессии как сообщение mN, N = seq ответа)
            self.words[f"m{ev.get('seq')}"] = (ev.get("ts") or 0, str(ev["entity"]).strip().lower())
        elif kind == "owner.todo_added" and plugin_name(d.get("sender") or "") == NAME:
            self.todo_ids[str(d.get("title") or "")] = f"t:{ev.get('seq')}"
        elif kind == "ext.post" and d.get("plugin") in (TEAMS, NAME):
            by = author(d)
            try:
                body = json.loads(d.get("text") or "")
            except (ValueError, TypeError):
                body = None
            if d["plugin"] == TEAMS and not isinstance(body, dict) and isinstance(d.get("reply_to"), str) \
                    and isinstance(d.get("text"), str) and d["text"].strip() and by not in (None, "owner", "плагин " + TEAMS):
                # черновик под сообщением (hub post teams --reply pN, разбор): переписка может уйти к новому пункту
                entry = {"id": f"p{ev.get('seq')}", "by": by, "ts": ev.get("ts") or now}
                self.hold.append((now, ev.get("seq"), DRAFT, entry, {"reply_to": d["reply_to"], "text": d["text"]}))
                return
            if by is None or not isinstance(body, dict):
                return
            entry = {"id": f"p{ev.get('seq')}", "by": by, "ts": ev.get("ts") or now}
            self.hold.append((now, ev.get("seq"), d["plugin"], entry, body))


class IO:
    """Ящик ядра и состояние хаба — для engine."""

    teams_name = TEAMS

    def __init__(self, jr, st):
        self.jr, self.st = jr, st
        self.tz = self._tz()
        self._core, self._core_at = {}, 0
        self._digester = None
        if not self.WA:
            self.wa_out = None    # нет команды — проверки исходящих нет (engine смотрит callable)
        if not self.SEND:
            self.wa_read = None

    @staticmethod
    def _tz():
        try:
            from zoneinfo import ZoneInfo
            from core import catalog
            name = (catalog.load_config(STATE) or {}).get("timezone")
            return ZoneInfo(name) if name else None
        except Exception:   # noqa: BLE001 — нет зоны: часы машины
            return None

    def now(self):
        return time.time()

    def local(self, ts):
        return datetime.fromtimestamp(ts, self.tz)

    # --- в ящик ----------------------------------------------------------------------------------------------
    def _put(self, kind, data, entity=None):
        spool.put(os.path.join(STATE, "spool"), kind, entity, {**data, "channel": "plugin", "owner": False,
                                                                 "sender": NAME}, src=f"ext:{NAME}")

    def _post(self, plugin, data, reply_to=None):
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        if len(text) > POST_MAX and isinstance(data, dict):   # пост канала — до 2000: необязательное отбрасываем
            for k in ("why", "noise", "who", "where"):
                data = {x: y for x, y in data.items() if x != k}
                text = json.dumps(data, ensure_ascii=False)
                if len(text) <= POST_MAX:
                    break
        if len(text) > POST_MAX:
            text = text[:POST_MAX - 1] + "…"
        self._put("ext.post", {"plugin": plugin, "text": text, **({"reply_to": reply_to} if reply_to else {})})

    def post(self, data):
        self._post(NAME, data)

    def post_teams(self, data, reply_to=None):
        # черновик — просто текст ответом на пост сообщения; отправка — {"kind": "send", …}: принимает её plugin teams,
        # только если в его sources.json стоит triage: "proactivity" (владелец разрешил) — иначе пост игнорируется
        self._post(TEAMS, data if data.get("kind") else data["text"], reply_to)

    def ask(self, session, text):
        self._put("message.received", {"to": session, "text": text})

    def notify(self, title, text, urgent, notice_id=None, push=True):
        # push: false — только лента и Telegram, баннером в alerts не показывать (Module API 2.5)
        self._put("owner.notify", {"title": title, "text": text, "urgent": bool(urgent),
                                   **({'id': notice_id} if notice_id else {}),
                                   **({} if push else {'push': False})})

    def resolve_notice(self, notice_id):
        self._put('owner.notify_resolved', {'id': notice_id})

    def notice(self, data):
        # запись уведомления в свой канал: ядро принимает {kind: notification} только от процесса этого канала
        self._post(NAME, data)

    def todo_done(self, key, title, link):
        ident = self.jr.todo_ids.pop(title, None)
        if not ident:   # положили до перезапуска процесса — ищем в состоянии хаба
            todo = ((self.core().get("todo") or {}).get("items")) or {}
            ident = next((i for i, row in todo.items() if row.get("session") == NAME and (
                row.get("title") == title or (link and link in (row.get("links") or [])))), None)
        if ident:
            self._put("owner.todo_done", {"id": ident})

    def record(self, row):
        """След чистки по ответу владельца (link-fade): строка в closes.jsonl рядом с состоянием; откат — по ней."""
        try:
            os.makedirs(OWN, exist_ok=True)
            with open(os.path.join(OWN, "closes.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"{NAME}: closes: {e}", file=sys.stderr, flush=True)

    def fact(self, what, data):
        spool.put(os.path.join(STATE, "spool"), f"ext.{NAME}.{what}", None, data, src=f"ext:{NAME}")

    # --- кто есть ---------------------------------------------------------------------------------------------
    def core(self):
        """Состояние хаба из файла ядра (core.journal.load_state), не чаще раза в 30 с."""
        if time.time() - self._core_at > 30:
            try:
                self._core = journal.load_state(STATE) or {}
            except Exception:   # noqa: BLE001 — файла нет или он пишется: прежнее
                pass
            self._core_at = time.time()
        return self._core

    def sessions(self):
        return {n: s for n, s in (self.core().get("sessions") or {}).items()
                if s.get("state") not in (None, "removed", "closed", "failed")}

    def digest(self, ref):
        """Содержание видео/голосового/YouTube пункта (media.Digester): строка или None — ещё считается."""
        if self._digester is None:
            try:
                from core import catalog
                cmd = ((catalog.load_config(STATE) or {}).get("voice") or {}).get("cmd")
            except Exception:   # noqa: BLE001 — нет настроек: без речи, кадры и YouTube всё равно
                cmd = None
            self._digester = media.Digester(os.path.join(STATE, "attachments", "inbox", "digest"), stt_cmd=cmd)
        return self._digester.get(ref)

    def owner_sessions(self):
        """Живые сессии, которые могут вести переписку или тему (25.10): агенты и самостоятельные сессии —
        не хаб, не исполнители чужих задач, не сдавшие. Имя → чем занимается (about, иначе последняя сводка) и папка;
        агенты первыми."""
        out = {}
        for n, s in sorted(self.sessions().items(), key=lambda x: (x[1].get("role") != "agent", x[0])):
            if s.get("kind") == "hub" or s.get("raised_by") or s.get("retired"):
                continue
            text = s.get("about") or next((s[k].get("text") for k in ("away", "gist", "recap")
                                           if isinstance(s.get(k), dict) and s[k].get("text")), "")
            where = "/".join(str(s.get("cwd") or "").rstrip("/").split("/")[-2:])
            out[n] = " ".join(str(text).split())[:160] + (f" (папка …/{where})" if where and s.get("kind") != "hub"
                                                          and "/.hub-core/" not in str(s.get("cwd")) else "")
        return out

    def session_parent(self, name):
        """Кто поднял исполнителя (raised_by) — его переписку ведёт родитель; не исполнитель — None."""
        return (self.sessions().get(name) or {}).get("raised_by")

    def pending_asks(self):
        """Наши просьбы разборщикам, ещё не доставленные (в очереди сессии): сессия → посты из их команды чтения."""
        out = {}
        for m in (self.core().get("messages") or {}).values():
            frm = m.get("from") or {}
            if m.get("state") in ("queued", "typing") and frm.get("kind") == "plugin" and frm.get("name") == NAME:
                found = ASK_POSTS.search(str(m.get("text") or ""))
                if found:
                    out.setdefault(m.get("session"), set()).update(found.group(1).split("|"))
        return out

    def owner_facts(self):
        """Справочник данных владельца (engine.OWNER_FACTS_FILE в папке настроек хаба): словарь или None. Файл ведёт
        владелец вне репо; битый или чужой формат — как нет файла."""
        try:
            from core import catalog
            with open(os.path.join(catalog.config_dir(), engine.OWNER_FACTS_FILE), encoding="utf-8") as f:
                facts = json.load(f)
        except (OSError, ValueError):
            return None
        return {k: v for k, v in facts.items() if isinstance(v, (str, int, float))} if isinstance(facts, dict) else None

    # --- чат WhatsApp: чтение сохранённой копии и отметка «прочитано» (1.1.7). Команды — те же, что у плагина teams:
    # PROACTIVITY_WA (`<wa> thread <номер> --cached --json …`) и PROACTIVITY_SEND (`<send> wa-read <номер>`); не заданы —
    # проверки нет (движок видит, что метода нет) ---
    WA = os.path.expanduser(os.environ.get("PROACTIVITY_WA", ""))
    SEND = os.path.expanduser(os.environ.get("PROACTIVITY_SEND", ""))

    def wa_out(self, channel, digits):
        """Время (unix) последнего нашего сообщения в личном чате по сохранённой копии (`wa thread --cached` — без вкладки
        и без синих галочек); 0.0 — исходящих нет; None — прочитать не вышло (смотрим в следующий такт)."""
        try:
            r = subprocess.run([self.WA, "thread", digits, "--cached", "--json", "--limit", "30", "--channel", channel],
                               capture_output=True, text=True, timeout=30)
            data = json.loads(r.stdout)
            return max([float(m.get("t") or 0) for m in data.get("messages") or [] if m.get("out") is True] or [0.0])
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError) as e:
            print(f"proactivity: wa thread {digits}: {type(e).__name__}", file=sys.stderr, flush=True)
            return None

    def wa_read(self, channel, digits):
        """`send wa-read <номер>` — отметить чат прочитанным (идемпотентно). (успех, причина сбоя); команды ещё нет —
        сбой с причиной, вердикт не страдает."""
        cmd = [self.SEND, "wa-read", digits] + (["--channel", channel] if channel != "whatsapp" else [])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env={**os.environ, "HUB_SESSION": ""})
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"{type(e).__name__}: {e}"
        return r.returncode == 0, ((r.stderr or r.stdout or "").strip()[-200:] or f"код {r.returncode}")

    def hub_name(self):
        return next((n for n, s in self.sessions().items() if s.get("kind") == "hub"), "hub")

    def triager(self, cfg):
        want = cfg.get("triager") or "auto"
        live = self.sessions()
        if want != "auto" and want in live:
            return want
        return "inbox" if want == "auto" and "inbox" in live else "hub"

    def triagers(self, cfg):
        return {self.triager(cfg), self.hub_name()}

    def owner_word(self, entry, body):
        """Настройки и «сводку сейчас» принимаем от владельца (страница) и от сессии по его слову: `for: mN` — его
        сообщение этой сессии (хабу — ссылается хаб) в журнале не старше суток."""
        by = str(entry.get("by") or "")
        if by == "owner":
            return True
        ts, to = self.jr.words.get(str(body.get("for") or ""), (0, None))
        hub = {"", "hub", "хаб", self.hub_name().lower()}
        # слово сказано хабу — ссылается хаб; сказано сессии (ответ на её карточку) — ссылается она сама
        spoken_to_poster = (by == self.hub_name() and to in hub) or (bool(to) and to == by.lower())
        return bool(ts and spoken_to_poster and 0 <= entry.get("ts", 0) - ts <= WORD_TTL)


def number(entry):
    try:
        return int(str(entry["id"])[1:])
    except (KeyError, ValueError):
        return 0


def step(eng, io, jr):
    """Один проход: новые посты каналов → автомат, потом ход времени."""
    st = eng.st
    for item in jr.read(io.now()):
        entry, body, plugin = item["entry"], item["body"], item["plugin"]
        mark = "teams_seq" if plugin in (TEAMS, DRAFT) else "word_seq" if plugin == WORD else "own_seq"
        n = number(entry)
        if n <= st.get(mark, 0):   # уже разобрано до перезапуска процесса
            continue
        st[mark] = n
        if plugin == TEAMS:
            eng.teams(entry, body)
        elif plugin == DRAFT:
            eng.draft_seen(entry, body["reply_to"], body["text"])
        elif plugin == WORD:
            eng.handover(entry, body)
        else:
            eng.own(entry, body, io.owner_word(entry, body))
    eng.tick()
    st["fresh"] = False


def main():
    now = time.time()
    st = load(now)
    jr = Journal(os.path.join(STATE, "journal.jsonl"))
    io = IO(jr, st)
    eng = engine.Engine(st, io)
    print(f"{NAME}: старт, состояние {OWN}", file=sys.stderr, flush=True)
    while True:
        try:
            step(eng, io, jr)
            save(st)
        except Exception as e:   # noqa: BLE001 — процесс живёт дальше; сбой виден в логе хаба
            print(f"{NAME}: сбой: {e}", file=sys.stderr, flush=True)
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
