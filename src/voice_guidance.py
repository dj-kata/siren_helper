"""VOICEVOXによるキュー式音声案内。"""

import json
import queue
import random
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.logger import get_logger
from src.voice_audio import play_wav

logger = get_logger(__name__)

VOICE_DEFAULTS = {
    "voice_startup": False,
    "voice_shutdown": False,
    "voice_errors": False,
    "voice_dosukoi_alert": False,
    "voice_entou_alert": False,
    "voice_capture_saved": False,
    "voice_shop_price": False,
    "voicevox_url": "http://127.0.0.1:50021",
    "voicevox_speaker_id": 1,
    "voicevox_timeout_seconds": 30,
    "voice_output_device": "",
    "voice_volume": 100,
    "voice_pan": 0,
}

VOICE_TEST_MESSAGES = (
    "6500ギタン腕輪、毒消しか忍び足です",
    "満腹度が減少しています",
    "遠投状態です",
    "キャプチャ画像を保存しました",
    "25階なので自動キャプチャしました",
)


def synthesize(text, url, speaker, timeout=30):
    base_url = url.rstrip("/")
    query_url = f'{base_url}/audio_query?{urlencode({"text": text, "speaker": speaker})}'
    with urlopen(
        Request(query_url, data=b"", method="POST"),
        timeout=timeout,
    ) as response:
        query = json.load(response)
    request = Request(
        f'{base_url}/synthesis?{urlencode({"speaker": speaker})}',
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def synthesize_with_retry(text, url, speaker, timeout, category="preview"):
    attempts = 2
    for attempt in range(1, attempts + 1):
        started_at = time.monotonic()
        logger.info(
            "VOICEVOX音声合成を開始します: category=%s attempt=%d/%d "
            "timeout=%ss speaker=%s text=%r",
            category,
            attempt,
            attempts,
            timeout,
            speaker,
            text,
        )
        try:
            wav = synthesize(text, url, speaker, timeout)
        except TimeoutError:
            elapsed = time.monotonic() - started_at
            if attempt < attempts:
                logger.warning(
                    "VOICEVOX音声合成がタイムアウトしたため再試行します: "
                    "category=%s attempt=%d/%d elapsed=%.3fs text=%r",
                    category,
                    attempt,
                    attempts,
                    elapsed,
                    text,
                )
                continue
            logger.error(
                "VOICEVOX音声合成が再試行後もタイムアウトしました: "
                "category=%s attempt=%d/%d elapsed=%.3fs text=%r",
                category,
                attempt,
                attempts,
                elapsed,
                text,
            )
            raise
        elapsed = time.monotonic() - started_at
        logger.info(
            "VOICEVOX音声合成が完了しました: category=%s attempt=%d/%d "
            "elapsed=%.3fs bytes=%d text=%r",
            category,
            attempt,
            attempts,
            elapsed,
            len(wav),
            text,
        )
        return wav


class VoicePreviewThread(threading.Thread):
    def __init__(self, url, speaker, device_id, volume, pan, timeout):
        super().__init__(name="voice-preview", daemon=True)
        self.url = url
        self.speaker = speaker
        self.device_id = device_id
        self.volume = volume
        self.pan = pan
        self.timeout = timeout
        self.failure = None

    def run(self):
        try:
            text = random.choice(VOICE_TEST_MESSAGES)
            wav = synthesize_with_retry(
                text,
                self.url,
                self.speaker,
                self.timeout,
            )
            started_at = time.monotonic()
            logger.info("VOICEVOXテスト再生を開始します: text=%r", text)
            play_wav(wav, self.device_id, self.volume, self.pan)
            logger.info(
                "VOICEVOXテスト再生が完了しました: elapsed=%.3fs text=%r",
                time.monotonic() - started_at,
                text,
            )
        except Exception as error:
            self.failure = str(error) or type(error).__name__
            logger.exception(
                "VOICEVOXテスト再生に失敗しました（VOICEVOXの起動と設定を確認してください）"
            )


def start_voice_preview(
    url,
    speaker,
    device_id="",
    volume=100,
    pan=0,
    timeout=30,
):
    worker = VoicePreviewThread(url, speaker, device_id, volume, pan, timeout)
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
        self._active_errors = set()
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
            if not self._settings["voice_errors"]:
                self._active_errors.clear()
            self._generation += 1

    def announce(self, category, text):
        with self._lock:
            enabled_key = f"voice_{category}"
            if (
                self._closing
                or not text
                or not self._settings.get(enabled_key, False)
            ):
                return False
            try:
                self._queue.put_nowait(
                    (
                        self._generation,
                        str(category),
                        str(text),
                        self._settings.copy(),
                    )
                )
                logger.info(
                    "VOICEVOX音声案内をキューへ追加しました: category=%s text=%r",
                    category,
                    text,
                )
                return True
            except queue.Full:
                logger.warning("VOICEVOX音声案内キューが満杯のため案内を省略しました")
                return False

    def error_state(self, key, message=None):
        """エラーの発生時に一度だけ読み上げ、復旧時に再通知可能にする。"""
        with self._lock:
            if not message:
                self._active_errors.discard(key)
                return
            if key in self._active_errors or not self._settings["voice_errors"]:
                return
            if self.announce("errors", message):
                self._active_errors.add(key)

    def shutdown(self):
        with self._lock:
            if self._closing:
                return
            self._generation += 1
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
            self.announce("shutdown", "シレン6ヘルパーを終了します")
            self._closing = True

    def is_finished(self):
        return not self._worker.is_alive()

    def _run(self):
        cache = {}
        while True:
            try:
                generation, category, text, settings = self._queue.get(timeout=0.1)
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
                    wav = synthesize_with_retry(
                        text,
                        key[0],
                        key[1],
                        settings["voicevox_timeout_seconds"],
                        category,
                    )
                    if len(cache) >= 64:
                        cache.clear()
                    cache[key] = wav
                else:
                    logger.info(
                        "VOICEVOX音声合成キャッシュを使用します: "
                        "category=%s text=%r",
                        category,
                        text,
                    )
                with self._lock:
                    if generation != self._generation:
                        continue
                started_at = time.monotonic()
                logger.info(
                    "VOICEVOX音声案内の再生を開始します: category=%s text=%r",
                    category,
                    text,
                )
                play_wav(
                    cache[key],
                    settings["voice_output_device"],
                    settings["voice_volume"],
                    settings["voice_pan"],
                )
                logger.info(
                    "VOICEVOX音声案内の再生が完了しました: "
                    "category=%s elapsed=%.3fs text=%r",
                    category,
                    time.monotonic() - started_at,
                    text,
                )
            except Exception:
                logger.exception(
                    "VOICEVOX音声案内に失敗しました: category=%s text=%r "
                    "（VOICEVOXの起動と設定を確認してください）",
                    category,
                    text,
                )
            finally:
                self._queue.task_done()
