import re
from dataclasses import dataclass
from pathlib import Path

from src.define import PosManpukuNumbers, crop_for_ocr
from src.logger import get_logger
from src.shop_ocr import ShopOcrText, normalize_price_text


logger = get_logger(__name__)
NUMBER_PATTERN = re.compile(r"\d+")
DEBUG_CROP_DIR = Path("log") / "manpuku_ocr_crops"


@dataclass(frozen=True)
class ManpukuOcrResult:
    current: int
    maximum: int
    raw_texts: tuple[str, ...]


def _box_left(box) -> float:
    try:
        return min(point[0] for point in box)
    except Exception:
        return 0.0


def extract_manpuku_numbers(texts: list[str]) -> tuple[int | None, int | None]:
    joined_text = normalize_price_text("".join(texts))
    numbers = [int(match.group(0)) for match in NUMBER_PATTERN.finditer(joined_text)]
    if len(numbers) < 2:
        return None, None
    return numbers[0], numbers[1]


class ManpukuOcrReader:
    def __init__(self, config=None):
        self.config = config
        self._ocr = None

    def _debug_mode(self) -> bool:
        return bool(getattr(self.config, "debug_mode", False))

    def read(self, screen) -> ManpukuOcrResult | None:
        if screen is None:
            logger.info("満腹度OCR: screen is None")
            return None

        texts = self._read_crop(screen, PosManpukuNumbers.CROP_XYWH, "PosManpukuNumbers")
        raw_texts = [text.text for text in texts]
        current, maximum = extract_manpuku_numbers(raw_texts)
        if current is None or maximum is None:
            logger.info("満腹度OCR: 数字抽出失敗 raw=%s", tuple(raw_texts))
            return None

        logger.info("満腹度OCR: current=%s maximum=%s raw=%s", current, maximum, tuple(raw_texts))
        return ManpukuOcrResult(current=current, maximum=maximum, raw_texts=tuple(raw_texts))

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
        texts = sorted(texts, key=lambda data: _box_left(data.box))
        logger.info(
            "満腹度OCR crop=%s xywh=%s crop_box=%s crop_size=%s texts=%s ocr_boxes=%s",
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
            logger.exception("満腹度OCR debug crop保存エラー label=%s", label)

    def _engine(self):
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr(use_gpu=False, lang="japan", show_log=False)
        return self._ocr
