"""Run: uv run --active python -B -m unittest misc.test_voice_guidance"""

import io
import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import numpy as np
from PySide6.QtMultimedia import QtAudio

from src.config import ALERT_OUTPUT_VOICEVOX, Config
from src.http_server import BrowserHTTPServer
from src.voice_audio import (
    _StreamingPlaybackThread,
    StreamingPlaybackError,
    apply_pan,
    streaming_playback_complete,
    streaming_wav_header,
    wav_pcm,
)
from src.voice_guidance import (
    VoiceGuidance,
    load_cached_wav,
    save_cached_wav,
    shop_price_announcement,
    start_voice_preview,
    synthesize_streaming_and_play,
)


def wav_data(samples=(1000, -1000), channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(np.array(samples, dtype="<i2").tobytes())
    return output.getvalue()


class VoiceAudioTest(unittest.TestCase):
    def test_apply_pan_expands_mono_and_places_sound_left(self):
        pcm, audio_format = wav_pcm(wav_data())
        result, output_format = apply_pan(pcm, audio_format, -100)

        samples = np.frombuffer(result, dtype="<i2").reshape(-1, 2)
        self.assertEqual(output_format.channelCount(), 2)
        self.assertTrue(np.array_equal(samples[:, 0], np.array([1000, -1000])))
        self.assertTrue(np.array_equal(samples[:, 1], np.array([0, 0])))

    def test_center_does_not_rewrite_audio(self):
        pcm, audio_format = wav_pcm(wav_data())
        result, same_format = apply_pan(pcm, audio_format, 0)
        self.assertIs(result, pcm)
        self.assertIs(same_format, audio_format)

    def test_streaming_wav_header_finds_pcm_start_and_format(self):
        wav = wav_data()
        pcm_offset, audio_format = streaming_wav_header(wav)

        self.assertEqual(wav[pcm_offset:], np.array([1000, -1000], dtype="<i2").tobytes())
        self.assertEqual(audio_format.sampleRate(), 24000)
        self.assertEqual(audio_format.channelCount(), 1)

    def test_streaming_playback_completes_when_active_sink_processed_all_audio(self):
        sink = MagicMock()
        sink.state.return_value = QtAudio.State.ActiveState
        sink.processedUSecs.return_value = 1_000_000

        self.assertTrue(streaming_playback_complete(sink, 1_000_000))

    def test_streaming_playback_waits_while_active_sink_has_audio_remaining(self):
        sink = MagicMock()
        sink.state.return_value = QtAudio.State.ActiveState
        sink.processedUSecs.return_value = 999_999

        self.assertFalse(streaming_playback_complete(sink, 1_000_000))

    @patch("src.voice_audio.QAudioSink")
    @patch("src.voice_audio.resolve_audio_device")
    def test_streaming_player_writes_pcm_before_response_finishes(
        self,
        resolve_device,
        audio_sink,
    ):
        wav = wav_data(samples=tuple(range(200)))
        chunks = [wav[:17], wav[17:51], wav[51:173], wav[173:], b""]
        response = MagicMock()
        response.read.side_effect = chunks
        resolve_device.return_value.isFormatSupported.return_value = True
        sink = audio_sink.return_value
        sink.error.return_value = QtAudio.Error.NoError
        sink.bytesFree.return_value = 65536
        sink.state.return_value = QtAudio.State.IdleState
        output = sink.start.return_value
        output.write.side_effect = lambda data: len(data)

        worker = _StreamingPlaybackThread(response, "", 100, 0)
        worker.run()

        self.assertIsNone(worker.failure)
        self.assertTrue(worker.audio_started)
        self.assertEqual(worker.wav, wav)
        self.assertGreaterEqual(output.write.call_count, 2)


class HTTPServerErrorTest(unittest.TestCase):
    @patch(
        "src.http_server._ThreadingHTTPServer",
        side_effect=OSError(10048, "address already in use"),
    )
    def test_listen_error_is_retained_for_voice_guidance(self, _server):
        server = BrowserHTTPServer(SimpleNamespace(), port=8787)

        self.assertFalse(server.start())
        self.assertEqual(server.last_error.errno, 10048)


class VoiceGuidanceTest(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "voice_startup": False,
            "voice_shutdown": False,
            "voice_errors": False,
            "voice_dosukoi_alert": False,
            "voice_entou_alert": False,
            "voice_capture_saved": False,
            "voice_shop_price": False,
            "voicevox_url": "http://127.0.0.1:50021",
            "voicevox_speaker_id": 3,
            "voicevox_timeout_seconds": 30,
            "voice_output_device": "device-id",
            "voice_volume": 80,
            "voice_pan": -25,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_shop_price_message_is_natural(self):
        self.assertEqual(
            shop_price_announcement(
                6500,
                "腕輪",
                ["毒消しの腕輪", "忍び足の腕輪"],
            ),
            "6500ギタン腕輪、毒消しか忍び足です",
        )

    @patch("src.voice_guidance.save_cached_wav")
    @patch("src.voice_guidance.load_cached_wav", return_value=None)
    @patch("src.voice_guidance.synthesize_streaming_and_play", return_value=b"wav")
    def test_enabled_message_is_streamed_and_cached(
        self,
        stream_play,
        _load_cache,
        save_cache,
    ):
        guidance = VoiceGuidance(self.config(voice_capture_saved=True))
        try:
            guidance.announce("capture_saved", "キャプチャ画像を保存しました")
            deadline = time.monotonic() + 2
            while not stream_play.called and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        stream_play.assert_called_once_with(
            "キャプチャ画像を保存しました",
            "http://127.0.0.1:50021",
            3,
            "device-id",
            80,
            -25,
            30,
            "capture_saved",
        )
        save_cache.assert_called_once_with(
            "http://127.0.0.1:50021",
            3,
            "キャプチャ画像を保存しました",
            b"wav",
        )

    @patch("src.voice_guidance.synthesize_streaming_and_play")
    def test_disabled_message_is_ignored(self, stream_play):
        guidance = VoiceGuidance(self.config())
        guidance.announce("shop_price", "6500ギタン腕輪、毒消しです")
        time.sleep(0.15)
        guidance.shutdown()
        stream_play.assert_not_called()

    @patch("src.voice_guidance.load_cached_wav", return_value=None)
    @patch("src.voice_guidance.synthesize_streaming_and_play", return_value=b"wav")
    def test_startup_announcement_uses_its_own_switch(
        self,
        stream_play,
        _load_cache,
    ):
        guidance = VoiceGuidance(self.config(voice_startup=True))
        try:
            guidance.announce("startup", "シレン6ヘルパーを起動しました")
            deadline = time.monotonic() + 2
            while not stream_play.called and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        self.assertEqual(stream_play.call_args.args[-1], "startup")

    @patch("src.voice_guidance.random.choice", return_value="遠投状態です")
    @patch("src.voice_guidance.load_cached_wav", return_value=b"wav")
    @patch("src.voice_guidance.play_wav", side_effect=RuntimeError("device error"))
    def test_preview_uses_random_event_message_and_exposes_playback_failure(
        self,
        _play_wav,
        _load_cache,
        choice,
    ):
        worker = start_voice_preview("http://127.0.0.1:50021", 1)
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(worker.failure, "device error")
        choice.assert_called_once()

    @patch("src.voice_guidance.load_cached_wav", return_value=None)
    @patch("src.voice_guidance.synthesize_streaming_and_play", return_value=b"wav")
    def test_shutdown_announcement_finishes_before_worker_exits(
        self,
        stream_play,
        _load_cache,
    ):
        guidance = VoiceGuidance(self.config(voice_shutdown=True))
        guidance.shutdown()
        guidance._worker.join(timeout=2)

        self.assertTrue(guidance.is_finished())
        self.assertEqual(stream_play.call_args.args[-1], "shutdown")

    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.load_cached_wav", return_value=None)
    @patch("src.voice_guidance.synthesize_streaming_and_play", return_value=b"wav")
    def test_error_is_announced_once_until_recovery(
        self,
        stream_play,
        _load_cache,
        play_wav,
    ):
        guidance = VoiceGuidance(self.config(voice_errors=True))
        try:
            guidance.error_state("http", "HTTPサーバーを起動できません")
            guidance.error_state("http", "HTTPサーバーを起動できません")
            deadline = time.monotonic() + 2
            while not stream_play.called and time.monotonic() < deadline:
                time.sleep(0.01)

            guidance.error_state("http")
            guidance.error_state("http", "HTTPサーバーを起動できません")
            deadline = time.monotonic() + 2
            while not play_wav.called and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        self.assertEqual(stream_play.call_count, 1)
        play_wav.assert_called_once_with(b"wav", "device-id", 80, -25)

    @patch("src.voice_guidance.synthesize_streaming_and_play")
    def test_error_is_ignored_when_error_voice_is_disabled(self, stream_play):
        guidance = VoiceGuidance(self.config())
        guidance.error_state("spout", "Spoutの映像を受信できません")
        time.sleep(0.15)
        guidance.shutdown()

        stream_play.assert_not_called()

    def test_persistent_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.voice_guidance.VOICE_CACHE_DIR",
            Path(temp_dir),
        ):
            save_cached_wav("http://127.0.0.1:50021", 3, "テスト", wav_data())
            cached = load_cached_wav("http://127.0.0.1:50021", 3, "テスト")

        self.assertEqual(cached, wav_data())

    @patch("src.voice_guidance.log_engine_capabilities")
    @patch("src.voice_guidance._audio_query", return_value={})
    @patch("src.voice_guidance.play_wav_stream")
    @patch("src.voice_guidance.urlopen")
    def test_timeout_before_audio_is_retried_once(
        self,
        urlopen,
        play_stream,
        _audio_query,
        _capabilities,
    ):
        response = MagicMock()
        urlopen.return_value.__enter__.return_value = response
        play_stream.side_effect = (
            StreamingPlaybackError(TimeoutError("timed out"), False),
            (b"wav", 0.25),
        )

        result = synthesize_streaming_and_play(
            "テスト",
            "http://127.0.0.1:50021",
            3,
            "device-id",
            80,
            0,
            30,
        )

        self.assertEqual(result, b"wav")
        self.assertEqual(play_stream.call_count, 2)

    @patch("src.voice_guidance.log_engine_capabilities")
    @patch("src.voice_guidance._audio_query", return_value={})
    @patch(
        "src.voice_guidance.play_wav_stream",
        side_effect=StreamingPlaybackError(TimeoutError("timed out"), True),
    )
    @patch("src.voice_guidance.urlopen")
    def test_timeout_after_audio_started_is_not_retried(
        self,
        urlopen,
        play_stream,
        _audio_query,
        _capabilities,
    ):
        urlopen.return_value.__enter__.return_value = MagicMock()

        with self.assertRaises(StreamingPlaybackError):
            synthesize_streaming_and_play(
                "テスト",
                "http://127.0.0.1:50021",
                3,
                "device-id",
                80,
                0,
                30,
            )

        self.assertEqual(play_stream.call_count, 1)

    @patch("src.voice_guidance.log_engine_capabilities")
    @patch("src.voice_guidance._audio_query", return_value={})
    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.urlopen")
    def test_unsupported_streaming_falls_back_to_standard_synthesis(
        self,
        urlopen,
        play_wav,
        _audio_query,
        _capabilities,
    ):
        standard_response = MagicMock()
        standard_response.read.return_value = b"wav"
        standard_context = MagicMock()
        standard_context.__enter__.return_value = standard_response
        urlopen.side_effect = (
            HTTPError("http://voicevox/streaming_synthesis", 404, "", {}, None),
            standard_context,
        )

        result = synthesize_streaming_and_play(
            "テスト",
            "http://127.0.0.1:50021",
            3,
            "device-id",
            80,
            0,
            30,
        )

        self.assertEqual(result, b"wav")
        play_wav.assert_called_once_with(b"wav", "device-id", 80, 0)


class VoiceConfigTest(unittest.TestCase):
    def test_voice_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            config.alert_output = ALERT_OUTPUT_VOICEVOX
            config.voice_startup = True
            config.voice_shutdown = True
            config.voice_errors = True
            config.voice_shop_price = True
            config.voicevox_speaker_id = 42
            config.voicevox_timeout_seconds = 45
            config.voice_output_device = "abc123"
            config.voice_volume = 60
            config.voice_pan = 75
            config.save_config()

            loaded = Config(str(config_path))

        self.assertEqual(loaded.alert_output, ALERT_OUTPUT_VOICEVOX)
        self.assertTrue(loaded.voice_startup)
        self.assertTrue(loaded.voice_shutdown)
        self.assertTrue(loaded.voice_errors)
        self.assertTrue(loaded.voice_shop_price)
        self.assertEqual(loaded.voicevox_speaker_id, 42)
        self.assertEqual(loaded.voicevox_timeout_seconds, 45)
        self.assertEqual(loaded.voice_output_device, "abc123")
        self.assertEqual(loaded.voice_volume, 60)
        self.assertEqual(loaded.voice_pan, 75)

    def test_invalid_voice_values_are_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "alert_output": "invalid",
                        "voicevox_speaker_id": -5,
                        "voicevox_timeout_seconds": 500,
                        "voice_volume": 500,
                        "voice_pan": -500,
                    }
                ),
                encoding="utf-8",
            )
            config = Config(str(config_path))

        self.assertEqual(config.alert_output, "sound")
        self.assertEqual(config.voicevox_speaker_id, 0)
        self.assertEqual(config.voicevox_timeout_seconds, 300)
        self.assertEqual(config.voice_volume, 100)
        self.assertEqual(config.voice_pan, -100)


if __name__ == "__main__":
    unittest.main()
