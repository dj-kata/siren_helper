"""Spoutの接続管理とフレーム変換を、OBS/GPUを使わずに検証する。"""

import ctypes
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.config import CAPTURE_MODE_SPOUT, Config, DEFAULT_SPOUT_SENDER_NAME, OCR_CAPTURE_SIZE
from src.spout_capture import SpoutCapture


class ConfigTests(unittest.TestCase):
    def test_sender_round_trip_and_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"obs_enabled": True}))
            config = Config(str(path))
            self.assertEqual(config.capture_mode, "obs")
            self.assertEqual(config.spout_sender_name, DEFAULT_SPOUT_SENDER_NAME)
            config.capture_mode = CAPTURE_MODE_SPOUT
            config.spout_sender_name = "  Shiren Filter  "
            config.save_config()
            loaded = Config(str(path))
            self.assertEqual(loaded.capture_mode, CAPTURE_MODE_SPOUT)
            self.assertFalse(loaded.obs_enabled)
            self.assertEqual(loaded.spout_sender_name, "Shiren Filter")
            loaded.spout_sender_name = "  "
            loaded.save_config()
            self.assertEqual(Config(str(path)).spout_sender_name, DEFAULT_SPOUT_SENDER_NAME)


class ReceiverTests(unittest.TestCase):
    def test_missing_dependency_reports_error(self):
        capture = SpoutCapture()
        with patch.object(capture, "dependency_error", return_value="missing SpoutGL"):
            self.assertFalse(capture.start("Filter"))
        self.assertEqual(capture.current_status(), ("error", "missing SpoutGL"))
        self.assertIsNone(capture.get_latest_frame())

    def test_sender_change_restarts_and_stop_clears_frame(self):
        capture = SpoutCapture()
        gui = SimpleNamespace(QOffscreenSurface=Mock())
        with patch.dict("sys.modules", {"PySide6.QtGui": gui}), patch.object(
            capture, "dependency_error", return_value=None
        ), patch.object(capture, "_run", side_effect=lambda: capture._stop_event.wait(2)):
            try:
                self.assertTrue(capture.start("  First  "))
                first_thread = capture._thread
                self.assertFalse(capture.start("First"))
                self.assertIs(capture._thread, first_thread)
                capture._latest_frame = np.zeros((1, 1, 3), dtype=np.uint8)
                self.assertTrue(capture.start("Second"))
                self.assertFalse(first_thread.is_alive())
                self.assertEqual(capture._sender_name, "Second")
                self.assertIsNone(capture.get_latest_frame())
            finally:
                self.assertTrue(capture.stop())
            self.assertIsNone(capture._thread)
            self.assertIsNone(capture._surface)

    def test_receive_resize_disconnect_and_reconnect(self):
        capture = SpoutCapture()
        capture._sender_name = "Shiren Filter"
        capture._surface = Mock()
        context = Mock()
        gl = Mock()
        # First connection, one frame, disconnect, reconnect with a new size, one frame.
        sizes = [(1920, 1080), (1920, 1080), (0, 0), (1280, 720), (1280, 720)]
        received = []
        sender = Mock()
        sender.__enter__ = Mock(return_value=sender)
        sender.__exit__ = Mock(return_value=False)
        sender.getSenderList.return_value = []
        step = -1

        def receive(*_args):
            nonlocal step
            step += 1
            width, height = sizes[step]
            sender.isConnected.return_value = width > 0
            sender.getSenderWidth.return_value = width
            sender.getSenderHeight.return_value = height
            sender.isUpdated.return_value = False
            sender.isFrameNew.return_value = True
            if step == 3:
                # A disconnected sender must not leave an old frame available to OCR.
                self.assertIsNone(capture.get_latest_frame())
            return True

        def read_pixels(_target, _level, _format, _type, destination):
            width, height = sizes[step]
            rgba = np.full((height, width, 4), (231, 42, 17, 255), dtype=np.uint8)
            ctypes.memmove(destination, rgba.ctypes.data, rgba.nbytes)

        def sync(*_args):
            received.append(capture.get_latest_frame().copy())
            if step == len(sizes) - 1:
                capture._stop_event.set()

        sender.receiveTexture.side_effect = receive
        sender.waitFrameSync.side_effect = sync
        gl.glGenTextures.side_effect = lambda _count, pointer: setattr(pointer._obj, "value", 1)
        gl.glGetTexImage.side_effect = read_pixels
        gui = SimpleNamespace(QOpenGLContext=Mock(return_value=context))
        with patch.dict("sys.modules", {
            "SpoutGL": SimpleNamespace(SpoutReceiver=Mock(return_value=sender)),
            "PySide6.QtGui": gui,
        }), patch("ctypes.WinDLL", return_value=gl, create=True):
            capture._run()
        sender.setReceiverName.assert_called_once_with("Shiren Filter")
        self.assertEqual(len(received), 2)
        for frame in received:
            self.assertEqual(frame.shape, (OCR_CAPTURE_SIZE[1], OCR_CAPTURE_SIZE[0], 3))
            self.assertTrue(np.all(frame == (231, 42, 17)))
        gl.glDeleteTextures.assert_called_once()
        context.doneCurrent.assert_called_once()
        self.assertEqual(capture.current_status()[0], "connected")

    def test_receiver_error_discards_old_frame(self):
        capture = SpoutCapture()
        capture._latest_frame = np.zeros((1, 1, 3), dtype=np.uint8)
        with patch.dict("sys.modules", {"SpoutGL": None}):
            capture._run()
        self.assertIsNone(capture.get_latest_frame())
        self.assertFalse(capture.is_connected)
        self.assertEqual(capture.current_status()[0], "error")


if __name__ == "__main__":
    unittest.main()
