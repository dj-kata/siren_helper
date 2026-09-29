from dataclasses import dataclass

from src.define import (
    LIVE_EXPLORATION_MODE_NONE,
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
    normalize_live_exploration_mode,
)
from src.dungeon_ocr import normalize_ocr_text
from src.live_exploration_mode import read_crop_text

ADVENTURE_RESULT_FAILED = "failed"
ADVENTURE_RESULT_CLEAR = "clear"
ADVENTURE_RESULT_TITLE_TEXT = "冒険の結果"
ADVENTURE_RESULT_TITLE_TEXT_ALIASES = (ADVENTURE_RESULT_TITLE_TEXT,)
ADVENTURE_RESULT_CLEAR_TEXT = "クリアした"
ADVENTURE_RESULT_CLEAR_TEXT_ALIASES = (ADVENTURE_RESULT_CLEAR_TEXT,)

FAILED_TYPE0_RESULT_TITLE_CROP_XYWH = (675, 53, 592, 84)
FAILED_TYPE1_RESULT_TITLE_CROP_XYWH = (512, 41, 422, 62)
FAILED_TYPE2_RESULT_TITLE_CROP_XYWH = (540, 43, 504, 66)
FAILED_TYPE3_RESULT_TITLE_CROP_XYWH = (613, 46, 521, 75)
CLEAR_RESULT_TITLE_CROP_XYWH = (688, 54, 557, 84)
CLEAR_RESULT_CLEAR_TEXT_CROP_XYWH = (553, 354, 885, 107)


@dataclass(frozen=True)
class AdventureResultDetection:
    result_type: str
    live_mode: str | None = None

    @property
    def label(self) -> str:
        if self.result_type == ADVENTURE_RESULT_CLEAR:
            return ADVENTURE_RESULT_CLEAR
        if self.live_mode:
            return f"{self.result_type}_{self.live_mode}"
        return self.result_type


def contains_normalized_text(screen, crop_xywh, aliases) -> bool:
    if screen is None:
        return False
    text = read_crop_text(screen, crop_xywh)
    normalized = normalize_ocr_text(text)
    return any(normalize_ocr_text(alias) in normalized for alias in aliases)


def contains_adventure_result_title(screen, crop_xywh) -> bool:
    return contains_normalized_text(screen, crop_xywh, ADVENTURE_RESULT_TITLE_TEXT_ALIASES)


def contains_clear_text(screen, crop_xywh) -> bool:
    return contains_normalized_text(screen, crop_xywh, ADVENTURE_RESULT_CLEAR_TEXT_ALIASES)


def is_failed_type0(screen) -> bool:
    return contains_adventure_result_title(screen, FAILED_TYPE0_RESULT_TITLE_CROP_XYWH)


def is_failed_type1(screen) -> bool:
    return contains_adventure_result_title(screen, FAILED_TYPE1_RESULT_TITLE_CROP_XYWH)


def is_failed_type2(screen) -> bool:
    return contains_adventure_result_title(screen, FAILED_TYPE2_RESULT_TITLE_CROP_XYWH)


def is_failed_type3(screen) -> bool:
    return contains_adventure_result_title(screen, FAILED_TYPE3_RESULT_TITLE_CROP_XYWH)


def is_clear(screen) -> bool:
    return (
        contains_adventure_result_title(screen, CLEAR_RESULT_TITLE_CROP_XYWH)
        and contains_clear_text(screen, CLEAR_RESULT_CLEAR_TEXT_CROP_XYWH)
    )


FAILED_DETECTORS = {
    LIVE_EXPLORATION_MODE_NONE: is_failed_type0,
    LIVE_EXPLORATION_MODE_1: is_failed_type1,
    LIVE_EXPLORATION_MODE_2: is_failed_type2,
    LIVE_EXPLORATION_MODE_3: is_failed_type3,
}


def detect_adventure_result(screen, live_mode=None) -> AdventureResultDetection | None:
    if screen is None:
        return None

    normalized_live_mode = normalize_live_exploration_mode(live_mode)
    if normalized_live_mode == LIVE_EXPLORATION_MODE_NONE and is_clear(screen):
        return AdventureResultDetection(ADVENTURE_RESULT_CLEAR)

    failed_detector = FAILED_DETECTORS.get(normalized_live_mode)
    if failed_detector and failed_detector(screen):
        return AdventureResultDetection(ADVENTURE_RESULT_FAILED, normalized_live_mode)

    return None
