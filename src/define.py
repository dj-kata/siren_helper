"""座標など固定のデータをここに記載"""

from src.classes import *

BASE_CAPTURE_SIZE = (1920, 1080)
LIVE_EXPLORATION_MODE_NONE = "type0"
LIVE_EXPLORATION_MODE_1 = "type1"
LIVE_EXPLORATION_MODE_2 = "type2"
LIVE_EXPLORATION_MODE_3 = "type3"
LIVE_EXPLORATION_MODES = (
    LIVE_EXPLORATION_MODE_NONE,
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
)
DEFAULT_LIVE_EXPLORATION_MODE = LIVE_EXPLORATION_MODE_NONE
LIVE_EXPLORATION_MODE_LABELS = {
    LIVE_EXPLORATION_MODE_NONE: "ライブ探索モードなし",
    LIVE_EXPLORATION_MODE_1: "ライブ探索モード1",
    LIVE_EXPLORATION_MODE_2: "ライブ探索モード2",
    LIVE_EXPLORATION_MODE_3: "ライブ探索モード3",
}


def normalize_live_exploration_mode(mode):
    if mode in LIVE_EXPLORATION_MODES:
        return mode
    return DEFAULT_LIVE_EXPLORATION_MODE


def live_exploration_mode_label(mode):
    return LIVE_EXPLORATION_MODE_LABELS.get(
        normalize_live_exploration_mode(mode),
        LIVE_EXPLORATION_MODE_LABELS[DEFAULT_LIVE_EXPLORATION_MODE],
    )


def live_exploration_mode_has_status(mode):
    return normalize_live_exploration_mode(mode) != LIVE_EXPLORATION_MODE_NONE


def scale_xywh(crop_xywh, image_size):
    """FullHD基準のxywhを実画像サイズへスケールする。"""
    base_width, base_height = BASE_CAPTURE_SIZE
    image_width, image_height = image_size
    scale_x = image_width / base_width
    scale_y = image_height / base_height
    x, y, width, height = crop_xywh
    scaled_x = round(x * scale_x)
    scaled_y = round(y * scale_y)
    scaled_width = max(1, round(width * scale_x))
    scaled_height = max(1, round(height * scale_y))
    scaled_x = min(max(0, scaled_x), max(0, image_width - 1))
    scaled_y = min(max(0, scaled_y), max(0, image_height - 1))
    scaled_width = min(scaled_width, image_width - scaled_x)
    scaled_height = min(scaled_height, image_height - scaled_y)
    return (scaled_x, scaled_y, scaled_width, scaled_height)


def xywh_to_box(crop_xywh):
    x, y, width, height = crop_xywh
    return (x, y, x + width, y + height)


def scaled_xywh_to_box(crop_xywh, image_size):
    return xywh_to_box(scale_xywh(crop_xywh, image_size))


def crop_for_ocr(screen, crop_xywh):
    """実画像サイズで切り出し、OCR入力だけFullHD基準のcropサイズへ戻す。"""
    from PIL import Image

    crop_box = scaled_xywh_to_box(crop_xywh, screen.size)
    crop = screen.crop(crop_box).convert("RGB")
    _x, _y, width, height = crop_xywh
    if crop.size != (width, height):
        crop = crop.resize((width, height), Image.Resampling.LANCZOS)
    return crop_box, crop


class DetectOnShop:
    """店において買取価格表示があるかどうかを判定"""

    CROP_XYWH = (780, 580, 700, 50)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH,
    }
    target = "識別されていないのでよくわからない"

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosMyItemPrice:
    """手持ちアイテムの買取価格部分の切り取り。
    アイコンは入れず、アイテム名～価格末尾までを切り出す。"""

    CROP_XYWH_TYPE0 = (1010, 670, 780, 55)
    CROP_XYWH_TYPE1 = (757, 500, 580, 45)
    CROP_XYWH_TYPE2 = (808, 530, 620, 50)
    CROP_XYWH_TYPE3 = (910, 600, 700, 55)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH_TYPE0,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH_TYPE1,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH_TYPE2,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH_TYPE3,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosShopItemPrice:
    """店売りアイテムの買取価格部分の切り取り"""

    CROP_XYWH = (200, 240, 550, 50)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosMyItems:
    """所持品一覧の切り取り(type1)"""

    CROP_XYWH = (1600, 0, 320, 1080)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosItemIcons:
    """アイテムカテゴリ判別用。アイテム名左のアイコンを切り取る。"""

    CROP_XYWH = (783, 546, 23, 19)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosManpukuNumbers:
    """満腹度読み取り用"""

    CROP_XYWH_TYPE0 = (790, 75, 290, 60)
    CROP_XYWH_TYPE1 = (590, 60, 215, 40)
    CROP_XYWH_TYPE2 = (630, 65, 233, 40)
    CROP_XYWH_TYPE3 = (700, 70, 265, 50)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH_TYPE0,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH_TYPE1,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH_TYPE2,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH_TYPE3,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]


class PosStatusStrings:
    """状態文字列読み取り用"""

    CROP_XYWH_TYPE0 = (1, 1, 1, 1)
    CROP_XYWH_TYPE1 = (970, 970, 450, 80)
    CROP_XYWH_TYPE2 = (1065, 970, 470, 80)
    CROP_XYWH_TYPE3 = (1370, 980, 550, 90)
    CROP_XYWH_BY_LIVE_MODE = {
        LIVE_EXPLORATION_MODE_NONE: CROP_XYWH_TYPE0,
        LIVE_EXPLORATION_MODE_1: CROP_XYWH_TYPE1,
        LIVE_EXPLORATION_MODE_2: CROP_XYWH_TYPE2,
        LIVE_EXPLORATION_MODE_3: CROP_XYWH_TYPE3,
    }

    @classmethod
    def get(cls, live_mode=None):
        return cls.CROP_XYWH_BY_LIVE_MODE[normalize_live_exploration_mode(live_mode)]
