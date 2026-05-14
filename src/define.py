"""座標など固定のデータをここに記載
"""
from src.classes import *

BASE_CAPTURE_SIZE = (1920, 1080)


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
    '''店において買取価格表示があるかどうかを判定'''
    CROP_XYWH = (780,580,700,50)
    target = '識別されていないのでよくわからない'

class PosMyItemPrice:
    '''手持ちアイテムの買取価格部分の切り取り'''
    CROP_XYWH = (808,530,620,50)

class PosShopItemPrice:
    '''店売りアイテムの買取価格部分の切り取り'''
    CROP_XYWH = (200,240,550,50)

class PosMyItems:
    '''所持品一覧の切り取り(type1)'''
    CROP_XYWH = (1600,0,320,1080)

class PosItemIcons:
    '''アイテムカテゴリ判別用。アイテム名左のアイコンを切り取る。'''
    CROP_XYWH = (783, 546, 23, 19)