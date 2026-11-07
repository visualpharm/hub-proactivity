"""Видео, голосовые и YouTube пункта — содержание разборщику (27.10, владелец m4411: «нету самого видео… тебе нужно
всё-таки разбирать видео, которые присылают. Хотя бы читать summary из YouTube»). Внешние команды — подставные
скрипты: ffmpeg пишет файл-заглушку, hub-stt печатает текст, yt-dlp кладёт info.json и субтитры."""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_proactivity import Case  # noqa: E402

import engine  # noqa: E402
import media  # noqa: E402


def script(d, name, body):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write("#!/bin/sh\n" + textwrap.dedent(body))
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


class Fakes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proactivity-media-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "calls.log")
        # ffmpeg: последний аргумент — выходной файл; звук из «немого» видео — ошибка, как у настоящего
        script(self.bin, "ffmpeg", f"""
            echo "ffmpeg $*" >> {self.log}
            for a; do out="$a"; done
            case "$*" in *mute*-vn*) echo "Output file does not contain any stream" >&2; exit 1;; esac
            echo x > "$out"
        """)
        script(self.bin, "ffprobe", 'echo 42.0\n')
        self.stt = script(self.bin, "hub-stt", f"""
            echo "stt $* lang=$HUB_VOICE_LANGS archive=$HUB_VOICE_ARCHIVE" >> {self.log}
            echo 'whisper: noise'
            echo '{{"text": "Hola the owner, mira el arco del Valle Encantado"}}'
        """)
        script(self.bin, "yt-dlp", f"""
            echo "yt-dlp $*" >> {self.log}
            for a; do url="$a"; done
            prev=""; for a; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
            dir=$(dirname "$out")
            case "$url" in *NOSUBS00000*)
              echo '{{"title": "Sin subtítulos", "channel": "Canal", "duration": 75, "description": "Descripción corta"}}' > "$dir/NOSUBS00000.info.json"; exit 0;;
            *GONE0000000*) echo "ERROR: Video unavailable" >&2; exit 1;;
            esac
            echo '{{"title": "Cómo instalar la bomba", "channel": "Agua Sur", "duration": 754, "language": "es",
                   "description": "Paso a paso", "subtitles": {{}}}}' > "$dir/dQw4w9WgXcQ.info.json"
            printf 'WEBVTT\\nKind: captions\\nLanguage: es\\n\\n00:00:01.000 --> 00:00:03.000\\nprimero <c>cerrá</c> la llave\\n\\n00:00:03.000 --> 00:00:05.000\\nprimero cerrá la llave\\n\\n00:00:05.000 --> 00:00:07.000\\ndespués sacá el filtro\\n' > "$dir/dQw4w9WgXcQ.es-orig.vtt"
            printf 'WEBVTT\\n\\n00:00:01.000 --> 00:00:03.000\\nfirst close the valve\\n' > "$dir/dQw4w9WgXcQ.en.vtt"
        """)
        self.env = {k: os.environ.get(k) for k in ("PROACTIVITY_FFMPEG", "PROACTIVITY_FFPROBE", "PROACTIVITY_YTDLP")}
        os.environ["PROACTIVITY_FFMPEG"] = os.path.join(self.bin, "ffmpeg")
        os.environ["PROACTIVITY_FFPROBE"] = os.path.join(self.bin, "ffprobe")
        os.environ["PROACTIVITY_YTDLP"] = os.path.join(self.bin, "yt-dlp")
        self.att = os.path.join(self.tmp, "st", "attachments", "inbox", "wa")
        os.makedirs(self.att)
        self.dg = media.Digester(os.path.join(self.tmp, "digest"), stt_cmd=self.stt + " {wav}")

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def file(self, name):
        p = os.path.join(self.att, name)
        with open(p, "w") as f:
            f.write("v")
        return p

    def run_ref(self, ref):
        self.assertIsNone(self.dg.get(ref))   # первый раз — запущено в потоке
        self.dg.wait()
        return self.dg.get(ref)

    def calls(self):
        with open(self.log) as f:
            return f.read()


class Wanted(Fakes):
    def test_video_untranscribed_voice_and_youtube_are_taken_others_not(self):
        v = self.file("a.mp4")
        body = {"text": "mirá https://youtu.be/dQw4w9WgXcQ y https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "media": [{"kind": "video", "url": "/api/file?path=" + quote(v, safe=""), "dur": 22.3},
                          {"kind": "voice", "url": "/api/file?path=" + quote(v, safe=""), "text": "ya transcrito"},
                          {"kind": "video", "url": "https://evil/x.mp4"},
                          {"kind": "video", "url": "/api/file?path=" + quote(v + "-thumb.jpg", safe=""), "thumb": True},
                          {"kind": "image", "url": "/api/file?path=" + quote(v, safe="")}],
                "links": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Bomba"}]}
        self.assertEqual(media.wanted(body), [{"k": "video", "path": v, "dur": 22.3},
                                              {"k": "yt", "id": "dQw4w9WgXcQ", "title": "Bomba"}])

    def test_voice_without_transcript_is_taken(self):
        v = self.file("b.ogg")
        self.assertEqual(media.wanted({"media": [{"kind": "voice", "url": "/api/file?path=" + quote(v, safe="")}]}),
                         [{"k": "voice", "path": v, "dur": 0}])


class Digests(Fakes):
    def test_video_gives_speech_and_three_frames(self):
        line = self.run_ref({"k": "video", "path": self.file("a.mp4"), "dur": 22.3})
        self.assertTrue(line.startswith("видео 0:22: речь «Hola the owner, mira el arco del Valle Encantado»"), line)
        frames = line.split("кадры: ")[1].split("; ")
        self.assertEqual(len(frames), 3)
        self.assertTrue(all(os.path.exists(p) for p in frames))
        self.assertIn("archive=off", self.calls())
        self.assertIn("lang=es,ru,en", self.calls())
        self.assertNotIn("-t 180", self.calls())

    def test_long_video_transcribes_only_the_first_three_minutes(self):
        line = self.run_ref({"k": "video", "path": self.file("long.mp4"), "dur": 1500})
        self.assertIn("-t 180", self.calls())
        self.assertIn("только первые 3 мин", line)
        self.assertTrue(line.startswith("видео 25:00:"), line)

    def test_video_without_sound_still_has_frames(self):
        line = self.run_ref({"k": "video", "path": self.file("mute.mp4"), "dur": 5})
        self.assertIn("звука нет", line)
        self.assertIn("кадры: ", line)

    def test_failed_transcription_is_a_reason_not_a_stop(self):
        self.dg.stt_cmd = script(self.bin, "stt-bad", "echo 'model missing' >&2; exit 3\n") + " {wav}"
        line = self.run_ref({"k": "video", "path": self.file("c.mp4"), "dur": 9})
        self.assertIn("речь не разобрана — расшифровка: model missing", line)
        self.assertIn("кадры: ", line)

    def test_voice_without_transcript(self):
        line = self.run_ref({"k": "voice", "path": self.file("v.ogg"), "dur": 0})
        self.assertEqual(line, "голосовое 0:42: речь «Hola the owner, mira el arco del Valle Encantado»")

    def test_result_is_kept_on_disk_and_not_computed_twice(self):
        ref = {"k": "voice", "path": self.file("v2.ogg"), "dur": 5}
        line = self.run_ref(ref)
        again = media.Digester(self.dg.dir, stt_cmd=self.dg.stt_cmd)
        self.assertEqual(again.get(ref), line)
        self.assertEqual(self.calls().count("stt "), 1)

    def test_youtube_title_description_and_original_subtitles(self):
        line = self.run_ref({"k": "yt", "id": "dQw4w9WgXcQ", "title": ""})
        self.assertTrue(line.startswith("YouTube «Cómo instalar la bomba» (Agua Sur, 12:34): "
                                        "субтитры «primero cerrá la llave después sacá el filtro»; "
                                        "описание «Paso a paso» (всё: "), line)
        path = line.rsplit("(всё: ", 1)[1].rstrip(")")
        with open(path) as f:
            self.assertIn("Описание:\nPaso a paso", f.read())
        self.assertIn("--skip-download", self.calls())
        self.assertEqual(os.listdir(self.dg.dir).count(os.path.basename(path)), 1)
        self.assertFalse([x for x in os.listdir(self.dg.dir) if x.endswith("-yt")])   # info.json не копится

    def test_youtube_without_subtitles_gives_title_and_description(self):
        line = self.run_ref({"k": "yt", "id": "NOSUBS00000", "title": ""})
        self.assertTrue(line.startswith("YouTube «Sin subtítulos» (Canal, 1:15): субтитров нет; "
                                        "описание «Descripción corta»"), line)

    def test_youtube_failure_keeps_the_title_from_the_collector(self):
        line = self.run_ref({"k": "yt", "id": "GONE0000000", "title": "Bomba"})
        self.assertEqual(line, "YouTube «Bomba»: описание не получено — ERROR: Video unavailable")


class TriagerGetsContent(Case):
    """Движок: пункт с видео ждёт разбора вложений (не дольше MEDIA_WAIT) и несёт строки в просьбе."""

    def setUp(self):
        super().setUp()
        self.teams({"kind": "config", "triage": "proactivity", "autodraft": False})
        self.lines = {}
        self.io.digest = lambda ref: self.lines.get(media.key(ref))
        self.video = "/st/attachments/inbox/wa/abc.mp4"
        self.media = [{"kind": "video", "dur": 22, "url": "/api/file?path=" + quote(self.video, safe="")}]

    def test_waits_for_the_digest_then_asks_with_it(self):
        self.incoming("k1", text="", media=self.media)
        self.eng.tick()
        self.assertEqual(self.io.asked, [])
        self.lines["video:" + self.video] = "видео 0:22: речь «hola»; кадры: /d/f1.jpg"
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertIn("видео 0:22: речь «hola»; кадры: /d/f1.jpg", text)
        self.assertIn("Base why and the draft on that content", text)

    def test_does_not_wait_forever(self):
        self.incoming("k1", text="", media=self.media)
        self.eng.tick()
        self.io.t += engine.MEDIA_WAIT + 1
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertIn("видео: разбор не успел за 5 мин", text)

    def test_item_without_media_is_not_held(self):
        self.incoming("k1", text="hola")
        self.eng.tick()
        self.assertEqual(len(self.io.asked), 1)

    def test_youtube_link_in_text(self):
        self.lines["yt:dQw4w9WgXcQ"] = "YouTube «Bomba» (Agua Sur, 12:34): субтитры «primero…»"
        self.incoming("k1", text="mirá https://youtu.be/dQw4w9WgXcQ")
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertIn("YouTube «Bomba» (Agua Sur, 12:34)", text)

    def test_repost_with_new_video_digests_again(self):
        self.lines["video:" + self.video] = "видео 0:22: речь «hola»"
        self.incoming("k1", text="", media=self.media, inbox={"v": 1, "version": "a"})
        self.eng.tick()
        self.verdict(self.item("k1")["post"], do="wait", why="видео")
        self.io.asked.clear()
        other = "/st/attachments/inbox/wa/def.mp4"
        self.incoming("k1", text="", inbox={"v": 1, "version": "b"},
                      media=[{"kind": "video", "url": "/api/file?path=" + quote(other, safe="")}])
        self.eng.tick()
        self.assertEqual(self.io.asked, [])   # новое видео ещё считается
        self.lines["video:" + other] = "видео 0:05: речи нет"
        self.eng.tick()
        (_, text), = self.io.asked
        self.assertIn("видео 0:05: речи нет", text)
        self.assertNotIn("hola", text)


if __name__ == "__main__":
    unittest.main()
