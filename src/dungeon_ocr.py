import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.logger import get_logger


logger = get_logger(__name__)
DUNGEON_INFO_CROP_XYWH = (0, 0, 500, 125)
DEBUG_CROP_PATH = Path("log") / "dungeon_ocr_crop.png"
MIN_DUNGEON_MATCH_SCORE = 0.72
FLOOR_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*(?:F|階)")
TEXT_NOISE_PATTERN = re.compile(r"[\s・･\-_ー,，.。:：/／\\|｜()\[\]{}「」『』【】]+")


@dataclass(frozen=True)
class DungeonOcrResult:
    dungeon_key: str
    dungeon_name: str
    floor: int
    raw_text: str
    score: float


def normalize_ocr_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("髓", "髄").replace("随", "髄")
    return TEXT_NOISE_PATTERN.sub("", normalized)


def xywh_to_box(crop_xywh):
    x, y, width, height = crop_xywh
    return (x, y, x + width, y + height)


def extract_floor(text: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", text or "").upper()
    normalized = normalized.replace("階層", "階")
    match = FLOOR_PATTERN.search(normalized)
    if not match:
        return None
    try:
        floor = int(match.group(1))
    except ValueError:
        return None
    return floor if floor > 0 else None


def match_dungeon(text: str, dungeons: list[dict]) -> tuple[dict | None, float]:
    target = normalize_ocr_text(text)
    if not target:
        return None, 0.0

    best_dungeon = None
    best_score = 0.0
    for dungeon in dungeons:
        name = dungeon.get("name", "")
        normalized_name = normalize_ocr_text(name)
        if not normalized_name:
            continue
        if normalized_name in target:
            score = 1.0
        else:
            score = SequenceMatcher(None, normalized_name, target).ratio()
        if score > best_score:
            best_dungeon = dungeon
            best_score = score

    if best_score < MIN_DUNGEON_MATCH_SCORE:
        return None, best_score
    return best_dungeon, best_score


class DungeonOcrReader:
    def __init__(self):
        self._ocr = None

    def read(self, screen, dungeons: list[dict]) -> DungeonOcrResult | None:
        if screen is None or not dungeons:
            return None

        raw_text = self._read_text(screen)
        floor = extract_floor(raw_text)
        dungeon, score = match_dungeon(raw_text, dungeons)
        logger.info(
            "ダンジョンOCR: raw=%r floor=%s dungeon=%s score=%.3f",
            raw_text,
            floor,
            dungeon.get("name", "") if dungeon else None,
            score,
        )
        if floor is None or not dungeon:
            return None

        return DungeonOcrResult(
            dungeon_key=dungeon["key"],
            dungeon_name=dungeon["name"],
            floor=floor,
            raw_text=raw_text,
            score=score,
        )

    def _read_text(self, screen) -> str:
        import cv2
        import numpy as np

        crop_box = xywh_to_box(DUNGEON_INFO_CROP_XYWH)
        crop = screen.crop(crop_box).convert("RGB")
        self._save_debug_crop(crop)
        image = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2BGR)
        result = self._engine().ocr(image, cls=False)
        texts = []
        for page in result or []:
            if not page:
                continue
            for _box, text_score in page:
                if not text_score:
                    continue
                text, _score = text_score
                if text:
                    texts.append(str(text))
        logger.info(
            "ダンジョンOCR crop xywh=%s crop_box=%s crop_size=%s texts=%s",
            DUNGEON_INFO_CROP_XYWH,
            crop_box,
            crop.size,
            tuple(texts),
        )
        return " ".join(texts)

    def _save_debug_crop(self, crop):
        try:
            DEBUG_CROP_PATH.parent.mkdir(parents=True, exist_ok=True)
            crop.save(DEBUG_CROP_PATH)
        except Exception:
            logger.exception("ダンジョンOCR debug crop保存エラー")

    def _engine(self):
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr(use_gpu=False, lang="japan", show_log=False)
        return self._ocr
