"""Правила разбора входящих — чистые функции без ввода-вывода (тесты гоняют их реплеем).

Три слоя, и только первые два — настройка владельца:
  1. шум — что не идёт ни в разбор, ни в чат (боты, автоответы, заглушённые): попадает в сводку;
  2. уровень — что плагину разрешено сделать с ответом человеку: эскалация / черновик / отправить самому;
  3. гейты — что стоит на отправке всегда, каким бы ни был уровень: стоп-список владельца (деньги с его счетов, его подпись
     и юр. обязательства, необратимое, его вкус и здоровье — владелец 22.10), чужие просьбы «выполни», секреты,
     дубли и частота. Гейт не настраивается: он закрывает путь «людям без «да» владельца» там, где слову модели верить
     нельзя. Сверх стоп-списка гейтов нет: срочное, длинное и сообщения в группах уходят сами (владелец 22.10,
     «сам сам все сам»).
"""
import re
from datetime import datetime, timedelta

PRESETS = ("escalate", "draft", "colleagues", "everyone")
DEFAULT_PRESET = "draft"   # до выбора владельца: черновик под сообщением (как «Черновик сразу»); людям не уходит ничего
LEVELS = ("escalate", "draft", "send")
ROUTINE = ("ack", "answer")   # виды сообщений, на которые вообще можно ответить самому: «получил/спасибо», простой факт
KINDS = ("ack", "answer", "task", "decision", "info", "other")

SENDER_CLASSES = ("colleague", "other")


def level(preset, sender, routine):
    """Уровень по настройке: escalate — только сказать владельцу; draft — черновик под сообщением; send — отправить
    самому (только рутина и только тем, кому позволил пресет). Неизвестный пресет — как не выбранный."""
    if preset == "escalate":
        return "escalate"
    if routine and ((preset == "colleagues" and sender == "colleague") or preset == "everyone"):
        return "send"
    return "draft"


# --- шум -----------------------------------------------------------------------------------------------------------
AUTOREPLY = re.compile(
    r"out of (?:the )?office|automatic reply|auto[- ]?reply|autoresponder|on vacation|"
    r"автоответ|автоматическ\w+ ответ|вне офиса|нахожусь в отпуске|fuera de (?:la )?oficina|respuesta autom[aá]tica",
    re.IGNORECASE)
BOT = re.compile(
    r"(?<!\w)bot(?!\w)|(?<!\w)бот(?!\w)|no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|jira|github|"
    r"gitlab|sentry|grafana|pagerduty|calendar|incoming webhook|workflows?|planner|power automate|viva|notifications?",
    re.IGNORECASE)


# Спам на входе (06.11: казино-группа в Telegram висела в Inbox весь день). Один признак — не повод: «ходили в
# казино», «бонус к зарплате» пишут живые люди. Режем, только когда признаков игорной рекламы два и больше.
GAMBLING = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"casino|казино|cas[i1]no",
    r"jackpot|джекпот",
    r"фри ?спин|free ?spins?|giros gratis",
    r"(?<!\w)(?:1xbet|1win|vavada|pin-?up|melbet|mostbet|bet365|joycasino|leon ?bet)(?!\w)",
    r"игров\w* клуб|gaming club|club de juego",
    r"приветственн\w* (?:пакет|бонус)|welcome (?:bonus|package)|bono de bienvenida",
    r"бонус\w* (?:на|к) депозит|deposit bonus|bono (?:de|por) dep[oó]sito|\d{3}\s*% (?:на старте|к депозиту|bonus|бонус)",
    r"испыта\w* удач|выигр\w* (?:до|от|сразу)|win up to|gan[aá] hasta",
    r"ставк\w* на спорт|букмекер|sports? betting|apuestas? (?:deportivas|online|en vivo)",
    r"слот\w*(?:-| )автомат|slot machines?|tragamonedas"))
# Рассылка и холодное письмо: строка отписки в начале текста (почта приходит обрезанной до ~400 знаков, подвал с
# «Unsubscribe» обычно не виден — режем только явное).
NEWSLETTER = re.compile(
    r"(?<!\w)(?:unsubscribe|opt[- ]?out)(?!\w)|view (?:this email |it )?in (?:your )?browser|"
    r"(?:don.?t|do not|no longer) (?:want|wish) to (?:hear|receive|get)|reply (?:with )?.?(?:stop|unsubscribe|no).?(?:\W|$)|"
    r"отписаться|отписк\w|darse de baja|desuscrib\w+|cancelar (?:la )?suscripci[oó]n|ver (?:este correo )?en (?:el|tu|su) navegador",
    re.IGNORECASE)


def spam_reason(item):
    """«спам» (игорная реклама: два признака и больше) или «рассылка» (явная строка отписки в письме) — иначе None."""
    who, text = str(item.get("from") or ""), str(item.get("text") or "")
    hay = who + "\n" + text[:1000]
    if sum(1 for rx in GAMBLING if rx.search(hay)) >= 2:
        return "спам"
    if item.get("src") == "email" and NEWSLETTER.search(text[:1000]):
        return "рассылка"
    return None


def _re(pattern):
    try:
        return re.compile(str(pattern), re.IGNORECASE)
    except re.error:
        return None


def noise_reason(item, mute=()):
    """Почему сообщение — шум (короткая метка для сводки) или None. Только явные признаки: сомнение — в разбор."""
    who, text = str(item.get("from") or ""), str(item.get("text") or "")
    for pat in mute or ():
        rx = _re(pat)
        if rx and (rx.search(who) or rx.search(text)):
            return "заглушено"
    if AUTOREPLY.search(text[:400]):
        return "автоответ"
    spam = spam_reason(item)
    if spam:
        return spam
    if BOT.search(who) or BOT.search(str(item.get("contact") or "")):
        return "бот"
    return None


# --- чужой текст: признаки инструкции (порт teams/web/main.js SUSPICIOUS — две реализации держим в согласии) ----------
_L = r"(?<![^\W\d_])"   # не внутри слова: \b не видит границ русских слов в классе букв
_R = r"(?![^\W\d_])"
SUSPICIOUS = [
    (re.compile(
        _L + r"(ignore|disregard|forget)" + _R + r"[^.\n]{0,30}" + _L + r"(previous|prior|above|all)" + _R +
        r"[^.\n]{0,30}(instruction|prompt|message|rule)|игнорируй|забудь[^.\n]{0,20}(предыдущ|инструкц|правил)|"
        r"нов(ые|ая) инструкци|system prompt|системн\w* промпт|you are now|" + _L + r"ты теперь" + _R,
        re.IGNORECASE), "просит забыть прежние указания"),
    (re.compile(
        _L + r"(claude|chatgpt|gpt|llm|assistant|ии|агент|ассистент|нейросеть|бот)[,:]?\s+(please\s+)?"
        r"(выполни|сделай|запусти|отправь|перешли|удали|run|execute|send|delete|ignore)" + _R + "|" + _L +
        r"hub (send|task|post|restart|session)" + _R, re.IGNORECASE), "обращается к ИИ или хабу"),
    (re.compile(
        r"(владелец|владельца|owner|хозяин)[^.\n]{0,25}(разрешил|одобрил|дал добро|согласовал|approved)|"
        r"(моё|мое) «?да»? уже|already approved|approved by", re.IGNORECASE), "ссылается на разрешение"),
    (re.compile(
        r"(пришли|отправь|перешли|скинь|выложи|покажи|send|share|post|paste)[^.\n]{0,40}"
        r"(ключ|токен|пароль|секрет|token|password|secret|\.ssh|\.env|credential)", re.IGNORECASE),
     "просит ключи или пароли"),
    (re.compile(
        r"(curl|wget)[^\n]{0,120}\|\s*(sudo\s+)?(sh|bash|zsh|python)|rm\s+-rf\s|" + _L + r"sudo\s|base64\s+(-d|--decode)|"
        r"chmod\s+\+x", re.IGNORECASE), "опасная команда"),
]


# Агенты коллег пишут с аккаунтов своих людей и подписываются (разведка 13.10): «— 🤖 написано агентом», «sent via
# Claude Code🤖», «(агент хаба)», «агент Ильи, от имени…», ассистент Юли — ✨ последней строкой
AGENT_SIG = re.compile(r"(?:—|-|–)\s*🤖\s*агент\b|\[агент [^\]]+\]|написано агентом|sent via claude code|\(агент хаба\)|агент \w+, (?:от имени|хаб )|✨\s*$",
                       re.IGNORECASE)


def colleague_agent(text):
    """Пишет агент коллеги, а не сам коллега (14.10, владелец: «пишет её агент твоему агенту — отвечать просто, чтобы
    вместе говорили, а не мне в Inbox»). Только вместе с отметкой «коллега» от Inbox — подпись сама по себе не довод."""
    return bool(AGENT_SIG.search(str(text or "").strip()))


def suspicious(text):
    """Признаки инструкции в чужом тексте — список меток (пусто — нет). Не защита, а предохранитель: такое сообщение
    дальше эскалации не идёт, как бы ни был настроен уровень."""
    return [why for rx, why in SUSPICIOUS if rx.search(str(text or ""))]


# --- секреты в исходящем -------------------------------------------------------------------------------------------
SECRET = re.compile(
    r"(?i)(password|passwd|пароль|token|токен|api[_ -]?key|secret|секрет|ключ)\s*[:=]\s*\S{4,}|"
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*KEY|"
    r"op://\S+|[A-Za-z0-9+/=_-]{40,}")


def has_secret(text):
    return bool(SECRET.search(str(text or "")))


def contact_key(item):
    """Собеседник: ключ из Inbox; нет его (старый teams) — источник и имя."""
    return str(item.get("contact") or "") or f"{item.get('src')}:{item.get('from')}"


# --- гейты отправки ------------------------------------------------------------------------------------------------
# Метки риска, которые больше не стоп (владелец 22.10: стоп только деньги с его счетов, подпись/юр., необратимое,
# вкус/здоровье): вердикты, разобранные по прежней формулировке, их ещё несут. Прочие метки держат отправку как раньше —
# незнакомое слово модели не пропускаем.
RETIRED_RISKS = ("strategic", "access", "owner_information")
SEND_PER_HOUR = 6               # не больше отправок в час всего — и один собеседник не чаще раза в полчаса
SAME_CONTACT = 30 * 60
AGENT_SAME_CONTACT = 5 * 60     # и чаще: агенты переписываются по ходу работы
HOUR = 3600


def send_gate(item, verdict, *, preset, caps, sent, now):
    """None — можно отправлять; иначе причина по-русски, по которой ответ остаётся черновиком/эскалацией.
    sent — [(ts, contact)] отправленного самим плагином."""
    if caps.get("triage") is not True:
        return "Inbox не разрешил плагину отправку (teams: triage)"
    sender = "colleague" if item.get("sign") else "other"
    kind = verdict.get("type")
    agent = item.get("agent") is True
    if level(preset, sender, kind in ROUTINE or agent) != "send":
        return "уровень не «отправлять самому» для этого отправителя и вида сообщения"
    if item.get("sus"):
        return "в тексте признаки инструкции: " + "; ".join(item["sus"])
    risk = [str(x) for x in verdict.get("risk") or [] if str(x).strip().lower() not in RETIRED_RISKS]
    if risk:
        return "риск: " + ", ".join(risk)
    if verdict.get('owner_only'):
        return 'Owner-only decision requires an explicit owner action'
    if not item.get("reply"):
        return "в источник ответить нельзя"
    # группы, каналы и срочное — не гейт (владелец 22.10): нужен ли ответ в группе, решает разборщик по ветке
    text = str(verdict.get("text") or "").strip()
    if not text:
        return "пустой ответ"
    if has_secret(text):
        return "в ответе похоже на секрет"
    if len([1 for ts, *_ in sent if now - ts < HOUR]) >= SEND_PER_HOUR:
        return f"уже {SEND_PER_HOUR} отправок за час"
    # пауза на собеседника — только против двух наших подряд: написал после нашего последнего ответа — отвечаем сразу
    # (владелец 21.10: Miguel ждал полчаса ответа на своё же новое сообщение)
    mine = [x for x in sent if x[1] == contact_key(item) and now - x[0] < (AGENT_SAME_CONTACT if agent else SAME_CONTACT)]
    wrote = epoch(item.get("at"))
    if mine and not (wrote is not None and all(wrote > max(x[0], x[2] if len(x) > 2 and x[2] else 0) for x in mine)):
        return "этому собеседнику уже отвечали меньше получаса назад"
    return None


def epoch(at):
    """Время сообщения (эпоха или ISO) — секунды; нет или не разобрать — None."""
    try:
        if isinstance(at, (int, float)) and not isinstance(at, bool) or str(at).replace(".", "", 1).isdigit():
            return float(at)
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp() if at else None
    except (TypeError, ValueError, OverflowError):
        return None


# --- когда людям можно писать в мессенджеры ------------------------------------------------------------------------
TEAMS_SRC = ("dm", "mention", "channel", "teams")   # источники сборщика teams (collect.py), без src — тоже Teams


def send_after(src, local, weekend_ok=False):
    """WhatsApp и Telegram — не ночью (23:00–08:00) и не в воскресенье (правило владельца): ближайшее разрешённое местное
    время, если local вне окна, иначе None. weekend_ok — выходной запрет снят (владелец 18.10: тому, кто сам
    написал в выходные, отвечаем в те же выходные; агентам коллег выходные не мешают), ночной остаётся. Команда send сама
    не пускает ночью, а воскресенье держит только для WhatsApp — плагин ставит время отправки сам, ответ ждёт в очереди
    Inbox. Teams (личка, упоминание, канал) — только ночь, выходные не держат."""
    if src in TEAMS_SRC:   # Teams коллегам — любой день, только не ночью (владелец 18.10)
        weekend_ok = True
    elif src not in ("whatsapp", "telegram", "agent"):   # agent — агенты коллег: им тоже не ночью
        return None
    t = local
    if t.hour >= 23:
        t = (t + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    elif t.hour < 8:
        t = t.replace(hour=8, minute=0, second=0, microsecond=0)
    if t.weekday() == 6 and not weekend_ok:
        t = (t + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return None if t == local else t


def wrote_on_weekend(at, tz):
    """Собеседник сам написал в субботу или воскресенье (время сообщения — эпоха или ISO); не разобрали — нет."""
    try:
        d = datetime.fromtimestamp(float(at), tz) if isinstance(at, (int, float)) or str(at).replace(".", "", 1).isdigit() \
            else datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(tz)
    except (TypeError, ValueError, OverflowError):
        return False
    return d.weekday() >= 5


# --- тихие часы владельца (чат, сводка) ----------------------------------------------------------------------------
def minutes(hhmm):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hhmm or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else None


def in_quiet(local, quiet):
    """local — datetime по часам владельца; quiet — ["23:00", "08:00"] (окно через полночь допустимо)."""
    try:
        a, b = minutes(quiet[0]), minutes(quiet[1])
    except (TypeError, IndexError, KeyError):
        return False
    if a is None or b is None or a == b:
        return False
    now = local.hour * 60 + local.minute
    return a <= now < b if a < b else (now >= a or now < b)


PICTURES_MAX = 4


def pictures(media):
    """Картинки пункта, которые разборщик может открыть сам: файлы, скачанные сборщиком в attachments хаба
    (`/api/file?path=…/attachments/inbox/…`), только kind image; чужие адреса и голосовые — нет (26.10)."""
    from urllib.parse import unquote
    out = []
    for m in media if isinstance(media, list) else []:
        url = str((m or {}).get("url") or "") if isinstance(m, dict) else ""
        if m.get("kind") != "image" or not url.startswith("/api/file?path="):
            continue
        path = unquote(url.split("path=", 1)[1].split("&", 1)[0])
        if path.startswith("/") and "/attachments/inbox/" in path and ".." not in path and path not in out:
            out.append(path)
    return out[:PICTURES_MAX]


def clip(text, n):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def clip_lines(text, n):
    """clip с сохранением строк (markdown-пункты): пробелы внутри строки — по одному, пустые строки — одна."""
    lines = [" ".join(l.split()) for l in str(text or "").replace("\r", "").split("\n")]
    s = "\n".join(l for i, l in enumerate(lines) if l or (i and lines[i - 1])).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def stamp(ts, tz=None):
    return datetime.fromtimestamp(ts, tz)


LINKS_MAX, LINK_LEN = 5, 500


def links(raw, skip=()):
    """Ссылки действия из вердикта (оплата, подтверждение, подпись…): [{label, url}] или голые адреса. Только http(s)
    без пробелов и управляющих знаков, без повторов и без ссылки на само сообщение (skip); не больше LINKS_MAX."""
    out, seen = [], set(skip)
    for x in raw if isinstance(raw, list) else []:
        url, label = (x.get("url"), x.get("label")) if isinstance(x, dict) else (x, "")
        url = str(url or "").strip()
        if not re.fullmatch(r"https?://[^\s\x00-\x1f<>\"']{4,%d}" % LINK_LEN, url) or url in seen:
            continue
        seen.add(url)
        out.append({"label": clip(label, 60) if label else "", "url": url})
    return out[:LINKS_MAX]
