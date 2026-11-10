"""VOICEVOXによるキュー式音声案内。"""

import hashlib
import json
import os
from pathlib import Path
import queue
import random
import threading
import time
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.logger import get_logger
from src.voice_audio import StreamingPlaybackError, play_wav, play_wav_stream

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

VOICE_CACHE_DIR = Path("cache") / "voicevox"
STREAM_SEGMENT_SECONDS = 0.5
_voicevox_request_lock = threading.Lock()
_logged_engine_urls = set()
_engine_log_attempts = {}
_engine_log_lock = threading.Lock()


def _audio_query(text, url, speaker, timeout):
    base_url = url.rstrip("/")
    query_url = f'{base_url}/audio_query?{urlencode({"text": text, "speaker": speaker})}'
    with urlopen(
        Request(query_url, data=b"", method="POST"),
        timeout=timeout,
    ) as response:
        return json.load(response)


def _synthesis_request(query, url, speaker, endpoint="synthesis"):
    base_url = url.rstrip("/")
    parameters = {"speaker": speaker}
    if endpoint == "streaming_synthesis":
        parameters["segment_length"] = STREAM_SEGMENT_SECONDS
    return Request(
        f'{base_url}/{endpoint}?{urlencode(parameters)}',
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _cache_path(url, speaker, text):
    cache_key = json.dumps(
        [url.rstrip("/"), int(speaker), str(text)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return VOICE_CACHE_DIR / f"{hashlib.sha256(cache_key).hexdigest()}.wav"


def load_cached_wav(url, speaker, text):
    path = _cache_path(url, speaker, text)
    try:
        wav = path.read_bytes()
        if not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
            raise ValueError("WAVヘッダーが不正です")
        return wav
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("VOICEVOX音声キャッシュを読み込めません: path=%s", path)
        return None


def save_cached_wav(url, speaker, text, wav):
    if not wav:
        return
    path = _cache_path(url, speaker, text)
    temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(wav)
        os.replace(temporary, path)
    except Exception:
        logger.warning("VOICEVOX音声キャッシュを保存できません: path=%s", path)
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass


def log_engine_capabilities(url, timeout):
    base_url = url.rstrip("/")
    now = time.monotonic()
    with _engine_log_lock:
        if base_url in _logged_engine_urls:
            return
        if now - _engine_log_attempts.get(base_url, 0) < 60:
            return
        _engine_log_attempts[base_url] = now
    try:
        with urlopen(f"{base_url}/supported_devices", timeout=min(timeout, 3)) as response:
            devices = json.load(response)
        with urlopen(f"{base_url}/engine_manifest", timeout=min(timeout, 3)) as response:
            manifest = json.load(response)
        supported_features = manifest.get("supported_features", {})
        streaming_feature = supported_features.get("streaming_synthesis", False)
        if isinstance(streaming_feature, dict):
            streaming_feature = streaming_feature.get("value", False)
        logger.info(
            "VOICEVOXエンジン情報: cpu=%s cuda=%s dml=%s "
            "streaming_synthesis=%s",
            devices.get("cpu"),
            devices.get("cuda"),
            devices.get("dml"),
            bool(streaming_feature),
        )
        if not devices.get("cuda") and not devices.get("dml"):
            logger.info("VOICEVOXはCPUのみ利用可能です")
        with _engine_log_lock:
            _logged_engine_urls.add(base_url)
    except Exception:
        logger.warning("VOICEVOXエンジン情報を取得できません", exc_info=True)


def _timeout_error(error):
    if isinstance(error, StreamingPlaybackError):
        error = error.original_error
    if isinstance(error, URLError):
        error = error.reason
    return isinstance(error, TimeoutError)


def synthesize_streaming_and_play(
    text,
    url,
    speaker,
    device_id,
    volume,
    pan,
    timeout,
    category="preview",
):
    """ストリーミング優先で合成・再生し、完成したWAVを返す。"""
    log_engine_capabilities(url, timeout)
    attempts = 2
    with _voicevox_request_lock:
        for attempt in range(1, attempts + 1):
            started_at = time.monotonic()
            standard_fallback = False
            logger.info(
                "VOICEVOXストリーミング合成を開始します: "
                "category=%s attempt=%d/%d timeout=%ss speaker=%s text=%r",
                category,
                attempt,
                attempts,
                timeout,
                speaker,
                text,
            )
            try:
                query = _audio_query(text, url, speaker, timeout)
                request = _synthesis_request(
                    query,
                    url,
                    speaker,
                    "streaming_synthesis",
                )
                try:
                    with urlopen(request, timeout=timeout) as response:
                        stream_started_at = time.monotonic()
                        wav, first_audio_seconds = play_wav_stream(
                            response,
                            device_id,
                            volume,
                            pan,
                        )
                    first_audio_seconds += stream_started_at - started_at
                    logger.info(
                        "VOICEVOXストリーミング再生が完了しました: "
                        "category=%s attempt=%d/%d first_audio=%.3fs "
                        "elapsed=%.3fs bytes=%d text=%r",
                        category,
                        attempt,
                        attempts,
                        first_audio_seconds,
                        time.monotonic() - started_at,
                        len(wav),
                        text,
                    )
                    return wav
                except HTTPError as error:
                    if error.code not in (404, 405, 422):
                        raise
                    logger.warning(
                        "VOICEVOXがストリーミング合成に対応していないため"
                        "通常合成へフォールバックします: status=%s",
                        error.code,
                    )
                    standard_fallback = True
                    request = _synthesis_request(query, url, speaker)
                    with urlopen(request, timeout=timeout) as response:
                        wav = response.read()
                    play_wav(wav, device_id, volume, pan)
                    logger.info(
                        "VOICEVOX通常合成の再生が完了しました: "
                        "category=%s elapsed=%.3fs bytes=%d text=%r",
                        category,
                        time.monotonic() - started_at,
                        len(wav),
                        text,
                    )
                    return wav
            except Exception as error:
                audio_started = isinstance(error, StreamingPlaybackError) and (
                    error.audio_started
                )
                can_retry = _timeout_error(error) and not audio_started
                can_retry = can_retry and not standard_fallback
                if can_retry and attempt < attempts:
                    logger.warning(
                        "VOICEVOX音声受信前にタイムアウトしたため再試行します: "
                        "category=%s attempt=%d/%d elapsed=%.3fs text=%r",
                        category,
                        attempt,
                        attempts,
                        time.monotonic() - started_at,
                        text,
                    )
                    continue
                if audio_started:
                    logger.error(
                        "VOICEVOX音声の再生開始後に失敗したため再試行しません: "
                        "category=%s elapsed=%.3fs text=%r",
                        category,
                        time.monotonic() - started_at,
                        text,
                    )
                raise


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
            wav = load_cached_wav(self.url, self.speaker, text)
            if wav is not None:
                logger.info("VOICEVOXテスト再生にキャッシュを使用します: text=%r", text)
                play_wav(wav, self.device_id, self.volume, self.pan)
            else:
                wav = synthesize_streaming_and_play(
                    text,
                    self.url,
                    self.speaker,
                    self.device_id,
                    self.volume,
                    self.pan,
                    self.timeout,
                )
                save_cached_wav(self.url, self.speaker, text, wav)
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
                    cached_wav = load_cached_wav(key[0], key[1], text)
                    if cached_wav is not None:
                        logger.info(
                            "VOICEVOX永続キャッシュを使用します: "
                            "category=%s text=%r",
                            category,
                            text,
                        )
                        cache[key] = cached_wav
                    else:
                        wav = synthesize_streaming_and_play(
                            text,
                            key[0],
                            key[1],
                            settings["voice_output_device"],
                            settings["voice_volume"],
                            settings["voice_pan"],
                            settings["voicevox_timeout_seconds"],
                            category,
                        )
                        save_cached_wav(key[0], key[1], text, wav)
                        if len(cache) >= 64:
                            cache.clear()
                        cache[key] = wav
                        continue
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
