from dataclasses import dataclass
from pathlib import Path

from src.define import PosStatusStrings, crop_for_ocr
from src.dungeon_ocr import normalize_ocr_text
from src.logger import get_logger
from src.shop_ocr import ShopOcrText


logger = get_logger(__name__)
DEBUG_CROP_DIR = Path("log") / "status_ocr_crops"
STATUS_TITLE_TEXT = "現在の状態"
ENTOU_TEXT_ALIASES = ("遠投", "速投")
LINE_GROUP_Y_THRESHOLD = 16.0


@dataclass(frozen=True)
class StatusOcrResult:
    is_entou: bool
    lines: tuple[str, ...]
    raw_texts: tuple[str, ...]


def _box_left(box) -> float:
    try:
        return min(point[0] for point in box)
    except Exception:
        return 0.0


def _box_center_y(box) -> float:
    try:
        ys = [point[1] for point in box]
        return (min(ys) + max(ys)) / 2
    except Exception:
        return 0.0


def group_ocr_texts_by_line(texts: list[ShopOcrText]) -> tuple[str, ...]:
    lines: list[list[ShopOcrText]] = []
    for text in sorted(texts, key=lambda data: (_box_center_y(data.box), _box_left(data.box))):
        center_y = _box_center_y(text.box)
        for line in lines:
            line_y = sum(_box_center_y(item.box) for item in line) / len(line)
            if abs(center_y - line_y) <= LINE_GROUP_Y_THRESHOLD:
                line.append(text)
                break
        else:
            lines.append([text])

    return tuple(
        "".join(item.text for item in sorted(line, key=lambda data: _box_left(data.box)))
        for line in lines
    )


def is_entou_status_lines(lines: tuple[str, ...]) -> bool:
    if len(lines) < 2:
        return False

    first_line = normalize_ocr_text(lines[0])
    second_line = normalize_ocr_text(lines[1])
    return (
        normalize_ocr_text(STATUS_TITLE_TEXT) in first_line
        and any(
            normalize_ocr_text(alias) in second_line
            for alias in ENTOU_TEXT_ALIASES
        )
    )


class StatusOcrReader:
    def __init__(self, config=None):
        self.config = config
        self._ocr = None

    def _debug_mode(self) -> bool:
        return bool(getattr(self.config, "debug_mode", False))

    def read(self, screen, live_mode=None) -> StatusOcrResult | None:
        if screen is None:
            logger.info("状態OCR: screen is None")
            return None

        texts = self._read_crop(screen, PosStatusStrings.get(live_mode), "PosStatusStrings")
        raw_texts = tuple(text.text for text in texts)
        lines = group_ocr_texts_by_line(texts)
        is_entou = is_entou_status_lines(lines)
        logger.info("状態OCR: is_entou=%s lines=%s raw=%s", is_entou, lines, raw_texts)
        return StatusOcrResult(is_entou=is_entou, lines=lines, raw_texts=raw_texts)

    def _read_crop(self, screen, crop_xywh, label) -> list[ShopOcrText]:
        import cv2
        import numpy as np

        crop_box, crop = crop_for_ocr(screen, crop_xywh)
        self._save_debug_crop(label, crop)
        image = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2BGR)
        result = self._engine().ocr(image, cls=False)
        texts = []
        for page in result or []:
            if not page:
                continue
            for ocr_box, text_score in page:
                if not text_score:
                    continue
                text, score = text_score
                text = str(text).strip()
                if text:
                    texts.append(ShopOcrText(text=text, score=float(score), box=ocr_box))
        texts = sorted(texts, key=lambda data: (_box_center_y(data.box), _box_left(data.box)))
        logger.info(
            "状態OCR crop=%s xywh=%s crop_box=%s crop_size=%s texts=%s ocr_boxes=%s",
            label,
            crop_xywh,
            crop_box,
            crop.size,
            tuple((text.text, round(text.score, 3)) for text in texts),
            tuple(text.box for text in texts),
        )
        return texts

    def _save_debug_crop(self, label, crop):
        if not self._debug_mode():
            return
        try:
            DEBUG_CROP_DIR.mkdir(parents=True, exist_ok=True)
            crop.save(DEBUG_CROP_DIR / f"{label}.png")
        except Exception:
            logger.exception("状態OCR debug crop保存エラー label=%s", label)

    def _engine(self):
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr(use_gpu=False, lang="japan", show_log=False)
        return self._ocr
