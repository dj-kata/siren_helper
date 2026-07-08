from pathlib import Path

from src.define import (
    DEFAULT_LIVE_EXPLORATION_MODE,
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
    LIVE_EXPLORATION_MODE_NONE,
    crop_for_ocr,
    normalize_live_exploration_mode,
)
from src.dungeon_ocr import normalize_ocr_text


TYPE0_STATUS_TITLE_CROP_XYWH = (1, 1, 1, 1)
TYPE1_STATUS_TITLE_CROP_XYWH = (970, 970, 150, 40)
TYPE2_STATUS_TITLE_CROP_XYWH = (1070, 970, 150, 45)
TYPE3_STATUS_TITLE_CROP_XYWH = (1370, 977, 150, 50)
STATUS_TITLE_TEXT = "現在の状態"
_ocr = None


def _engine():
    global _ocr
    if _ocr is None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr

        _ocr = ONNXPaddleOcr(use_gpu=False, lang="japan", show_log=False)
    return _ocr


def read_crop_text(screen, crop_xywh) -> str:
    import cv2
    import numpy as np

    _crop_box, crop = crop_for_ocr(screen, crop_xywh)
    image = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2BGR)
    result = _engine().ocr(image, cls=False)
    texts = []
    for page in result or []:
        if not page:
            continue
        for _box, text_score in page:
            if not text_score:
                continue
            text, _score = text_score
            text = str(text).strip()
            if text:
                texts.append(text)
    return "".join(texts)


def is_type0_status_title(screen) -> bool:
    text = read_crop_text(screen, TYPE0_STATUS_TITLE_CROP_XYWH)
    return normalize_ocr_text(STATUS_TITLE_TEXT) in normalize_ocr_text(text)


def is_type1_status_title(screen) -> bool:
    text = read_crop_text(screen, TYPE1_STATUS_TITLE_CROP_XYWH)
    return normalize_ocr_text(STATUS_TITLE_TEXT) in normalize_ocr_text(text)


def is_type2_status_title(screen) -> bool:
    text = read_crop_text(screen, TYPE2_STATUS_TITLE_CROP_XYWH)
    return normalize_ocr_text(STATUS_TITLE_TEXT) in normalize_ocr_text(text)


def is_type3_status_title(screen) -> bool:
    text = read_crop_text(screen, TYPE3_STATUS_TITLE_CROP_XYWH)
    return normalize_ocr_text(STATUS_TITLE_TEXT) in normalize_ocr_text(text)


def detect_live_exploration_mode(screen, source_path=None):
    """ゲーム内のライブ探索表示タイプを判定する。

    具体的な画像判定条件は後でここに追加する。テスト画像は type0.png
    のようなファイル名でも仮判定できるようにしている。
    """
    if screen is not None:
        try:
            if is_type0_status_title(screen):
                return LIVE_EXPLORATION_MODE_NONE
            elif is_type1_status_title(screen):
                return LIVE_EXPLORATION_MODE_1
            elif is_type2_status_title(screen):
                return LIVE_EXPLORATION_MODE_2
            elif is_type3_status_title(screen):
                return LIVE_EXPLORATION_MODE_3
        except Exception:
            pass

    return DEFAULT_LIVE_EXPLORATION_MODE


def is_live_exploration_mode(value):
    return normalize_live_exploration_mode(value) == value
