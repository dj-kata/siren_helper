#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch selected Shiren 6 dungeon tables and save one JSON file per dungeon."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://shiren6.game-info.wiki"
DEFAULT_OUTPUT_DIR = Path("data/6_dungeons")
DEFAULT_ITEM_DATA = Path("data/6_items.json")


@dataclass(frozen=True)
class DungeonPage:
    key: str
    name: str
    url: str


DUNGEON_PAGES = [
    DungeonPage(
        "toguro_shinzui",
        "とぐろ島の神髄",
        f"{BASE_URL}/d/%a4%c8%a4%b0%a4%ed%c5%e7%a4%ce%bf%c0%bf%f1",
    ),
    DungeonPage(
        "chinmoku_shinzui",
        "沈黙の神髄",
        f"{BASE_URL}/d/%c4%c0%cc%db%a4%ce%bf%c0%bf%f1",
    ),
    DungeonPage(
        "cho_shinzui",
        "超・神髄",
        f"{BASE_URL}/d/%c4%b6%a1%a6%bf%c0%bf%f1",
    ),
]

ITEM_AVAILABILITY_COLUMNS = {
    "床落": "floor",
    "店売": "shop",
    "願い": "wish",
    "敵落": "enemy_drop",
    "壁": "wall_pillar",
    "壁柱": "wall_pillar",
    "トド": "todoroki_drop",
    "浮島": "floating_island",
    "変化": "change_pot",
    "ビ壺": "beaker_pot",
    "熱狂": "fever",
    "デ怪": "dekkai",
    "太陽": "sun",
    "雨": "rain",
}
TRUE_MARKS = {"○", "◯", "〇", "有", "あり", "黄", "灰", "黒"}


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n+ *", " / ", value)
    return value.strip()


def cell_text(cell: Tag) -> str:
    text = normalize_text(cell.get_text("\n", strip=True))
    return "" if text == "-" else text


def make_unique_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result = []
    for header in headers:
        base = header or "column"
        counts[base] = counts.get(base, 0) + 1
        result.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return result


def normalize_column_name(value: str) -> str:
    return re.sub(r"[\s/]+", "", value)


def expand_rows(table: Tag) -> list[list[str]]:
    rows = []
    rowspans: dict[int, list[Any]] = {}

    for row in table.select("tr"):
        values = []
        column_index = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            while column_index in rowspans:
                remaining, value = rowspans[column_index]
                values.append(value)
                if remaining <= 1:
                    del rowspans[column_index]
                else:
                    rowspans[column_index] = [remaining - 1, value]
                column_index += 1

            value = cell_text(cell)
            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            for offset in range(colspan):
                values.append(value)
                if rowspan > 1:
                    rowspans[column_index + offset] = [rowspan - 1, value]
            column_index += colspan

        while column_index in rowspans:
            remaining, value = rowspans[column_index]
            values.append(value)
            if remaining <= 1:
                del rowspans[column_index]
            else:
                rowspans[column_index] = [remaining - 1, value]
            column_index += 1

        if values:
            rows.append(values)
    return rows


def parse_floor(value: str) -> int | str:
    return int(value) if re.fullmatch(r"\d+", value) else value


def monster_name(value: str) -> str:
    return value.replace(" / ", "")


def find_monster_table(soup: BeautifulSoup) -> Tag:
    for table in soup.select("div.user-area table"):
        rows = expand_rows(table)
        if not rows:
            continue
        header = rows[0]
        monster_header_names = {"出現モンスター", "その他の出現モンスター"}
        if "階" in header and monster_header_names.intersection(header) and "編集" in header:
            return table
    raise ValueError("monster table was not found")


def parse_monster_table(table: Tag) -> dict[str, Any]:
    rows = expand_rows(table)
    headers = rows[0]
    monster_indexes = [
        i
        for i, name in enumerate(headers)
        if name in {"出現モンスター", "その他の出現モンスター"}
    ]
    dekkai_indexes = [i for i, name in enumerate(headers) if name == "デッ怪"]
    maze_indexes = [i for i, name in enumerate(headers) if name == "マゼ種"]
    visibility_indexes = [i for i, name in enumerate(headers) if name == "視界"]

    floors = []
    for row in rows[1:]:
        if not row or not row[0] or row[0] == "階":
            continue
        monsters = [
            monster_name(row[i])
            for i in monster_indexes
            if i < len(row) and row[i] and row[i] != "編集" and not row[i].isdigit()
        ]
        dekkai_monsters = [
            monster_name(row[i])
            for i in dekkai_indexes
            if i < len(row) and row[i] and row[i] != "編集"
        ]
        maze_monsters = [
            monster_name(row[i])
            for i in maze_indexes
            if i < len(row) and row[i] and row[i] != "編集"
        ]
        floors.append({
            "floor": parse_floor(row[0]),
            "visibility": row[visibility_indexes[0]]
            if visibility_indexes and visibility_indexes[0] < len(row)
            else "",
            "monsters": monsters,
            "dekkai": bool(dekkai_monsters),
            "dekkai_monsters": dekkai_monsters,
            "maze_monsters": maze_monsters,
        })

    return {
        "table_id": table.get("id", ""),
        "columns": headers,
        "floors": floors,
    }


def load_item_categories(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    categories = {}
    for key, category in data.get("categories", {}).items():
        for item in category.get("items", []):
            name = item.get("名前")
            if name:
                categories[name] = key
    return categories


def is_available(value: str) -> bool:
    if not value:
        return False
    parts = re.split(r"[/、,・\s]+", value)
    return any(part in TRUE_MARKS for part in parts)


def find_item_tables(soup: BeautifulSoup) -> list[Tag]:
    tables = []
    for table in soup.select("div.user-area table"):
        rows = expand_rows(table)
        if not rows:
            continue
        header = [normalize_column_name(value) for value in rows[0]]
        has_flag_columns = "床落" in header and "店売" in header
        has_method_column = "主な入手方法" in header
        if "名称" in header and (has_flag_columns or has_method_column):
            tables.append(table)
    return tables


def empty_availability() -> tuple[dict[str, bool], dict[str, str]]:
    keys = set(ITEM_AVAILABILITY_COLUMNS.values())
    return (
        {json_key: False for json_key in keys},
        {json_key: "" for json_key in keys},
    )


def availability_from_methods(methods: str) -> tuple[dict[str, bool], dict[str, str]]:
    availability, raw_availability = empty_availability()
    method_checks = {
        "floor": ["床落"],
        "shop": ["店売"],
        "wish": ["願い"],
        "enemy_drop": ["敵落", "ドロップ"],
        "wall_pillar": ["壁", "柱"],
        "todoroki_drop": ["トド"],
        "floating_island": ["浮島"],
        "change_pot": ["変化"],
        "beaker_pot": ["ビ壺"],
        "fever": ["熱狂", "祭"],
        "dekkai": ["デ怪"],
        "sun": ["太陽"],
        "rain": ["雨"],
    }
    for key, needles in method_checks.items():
        if any(needle in methods for needle in needles):
            availability[key] = True
            raw_availability[key] = methods
    return availability, raw_availability


def parse_item_tables(
    tables: list[Tag],
    item_categories: dict[str, str],
) -> dict[str, Any]:
    items = []
    columns: list[str] = []
    seen: set[tuple[str, str]] = set()

    for table in tables:
        rows = expand_rows(table)
        if not rows:
            continue
        raw_headers = [normalize_column_name(value) for value in rows[0]]
        headers = make_unique_headers(raw_headers)
        columns = rows[0]
        for row in rows[1:]:
            values = dict(zip(headers, row))
            name = values.get("名称", "")
            if not name or name == "アイテム名" or name == "名称":
                continue

            category = item_categories.get(name, "")
            key = (name, category)
            if key in seen:
                continue
            seen.add(key)

            method_text = values.get("主な入手方法", "")
            if method_text:
                availability, raw_availability = availability_from_methods(method_text)
                source_format = "method_text"
                other = method_text
            else:
                availability, raw_availability = empty_availability()
                source_format = "availability_flags"
                for header, json_key in ITEM_AVAILABILITY_COLUMNS.items():
                    raw_value = values.get(header, "")
                    if raw_value:
                        raw_availability[json_key] = raw_value
                        availability[json_key] = availability[json_key] or is_available(raw_value)
                other = values.get("その他入手方法", "")

            other = "" if other == "他" else other
            if not any(availability.values()) and not other:
                continue

            items.append({
                "name": name,
                "category": category,
                "source_format": source_format,
                "available": availability,
                "raw_available": raw_availability,
                "other_methods": other,
            })

    return {
        "columns": columns,
        "table_count": len(tables),
        "items": sorted(items, key=lambda item: (item["category"], item["name"])),
    }


def fetch_page(
    session: requests.Session,
    dungeon: DungeonPage,
    timeout: float,
    item_categories: dict[str, str],
) -> dict[str, Any]:
    response = session.get(dungeon.url, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.content.decode("euc_jp", errors="replace"), "html.parser")

    title = soup.find("title")
    generated = soup.find("meta", attrs={"name": "generated"})

    monster_table = parse_monster_table(find_monster_table(soup))
    item_tables = parse_item_tables(find_item_tables(soup), item_categories)
    source_notes = []
    if not any(floor["monsters"] for floor in monster_table["floors"]):
        source_notes.append("monster table did not contain monster names in the source page")
    if item_tables["table_count"] == 0:
        source_notes.append("item availability table was not found in the source page")
    elif not item_tables["items"]:
        source_notes.append("item tables contained no available items after filtering placeholders")

    return {
        "name": dungeon.name,
        "key": dungeon.key,
        "url": dungeon.url,
        "title": title.get_text(strip=True) if title else "",
        "generated_at": generated.get("content", "") if generated else "",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_notes": source_notes,
        "monster_table": monster_table,
        "items": item_tables,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Shiren 6 dungeon monster and item tables.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--item-data",
        type=Path,
        default=DEFAULT_ITEM_DATA,
        help=f"item master JSON path for category names (default: {DEFAULT_ITEM_DATA})",
    )
    parser.add_argument(
        "--dungeon",
        action="append",
        choices=[page.key for page in DUNGEON_PAGES],
        help="fetch only the specified dungeon key; can be used multiple times",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="seconds to wait between requests (default: 0.5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="request timeout seconds (default: 20)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected_keys = set(args.dungeon or [])
    pages = [
        page for page in DUNGEON_PAGES
        if not selected_keys or page.key in selected_keys
    ]
    item_categories = load_item_categories(args.item_data)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "siren5_helper dungeon fetcher",
    })

    for index, page in enumerate(pages):
        data = fetch_page(session, page, args.timeout, item_categories)
        output_path = args.output_dir / f"{page.key}.json"
        write_json(output_path, data)
        print(
            f"{page.name}: "
            f"{len(data['monster_table']['floors'])} floors, "
            f"{len(data['items']['items'])} items -> {output_path}"
        )
        if args.sleep > 0 and index + 1 < len(pages):
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
