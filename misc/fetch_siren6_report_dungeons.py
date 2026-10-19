#!/usr/bin/env python3
"""Import dungeon tables from the public Dungeon Report Viewer export.

Run from the repository root with --export-js to reuse a downloaded export,
or without it to fetch exported_reports.js from the source site.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BASE_URL = "https://tsuemaki-daisuki.vercel.app/"
DUNGEONS = {
    "D080": ("chinmoku_shinzui", "沈黙の神髄"),
    "D075": ("chihen_gakusha", "地変学者の実験場"),
    "D066": ("inishie_cave", "いにしえの洞窟"),
    "D067": ("furai_kaido", "風来街道"),
    "D074": ("floral_garden", "フローラルガーデン"),
}
# Table types are positions in each floor's item_tables, not table IDs.
TABLE_TYPES = {
    0: ("floor", "enemy_drop"),
    1: ("shop",),
    2: ("change_pot",),
    3: ("todoroki_drop",),
    4: ("floating_island", "wall_pillar", "beaker_pot"),
    5: (),  # NPC exchange
    6: ("dekkai",),
    7: ("wall_pillar",),
    8: ("shop",),  # Buried shops
    9: (),  # Steal, knock, etc.
}
AVAILABILITY_KEYS = (
    "floor", "shop", "wish", "enemy_drop", "wall_pillar", "todoroki_drop",
    "floating_island", "change_pot", "beaker_pot", "fever", "dekkai", "sun", "rain",
)
MAZE_MONSTERS = {"マゼルン", "マゼモン", "マゼゴン", "マゼドン"}


def decode_export(source: str) -> tuple[list, dict, dict]:
    """Decode only the data constants; never execute downloaded JavaScript."""
    result = []
    for name in ("Reports", "Dicts", "Localization"):
        match = re.search(rf'const compressed{name}\s*=\s*"([A-Za-z0-9+/=]+)"', source)
        if not match:
            raise ValueError(f"compressed{name} was not found")
        result.append(json.loads(zlib.decompress(base64.b64decode(match[1], validate=True))))
    return tuple(result)


def localized(localization: dict, category: str, key: int) -> str:
    return localization.get(category, {}).get(str(key), {}).get("ja", "")


def convert_monsters(report: dict, dictionaries: dict, localization: dict) -> dict:
    floors = []
    for number, floor in sorted(report["floors"].items(), key=lambda pair: int(pair[0])):
        normal, maze = [], []
        dekkai = False
        for entry in sorted(floor["monster"]["monster_table"], key=lambda e: -e["weight"]):
            creature = dictionaries["creature_data"][str(entry["creature_id"])]
            if entry["weight"] <= 0 or creature["creature_kind_str"] != "monster":
                continue
            if creature["is_behemoth"]:
                dekkai = dekkai or floor["monster"]["behemoth_prob"] > 0
                continue
            name = localized(localization, "creature_name", entry["creature_id"])
            name = name or localized(localization, "actor_name", creature["actor_name"])
            if not name:
                raise ValueError(f"Unknown monster: {entry['creature_id']}")
            flags = entry.get("flag", {})
            # The current UI lists naturally occurring monsters, like the existing tables.
            if any(flags.get(flag) for flag in ("MH_only", "summon_only", "boss")):
                continue
            target = maze if name in MAZE_MONSTERS else normal
            if name not in target:
                target.append(name)
        dark = bool(floor["dungeon"]["floor_type"] & 4)
        floors.append({
            "floor": int(number),
            "visibility": "暗" if dark else "明",
            "visibility_background": "#000000" if dark else "",
            "visibility_foreground": "#ffffff" if dark else "",
            "monsters": normal,
            "monster_cells": [{"name": name, "background": "", "foreground": ""} for name in normal],
            "dekkai": dekkai,
            "dekkai_monsters": ["デッ怪"] if dekkai else [],
            "dekkai_cells": [{"name": "デッ怪", "background": "#000000", "foreground": "#ffffff"}] if dekkai else [],
            "maze_monsters": maze,
            "maze_cells": [{"name": name, "background": "#00cdcd", "foreground": "#ffffff"} for name in maze],
        })
    return {"table_id": report["dungeon"]["dungeon_id"], "columns": ["階", "視界", "出現モンスター", "デッ怪", "マゼ種"], "floors": floors}


def convert_items(report: dict, dictionaries: dict, localization: dict, categories: dict) -> dict:
    table_types: dict[int, set[int]] = {}
    for floor in report["floors"].values():
        for table_type, table_id in enumerate(floor["item"]["item_tables"]):
            table_types.setdefault(table_id, set()).add(table_type)

    items = {}

    def add_item(item_id: int) -> dict:
        name = localized(localization, "item_name", item_id)
        if not name:
            raise ValueError(f"Unknown item: {item_id}")
        if name not in items:
            items[name] = {
                "name": name, "source_name": "", "category": categories.get(name, ""),
                "source_format": "tsuemaki_item_tables", "table_ids": [],
                "shop_only": False, "dekkai_reward": False,
                "available": dict.fromkeys(AVAILABILITY_KEYS, False),
                "raw_available": dict.fromkeys(AVAILABILITY_KEYS, ""),
                "other_methods": "",
            }
        return items[name]

    for table_id, types in sorted(table_types.items()):
        table = report["dungeon"]["item_tables"][str(table_id)]
        weights = {c["category_id"]: c["weight"] for c in table["categories"]}
        for entry in table["items"]:
            category_id = entry["category_id"]
            # The viewer splits sacred weapons/shields into separate categories.
            rarity = dictionaries["item_data"][str(entry["item_id"])]["rarity"]
            sacred_categories = {432758880: {1: 1045712042, 2: 1688617513}, 1852511598: {1: 1197509669, 2: 1773773493}}
            category_id = sacred_categories.get(category_id, {}).get(rarity, category_id)
            if entry["weight"] <= 0 or weights.get(category_id, 0) <= 0:
                continue
            item = add_item(entry["item_id"])
            if table_id not in item["table_ids"]:
                item["table_ids"].append(table_id)
            for table_type in types:
                for method in TABLE_TYPES[table_type]:
                    item["available"][method] = True
            if types.intersection({5, 9}):
                item["other_methods"] = "交換系NPC・盗み等のテーブルを含む"

    for fixed in report["dungeon"]["item_attach"]["attach_info"].values():
        if fixed["floors"]:
            add_item(fixed["item_id"])["other_methods"] = "確定出現"

    for item in items.values():
        # An item is shop-only if every active source table is a shop table.
        types = set().union(*(table_types[t] for t in item["table_ids"]))
        item["shop_only"] = bool(types) and types <= {1, 8} and not item["other_methods"]
        item["dekkai_reward"] = item["available"]["dekkai"]
        for method in AVAILABILITY_KEYS:
            ids = [t for t in item["table_ids"] if any(method in TABLE_TYPES[k] for k in table_types[t])]
            item["raw_available"][method] = ", ".join(f"Table #{t}" for t in ids)
    return {"columns": list(AVAILABILITY_KEYS), "table_count": len(table_types), "items": sorted(items.values(), key=lambda i: (i["category"], i["name"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-js", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/6_dungeons"))
    parser.add_argument("--item-data", type=Path, default=Path("data/6_items.json"))
    args = parser.parse_args()
    if args.export_js:
        source = args.export_js.read_text(encoding="utf-8")
    else:
        with urlopen(BASE_URL + "exported_reports.js", timeout=30) as response:
            source = response.read().decode("utf-8")
    reports, dictionaries, localization = decode_export(source)
    master = json.loads(args.item_data.read_text(encoding="utf-8"))
    categories = {i["名前"]: key for key, c in master["categories"].items() for i in c["items"]}
    by_id = {report["dungeon"]["dungeon_id"]: report for report in reports}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for dungeon_id, (key, name) in DUNGEONS.items():
        report = by_id[dungeon_id]
        if localized(localization, "place_name", report["dungeon"]["dungeon_name"]) != name:
            raise ValueError(f"Dungeon name mismatch: {dungeon_id}")
        data = {
            "name": name, "key": key, "url": BASE_URL + f"?dungeon={dungeon_id}&lang=ja",
            "title": f"Report Viewer - {name}", "generated_at": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(), "source_notes": [],
            "floor_counts": report["dungeon"]["floors"],
            "monster_table": convert_monsters(report, dictionaries, localization),
            "items": convert_items(report, dictionaries, localization, categories),
        }
        path = args.output_dir / f"{key}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {len(data['monster_table']['floors'])} floors, {len(data['items']['items'])} items -> {path}")


if __name__ == "__main__":
    main()
