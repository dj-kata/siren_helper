import argparse
import json
import sys
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import OCR_CAPTURE_RESOLUTION, OCR_CAPTURE_SIZE
from src.define import DetectOnShop, PosMyItemPrice, PosShopItemPrice
from src.dungeon_ocr import DungeonOcrReader, normalize_ocr_text
from src.item import ItemList
from src.shop_ocr import ShopOcrReader, extract_price


ITEM_CATEGORIES = ["kusa", "makimono", "udewa", "tubo", "okou", "tue", "buki", "tate"]
MIN_IDENTIFIED_ITEM_MATCH_SCORE = 0.82
EQUIPMENT_PRICE_CORRECTION_MAX = 99
EQUIPMENT_BUY_CORRECTION_UNIT = 100
EQUIPMENT_SELL_CORRECTION_UNIT = 40
ITEM_CATEGORY_LABELS = {
    "kusa": "草",
    "makimono": "巻物",
    "udewa": "腕輪",
    "tubo": "壺",
    "okou": "お香",
    "tue": "杖",
    "buki": "武器",
    "tate": "盾",
}
NON_BLESSABLE_ITEM_CATEGORIES = {"buki", "tate", "udewa", "tubo", "tue"}
SHOP_CATEGORY_HINTS = {
    "草": "kusa",
    "種": "kusa",
    "巻物": "makimono",
    "腕輪": "udewa",
    "壺": "tubo",
    "香": "okou",
    "杖": "tue",
    "剣": "buki",
    "盾": "tate",
}


def load_dungeons():
    dungeon_dir = ROOT / "data" / "6_dungeons"
    if not dungeon_dir.exists():
        return []

    reverse_categories = {
        json_key: category
        for category, json_key in ItemList.category_json_keys.items()
    }
    dungeons = []
    for path in sorted(dungeon_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        item_names_by_category = {category: set() for category in ITEM_CATEGORIES}
        for item in data.get("items", {}).get("items", []):
            category = reverse_categories.get(item.get("category", ""))
            name = item.get("name", "")
            if category and name:
                item_names_by_category[category].add(name)

        dungeons.append({
            "key": data.get("key") or path.stem,
            "name": data.get("name") or path.stem,
            "item_names_by_category": item_names_by_category,
        })
    return dungeons


def resize_for_ocr(image):
    if image.size == OCR_CAPTURE_SIZE:
        return image
    return image.resize(OCR_CAPTURE_SIZE, Image.Resampling.LANCZOS)


def normalize_item_match_text(text):
    return normalize_ocr_text(text).replace("力の草", "ちからの草")


def detect_shop_item_category(text):
    target = normalize_ocr_text(text)
    for hint, category in SHOP_CATEGORY_HINTS.items():
        if hint in target:
            return category
    return None


def get_target_items(itemlist, category, dungeon):
    items = getattr(itemlist, category)
    if not dungeon:
        return items
    item_names = dungeon["item_names_by_category"].get(category, set())
    return [item for item in items if item.name in item_names]


def find_item_by_name(itemlist, text):
    target = normalize_item_match_text(text)
    if not target:
        return None

    containing_match = None
    best_match = None
    best_score = 0.0
    for category in ITEM_CATEGORIES:
        for item in getattr(itemlist, category):
            item_name = normalize_item_match_text(item.name)
            if item_name == target:
                return category, item, 1.0
            if item_name and item_name in target:
                containing_match = containing_match or (category, item, 1.0)
            score = SequenceMatcher(None, item_name, target).ratio()
            if score > best_score:
                best_match = (category, item, score)
                best_score = score

    if containing_match:
        return containing_match
    if best_match and best_score >= MIN_IDENTIFIED_ITEM_MATCH_SCORE:
        return best_match
    return None


def get_equipment_base_power(item):
    try:
        return max(0, int(item.raw_data.get("基礎値", 0)))
    except (TypeError, ValueError):
        return 0


def iter_item_prices(item, price_kind):
    attr = "sell" if price_kind == "sell" else "buy"
    unit_attr = "sell_unit" if price_kind == "sell" else "buy_unit"
    base = getattr(item, attr, 0)
    if item.category.name in ("buki", "tate"):
        unit = EQUIPMENT_SELL_CORRECTION_UNIT if price_kind == "sell" else EQUIPMENT_BUY_CORRECTION_UNIT
        correction_min = -get_equipment_base_power(item)
        for correction in range(correction_min, EQUIPMENT_PRICE_CORRECTION_MAX + 1):
            price = base + unit * correction
            if price <= 0:
                continue
            sign = "+" if correction > 0 else ""
            detail = f"{sign}{correction}" if correction else ""
            yield price, detail
        return

    unit = getattr(item, unit_attr, None)
    if unit is None:
        yield base, ""
        return

    for capacity in range(item.capa_min, item.capa_max + 1):
        yield base + unit * capacity, f"[{capacity}]"


def find_item_price_candidates(item, price, price_kind):
    candidates = []
    can_be_blessed = item.category.name not in NON_BLESSABLE_ITEM_CATEGORIES
    for candidate_price, detail in iter_item_prices(item, price_kind):
        if candidate_price == price:
            candidates.append((item, detail, ""))
        if can_be_blessed and candidate_price * 2 == price:
            candidates.append((item, detail, "祝福"))
        if candidate_price * 87 // 100 == price:
            candidates.append((item, detail, "呪い"))
    return sort_shop_price_candidates(candidates)


def sort_shop_price_candidates(candidates):
    return sorted(candidates, key=lambda candidate: candidate[2] == "祝福")


def find_shop_price_candidates(itemlist, category, price, price_kind, dungeon):
    candidates = []
    for item in get_target_items(itemlist, category, dungeon):
        if item.get or item.default_get:
            continue
        candidates.extend(find_item_price_candidates(item, price, price_kind))
    return sort_shop_price_candidates(candidates)


def find_all_shop_price_candidates(itemlist, price, price_kind, dungeon):
    candidates = []
    for category in ("kusa", "makimono", "udewa", "tubo", "okou", "tue"):
        candidates.extend(find_shop_price_candidates(itemlist, category, price, price_kind, dungeon))
    return sort_shop_price_candidates(candidates)


def format_candidate(candidate):
    item, detail, price_state = candidate
    price_state_text = f"({price_state})" if price_state else ""
    return {
        "name": item.name,
        "label": f"{item.name}{detail}{price_state_text}",
        "category": item.category.name,
        "category_label": ITEM_CATEGORY_LABELS.get(item.category.name, item.category.ja),
        "buy": item.buy,
        "sell": item.sell,
        "detail": detail,
        "price_state": price_state,
    }


def inspect_shop_crops(shop_reader, image):
    detect_texts = shop_reader._read_crop(image, DetectOnShop.CROP_XYWH, "DetectOnShop")
    my_texts = shop_reader._read_crop(image, PosMyItemPrice.CROP_XYWH, "PosMyItemPrice")
    shop_texts = shop_reader._read_crop(image, PosShopItemPrice.CROP_XYWH, "PosShopItemPrice")
    sell_price = extract_price(my_texts[-1].text) if len(my_texts) >= 2 else None
    buy_price = extract_price(shop_texts[-1].text) if len(shop_texts) >= 2 else None
    return {
        "is_item_screen": bool(detect_texts or my_texts or shop_texts),
        "has_buy_price": buy_price is not None,
        "buy_price": buy_price,
        "buy_raw_texts": [text.text for text in shop_texts],
        "has_sell_price": sell_price is not None,
        "sell_price": sell_price,
        "sell_raw_texts": [text.text for text in my_texts],
        "detail_raw_texts": [text.text for text in detect_texts],
    }


def resolve_candidates(itemlist, shop_result, dungeon):
    if not shop_result or shop_result.price is None:
        return {
            "category": None,
            "category_label": None,
            "exact_item": None,
            "candidates": [],
        }

    exact = find_item_by_name(itemlist, shop_result.item_text)
    if exact:
        category, item, score = exact
        if shop_result.price is not None:
            candidates = find_item_price_candidates(item, shop_result.price, shop_result.price_kind)
        else:
            candidates = [(item, "", "")]
        return {
            "category": category,
            "category_label": ITEM_CATEGORY_LABELS.get(category, category),
            "exact_item": {"name": item.name, "score": round(score, 3)},
            "candidates": [format_candidate(candidate) for candidate in candidates],
        }

    category = detect_shop_item_category(shop_result.item_text)
    candidates = find_shop_price_candidates(itemlist, category, shop_result.price, shop_result.price_kind, dungeon) if category else find_all_shop_price_candidates(itemlist, shop_result.price, shop_result.price_kind, dungeon)
    return {
        "category": category,
        "category_label": ITEM_CATEGORY_LABELS.get(category, category) if category else None,
        "exact_item": None,
        "candidates": [format_candidate(candidate) for candidate in candidates],
    }


def print_result(result):
    print(f"画像: {result['path']}")
    print(f"処理解像度: {result['processed_size'][0]}x{result['processed_size'][1]} (入力: {result['original_size'][0]}x{result['original_size'][1]})")

    dungeon = result["dungeon"]
    print("ダンジョン:")
    if dungeon:
        print(f"  名前: {dungeon['dungeon_name']}")
        print(f"  階層: {dungeon['floor']}F")
        print(f"  raw: {dungeon['raw_text']}")
        print(f"  score: {dungeon['score']:.3f}")
    else:
        print("  判定なし")

    shop = result["shop_inspection"]
    print("ショップ/アイテム画面:")
    print(f"  アイテム画面らしい: {shop['is_item_screen']}")
    print(f"  買値あり: {shop['has_buy_price']} price={shop['buy_price']} raw={shop['buy_raw_texts']}")
    print(f"  売値あり: {shop['has_sell_price']} price={shop['sell_price']} raw={shop['sell_raw_texts']}")
    print(f"  詳細欄raw: {shop['detail_raw_texts']}")

    shop_result = result["shop_result"]
    print("店OCR判別:")
    if shop_result:
        print(f"  item_text: {shop_result['item_text']}")
        print(f"  price_kind: {shop_result['price_kind']}")
        print(f"  price: {shop_result['price']}")
        print(f"  raw_texts: {shop_result['raw_texts']}")
    else:
        print("  判定なし")

    candidate_info = result["candidate_info"]
    print("候補:")
    print(f"  種別: {candidate_info['category_label'] or '判定なし'}")
    if candidate_info["exact_item"]:
        exact = candidate_info["exact_item"]
        print(f"  名前一致: {exact['name']} score={exact['score']}")
    if candidate_info["candidates"]:
        for candidate in candidate_info["candidates"]:
            print(f"  - {candidate['label']} / 買値{candidate['buy']}G / 売値{candidate['sell']}G")
    else:
        print("  候補なし")


def main():
    parser = argparse.ArgumentParser(description="シレン6 OCR判別の単体検証")
    parser.add_argument("images", nargs="+", help="検証する画像ファイル")
    parser.add_argument("--debug-crops", action="store_true", help="OCR crop画像をlogへ保存する")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力する")
    args = parser.parse_args()

    config = SimpleNamespace(debug_mode=args.debug_crops)
    dungeon_reader = DungeonOcrReader(config)
    shop_reader = ShopOcrReader(config)
    itemlist = ItemList()
    dungeons = load_dungeons()

    results = []
    for image_path in args.images:
        path = Path(image_path)
        with Image.open(path) as source:
            original = source.convert("RGB")
        image = resize_for_ocr(original)

        dungeon_result = dungeon_reader.read(image, dungeons)
        dungeon = None
        matched_dungeon = None
        if dungeon_result:
            dungeon = asdict(dungeon_result)
            matched_dungeon = next((data for data in dungeons if data["key"] == dungeon_result.dungeon_key), None)

        shop_inspection = inspect_shop_crops(shop_reader, image)
        shop_result = shop_reader.read(image)
        candidate_info = resolve_candidates(itemlist, shop_result, matched_dungeon)

        result = {
            "path": str(path),
            "original_size": original.size,
            "processed_size": image.size,
            "resolution": OCR_CAPTURE_RESOLUTION,
            "use_gpu": False,
            "dungeon": dungeon,
            "shop_inspection": shop_inspection,
            "shop_result": asdict(shop_result) if shop_result else None,
            "candidate_info": candidate_info,
        }
        results.append(result)

        if not args.json:
            print_result(result)
            print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
