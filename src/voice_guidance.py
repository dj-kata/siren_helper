"""VOICEVOXによるキュー式音声案内。"""

import json
import queue
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.logger import get_logger
from src.voice_audio import play_wav

logger = get_logger(__name__)

VOICE_DEFAULTS = {
    "voice_dosukoi_alert": False,
    "voice_entou_alert": False,
    "voice_capture_saved": False,
    "voice_shop_price": False,
    "voicevox_url": "http://127.0.0.1:50021",
    "voicevox_speaker_id": 1,
    "voice_output_device": "",
    "voice_volume": 100,
    "voice_pan": 0,
}

VOICE_TEST_MESSAGE = "VOICEVOXのテスト再生です"


def synthesize(text, url, speaker):
    base_url = url.rstrip("/")
    query_url = f'{base_url}/audio_query?{urlencode({"text": text, "speaker": speaker})}'
    with urlopen(Request(query_url, data=b"", method="POST"), timeout=3) as response:
        query = json.load(response)
    request = Request(
        f'{base_url}/synthesis?{urlencode({"speaker": speaker})}',
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return response.read()


def start_voice_preview(url, speaker, device_id="", volume=100, pan=0):
    def run():
        try:
            play_wav(synthesize(VOICE_TEST_MESSAGE, url, speaker), device_id, volume, pan)
        except Exception:
            logger.exception(
                "VOICEVOXテスト再生に失敗しました（VOICEVOXの起動と設定を確認してください）"
            )

    worker = threading.Thread(target=run, name="voice-preview", daemon=True)
    worker.start()
    return worker


def shop_price_announcement(price, category_label, candidate_names):
    names = []
    redundant_suffix = f"の{category_label}"
    for candidate_name in candidate_names:
        name = str(candidate_name).strip()
        if name.endswith(redundant_suffix):
            name = name[: -len(redundant_suffix)]
        if name:
            names.append(name)
    if price is None or not category_label or not names:
        return ""
    return f'{price}ギタン{category_label}、{"か".join(names)}です'


class VoiceGuidance:
    def __init__(self, config):
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=32)
        self._generation = 0
        self._closing = False
        self.set_config(config)
        self._worker = threading.Thread(
            target=self._run,
            name="voice-guidance",
            daemon=True,
        )
        self._worker.start()

    def set_config(self, config):
        with self._lock:
            self._settings = {
                key: getattr(config, key, default)
                for key, default in VOICE_DEFAULTS.items()
            }
            self._generation += 1

    def announce(self, category, text):
        with self._lock:
            enabled_key = f"voice_{category}"
            if (
                self._closing
                or not text
                or not self._settings.get(enabled_key, False)
            ):
                return
            try:
                self._queue.put_nowait(
                    (self._generation, str(text), self._settings.copy())
                )
            except queue.Full:
                logger.warning("VOICEVOX音声案内キューが満杯のため案内を省略しました")

    def shutdown(self):
        with self._lock:
            if self._closing:
                return
            self._generation += 1
            self._closing = True
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break

    def _run(self):
        cache = {}
        while True:
            try:
                generation, text, settings = self._queue.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    if self._closing and self._queue.empty():
                        return
                continue
            try:
                with self._lock:
                    if generation != self._generation:
                        continue
                key = (
                    settings["voicevox_url"].rstrip("/"),
                    settings["voicevox_speaker_id"],
                    text,
                )
                if key not in cache:
                    wav = synthesize(text, key[0], key[1])
                    if len(cache) >= 64:
                        cache.clear()
                    cache[key] = wav
                with self._lock:
                    if generation != self._generation:
                        continue
                play_wav(
                    cache[key],
                    settings["voice_output_device"],
                    settings["voice_volume"],
                    settings["voice_pan"],
                )
            except Exception:
                logger.exception(
                    "VOICEVOX音声案内に失敗しました（VOICEVOXの起動と設定を確認してください）"
                )
            finally:
                self._queue.task_done()
