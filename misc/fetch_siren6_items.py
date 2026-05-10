#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Shiren 6 item list tables from Seesaa Wiki and save them as JSON."""

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
DEFAULT_OUTPUT = Path("data/6_items.json")


@dataclass(frozen=True)
class CategoryPage:
    key: str
    name: str
    url: str


CATEGORY_PAGES = [
    CategoryPage("buki", "武器", f"{BASE_URL}/d/%c9%f0%b4%ef"),
    CategoryPage("tate", "盾", f"{BASE_URL}/d/%bd%e2"),
    CategoryPage("udewa", "腕輪", f"{BASE_URL}/d/%cf%d3%ce%d8"),
    CategoryPage("ya_ishi", "矢・石", f"{BASE_URL}/d/%cc%f0%a1%a6%c0%d0"),
    CategoryPage("shokuryo", "食料", f"{BASE_URL}/d/%bf%a9%ce%c1"),
    CategoryPage("kusa_tane", "草・種", f"{BASE_URL}/d/%c1%f0%a1%a6%bc%ef"),
    CategoryPage("makimono", "巻物", f"{BASE_URL}/d/%b4%ac%ca%aa"),
    CategoryPage("tue", "杖", f"{BASE_URL}/d/%be%f3"),
    CategoryPage("okou", "お香", f"{BASE_URL}/d/%a4%aa%b9%e1"),
    CategoryPage("tubo", "壺", f"{BASE_URL}/d/%d4%e4"),
    CategoryPage("momoman", "桃まん", f"{BASE_URL}/d/%c5%ed%a4%de%a4%f3"),
]


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n+ *", " / ", value)
    return value.strip()


def normalize_header(cell: Tag) -> str:
    return normalize_text(cell.get_text("", strip=True))


def make_unique_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique_headers = []
    for header in headers:
        base = header or "column"
        counts[base] = counts.get(base, 0) + 1
        unique_headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return unique_headers


def parse_value(value: str) -> Any:
    if value == "-":
        return ""
    number = value.replace(",", "")
    if re.fullmatch(r"[+-]?\d+", number):
        return int(number)
    return value


def cell_value(cell: Tag) -> Any:
    return parse_value(normalize_text(cell.get_text("\n", strip=True)))


def find_item_table(soup: BeautifulSoup) -> Tag:
    candidates = []
    for table in soup.select("table"):
        headers = table.select("thead th")
        rows = table.select("tbody tr")
        if headers and rows:
            has_list_class = int(
                "sort" in (table.get("class") or [])
                or "filter" in (table.get("class") or [])
            )
            candidates.append((has_list_class, len(rows), table))
    if not candidates:
        raise ValueError("item list table was not found")
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def expand_body_rows(table: Tag, column_count: int) -> list[tuple[Tag, list[Any]]]:
    expanded_rows = []
    rowspans: dict[int, list[Any]] = {}

    for row in table.select("tbody tr"):
        values: list[Any] = []
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

            value = cell_value(cell)
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

        if len(values) == column_count:
            expanded_rows.append((row, values))

    return expanded_rows


def parse_table(table: Tag) -> tuple[list[str], list[dict[str, Any]]]:
    original_headers = [normalize_header(th) for th in table.select("thead th")]
    headers = make_unique_headers(original_headers)
    items = []

    for index, (row, values) in enumerate(expand_body_rows(table, len(headers)), start=1):
        item: dict[str, Any] = {"index": index}
        first_cell = row.find(["th", "td"], recursive=False)
        first_link = first_cell.find("a", href=True) if first_cell else None
        if first_link and first_link["href"].startswith("#"):
            item["detail_anchor"] = first_link["href"]

        for header, value in zip(headers, values):
            item[header] = value
        items.append(item)

    return original_headers, items


def fetch_page(session: requests.Session, page: CategoryPage, timeout: float) -> dict[str, Any]:
    response = session.get(page.url, timeout=timeout)
    response.raise_for_status()
    html = response.content.decode("euc_jp", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    table = find_item_table(soup)
    columns, items = parse_table(table)

    title = soup.find("title")
    generated = soup.find("meta", attrs={"name": "generated"})

    return {
        "name": page.name,
        "url": page.url,
        "title": title.get_text(strip=True) if title else "",
        "generated_at": generated.get("content", "") if generated else "",
        "table_id": table.get("id", ""),
        "columns": columns,
        "items": items,
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
        description="Fetch Shiren 6 item list tables and save them as JSON.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--category",
        action="append",
        choices=[page.key for page in CATEGORY_PAGES],
        help="fetch only the specified category; can be used multiple times",
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
    selected_keys = set(args.category or [])
    pages = [
        page for page in CATEGORY_PAGES
        if not selected_keys or page.key in selected_keys
    ]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "siren5_helper item fetcher",
    })

    categories = {}
    for index, page in enumerate(pages):
        categories[page.key] = fetch_page(session, page, args.timeout)
        print(f"{page.name}: {len(categories[page.key]['items'])} items")
        if args.sleep > 0 and index + 1 < len(pages):
            time.sleep(args.sleep)

    data = {
        "source": BASE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "category_order": [page.key for page in pages],
        "categories": categories,
    }
    write_json(args.output, data)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
