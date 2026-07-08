import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.define import DetectOnShop, PosItemIcons, PosMyItemPrice, PosShopItemPrice, crop_for_ocr
from src.dungeon_ocr import normalize_ocr_text
from src.logger import get_logger


logger = get_logger(__name__)
PRICE_PATTERN = re.compile(r"\d+")
MIN_SHOP_DETECT_SCORE = 0.72
DEBUG_CROP_DIR = Path("log") / "shop_ocr_crops"
CATEGORY_ICON_DIR = Path("data") / "category"
CATEGORY_ICON_MATCH_MIN_SCORE = 0.0


@dataclass(frozen=True)
class ShopOcrText:
    text: str
    score: float
    box: object


@dataclass(frozen=True)
class ShopPriceResult:
    item_text: str
    price: int | None
    price_kind: str
    raw_texts: tuple[str, ...]
    has_detail_text: bool = True
    category_hint: str | None = None
    category_hint_score: float = 0.0


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


def can_use_name_only_identification(text: str) -> bool:
    normalized = normalize_price_text(text).strip()
    return bool(normalized)


def _box_left(box) -> float:
    try:
        return min(point[0] for point in box)
    except Exception:
        return 0.0


class ShopOcrReader:
    def __init__(self, config=None):
        self.config = config
        self._ocr = None
        self._category_templates = None

    def _debug_mode(self) -> bool:
        return bool(getattr(self.config, "debug_mode", False))

    def read(self, screen, live_mode=None) -> ShopPriceResult | None:
        if screen is None:
            logger.info("店OCR: screen is None")
            return None

        has_unknown_message, has_detail_text = self.detect_shop_message_state(screen, live_mode)
        if not has_detail_text:
            logger.info("店OCR: 説明文欄textなし。識別済みアイテム名一致確認のため価格欄OCRを継続")
        if not has_unknown_message:
            logger.info("店OCR: 未識別メッセージなし。識別済みアイテムの可能性があるため価格欄OCRを継続")

        category_hint, category_hint_score = self.detect_item_category(screen, live_mode)

        my_texts = self._read_crop(screen, PosMyItemPrice.get(live_mode), "PosMyItemPrice")
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
                    has_detail_text=has_detail_text,
                    category_hint=category_hint,
                    category_hint_score=category_hint_score,
                )
            logger.info("店OCR: 手持ち欄の価格抽出失敗 raw=%s", tuple(text.text for text in my_texts))

        if len(my_texts) != 1:
            logger.info("店OCR: 手持ち欄のtext数が想定外 raw=%s", tuple(text.text for text in my_texts))
            return None

        detail_item_text = my_texts[0].text if can_use_name_only_identification(my_texts[0].text) else ""

        shop_texts = self._read_crop(screen, PosShopItemPrice.get(live_mode), "PosShopItemPrice")
        logger.info("店OCR: 店売り欄 text_count=%s", len(shop_texts))
        if len(shop_texts) != 2:
            logger.info("店OCR: 店売り欄のtext数が想定外 raw=%s", tuple(text.text for text in shop_texts))
            if detail_item_text:
                logger.info(
                    "店OCR: 詳細欄アイテム名のみでDB照合 item=%r raw=%s",
                    detail_item_text,
                    tuple(text.text for text in my_texts),
                )
                return ShopPriceResult(
                    item_text=detail_item_text,
                    price=None,
                    price_kind="sell",
                    raw_texts=tuple(text.text for text in my_texts),
                    has_detail_text=has_detail_text,
                    category_hint=category_hint,
                    category_hint_score=category_hint_score,
                )
            return None

        price = extract_price(shop_texts[-1].text)
        if price is None:
            logger.info("店OCR: 店売り欄の価格抽出失敗 raw=%s", tuple(text.text for text in shop_texts))
            if detail_item_text:
                logger.info(
                    "店OCR: 店売り欄価格抽出失敗のため詳細欄アイテム名のみでDB照合 item=%r raw=%s",
                    detail_item_text,
                    tuple(text.text for text in my_texts),
                )
                return ShopPriceResult(
                    item_text=detail_item_text,
                    price=None,
                    price_kind="sell",
                    raw_texts=tuple(text.text for text in my_texts),
                    has_detail_text=has_detail_text,
                    category_hint=category_hint,
                    category_hint_score=category_hint_score,
                )
            return None
        item_text = detail_item_text or shop_texts[0].text
        logger.info(
            "店OCR: 店売りアイテム判定 item=%r price=%s raw=%s detail_raw=%s",
            item_text,
            price,
            tuple(text.text for text in shop_texts),
            tuple(text.text for text in my_texts),
        )
        return ShopPriceResult(
            item_text=item_text,
            price=price,
            price_kind="buy",
            raw_texts=tuple(text.text for text in my_texts + shop_texts),
            has_detail_text=has_detail_text,
            category_hint=category_hint,
            category_hint_score=category_hint_score,
        )

    def has_shop_buy_message(self, screen, live_mode=None) -> bool:
        matched, _has_text = self.detect_shop_message_state(screen, live_mode)
        return matched

    def detect_shop_message_state(self, screen, live_mode=None) -> tuple[bool, bool]:
        texts = self._read_crop(screen, DetectOnShop.get(live_mode), "DetectOnShop")
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
            "店OCR crop=%s xywh=%s crop_box=%s crop_size=%s texts=%s ocr_boxes=%s",
            label,
            crop_xywh,
            crop_box,
            crop.size,
            tuple((text.text, round(text.score, 3)) for text in texts),
            tuple(text.box for text in texts),
        )
        return texts

    def detect_item_category(self, screen, live_mode=None) -> tuple[str | None, float]:
        import numpy as np

        icon_crop_xywh = PosItemIcons.get(live_mode)
        templates = self._load_category_templates(icon_crop_xywh)
        if not templates:
            logger.info("店OCR: カテゴリアイコンテンプレートなし dir=%s", CATEGORY_ICON_DIR)
            return None, 0.0

        crop_box, crop = crop_for_ocr(screen, icon_crop_xywh)
        self._save_debug_crop("PosItemIcons", crop)
        crop_array = np.asarray(crop.convert("RGB"), dtype=np.float32)

        best_category = None
        best_name = ""
        best_score = -1.0
        for category, template_name, template_array in templates:
            if template_array.shape != crop_array.shape:
                continue
            mse = float(np.mean((crop_array - template_array) ** 2))
            score = 1.0 - mse / (255.0 ** 2)
            if score > best_score:
                best_category = category
                best_name = template_name
                best_score = score

        if best_score < CATEGORY_ICON_MATCH_MIN_SCORE:
            logger.info(
                "店OCR: カテゴリアイコン判定失敗 crop_box=%s best=%s score=%.4f",
                crop_box,
                best_name,
                best_score,
            )
            return None, best_score

        logger.info(
            "店OCR: カテゴリアイコン判定 category=%s template=%s score=%.4f crop_box=%s",
            best_category,
            best_name,
            best_score,
            crop_box,
        )
        return best_category, best_score

    def _load_category_templates(self, icon_crop_xywh=None):
        icon_crop_xywh = icon_crop_xywh or PosItemIcons.CROP_XYWH
        template_size = (icon_crop_xywh[2], icon_crop_xywh[3])
        if self._category_templates is not None and template_size in self._category_templates:
            return self._category_templates.get(template_size, [])

        import numpy as np
        from PIL import Image

        templates = []
        if CATEGORY_ICON_DIR.exists():
            for path in sorted(CATEGORY_ICON_DIR.glob("*.png")):
                category = path.stem.split("_", 1)[0]
                try:
                    with Image.open(path) as image:
                        template = image.convert("RGB")
                        if template.size != template_size:
                            template = template.resize(template_size, Image.Resampling.LANCZOS)
                        templates.append((category, path.name, np.asarray(template, dtype=np.float32)))
                except Exception:
                    logger.exception("店OCR: カテゴリアイコンテンプレート読込エラー path=%s", path)
        if self._category_templates is None:
            self._category_templates = {}
        self._category_templates[template_size] = templates
        return templates

    def _save_debug_crop(self, label, crop):
        if not self._debug_mode():
            return
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
