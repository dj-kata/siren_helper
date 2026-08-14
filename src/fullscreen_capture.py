import sys

from PIL import Image

from src.config import OCR_CAPTURE_SIZE
from src.direct_capture import DirectCaptureError, get_shiren_window_bbox
from src.logger import get_logger


logger = get_logger(__name__)
TARGET_SIZE = OCR_CAPTURE_SIZE
_camera = None


class FullscreenCaptureError(RuntimeError):
    pass


def capture_shiren_fullscreen(target_size=TARGET_SIZE) -> Image.Image:
    """フルスクリーン/ボーダーレス表示をDXGI経由で直接キャプチャする。"""
    if sys.platform != "win32":
        raise FullscreenCaptureError("フルスクリーン直接取得はWindows上でのみ利用できます")

    try:
        bbox = get_shiren_window_bbox()
    except DirectCaptureError as e:
        raise FullscreenCaptureError(str(e)) from e

    frame = _grab_frame(bbox)
    if frame is None:
        raise FullscreenCaptureError("DXGIによるゲーム画面取得に失敗しました")

    image = Image.fromarray(frame).convert("RGB")
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    return image


def _grab_frame(region):
    camera = _get_camera()
    try:
        return camera.grab(region=region, new_frame_only=False)
    except Exception:
        logger.debug("DXGI capture failed", exc_info=True)
        _reset_camera()
        return _get_camera().grab(region=region, new_frame_only=False)


def _get_camera():
    global _camera
    if _camera is None:
        try:
            import dxcam
        except ImportError as e:
            raise FullscreenCaptureError(
                "dxcamがインストールされていないため、フルスクリーン直接取得を利用できません"
            ) from e
        _camera = dxcam.create(output_color="RGB")
        if _camera is None:
            raise FullscreenCaptureError("DXGIキャプチャデバイスの初期化に失敗しました")
    return _camera


def _reset_camera():
    global _camera
    if _camera is not None:
        try:
            _camera.release()
        except Exception:
            pass
    _camera = None
