import ctypes
import sys
from ctypes import wintypes

from PIL import Image

from src.config import OCR_CAPTURE_SIZE
from src.direct_capture import (
    DirectCaptureError,
    get_shiren_window_bbox,
    get_shiren_window_hwnd,
)
from src.logger import get_logger


logger = get_logger(__name__)
TARGET_SIZE = OCR_CAPTURE_SIZE
_MONITOR_DEFAULTTONEAREST = 0x00000002
_camera_session = None


class FullscreenCaptureError(RuntimeError):
    pass


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _DxcamSession:
    def __init__(self):
        self.camera = None
        self.hmonitor = 0
        self.monitor_rect = None

    def close(self):
        camera = self.camera
        self.camera = None
        self.hmonitor = 0
        self.monitor_rect = None
        if camera is None:
            return
        try:
            if getattr(camera, "is_capturing", False):
                camera.stop()
        except Exception:
            pass
        try:
            camera.release()
        except Exception:
            pass

    def grab(self, hwnd, bbox):
        hmonitor = _monitor_from_window(hwnd)
        monitor_rect = _monitor_rect(hmonitor)
        if not hmonitor or monitor_rect is None:
            raise FullscreenCaptureError("対象ウィンドウのモニターを特定できません")

        if self.camera is None or self.hmonitor != hmonitor:
            self.close()
            self.camera = _create_camera_for_monitor(hmonitor)
            if self.camera is None:
                raise FullscreenCaptureError("対象モニターに対応するDXGI出力を特定できません")
            try:
                self.camera.start()
            except Exception as e:
                self.close()
                raise FullscreenCaptureError(f"DXGIキャプチャ開始に失敗しました: {e}") from e
            self.hmonitor = hmonitor
            logger.info("DXGI継続キャプチャ開始: hwnd=%s monitor=%s", hwnd, hmonitor)

        self.monitor_rect = monitor_rect
        frame = self.camera.grab()
        if frame is None:
            raise FullscreenCaptureError("DXGIによるゲーム画面取得に失敗しました")
        return _crop_frame_to_bbox(frame, bbox, monitor_rect)


def capture_shiren_fullscreen(target_size=TARGET_SIZE) -> Image.Image:
    """フルスクリーン/ボーダーレス表示をDXGI経由で直接キャプチャする。"""
    return capture_shiren_dxgi(target_size)


def capture_shiren_dxgi(target_size=TARGET_SIZE) -> Image.Image:
    """Steam版シレン6の表示領域をDXGI経由で直接キャプチャする。"""
    if sys.platform != "win32":
        raise FullscreenCaptureError("DXGI直接取得はWindows上でのみ利用できます")

    try:
        hwnd = get_shiren_window_hwnd()
        bbox = get_shiren_window_bbox()
    except DirectCaptureError as e:
        raise FullscreenCaptureError(str(e)) from e

    frame = _grab_frame(hwnd, bbox)
    if frame is None:
        raise FullscreenCaptureError("DXGIによるゲーム画面取得に失敗しました")

    image = Image.fromarray(frame).convert("RGB")
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    return image


def _grab_frame(hwnd, bbox):
    session = _get_session()
    try:
        return session.grab(hwnd, bbox)
    except Exception:
        logger.debug("DXGI capture failed", exc_info=True)
        _reset_camera()
        try:
            return _get_session().grab(hwnd, bbox)
        except Exception as e:
            raise FullscreenCaptureError("DXGIによるゲーム画面取得に失敗しました") from e


def _get_session():
    global _camera_session
    if _camera_session is None:
        _camera_session = _DxcamSession()
    return _camera_session


def _reset_camera():
    global _camera_session
    if _camera_session is not None:
        _camera_session.close()
    _camera_session = None


def _monitor_from_window(hwnd):
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    return int(user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST) or 0)


def _monitor_rect(hmonitor):
    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MONITORINFO))
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        return None

    rect = info.rcMonitor
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _create_camera_for_monitor(hmonitor):
    try:
        from dxcam import Device, Output, create, enum_dxgi_adapters
    except ImportError as e:
        raise FullscreenCaptureError(
            "dxcamがインストールされていないため、フルスクリーン直接取得を利用できません"
        ) from e

    for device_idx, adapter in enumerate(enum_dxgi_adapters()):
        device = Device(adapter)
        for output_idx, output_ptr in enumerate(device.enum_outputs()):
            output = Output(output_ptr)
            if int(output.hmonitor or 0) == hmonitor:
                return create(
                    device_idx=device_idx,
                    output_idx=output_idx,
                    output_color="RGB",
                    processor_backend="numpy",
                )
    return None


def _crop_frame_to_bbox(frame, bbox, monitor_rect):
    frame_height, frame_width = frame.shape[:2]
    monitor_left, monitor_top, monitor_right, monitor_bottom = monitor_rect
    monitor_width = monitor_right - monitor_left
    monitor_height = monitor_bottom - monitor_top
    if monitor_width <= 0 or monitor_height <= 0:
        return frame

    scale_x = frame_width / monitor_width
    scale_y = frame_height / monitor_height
    left, top, right, bottom = bbox
    crop_left = round((left - monitor_left) * scale_x)
    crop_top = round((top - monitor_top) * scale_y)
    crop_right = round((right - monitor_left) * scale_x)
    crop_bottom = round((bottom - monitor_top) * scale_y)

    crop_left = max(0, min(frame_width, crop_left))
    crop_top = max(0, min(frame_height, crop_top))
    crop_right = max(crop_left, min(frame_width, crop_right))
    crop_bottom = max(crop_top, min(frame_height, crop_bottom))
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return frame
    return frame[crop_top:crop_bottom, crop_left:crop_right]
