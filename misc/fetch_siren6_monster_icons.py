#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Shiren 6 monster icons from Kamigame and save them under data/icons."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_URL = "https://kamigame.jp/shiren6/page/300662776156709551.html"
DEFAULT_OUTPUT_DIR = Path("data/icons")
DEFAULT_FILENAME_MAP = Path("data/monster_icon_filenames.json")
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n+ *", " / ", value)
    return value.strip()


def safe_filename(value: str) -> str:
    name = INVALID_FILENAME_CHARS.sub("_", normalize_text(value))
    name = name.strip(" .")
    if not name:
        raise ValueError("empty monster name cannot be used as a filename")
    return name


def load_filename_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"filename map must be a JSON object: {path}")
    return {str(name): safe_filename(str(filename)) for name, filename in data.items()}


def image_extension(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[content_type]

    content = response.content
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    return ".img"


def table_rows(table: Tag) -> Iterable[list[Tag]]:
    for row in table.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if cells:
            yield cells


def find_monster_table(soup: BeautifulSoup) -> Tag:
    for table in soup.select("table"):
        rows = list(table_rows(table))
        if not rows:
            continue
        headers = [normalize_text(cell.get_text(" ", strip=True)) for cell in rows[0]]
        if headers[:3] == ["モンスター", "属性", "行動速度"]:
            return table
    raise ValueError("monster list table was not found")


def monster_icons(table: Tag, page_url: str) -> list[tuple[str, str]]:
    icons: list[tuple[str, str]] = []
    seen_names: set[str] = set()

    for img in table.select("tr td:first-child img"):
        name = normalize_text(img.get("alt", ""))
        src = img.get("src", "")
        if not name or not src or name in seen_names:
            continue
        seen_names.add(name)
        icons.append((name, urljoin(page_url, src)))

    if not icons:
        raise ValueError("monster icons were not found in the monster list table")
    return icons


def fetch_monster_icons(
    session: requests.Session,
    page_url: str,
    output_dir: Path,
    filename_map: dict[str, str],
    timeout: float,
    sleep: float,
    overwrite: bool,
    dry_run: bool,
) -> tuple[int, int]:
    response = session.get(page_url, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    icons = monster_icons(find_monster_table(soup), page_url)

    print(f"found {len(icons)} monster icons")
    if dry_run:
        for name, url in icons:
            print(f"{name}\t{url}")
        return len(icons), 0

    output_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for index, (name, url) in enumerate(icons, start=1):
        filename_base = filename_map.get(name) or safe_filename(name)
        existing = next(output_dir.glob(f"{filename_base}.*"), None)
        if existing and not overwrite:
            print(f"[{index:03}/{len(icons):03}] skip {name}: {existing}")
            continue

        icon_response = session.get(url, timeout=timeout)
        icon_response.raise_for_status()
        extension = image_extension(icon_response)
        path = output_dir / f"{filename_base}{extension}"

        if path.exists() and not overwrite:
            print(f"[{index:03}/{len(icons):03}] skip {name}: {path}")
            continue

        path.write_bytes(icon_response.content)
        saved += 1
        print(f"[{index:03}/{len(icons):03}] saved {name}: {path}")

        if sleep > 0 and index < len(icons):
            time.sleep(sleep)

    return len(icons), saved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Shiren 6 monster icons from Kamigame.",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"source page URL (default: {DEFAULT_URL})")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory to save icons (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--filename-map",
        type=Path,
        default=DEFAULT_FILENAME_MAP,
        help=f"JSON map from monster names to ASCII icon filenames (default: {DEFAULT_FILENAME_MAP})",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="request timeout seconds (default: 20)")
    parser.add_argument("--sleep", type=float, default=0.1, help="seconds to wait between icon requests (default: 0.1)")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing icon files")
    parser.add_argument("--dry-run", action="store_true", help="print detected icons without downloading them")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "siren5-helper/0.1 (+https://kamigame.jp/shiren6/)",
        "Accept": "text/html,image/png,image/jpeg,image/webp,*/*;q=0.8",
    })

    try:
        filename_map = load_filename_map(args.filename_map)
        found, saved = fetch_monster_icons(
            session=session,
            page_url=args.url,
            output_dir=args.output_dir,
            filename_map=filename_map,
            timeout=args.timeout,
            sleep=args.sleep,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except requests.RequestException as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"parse failed: {exc}", file=sys.stderr)
        return 1

    if not args.dry_run:
        print(f"done: found {found}, saved {saved}, output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
