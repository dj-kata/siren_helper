import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.define import DetectOnShop, PosMyItemPrice, PosShopItemPrice
from src.dungeon_ocr import normalize_ocr_text
from src.logger import get_logger


logger = get_logger(__name__)
PRICE_PATTERN = re.compile(r"\d+")
MIN_SHOP_DETECT_SCORE = 0.72
DEBUG_CROP_DIR = Path("log") / "shop_ocr_crops"


@dataclass(frozen=True)
class ShopOcrText:
    text: str
    score: float
    box: object


@dataclass(frozen=True)
class ShopPriceResult:
    item_text: str
    price: int
    price_kind: str
    raw_texts: tuple[str, ...]


def normalize_price_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").replace(",", "")


def extract_price(text: str) -> int | None:
    match = PRICE_PATTERN.search(normalize_price_text(text))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _box_left(box) -> float:
    try:
        return min(point[0] for point in box)
    except Exception:
        return 0.0


def xywh_to_box(crop_xywh):
    x, y, width, height = crop_xywh
    return (x, y, x + width, y + height)


class ShopOcrReader:
    def __init__(self):
        self._ocr = None

    def read(self, screen) -> ShopPriceResult | None:
        if screen is None:
            logger.info("店OCR: screen is None")
            return None

        has_unknown_message, has_detail_text = self.detect_shop_message_state(screen)
        if not has_detail_text:
            logger.info("店OCR: 説明文欄textなし")
            return None
        if not has_unknown_message:
            logger.info("店OCR: 未識別メッセージなし。識別済みアイテムの可能性があるため価格欄OCRを継続")

        my_texts = self._read_crop(screen, PosMyItemPrice.CROP_XYWH, "PosMyItemPrice")
        logger.info("店OCR: 手持ち欄 text_count=%s", len(my_texts))
        if len(my_texts) >= 2:
            price = extract_price(my_texts[-1].text)
            if price is not None:
                logger.info(
                    "店OCR: 手持ちアイテム判定 item=%r price=%s raw=%s",
                    my_texts[0].text,
                    price,
                    tuple(text.text for text in my_texts),
                )
                return ShopPriceResult(
                    item_text=my_texts[0].text,
                    price=price,
                    price_kind="sell",
                    raw_texts=tuple(text.text for text in my_texts),
                )
            logger.info("店OCR: 手持ち欄の価格抽出失敗 raw=%s", tuple(text.text for text in my_texts))

        if len(my_texts) != 1:
            logger.info("店OCR: 手持ち欄のtext数が想定外 raw=%s", tuple(text.text for text in my_texts))
            return None

        shop_texts = self._read_crop(screen, PosShopItemPrice.CROP_XYWH, "PosShopItemPrice")
        logger.info("店OCR: 店売り欄 text_count=%s", len(shop_texts))
        if len(shop_texts) != 2:
            logger.info("店OCR: 店売り欄のtext数が想定外 raw=%s", tuple(text.text for text in shop_texts))
            return None

        price = extract_price(shop_texts[-1].text)
        if price is None:
            logger.info("店OCR: 店売り欄の価格抽出失敗 raw=%s", tuple(text.text for text in shop_texts))
            return None
        logger.info(
            "店OCR: 店売りアイテム判定 item=%r price=%s raw=%s",
            shop_texts[0].text,
            price,
            tuple(text.text for text in shop_texts),
        )
        return ShopPriceResult(
            item_text=shop_texts[0].text,
            price=price,
            price_kind="buy",
            raw_texts=tuple(text.text for text in shop_texts),
        )

    def has_shop_buy_message(self, screen) -> bool:
        matched, _has_text = self.detect_shop_message_state(screen)
        return matched

    def detect_shop_message_state(self, screen) -> tuple[bool, bool]:
        texts = self._read_crop(screen, DetectOnShop.CROP_XYWH, "DetectOnShop")
        if not texts:
            logger.info("店OCR: DetectOnShop textなし")
            return False, False

        target = normalize_ocr_text(DetectOnShop.target)
        joined = normalize_ocr_text("".join(text.text for text in texts))
        if not target or not joined:
            logger.info("店OCR: DetectOnShop 正規化後textなし target=%r joined=%r", target, joined)
            return False, False
        if target in joined:
            logger.info("店OCR: DetectOnShop 一致 target=%r joined=%r score=1.0", target, joined)
            return True, True
        score = SequenceMatcher(None, target, joined).ratio()
        matched = score >= MIN_SHOP_DETECT_SCORE
        logger.info(
            "店OCR: DetectOnShop 近似判定 matched=%s score=%.3f target=%r joined=%r",
            matched,
            score,
            target,
            joined,
        )
        return matched, True

    def _read_crop(self, screen, crop_xywh, label) -> list[ShopOcrText]:
        import cv2
        import numpy as np

        crop_box = xywh_to_box(crop_xywh)
        crop = screen.crop(crop_box).convert("RGB")
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
            "店OCR crop=%s xywh=%s crop_box=%s crop_size=%s texts=%s ocr_boxes=%s",
            label,
            crop_xywh,
            crop_box,
            crop.size,
            tuple((text.text, round(text.score, 3)) for text in texts),
            tuple(text.box for text in texts),
        )
        return texts

    def _save_debug_crop(self, label, crop):
        try:
            DEBUG_CROP_DIR.mkdir(parents=True, exist_ok=True)
            crop.save(DEBUG_CROP_DIR / f"{label}.png")
        except Exception:
            logger.exception("店OCR debug crop保存エラー label=%s", label)

    def _engine(self):
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr(use_gpu=False, lang="japan", show_log=False)
        return self._ocr
