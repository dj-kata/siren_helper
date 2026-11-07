"""Run: uv run --active python -B -m unittest misc.test_voice_guidance"""

import io
import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.config import ALERT_OUTPUT_VOICEVOX, Config
from src.http_server import BrowserHTTPServer
from src.voice_audio import apply_pan, wav_pcm
from src.voice_guidance import (
    VoiceGuidance,
    shop_price_announcement,
    start_voice_preview,
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

    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.synthesize", return_value=b"wav")
    def test_enabled_message_is_synthesized_and_played(self, synthesize, play_wav):
        guidance = VoiceGuidance(self.config(voice_capture_saved=True))
        try:
            guidance.announce("capture_saved", "キャプチャ画像を保存しました")
            deadline = time.monotonic() + 2
            while not play_wav.called and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        synthesize.assert_called_once_with(
            "キャプチャ画像を保存しました",
            "http://127.0.0.1:50021",
            3,
        )
        play_wav.assert_called_once_with(b"wav", "device-id", 80, -25)

    @patch("src.voice_guidance.synthesize")
    def test_disabled_message_is_ignored(self, synthesize):
        guidance = VoiceGuidance(self.config())
        guidance.announce("shop_price", "6500ギタン腕輪、毒消しです")
        time.sleep(0.15)
        guidance.shutdown()
        synthesize.assert_not_called()

    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.synthesize", return_value=b"wav")
    def test_startup_announcement_uses_its_own_switch(self, synthesize, play_wav):
        guidance = VoiceGuidance(self.config(voice_startup=True))
        try:
            guidance.announce("startup", "シレン6ヘルパーを起動しました")
            deadline = time.monotonic() + 2
            while not play_wav.called and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        synthesize.assert_called_once_with(
            "シレン6ヘルパーを起動しました",
            "http://127.0.0.1:50021",
            3,
        )

    @patch("src.voice_guidance.random.choice", return_value="遠投状態です")
    @patch("src.voice_guidance.play_wav", side_effect=RuntimeError("device error"))
    @patch("src.voice_guidance.synthesize", return_value=b"wav")
    def test_preview_uses_random_event_message_and_exposes_playback_failure(
        self,
        synthesize,
        _play_wav,
        choice,
    ):
        worker = start_voice_preview("http://127.0.0.1:50021", 1)
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(worker.failure, "device error")
        choice.assert_called_once()
        synthesize.assert_called_once_with(
            "遠投状態です",
            "http://127.0.0.1:50021",
            1,
        )

    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.synthesize", return_value=b"wav")
    def test_shutdown_announcement_finishes_before_worker_exits(
        self,
        synthesize,
        play_wav,
    ):
        guidance = VoiceGuidance(self.config(voice_shutdown=True))
        guidance.shutdown()
        guidance._worker.join(timeout=2)

        self.assertTrue(guidance.is_finished())
        synthesize.assert_called_once_with(
            "シレン6ヘルパーを終了します",
            "http://127.0.0.1:50021",
            3,
        )
        play_wav.assert_called_once_with(b"wav", "device-id", 80, -25)

    @patch("src.voice_guidance.play_wav")
    @patch("src.voice_guidance.synthesize", return_value=b"wav")
    def test_error_is_announced_once_until_recovery(self, synthesize, play_wav):
        guidance = VoiceGuidance(self.config(voice_errors=True))
        try:
            guidance.error_state("http", "HTTPサーバーを起動できません")
            guidance.error_state("http", "HTTPサーバーを起動できません")
            deadline = time.monotonic() + 2
            while play_wav.call_count < 1 and time.monotonic() < deadline:
                time.sleep(0.01)

            guidance.error_state("http")
            guidance.error_state("http", "HTTPサーバーを起動できません")
            deadline = time.monotonic() + 2
            while play_wav.call_count < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            guidance.shutdown()

        synthesize.assert_called_once_with(
            "HTTPサーバーを起動できません",
            "http://127.0.0.1:50021",
            3,
        )
        self.assertEqual(play_wav.call_count, 2)

    @patch("src.voice_guidance.synthesize")
    def test_error_is_ignored_when_error_voice_is_disabled(self, synthesize):
        guidance = VoiceGuidance(self.config())
        guidance.error_state("spout", "Spoutの映像を受信できません")
        time.sleep(0.15)
        guidance.shutdown()

        synthesize.assert_not_called()


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
                        "voice_volume": 500,
                        "voice_pan": -500,
                    }
                ),
                encoding="utf-8",
            )
            config = Config(str(config_path))

        self.assertEqual(config.alert_output, "sound")
        self.assertEqual(config.voicevox_speaker_id, 0)
        self.assertEqual(config.voice_volume, 100)
        self.assertEqual(config.voice_pan, -100)


if __name__ == "__main__":
    unittest.main()
