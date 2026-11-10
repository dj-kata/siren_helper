"""選択したQt音声出力へVOICEVOXのWAVを同期再生する。"""

from io import BytesIO
import struct
import time
import wave

import numpy as np
from PySide6.QtCore import QBuffer, QEventLoop, QIODevice, QThread, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio


class StreamingPlaybackError(RuntimeError):
    def __init__(self, error, audio_started=False):
        super().__init__(str(error) or type(error).__name__)
        self.original_error = error
        self.audio_started = audio_started


def streaming_playback_complete(sink, expected_duration_us):
    """プッシュ再生が出力済みかをQtの状態と処理済み時間から判定する。"""
    if sink.state() == QtAudio.State.IdleState:
        return True
    return (
        expected_duration_us > 0
        and sink.processedUSecs() >= expected_duration_us
    )


def audio_output_devices():
    return [
        (bytes(device.id()).hex(), device.description())
        for device in QMediaDevices.audioOutputs()
    ]


def resolve_audio_device(device_id):
    if device_id:
        for device in QMediaDevices.audioOutputs():
            if bytes(device.id()).hex() == device_id:
                return device
        raise RuntimeError("選択した音声出力デバイスが見つかりません")
    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        raise RuntimeError("音声出力デバイスがありません")
    return device


def wav_pcm(wav):
    with wave.open(BytesIO(wav), "rb") as source:
        formats = {
            1: QAudioFormat.SampleFormat.UInt8,
            2: QAudioFormat.SampleFormat.Int16,
            4: QAudioFormat.SampleFormat.Int32,
        }
        sample_format = formats.get(source.getsampwidth())
        if sample_format is None:
            raise ValueError("対応していないWAVサンプル形式です")
        audio_format = QAudioFormat()
        audio_format.setSampleRate(source.getframerate())
        audio_format.setChannelCount(source.getnchannels())
        audio_format.setSampleFormat(sample_format)
        return source.readframes(source.getnframes()), audio_format


def streaming_wav_header(data):
    """WAVヘッダーが揃ったらPCM開始位置と音声形式を返す。"""
    if len(data) < 12:
        return None
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("VOICEVOXのストリームがWAV形式ではありません")

    offset = 12
    audio_format = None
    while True:
        if len(data) < offset + 8:
            return None
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_start = offset + 8
        if chunk_id == b"fmt ":
            if len(data) < chunk_start + chunk_size:
                return None
            if chunk_size < 16:
                raise ValueError("VOICEVOXのWAV fmtチャンクが不正です")
            format_code, channels, sample_rate, _byte_rate, _align, bits = (
                struct.unpack_from("<HHIIHH", data, chunk_start)
            )
            if format_code != 1:
                raise ValueError("VOICEVOXのWAVがPCM形式ではありません")
            sample_format = {
                8: QAudioFormat.SampleFormat.UInt8,
                16: QAudioFormat.SampleFormat.Int16,
                32: QAudioFormat.SampleFormat.Int32,
            }.get(bits)
            if sample_format is None:
                raise ValueError("対応していないWAVサンプル形式です")
            audio_format = QAudioFormat()
            audio_format.setSampleRate(sample_rate)
            audio_format.setChannelCount(channels)
            audio_format.setSampleFormat(sample_format)
        elif chunk_id == b"data":
            if audio_format is None:
                raise ValueError("VOICEVOXのWAVにfmtチャンクがありません")
            return chunk_start, audio_format

        if len(data) < chunk_start + chunk_size:
            return None
        offset = chunk_start + chunk_size + (chunk_size % 2)


def apply_pan(pcm, audio_format, pan):
    """直線的な左右バランスを適用し、必要ならモノラルをステレオ化する。"""
    pan = max(-100, min(100, pan)) / 100
    if not pan or not pcm:
        return pcm, audio_format
    channels = audio_format.channelCount()
    if channels not in (1, 2):
        raise ValueError("定位はモノラルまたはステレオ音声に対応しています")
    dtype = {
        QAudioFormat.SampleFormat.UInt8: np.dtype("u1"),
        QAudioFormat.SampleFormat.Int16: np.dtype("<i2"),
        QAudioFormat.SampleFormat.Int32: np.dtype("<i4"),
    }[audio_format.sampleFormat()]
    samples = np.frombuffer(pcm, dtype=dtype).reshape(-1, channels).astype(np.float64)
    offset = 128 if dtype == np.dtype("u1") else 0
    samples -= offset
    if channels == 1:
        samples = np.repeat(samples, 2, axis=1)
    samples *= [1 - max(0, pan), 1 + min(0, pan)]
    limits = np.iinfo(dtype)
    result = np.clip(np.rint(samples + offset), limits.min, limits.max).astype(dtype)
    output_format = QAudioFormat(audio_format)
    output_format.setChannelCount(2)
    return result.tobytes(), output_format


class _PlaybackThread(QThread):
    """音声sinkとイベントループをGUIスレッド外で所有する。"""

    def __init__(self, wav, device_id, volume, pan):
        super().__init__()
        self.wav = wav
        self.device_id = device_id
        self.volume = volume
        self.pan = pan
        self.failure = None

    def run(self):
        sink = None
        timeout = None
        state_timer = None
        playback_started = False
        try:
            pcm, audio_format = wav_pcm(self.wav)
            pcm, audio_format = apply_pan(pcm, audio_format, self.pan)
            if not pcm:
                return
            device = resolve_audio_device(self.device_id)
            if not device.isFormatSupported(audio_format):
                raise RuntimeError("音声出力デバイスがWAVの形式に対応していません")
            loop = QEventLoop()
            buffer = QBuffer()
            buffer.setData(pcm)
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            sink = QAudioSink(device, audio_format)
            sink.setVolume(max(0, min(100, self.volume)) / 100)

            def check_state():
                nonlocal playback_started
                state = sink.state()
                if state in (QtAudio.State.ActiveState, QtAudio.State.SuspendedState):
                    playback_started = True
                elif state == QtAudio.State.IdleState and (
                    playback_started or sink.processedUSecs() > 0
                ):
                    loop.quit()
                elif state == QtAudio.State.StoppedState and (
                    playback_started or sink.error() != QtAudio.Error.NoError
                ):
                    loop.quit()

            state_timer = QTimer()
            state_timer.setInterval(20)
            state_timer.timeout.connect(check_state)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            duration_ms = audio_format.durationForBytes(len(pcm)) // 1000
            timeout.start(int(duration_ms + 5000))
            sink.start(buffer)
            state_timer.start()
            loop.exec()
            if not timeout.isActive():
                raise RuntimeError("音声出力デバイスで再生を開始できませんでした")
            if sink.error() != QtAudio.Error.NoError:
                raise RuntimeError(f"音声再生に失敗しました: {sink.error()}")
            if not playback_started and sink.processedUSecs() <= 0:
                raise RuntimeError("音声出力デバイスで再生を開始できませんでした")
        except Exception as error:
            self.failure = error.with_traceback(None)
        finally:
            if state_timer is not None:
                state_timer.stop()
            if timeout is not None:
                timeout.stop()
            if sink is not None:
                sink.stop()


class _StreamingPlaybackThread(QThread):
    """VOICEVOXのWAVレスポンスを受信しながら再生する。"""

    def __init__(self, response, device_id, volume, pan, chunk_size=16384):
        super().__init__()
        self.response = response
        self.device_id = device_id
        self.volume = volume
        self.pan = pan
        self.chunk_size = chunk_size
        self.failure = None
        self.audio_started = False
        self.first_audio_seconds = None
        self.wav = b""

    @staticmethod
    def _sample_width(audio_format):
        return {
            QAudioFormat.SampleFormat.UInt8: 1,
            QAudioFormat.SampleFormat.Int16: 2,
            QAudioFormat.SampleFormat.Int32: 4,
        }[audio_format.sampleFormat()]

    @staticmethod
    def _write_all(target, sink, data):
        offset = 0
        while offset < len(data):
            if sink.error() != QtAudio.Error.NoError:
                raise RuntimeError(f"音声再生に失敗しました: {sink.error()}")
            available = sink.bytesFree()
            if available <= 0:
                QThread.msleep(5)
                continue
            written = target.write(data[offset : offset + available])
            if written < 0:
                raise RuntimeError("音声出力デバイスへの書き込みに失敗しました")
            if written == 0:
                QThread.msleep(5)
                continue
            offset += written

    def run(self):
        sink = None
        started_at = time.monotonic()
        wav = bytearray()
        header_buffer = bytearray()
        pending_pcm = bytearray()
        header_parsed = False
        input_format = None
        output_format = None
        output = None
        written_bytes = 0
        try:
            while True:
                chunk = self.response.read(self.chunk_size)
                if not chunk:
                    break
                wav.extend(chunk)
                if not header_parsed:
                    header_buffer.extend(chunk)
                    parsed = streaming_wav_header(header_buffer)
                    if parsed is None:
                        continue
                    pcm_offset, input_format = parsed
                    pending_pcm.extend(header_buffer[pcm_offset:])
                    header_parsed = True
                    header_buffer.clear()
                else:
                    pending_pcm.extend(chunk)

                frame_size = (
                    self._sample_width(input_format) * input_format.channelCount()
                )
                aligned_size = len(pending_pcm) - (len(pending_pcm) % frame_size)
                if aligned_size <= 0:
                    continue
                pcm = bytes(pending_pcm[:aligned_size])
                del pending_pcm[:aligned_size]
                pcm, chunk_format = apply_pan(pcm, input_format, self.pan)

                if sink is None:
                    output_format = chunk_format
                    device = resolve_audio_device(self.device_id)
                    if not device.isFormatSupported(output_format):
                        raise RuntimeError(
                            "音声出力デバイスがWAVの形式に対応していません"
                        )
                    sink = QAudioSink(device, output_format)
                    sink.setVolume(max(0, min(100, self.volume)) / 100)
                    output = sink.start()
                    if output is None:
                        raise RuntimeError("音声出力デバイスを開始できませんでした")
                    self.audio_started = True
                    self.first_audio_seconds = time.monotonic() - started_at

                self._write_all(output, sink, pcm)
                written_bytes += len(pcm)

            if not header_parsed:
                raise RuntimeError("VOICEVOXからWAVヘッダーを受信できませんでした")
            if pending_pcm:
                frame_size = (
                    self._sample_width(input_format) * input_format.channelCount()
                )
                if len(pending_pcm) % frame_size:
                    raise RuntimeError("VOICEVOXのPCMデータ長が不正です")
                pcm, chunk_format = apply_pan(
                    bytes(pending_pcm), input_format, self.pan
                )
                if sink is None:
                    output_format = chunk_format
                    device = resolve_audio_device(self.device_id)
                    sink = QAudioSink(device, output_format)
                    sink.setVolume(max(0, min(100, self.volume)) / 100)
                    output = sink.start()
                    self.audio_started = True
                    self.first_audio_seconds = time.monotonic() - started_at
                self._write_all(output, sink, pcm)
                written_bytes += len(pcm)

            if sink is None or written_bytes <= 0:
                raise RuntimeError("VOICEVOXから音声データを受信できませんでした")

            duration_us = output_format.durationForBytes(written_bytes)
            duration_seconds = duration_us / 1_000_000
            drain_deadline = time.monotonic() + duration_seconds + 5
            while time.monotonic() < drain_deadline:
                if sink.error() != QtAudio.Error.NoError:
                    raise RuntimeError(f"音声再生に失敗しました: {sink.error()}")
                if streaming_playback_complete(sink, duration_us):
                    break
                QThread.msleep(20)
            else:
                raise RuntimeError("ストリーミング音声の再生完了を確認できませんでした")
            self.wav = bytes(wav)
        except Exception as error:
            self.failure = StreamingPlaybackError(
                error.with_traceback(None),
                self.audio_started,
            )
        finally:
            if sink is not None:
                sink.stop()


def play_wav(wav, device_id="", volume=100, pan=0):
    worker = _PlaybackThread(wav, device_id, volume, pan)
    worker.start()
    worker.wait()
    if worker.failure is not None:
        raise worker.failure


def play_wav_stream(response, device_id="", volume=100, pan=0):
    worker = _StreamingPlaybackThread(response, device_id, volume, pan)
    worker.start()
    worker.wait()
    if worker.failure is not None:
        raise worker.failure
    return worker.wav, worker.first_audio_seconds
