import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


DUNGEON_INFO_CROP = (0, 0, 500, 125)
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

        crop = screen.crop(DUNGEON_INFO_CROP).convert("RGB")
        image = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2BGR)
        result = self._engine().ocr(image)
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
        return " ".join(texts)

    def _engine(self):
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr(use_gpu=False, lang="japan")
        return self._ocr
