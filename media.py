"""Содержание видео, голосовых и ссылок YouTube пункта — для разборщика (27.10, владелец: «нету самого видео…
тебе нужно всё-таки разбирать видео, которые присылают. Хотя бы читать summary из YouTube»).

Сборщик teams уже скачал файлы в attachments хаба (`media[]` поста: url `/api/file?path=…`) и нашёл ссылки YouTube
(`links[]`). Разборщику — сессии — плагин отдаёт готовое строкой к пункту:
- видео (и видео-заметка): речь — расшифровка командой голоса хаба (`voice.cmd`, звук через ffmpeg, архив выключен),
  у видео длиннее LONG — только первые HEAD секунд; 2–3 кадра ffmpeg — путями, разборщик открывает их сам (Read);
- голосовое без расшифровки (сборщик не смог) — тем же путём;
- YouTube: название, канал, длительность, описание и субтитры (`yt-dlp --skip-download`), без субтитров — что есть.
Полный текст — файлом рядом (путь в строке), в строке — начало. Тяжёлое идёт в своём потоке, по одному; итог хранится
файлом `<ключ>.json`: второй раз не считаем. Сбой — строка-причина, разбор идёт дальше. Платных API нет: yt-dlp
и ffmpeg локальные, речь — та же команда, что у диктовки хаба."""
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

VIDEO_KINDS = {"video", "gif", "ptv", "video_note"}
VOICE_KINDS = {"voice", "audio"}
KEEP = 3              # вложений и ссылок на пункт
LONG = 600            # с: видео длиннее — речь только с начала
HEAD = 180            # с: сколько речи брать у длинного
FRAMES = 3
EXCERPT = 350         # знаков текста в строке просьбы; полностью — файлом
FILE_MAX = 20000      # знаков в файле полного текста
WORD = {"video": "видео", "voice": "голосовое", "yt": "YouTube"}
STT_LANGS = "es,ru,en"   # Inbox — в основном испанский: при сбое определения языка голос хаба закрепляет первый
YOUTUBE = re.compile(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:[^\s<>\"']*?&)?v=|shorts/|live/|embed/)"
                     r"|youtu\.be/)([A-Za-z0-9_-]{11})")


def local_path(m):
    """Файл вложения, скачанный сборщиком под attachments/inbox хаба; чужие адреса и миниатюры — None."""
    if not isinstance(m, dict) or m.get("thumb") is True:   # Telegram: тяжёлый файл не качали — url ведёт на миниатюру
        return None
    url = str(m.get("url") or "")
    if not url.startswith("/api/file?path="):
        return None
    path = unquote(url.split("path=", 1)[1].split("&", 1)[0])
    return path if path.startswith("/") and "/attachments/inbox/" in path and ".." not in path else None


def wanted(body):
    """Что разобрать у поста сообщения: [{k: video|voice, path, dur} | {k: yt, id, title}] — не больше KEEP."""
    out, seen = [], set()

    def add(ref, key):
        if key not in seen and len(out) < KEEP:
            seen.add(key)
            out.append(ref)

    for m in body.get("media") if isinstance(body.get("media"), list) else []:
        path = local_path(m)
        if not path:
            continue
        kind, mime = str(m.get("kind") or ""), str(m.get("mime") or "")
        dur = m.get("dur") if isinstance(m.get("dur"), (int, float)) else 0
        if kind in VIDEO_KINDS or (kind == "file" and mime.startswith("video/")):
            add({"k": "video", "path": path, "dur": dur}, path)
        elif kind in VOICE_KINDS and not str(m.get("text") or "").strip():   # расшифрованное сборщиком — уже в посте
            add({"k": "voice", "path": path, "dur": dur}, path)
    links = body.get("links") if isinstance(body.get("links"), list) else []
    titles = {}
    for ln in links:
        g = YOUTUBE.search(str((ln or {}).get("url") or "")) if isinstance(ln, dict) else None
        if g:
            titles.setdefault(g.group(1), str(ln.get("title") or "")[:200])
    for vid in list(titles) + [g.group(1) for g in YOUTUBE.finditer(str(body.get("text") or ""))]:
        add({"k": "yt", "id": vid, "title": titles.get(vid, "")}, "yt:" + vid)
    return out


def key(ref):
    return f"{ref['k']}:{ref.get('path') or ref.get('id')}"


def clock(sec):
    sec = int(round(sec or 0))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def excerpt(text, n=EXCERPT):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def vtt_text(raw, until=None):
    """Субтитры VTT → сплошной текст: без шапки, времени и тегов; автоматические субтитры YouTube повторяют строку
    в соседних отрезках — повтор убираем. until — секунды: дальше не берём."""
    out, last = [], None
    skip = False
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"(\d+):(\d\d):(\d\d)\.\d+\s+-->", line) or re.match(r"(\d\d):(\d\d)\.\d+\s+-->", line)
        if m:
            parts = [int(x) for x in m.groups()]
            start = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
            skip = until is not None and start > until
            continue
        if not line or skip or line == "WEBVTT" or re.match(r"(Kind|Language|NOTE|STYLE)\b", line) or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line).replace("&nbsp;", " ").replace("&amp;", "&").strip()
        if line and line != last:
            out.append(line)
            last = line
    return " ".join(out)


def _tool(name, env):
    return os.environ.get(env) or shutil.which(name) or next(
        (p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}") if os.path.exists(p)), name)


class Digester:
    """Разбор вложений в своём потоке: get(ref) — готовая строка или None (ещё считается; запущено)."""

    def __init__(self, out_dir, stt_cmd=None, workers=1, timeout=900):
        self.dir = out_dir
        self.stt_cmd = stt_cmd
        self.timeout = timeout
        self.ffmpeg = _tool("ffmpeg", "PROACTIVITY_FFMPEG")
        self.ffprobe = _tool("ffprobe", "PROACTIVITY_FFPROBE")
        self.ytdlp = _tool("yt-dlp", "PROACTIVITY_YTDLP")
        self.done, self.busy, self.lock = {}, set(), threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="digest")

    def _base(self, k):
        return os.path.join(self.dir, hashlib.sha1(k.encode()).hexdigest()[:16])

    def get(self, ref):
        k = key(ref)
        with self.lock:
            if k in self.done:
                return self.done[k]
            try:
                with open(self._base(k) + ".json", encoding="utf-8") as f:
                    line = json.load(f)["line"]
                self.done[k] = line
                return line
            except (OSError, ValueError, KeyError, TypeError):
                pass
            if k not in self.busy:
                self.busy.add(k)
                self.pool.submit(self._run, ref, k)
        return None

    def wait(self):
        """Для тестов и живого прогона: дождаться всего начатого."""
        self.pool.shutdown(wait=True)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="digest")

    def _run(self, ref, k):
        base = self._base(k)
        try:
            os.makedirs(self.dir, exist_ok=True)
            line = {"video": self.video, "voice": self.voice, "yt": self.youtube}[ref["k"]](ref, base)
        except Exception as e:   # noqa: BLE001 — сбой одного вложения не держит разбор
            line = f"{WORD.get(ref['k'], ref['k'])}: не разобрано — {excerpt(e, 160)}"
            print(f"proactivity: разбор {k}: {e}", file=sys.stderr, flush=True)
        try:
            with open(base + ".json", "w", encoding="utf-8") as f:
                json.dump({"key": k, "line": line}, f, ensure_ascii=False)
        except OSError:
            pass
        with self.lock:
            self.done[k] = line
            self.busy.discard(k)
            while len(self.done) > 500:
                self.done.pop(next(iter(self.done)))

    # --- видео и голос ------------------------------------------------------------------------------------------
    def _sh(self, argv, timeout=120):
        r = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout or f"код {r.returncode}").strip().splitlines()[-1][:200])
        return r.stdout

    def _duration(self, path, dur):
        if dur:
            return float(dur)
        try:
            return float(self._sh([self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                   path], 30).strip())
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            return 0.0

    def speech(self, path, dur, base):
        """Речь файла → (текст, примечание); текст пуст — речи нет. Длинный — только первые HEAD секунд."""
        if not self.stt_cmd:
            return "", "расшифровки нет: голос хаба (voice.cmd) не настроен"
        wav = base + ".wav"
        cut = dur > LONG
        try:
            self._sh([self.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                      "-t", str(HEAD if cut else LONG), wav], 180)
        except RuntimeError as e:
            if "does not contain any stream" in str(e) or "matches no streams" in str(e):
                return "", "звука нет"
            raise
        try:
            cmd = shlex.split(os.path.expanduser(self.stt_cmd))
            argv = [a.replace("{wav}", wav) for a in cmd] + ([] if any("{wav}" in a for a in cmd) else [wav])
            env = {**os.environ, "HUB_VOICE_ARCHIVE": "off", "HUB_VOICE_LANGS": STT_LANGS}
            r = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env,
                               timeout=self.timeout)
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass
        last = (r.stdout or "").strip().splitlines()[-1:] or [""]
        try:
            got = json.loads(last[0])
        except ValueError:
            got = {}
        if r.returncode:
            if (got.get("partial") or "").strip():
                return got["partial"].strip(), "расшифровка неполная"
            raise RuntimeError("расшифровка: " + ((r.stderr or "").strip().splitlines() or [f"код {r.returncode}"])[-1][:160])
        note = f"речь — только первые {HEAD // 60} мин" if cut else ""
        return str(got.get("text") or "").strip(), note

    def _textfile(self, base, text):
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(text[:FILE_MAX])
        return base + ".txt"

    def _said(self, text, note, base):
        if not text:
            return note if note == "звука нет" or note.startswith("расшифровки нет") else "речи нет"
        whole = f" (весь текст: {self._textfile(base, text)})" if len(" ".join(text.split())) > EXCERPT else ""
        return f"речь «{excerpt(text)}»{whole}" + (f" ({note})" if note else "")

    def frames(self, path, dur, base):
        if dur and dur < 2:
            marks = [0]
        else:
            d = dur or 3
            marks = [round(d * f, 2) for f in ((0.15, 0.5, 0.85) if FRAMES == 3 else (0.25, 0.75))]
        out = []
        for i, t in enumerate(marks, 1):
            p = f"{base}-f{i}.jpg"
            try:
                self._sh([self.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-ss", str(t), "-i", path, "-frames:v", "1",
                          "-vf", "scale='min(640,iw)':-2", "-q:v", "4", p], 60)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                continue
            if os.path.exists(p) and os.path.getsize(p):
                out.append(p)
        return out

    def video(self, ref, base):
        path = ref["path"]
        if not os.path.exists(path):
            return "видео: файла нет на диске"
        dur = self._duration(path, ref.get("dur"))
        pics = self.frames(path, dur, base)
        try:
            text, note = self.speech(path, dur, base)
            said = self._said(text, note, base)
        except Exception as e:   # noqa: BLE001 — кадры есть и без речи
            said = f"речь не разобрана — {excerpt(e, 160)}"
        return (f"видео{' ' + clock(dur) if dur else ''}: {said}"
                + (f"; кадры: {'; '.join(pics)}" if pics else "; кадров нет"))

    def voice(self, ref, base):
        path = ref["path"]
        if not os.path.exists(path):
            return "голосовое: файла нет на диске"
        dur = self._duration(path, ref.get("dur"))
        text, note = self.speech(path, dur, base)
        return f"голосовое{' ' + clock(dur) if dur else ''}: {self._said(text, note, base)}"

    # --- YouTube ------------------------------------------------------------------------------------------------
    def youtube(self, ref, base):
        vid = ref["id"]
        tmp = base + "-yt"
        os.makedirs(tmp, exist_ok=True)
        try:
            r = subprocess.run([self.ytdlp, "--force-ipv4", "--skip-download", "--no-playlist", "--no-warnings",
                                "--write-info-json", "--write-subs", "--write-auto-subs",
                                "--sub-langs", ".*-orig,es,en,ru", "--sub-format", "vtt",
                                "-o", os.path.join(tmp, "%(id)s.%(ext)s"), "https://www.youtube.com/watch?v=" + vid],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
            infos = glob.glob(os.path.join(tmp, "*.info.json"))
            if not infos:
                why = ((r.stderr or "").strip().splitlines() or [f"код {r.returncode}"])[-1]
                title = ref.get("title")
                return (f"YouTube «{title}»: " if title else "YouTube: ") + f"описание не получено — {excerpt(why, 160)}"
            with open(infos[0], encoding="utf-8") as f:
                info = json.load(f)
            subs = {}
            for p in glob.glob(os.path.join(tmp, "*.vtt")):
                lang = os.path.basename(p)[len(vid) + 1:-4]
                with open(p, encoding="utf-8", errors="replace") as f:
                    subs[lang] = f.read()
            manual = set((info.get("subtitles") or {}).keys())
            orig = info.get("language") or ""

            def rank(lang):
                return (lang not in manual, not lang.endswith("-orig") and lang.split("-")[0] != orig,
                        ["es", "en", "ru"].index(lang.split("-")[0]) if lang.split("-")[0] in ("es", "en", "ru") else 9)
            lang = min(subs, key=rank) if subs else None
            said = vtt_text(subs[lang]) if lang else ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        title = str(info.get("title") or ref.get("title") or "").strip()
        desc = str(info.get("description") or "").strip()
        meta = ", ".join(x for x in (str(info.get("channel") or info.get("uploader") or "").strip(),
                                     clock(info["duration"]) if info.get("duration") else "") if x)
        full = "\n\n".join(x for x in (f"YouTube: {title}" + (f" ({meta})" if meta else ""),
                                       "https://www.youtube.com/watch?v=" + vid,
                                       "Описание:\n" + desc if desc else "",
                                       f"Субтитры ({lang}):\n{said}" if said else "") if x)
        path = self._textfile(base, full)
        parts = [f"субтитры «{excerpt(said)}»" if said else "субтитров нет"]
        if desc:
            parts.append(f"описание «{excerpt(desc, 200)}»")
        return (f"YouTube «{excerpt(title, 120)}»" + (f" ({meta})" if meta else "") + ": " + "; ".join(parts)
                + f" (всё: {path})")
