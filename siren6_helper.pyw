"""
Siren 6 Helper - メインプログラム
OBS連携でゲーム画面を自動取得しながら識別情報を管理するための骨組み。
"""

import asyncio
import datetime
import json
import os
import re
import sys
import threading
import traceback
import time
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

try:
    import keyboard

    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("警告: keyboardライブラリがインストールされていません。グローバルホットキーは無効です。")

from src.config import Config
from src.config_dialog import ConfigDialog
from src.dungeon_ocr import DungeonOcrReader
from src.dungeon_ocr import normalize_ocr_text
from src.funcs import escape_for_filename
from src.item import ItemList
from src.logger import get_logger
from src.main_window import MainWindowUI
from src.obs_dialog import OBSControlDialog
from src.obs_websocket_manager import OBSWebSocketManager
from src.shop_ocr import ShopOcrReader
from src.update import GitHubUpdater
from src.websocket_server import DataWebSocketServer

logger = get_logger("new_siren6_helper")

try:
    with open("version.txt", "r", encoding="utf-8") as f:
        tmp = f.readline()
        SWVER = tmp.strip()[1:] if tmp.startswith("v") else tmp.strip()
except Exception:
    SWVER = "0.0.0"

ITEM_CATEGORIES = ["kusa", "makimono", "udewa", "tubo", "okou", "tue", "buki", "tate"]
STAT_CATEGORIES = ["kusa", "makimono", "udewa", "tubo", "okou", "tue"]
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
SHOP_CATEGORY_HINTS = {
    "草": "kusa",
    "種": "kusa",
    "巻物": "makimono",
    "腕輪": "udewa",
    "壺": "tubo",
    "香": "okou",
    "杖": "tue",
    "剣": "buki",
    "刀": "buki",
    "盾": "tate",
}
DISABLED_DUNGEON_KEYS = {"chinmoku_shinzui"}
INVALID_ICON_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
ICON_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"]
MONSTER_ICON_NAME_ALIASES = {
    "洞窟マムル": "どうくつマムル",
}


class UserSettings:
    """siren6_helper.pyw と互換性のある識別・メモ設定"""

    def __init__(self, savefile="settings.json"):
        self.savefile = savefile
        self.params = self.load_settings()

    def get_default_settings(self):
        tmp = ItemList()
        ret = {
            "lx": 0,
            "ly": 0,
            "lw": 970,
            "lh": 930,
            "memo": "",
            "memo_const": "",
            "selected_dungeon": "",
            "selected_monster_floor": 1,
        }
        for key in ITEM_CATEGORIES:
            ret[key] = [False] * len(getattr(tmp, key))
        return ret

    def load_settings(self):
        default_val = self.get_default_settings()
        ret = {}
        try:
            with open(self.savefile, "r", encoding="utf-8") as f:
                ret = json.load(f)
        except Exception:
            logger.info("有効な識別設定ファイルなし。デフォルト値を使います。")

        for key, value in default_val.items():
            if key not in ret:
                ret[key] = value

        for key in ITEM_CATEGORIES:
            ret[key] = self._normalize_bool_list(ret.get(key, []), len(default_val[key]))

        return ret

    def _normalize_bool_list(self, values, length):
        normalized = [bool(v) for v in values[:length]]
        normalized.extend([False] * (length - len(normalized)))
        return normalized

    def save_settings(self):
        with open(self.savefile, "w", encoding="utf-8") as f:
            json.dump(self.params, f, ensure_ascii=False, indent=2)


class MainWindow(MainWindowUI):
    """メインウィンドウクラス - 制御ロジックを担当"""

    capture_processed = Signal(object)

    def __init__(self):
        self.config = Config()
        super().__init__(self.config)

        self.siren_settings = UserSettings()
        self.itemlist = ItemList()
        self.itemlist.load(self.siren_settings.params)
        self.dungeons = self.load_dungeon_filters()
        self.selected_dungeon_key = self.default_dungeon_key()

        self.obs_manager = OBSWebSocketManager()
        self.obs_manager.set_config(self.config)
        self.obs_manager.connection_changed.connect(self.on_obs_connection_changed)

        self._start_time = int(datetime.datetime.now().timestamp())
        self.capture_count = 0
        self.last_capture_time = None
        self.capture_status = self.ui.main.waiting_capture
        self.latest_screen = None
        self.last_capture_attempt_time = 0.0
        self.capture_interval = self.config.obs_capture_interval_seconds
        self.dungeon_ocr_reader = DungeonOcrReader()
        self.last_dungeon_ocr_time = 0.0
        self.dungeon_ocr_interval = 5.0
        self.shop_ocr_reader = ShopOcrReader()
        self.last_shop_ocr_time = 0.0
        self.shop_ocr_interval = 1.5
        self.last_shop_result_signature = None
        self.capture_worker = None
        self.capture_worker_running = False
        self.capture_worker_lock = threading.Lock()

        self.websocket_server = None
        self.websocket_loop = None
        self.websocket_thread = None
        self.start_websocket_server()

        self.init_ui()
        self.apply_main_font()
        self.init_identification_ui()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.config.keep_on_top)

        if self.config.obs_enabled:
            self.obs_manager.connect()
            QTimer.singleShot(1000, self.check_obs_configuration)
            self.execute_obs_triggers("app_start")
        else:
            self.obs_status_label.setText(self.ui.obs.disabled)

        self.main_timer = QTimer()
        self.main_timer.timeout.connect(self.main_loop)
        self.main_timer.start(250)
        self.capture_processed.connect(self.on_capture_processed)

        self.display_timer = QTimer()
        self.display_timer.timeout.connect(self.update_display)
        self.display_timer.start(500)

        self.setup_global_hotkeys()
        logger.info("アプリケーション起動完了")

    @property
    def start_time(self) -> int:
        return self._start_time

    def start_websocket_server(self):
        """画面取得状態を外部へ配信するWebSocketサーバーを開始"""
        self.websocket_server = DataWebSocketServer(self.config.websocket_data_port)
        self.websocket_loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(self.websocket_loop)
            self.websocket_server.start(self.websocket_loop)
            self.websocket_loop.run_forever()

        self.websocket_thread = threading.Thread(target=run_loop, daemon=True, name="DataWebSocketThread")
        self.websocket_thread.start()

    def stop_websocket_server(self):
        if self.websocket_server:
            self.websocket_server.stop()
        if self.websocket_loop:
            self.websocket_loop.call_soon_threadsafe(self.websocket_loop.stop)
        if self.websocket_thread:
            self.websocket_thread.join(timeout=2.0)

    def check_obs_configuration(self):
        if not self.config.obs_enabled:
            return

        status = self.obs_manager.get_detailed_status()
        warnings = []

        if not status["is_connected"]:
            warnings.append("・OBS WebSocketに接続できていません")
        if not status["is_source_configured"]:
            warnings.append("・監視対象ソースが設定されていません")

        if warnings:
            warning_message = "OBS設定に問題があります:\n\n" + "\n".join(warnings)
            warning_message += "\n\nOBSが起動していること及び、本アプリの設定を確認してください。"
            warning_message += "\n(メニュー: ファイル → OBS制御設定)"

            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("OBS設定の警告")
            msg_box.setText(warning_message)
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec()

            logger.warning(f"OBS configuration warning: {warnings}")

    def open_config_dialog(self):
        dialog = ConfigDialog(self.config, self)
        if dialog.exec():
            self.update_all_configs()
            logger.info("設定を更新しました")
            self.statusBar().showMessage("設定を更新しました", 3000)

    def open_obs_dialog(self):
        dialog = OBSControlDialog(self.config, self.obs_manager, self)
        if dialog.exec():
            self.update_all_configs()
            logger.info("OBS制御設定を更新しました")
            self.statusBar().showMessage("OBS制御設定を更新しました", 3000)

    def update_all_configs(self):
        old_port = self.config.websocket_data_port
        old_obs_enabled = self.config.obs_enabled
        self.config.load_config()
        self.obs_manager.set_config(self.config)
        self.capture_interval = self.config.obs_capture_interval_seconds

        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.config.keep_on_top)
        self.apply_main_font()
        if self.item_tables:
            self.update_item_tables()
        self.show()

        if old_port != self.config.websocket_data_port:
            self.stop_websocket_server()
            self.start_websocket_server()
            self.broadcast_monster_floor_state()

        if not self.config.obs_enabled:
            if self.obs_manager.is_connected or old_obs_enabled:
                self.obs_manager.disconnect()
            self.obs_status_label.setText(self.ui.obs.disabled)
            self.capture_status = self.ui.main.waiting_capture
            return

        if not self.obs_manager.is_connected:
            self.obs_manager.connect()

    def apply_main_font(self):
        font = QFont(self.font())
        font.setPointSize(self.config.main_font_size)
        self.setFont(font)

    def show_about(self):
        QMessageBox.about(
            self,
            self.ui.window.about_title,
            f"Siren 6 Helper {SWVER}\n\nauthor: dj-kata",
        )

    def init_identification_ui(self):
        self.memo_edit.setPlainText(self.siren_settings.params.get("memo", ""))
        self.memo_const_edit.setPlainText(self.siren_settings.params.get("memo_const", ""))
        self.init_dungeon_combo()
        self.mark_identified_button.clicked.connect(lambda: self.set_selected_items_identified(True))
        self.mark_unknown_button.clicked.connect(lambda: self.set_selected_items_identified(False))
        self.reset_button.clicked.connect(self.reset_identification)
        self.update_item_tables()

    def load_dungeon_filters(self):
        dungeon_dir = Path("data/6_dungeons")
        if not dungeon_dir.exists():
            return []

        preferred_order = ["toguro_shinzui", "chinmoku_shinzui", "cho_shinzui"]
        reverse_categories = {
            json_key: category
            for category, json_key in ItemList.category_json_keys.items()
        }
        dungeons = []

        for path in sorted(dungeon_dir.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                logger.warning(f"ダンジョンデータの読み込みに失敗しました: {path}")
                continue
            key = data.get("key") or path.stem
            if key in DISABLED_DUNGEON_KEYS:
                continue

            item_names_by_category = {category: set() for category in ITEM_CATEGORIES}
            for item in data.get("items", {}).get("items", []):
                category = reverse_categories.get(item.get("category", ""))
                name = item.get("name", "")
                if category and name:
                    item_names_by_category[category].add(name)

            dungeons.append({
                "key": key,
                "name": data.get("name") or path.stem,
                "path": str(path),
                "item_names_by_category": item_names_by_category,
                "monster_floors": data.get("monster_table", {}).get("floors", []),
            })

        order = {key: index for index, key in enumerate(preferred_order)}
        return sorted(dungeons, key=lambda dungeon: (order.get(dungeon["key"], 999), dungeon["name"]))

    def default_dungeon_key(self):
        saved_key = self.siren_settings.params.get("selected_dungeon", "")
        available_keys = {dungeon["key"] for dungeon in self.dungeons}
        if saved_key in available_keys:
            return saved_key
        return self.dungeons[0]["key"] if self.dungeons else ""

    def init_dungeon_combo(self):
        self.dungeon_combo.blockSignals(True)
        self.dungeon_combo.clear()
        for dungeon in self.dungeons:
            self.dungeon_combo.addItem(dungeon["name"], dungeon["key"])

        current_index = self.dungeon_combo.findData(self.selected_dungeon_key)
        if current_index < 0 and self.dungeon_combo.count() > 0:
            current_index = 0
            self.selected_dungeon_key = self.dungeon_combo.itemData(0)
        if current_index >= 0:
            self.dungeon_combo.setCurrentIndex(current_index)

        self.dungeon_combo.blockSignals(False)
        self.dungeon_combo.currentIndexChanged.connect(self.on_dungeon_changed)
        self.monster_floor_combo.currentIndexChanged.connect(self.on_monster_floor_changed)
        self.reset_monster_floor_filter(self.siren_settings.params.get("selected_monster_floor", 1))

    def on_dungeon_changed(self, *_args):
        self.selected_dungeon_key = self.dungeon_combo.currentData() or ""
        self.reset_monster_floor_filter()
        self.update_item_tables()
        self.update_monster_table()
        self.save_current_selection()
        name = self.dungeon_combo.currentText()
        if name:
            self.statusBar().showMessage(f"ダンジョンを変更しました: {name}", 3000)

    def on_monster_floor_changed(self, *_args):
        self.update_monster_table()
        self.save_current_selection()

    def current_dungeon(self):
        for dungeon in self.dungeons:
            if dungeon["key"] == self.selected_dungeon_key:
                return dungeon
        return None

    def get_target_items(self, category):
        items = getattr(self.itemlist, category)
        dungeon = self.current_dungeon()
        if not dungeon:
            return items
        item_names = dungeon["item_names_by_category"].get(category, set())
        return [item for item in items if item.name in item_names]

    def get_all_items(self, category):
        return getattr(self.itemlist, category)

    def reset_monster_floor_filter(self, preferred_floor=None):
        if not self.monster_floor_combo:
            return

        self.monster_floor_combo.blockSignals(True)
        self.monster_floor_combo.clear()
        dungeon = self.current_dungeon()
        floors = []
        if dungeon:
            floors = [
                floor.get("floor")
                for floor in dungeon.get("monster_floors", [])
                if isinstance(floor.get("floor"), int)
            ]
        max_floor = max(floors) if floors else 99
        for floor in range(1, max_floor + 1):
            self.monster_floor_combo.addItem(f"{floor}F以降", floor)
        index = 0 if self.monster_floor_combo.count() else -1
        if isinstance(preferred_floor, int):
            preferred_index = self.monster_floor_combo.findData(preferred_floor)
            if preferred_index >= 0:
                index = preferred_index
        self.monster_floor_combo.setCurrentIndex(index)
        self.monster_floor_combo.blockSignals(False)

    def update_monster_table(self, *_args):
        if not self.monster_table:
            return

        dungeon = self.current_dungeon()
        floors = dungeon.get("monster_floors", []) if dungeon else []
        start_floor = self.monster_floor_combo.currentData() if self.monster_floor_combo else 1
        if not isinstance(start_floor, int):
            start_floor = 1
        target = [
            floor
            for floor in floors
            if not isinstance(floor.get("floor"), int) or floor.get("floor") >= start_floor
        ]

        self.monster_table.setRowCount(len(target))
        monster_slots = max((len(floor.get("monster_cells") or floor.get("monsters", [])) for floor in target), default=0)
        dekkai_slots = max((len(floor.get("dekkai_cells") or floor.get("dekkai_monsters", [])) for floor in target), default=0)
        maze_slots = max((len(floor.get("maze_cells") or floor.get("maze_monsters", [])) for floor in target), default=0)
        headers = (
            ["階", "視界"]
            + [f"M{i}" for i in range(1, monster_slots + 1)]
            + [f"デッ怪{i}" for i in range(1, dekkai_slots + 1)]
            + [f"マゼ種{i}" for i in range(1, maze_slots + 1)]
        )
        self.monster_table.setColumnCount(len(headers))
        self.monster_table.setHorizontalHeaderLabels(headers)
        self.monster_table.setColumnWidth(0, 60)
        self.monster_table.setColumnWidth(1, 60)
        for column in range(2, len(headers)):
            self.monster_table.setColumnWidth(column, 120)

        row_height = self.monster_table.fontMetrics().height() + 6
        self.monster_table.verticalHeader().setDefaultSectionSize(row_height)

        for row, floor in enumerate(target):
            self.set_monster_table_item(row, 0, self.format_floor_label(floor.get("floor", "")))
            self.set_monster_table_item(
                row,
                1,
                floor.get("visibility", ""),
                floor.get("visibility_background", ""),
                floor.get("visibility_foreground", ""),
            )

            column = 2
            column = self.fill_monster_cells(row, column, monster_slots, floor, "monster_cells", "monsters")
            column = self.fill_monster_cells(row, column, dekkai_slots, floor, "dekkai_cells", "dekkai_monsters")
            self.fill_monster_cells(row, column, maze_slots, floor, "maze_cells", "maze_monsters")
            self.monster_table.setRowHeight(row, row_height)

        self.broadcast_monster_floor_state()

    def selected_monster_floor(self):
        dungeon = self.current_dungeon()
        floors = dungeon.get("monster_floors", []) if dungeon else []
        selected_floor = self.monster_floor_combo.currentData() if self.monster_floor_combo else 1
        if not isinstance(selected_floor, int):
            selected_floor = 1
        return self.monster_floor_by_number(floors, selected_floor)

    def monster_floor_by_number(self, floors, floor_number):
        for floor in floors:
            if floor.get("floor") == floor_number:
                return floor
        return None

    def monster_group_entries(self, floor, cell_key, names_key, group):
        cells = floor.get(cell_key) if floor else []
        if not cells:
            cells = [{"name": name} for name in floor.get(names_key, [])] if floor else []
        entries = []
        seen = set()
        for cell in cells:
            name = cell.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            entries.append({
                "name": name,
                "group": group,
                "icon_sources": self.monster_icon_sources(name),
                "background": cell.get("background", ""),
                "foreground": cell.get("foreground", ""),
            })
        return entries

    def safe_icon_filename(self, name):
        filename = INVALID_ICON_FILENAME_CHARS.sub("_", str(name).replace("\xa0", " "))
        return filename.strip(" .")

    def monster_icon_sources(self, name):
        filenames = []
        for candidate in (name, MONSTER_ICON_NAME_ALIASES.get(name, "")):
            filename = self.safe_icon_filename(candidate)
            if filename and filename not in filenames:
                filenames.append(filename)
        if not filenames:
            return []

        icon_dir = Path("data/icons")
        template_icon_dir = Path("../data/icons")
        if icon_dir.exists():
            existing = []
            for filename in filenames:
                existing.extend(
                    path
                    for path in icon_dir.glob(f"{filename}.*")
                    if path.suffix.lower() in ICON_EXTENSIONS
                )
            if existing:
                order = {extension: index for index, extension in enumerate(ICON_EXTENSIONS)}
                existing.sort(key=lambda path: order.get(path.suffix.lower(), 999))
                return [
                    (template_icon_dir / path.name).as_posix()
                    for path in existing
                ] + [path.as_posix() for path in existing]

        return [
            path.as_posix()
            for filename in filenames
            for extension in ICON_EXTENSIONS
            for path in (
                template_icon_dir / f"{filename}{extension}",
                icon_dir / f"{filename}{extension}",
            )
        ]

    def current_monster_floor_payload(self):
        dungeon = self.current_dungeon()
        floors = dungeon.get("monster_floors", []) if dungeon else []
        selected_floor = self.monster_floor_combo.currentData() if self.monster_floor_combo else 1
        if not isinstance(selected_floor, int):
            selected_floor = 1
        floor = self.monster_floor_by_number(floors, selected_floor)
        next_floor_number = selected_floor + 1
        next_floor = self.monster_floor_by_number(floors, next_floor_number)

        groups = self.monster_floor_groups(floor)

        return {
            "dungeon_key": dungeon.get("key", "") if dungeon else "",
            "dungeon_name": dungeon.get("name", "") if dungeon else "",
            "floor": selected_floor,
            "floor_label": self.format_floor_label(selected_floor),
            "visibility": floor.get("visibility", "") if floor else "",
            "groups": groups,
            "monsters": [monster for group in groups for monster in group["monsters"]],
            "next_floor": self.monster_floor_payload_part(next_floor, next_floor_number)
            if next_floor
            else None,
        }

    def monster_floor_groups(self, floor):
        return [
            {
                "key": "normal",
                "label": "出現モンスター",
                "monsters": self.monster_group_entries(floor, "monster_cells", "monsters", "normal"),
            },
            {
                "key": "dekkai",
                "label": "デッ怪",
                "monsters": self.monster_group_entries(floor, "dekkai_cells", "dekkai_monsters", "dekkai"),
            },
            {
                "key": "maze",
                "label": "マゼ種",
                "monsters": self.monster_group_entries(floor, "maze_cells", "maze_monsters", "maze"),
            },
        ]

    def monster_floor_payload_part(self, floor, floor_number):
        groups = self.monster_floor_groups(floor)
        return {
            "floor": floor_number,
            "floor_label": self.format_floor_label(floor_number),
            "visibility": floor.get("visibility", "") if floor else "",
            "groups": groups,
            "monsters": [monster for group in groups for monster in group["monsters"]],
        }

    def broadcast_monster_floor_state(self):
        if not self.websocket_server:
            return
        self.websocket_server.update_monster_floor_data(self.current_monster_floor_payload())

    def format_floor_label(self, floor):
        return f"{floor}F" if isinstance(floor, int) else str(floor)

    def fill_monster_cells(self, row, start_column, slot_count, floor, cell_key, names_key):
        cells = floor.get(cell_key)
        if not cells:
            cells = [{"name": name} for name in floor.get(names_key, [])]
        for offset in range(slot_count):
            if offset < len(cells):
                cell = cells[offset]
                self.set_monster_table_item(
                    row,
                    start_column + offset,
                    cell.get("name", ""),
                    cell.get("background", ""),
                    cell.get("foreground", ""),
                )
            else:
                self.set_monster_table_item(row, start_column + offset, "")
        return start_column + slot_count

    def set_monster_table_item(self, row, column, value, background="", foreground=""):
        cell = QTableWidgetItem(str(value))
        background_color = QColor(background)
        if background and background_color.isValid():
            cell.setBackground(QBrush(background_color))
        foreground_color = QColor(foreground)
        if foreground and foreground != background and foreground_color.isValid():
            cell.setForeground(QBrush(foreground_color))
        self.monster_table.setItem(row, column, cell)

    def set_selected_items_identified(self, identified: bool):
        category = ITEM_CATEGORIES[self.identify_tabs.currentIndex()]
        if category in ("buki", "tate"):
            self.statusBar().showMessage("武器・盾は識別状態の変更対象外です", 3000)
            return

        table = self.item_tables[category]
        selected_rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        if not selected_rows:
            self.statusBar().showMessage("変更する行を選択してください", 3000)
            return

        target = self.get_target_items(category)
        for row in selected_rows:
            if 0 <= row < len(target):
                target[row].get = identified

        self.update_item_tables()
        self.statusBar().showMessage("識別状態を更新しました", 3000)

    def reset_identification(self):
        self.itemlist.reset()
        self.memo_edit.clear()
        self.reset_monster_floor_filter()
        self.update_monster_table()
        self.update_item_tables()
        self.statusBar().showMessage("リセットしました", 3000)

    def update_item_tables(self):
        for category in ITEM_CATEGORIES:
            self.update_item_table(category)

        counts = self.get_item_stats()
        for category, (count, total) in counts.items():
            self.item_count_labels[category].setText(f"{count}/{total}")

        self.write_stat_xml(counts)
        self.update_monster_table()

    def update_item_table(self, category):
        table = self.item_tables[category]
        target = self.get_target_items(category)
        table.setRowCount(len(target))
        row_height = table.fontMetrics().height() + 6
        table.verticalHeader().setDefaultSectionSize(row_height)

        previous_buy = target[0].buy if target else None
        is_odd_price_group = False

        for row, item in enumerate(target):
            values = self.itemlist.get_table_values(category, item)
            values = [self.to_single_line(value) for value in values]

            if item.buy != previous_buy:
                previous_buy = item.buy
                is_odd_price_group = not is_odd_price_group

            background = QColor("#ffffb0" if is_odd_price_group else "#b0ffff")
            if item.get or item.default_get:
                background = QColor("#666666")
            foreground = QColor("#888888" if item.demerit else "#000000")

            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setBackground(QBrush(background))
                cell.setForeground(QBrush(foreground))
                table.setItem(row, column, cell)
            table.setRowHeight(row, row_height)

    def to_single_line(self, value):
        return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())

    def get_item_stats(self):
        counts = {}
        for category in STAT_CATEGORIES:
            total = 0
            count = 0
            for item in self.get_target_items(category):
                if item.default_get:
                    continue
                total += 1
                if item.get:
                    count += 1
            counts[category] = (count, total)
        return counts

    def write_stat_xml(self, counts):
        with open("stat.xml", "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write("<Items>\n")
            for category in STAT_CATEGORIES:
                count, total = counts[category]
                f.write(f"<{category}>{count}/{total}</{category}>\n")
            f.write("</Items>\n")

    def save_identification_settings(self):
        self.itemlist.save(self.siren_settings.params)
        self.siren_settings.params["memo"] = self.memo_edit.toPlainText()
        self.siren_settings.params["memo_const"] = self.memo_const_edit.toPlainText()
        self.siren_settings.params["selected_dungeon"] = self.selected_dungeon_key
        self.siren_settings.params["selected_monster_floor"] = self.current_monster_floor()
        self.siren_settings.save_settings()

    def current_monster_floor(self):
        if not self.monster_floor_combo:
            return 1
        floor = self.monster_floor_combo.currentData()
        return floor if isinstance(floor, int) else 1

    def save_current_selection(self):
        self.siren_settings.params["selected_dungeon"] = self.selected_dungeon_key
        self.siren_settings.params["selected_monster_floor"] = self.current_monster_floor()
        self.siren_settings.save_settings()

    def save_image(self):
        """現在取得しているゲーム画面を保存する"""
        try:
            if self.latest_screen is None:
                self.statusBar().showMessage("保存できる画面がまだありません", 3000)
                return False

            date = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = escape_for_filename(f"siren6_capture_{date}.png")
            os.makedirs(self.config.image_save_path, exist_ok=True)
            full_path = Path(self.config.image_save_path) / filename
            self.latest_screen.save(full_path)
            self.statusBar().showMessage(f"保存しました -> {filename}", 10000)
            return True
        except Exception as e:
            logger.error(f"画像保存エラー: {traceback.format_exc()}")
            self.statusBar().showMessage(f"画像保存エラー: {str(e)}", 3000)
            return False

    def on_obs_connection_changed(self, is_connected: bool, message: str):
        self.obs_status_label.setText(message)
        self.obs_status_label.setStyleSheet(
            "color: green; font-weight: bold;" if is_connected else "color: red; font-weight: bold;"
        )
        if is_connected:
            logger.info("OBS接続が確立されました")

    def main_loop(self):
        """OBSから監視対象ソースを定期取得する"""
        try:
            if not self.config.obs_enabled:
                self.capture_status = self.ui.main.waiting_capture
                return

            if not self.obs_manager.is_connected or not self.config.monitor_source_name:
                self.capture_status = self.ui.main.waiting_capture
                return

            with self.capture_worker_lock:
                if self.capture_worker_running:
                    return

            now = time.monotonic()
            if now - self.last_capture_attempt_time < self.capture_interval:
                return
            self.last_capture_attempt_time = now

            self.start_capture_worker()
        except Exception:
            logger.error(f"メインループエラー: {traceback.format_exc()}")

    def start_capture_worker(self):
        with self.capture_worker_lock:
            if self.capture_worker_running:
                return
            self.capture_worker_running = True

        self.capture_worker = threading.Thread(
            target=self.run_capture_pipeline,
            daemon=True,
            name="CapturePipelineThread",
        )
        self.capture_worker.start()

    def run_capture_pipeline(self):
        result = {
            "screen": None,
            "capture_failed": False,
            "dungeon_result": None,
            "shop_result": None,
        }
        try:
            self.obs_manager.screenshot()
            if self.obs_manager.screen is None:
                result["capture_failed"] = True
                return

            screen = self.obs_manager.screen
            result["screen"] = screen
            result["dungeon_result"] = self.read_dungeon_from_screen(screen)
            result["shop_result"] = self.read_shop_from_screen(screen)
        except Exception:
            logger.error(f"画面取得/OCRワーカーエラー: {traceback.format_exc()}")
        finally:
            self.capture_processed.emit(result)

    def on_capture_processed(self, result):
        try:
            if result.get("capture_failed"):
                self.capture_status = self.ui.main.capture_failed
                return

            screen = result.get("screen")
            if screen is None:
                return

            self.latest_screen = screen
            dungeon_result = result.get("dungeon_result")
            if dungeon_result:
                self.apply_detected_dungeon_floor(dungeon_result.dungeon_key, dungeon_result.floor)

            shop_result = result.get("shop_result")
            if shop_result:
                self.handle_shop_ocr_result(shop_result)

            self.capture_count += 1
            self.last_capture_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.capture_status = self.ui.main.capture_ok
            self.broadcast_capture_state()
        except Exception:
            logger.error(f"画面取得/OCR結果反映エラー: {traceback.format_exc()}")
        finally:
            with self.capture_worker_lock:
                self.capture_worker_running = False

    def update_dungeon_selection_from_screen(self, screen):
        result = self.read_dungeon_from_screen(screen)
        if result:
            self.apply_detected_dungeon_floor(result.dungeon_key, result.floor)

    def read_dungeon_from_screen(self, screen):
        now = time.monotonic()
        if now - self.last_dungeon_ocr_time < self.dungeon_ocr_interval:
            return None
        self.last_dungeon_ocr_time = now

        try:
            result = self.dungeon_ocr_reader.read(screen, self.dungeons)
            if not result:
                return None
            return result
        except Exception:
            logger.error(f"ダンジョンOCRエラー: {traceback.format_exc()}")
            return None

    def apply_detected_dungeon_floor(self, dungeon_key, floor):
        dungeon_index = self.dungeon_combo.findData(dungeon_key) if self.dungeon_combo else -1
        if dungeon_index < 0:
            return

        changed = False
        if self.dungeon_combo.currentData() != dungeon_key:
            self.dungeon_combo.setCurrentIndex(dungeon_index)
            changed = True

        floor_index = self.monster_floor_combo.findData(floor) if self.monster_floor_combo else -1
        if floor_index < 0:
            return

        if self.monster_floor_combo.currentData() != floor:
            self.monster_floor_combo.setCurrentIndex(floor_index)
            changed = True

        if changed:
            dungeon_name = self.dungeon_combo.currentText()
            self.statusBar().showMessage(f"OCRで更新しました: {dungeon_name} {floor}F", 3000)

    def update_shop_identification_from_screen(self, screen):
        result = self.read_shop_from_screen(screen)
        if result:
            self.handle_shop_ocr_result(result)

    def read_shop_from_screen(self, screen):
        now = time.monotonic()
        if now - self.last_shop_ocr_time < self.shop_ocr_interval:
            return None
        self.last_shop_ocr_time = now

        try:
            result = self.shop_ocr_reader.read(screen)
            if not result:
                return None
            return result
        except Exception:
            logger.error(f"店OCRエラー: {traceback.format_exc()}")
            return None

    def handle_shop_ocr_result(self, result):
        signature = (normalize_ocr_text(result.item_text), result.price_kind, result.price)
        if signature == self.last_shop_result_signature:
            logger.info(
                "店OCR: 同一結果 item=%r kind=%s price=%s raw=%s",
                result.item_text,
                result.price_kind,
                result.price,
                result.raw_texts,
            )
        self.last_shop_result_signature = signature
        logger.info(
            "店OCR: 判定結果 item=%r normalized=%r kind=%s price=%s raw=%s",
            result.item_text,
            normalize_ocr_text(result.item_text),
            result.price_kind,
            result.price,
            result.raw_texts,
        )
        self.apply_shop_price_result(result)

    def apply_shop_price_result(self, result):
        exact = self.find_item_by_name(result.item_text)
        if exact:
            category, item = exact
            if category in ("buki", "tate"):
                candidates = self.find_item_price_candidates(item, result.price, result.price_kind)
                self.broadcast_shop_price_state(result, category, candidates, exact_item=item)
                logger.info(
                    "店OCR: 識別済み装備品価格候補 category=%s kind=%s price=%s candidates=%s",
                    category,
                    result.price_kind,
                    result.price,
                    tuple(self.format_shop_candidate(candidate) for candidate in candidates),
                )
                self.select_items_in_table(category, [item])

                price_label = "売値" if result.price_kind == "sell" else "買値"
                if candidates:
                    names = [self.format_shop_candidate(candidate) for candidate in candidates]
                    preview = "、".join(names[:8])
                    suffix = f" 他{len(names) - 8}件" if len(names) > 8 else ""
                    self.statusBar().showMessage(
                        f"店OCR識別済: {price_label}{result.price} -> {preview}{suffix}",
                        8000,
                    )
                else:
                    self.statusBar().showMessage(
                        f"店OCR識別済: {item.name} ({price_label}{result.price})",
                        4000,
                    )
                return

            logger.info(
                "店OCR: 識別済みアイテム一致 ocr=%r category=%s item=%s before_get=%s",
                result.item_text,
                category,
                item.name,
                item.get,
            )
            self.broadcast_shop_price_state(result, category, [(item, "", "")], exact_item=item)
            item.get = True
            self.update_item_tables()
            self.select_items_in_table(category, [item])
            self.statusBar().showMessage(f"OCR識別済: {item.name}", 4000)
            return

        category = self.detect_shop_item_category(result.item_text)
        if not category:
            logger.info(
                "店OCR: 種別判定失敗 ocr=%r normalized=%r price=%s kind=%s",
                result.item_text,
                self.normalize_item_match_text(result.item_text),
                result.price,
                result.price_kind,
            )
            self.broadcast_shop_price_state(result, None, [])
            self.statusBar().showMessage(f"店OCR: 種別を判定できません ({result.item_text})", 4000)
            return

        candidates = self.find_shop_price_candidates(category, result.price, result.price_kind)
        self.broadcast_shop_price_state(result, category, candidates)
        logger.info(
            "店OCR: 価格候補 category=%s kind=%s price=%s candidates=%s",
            category,
            result.price_kind,
            result.price,
            tuple(self.format_shop_candidate(candidate) for candidate in candidates),
        )
        items = [candidate[0] for candidate in candidates]
        self.select_items_in_table(category, items)

        price_label = "売値" if result.price_kind == "sell" else "買値"
        category_label = ITEM_CATEGORY_LABELS.get(category, category)
        if candidates:
            names = [self.format_shop_candidate(candidate) for candidate in candidates]
            preview = "、".join(names[:8])
            suffix = f" 他{len(names) - 8}件" if len(names) > 8 else ""
            self.statusBar().showMessage(
                f"店OCR候補: {category_label} {price_label}{result.price} -> {preview}{suffix}",
                8000,
            )
        else:
            self.statusBar().showMessage(
                f"店OCR候補なし: {category_label} {price_label}{result.price}",
                5000,
            )

    def find_item_by_name(self, text):
        target = self.normalize_item_match_text(text)
        if not target:
            logger.info("店OCR: アイテム名照合 targetなし text=%r", text)
            return None

        containing_match = None
        best_match = None
        best_score = 0.0
        for category in ITEM_CATEGORIES:
            for item in self.get_all_items(category):
                item_name = self.normalize_item_match_text(item.name)
                if item_name == target:
                    logger.info(
                        "店OCR: アイテム名 完全一致 target=%r category=%s item=%s",
                        target,
                        category,
                        item.name,
                    )
                    return category, item
                if item_name and item_name in target:
                    containing_match = containing_match or (category, item)
                score = SequenceMatcher(None, item_name, target).ratio()
                if score > best_score:
                    best_match = (category, item)
                    best_score = score

        if containing_match:
            category, item = containing_match
            logger.info(
                "店OCR: アイテム名 部分一致 target=%r category=%s item=%s best_score=%.3f",
                target,
                category,
                item.name,
                best_score,
            )
            return containing_match
        if best_match and best_score >= MIN_IDENTIFIED_ITEM_MATCH_SCORE:
            category, item = best_match
            logger.info(
                "店OCR: アイテム名 近似一致 target=%r category=%s item=%s score=%.3f",
                target,
                category,
                item.name,
                best_score,
            )
            return best_match
        if best_match:
            category, item = best_match
            logger.info(
                "店OCR: アイテム名 一致なし target=%r best_category=%s best_item=%s best_score=%.3f threshold=%.3f",
                target,
                category,
                item.name,
                best_score,
                MIN_IDENTIFIED_ITEM_MATCH_SCORE,
            )
        return None

    def normalize_item_match_text(self, text):
        normalized = normalize_ocr_text(text)
        return normalized.replace("力の草", "ちからの草")

    def detect_shop_item_category(self, text):
        target = normalize_ocr_text(text)
        for hint, category in SHOP_CATEGORY_HINTS.items():
            if hint in target:
                logger.info("店OCR: 種別判定 target=%r hint=%s category=%s", target, hint, category)
                return category
        logger.info("店OCR: 種別判定なし target=%r", target)
        return None

    def find_shop_price_candidates(self, category, price, price_kind):
        candidates = []
        for item in self.get_target_items(category):
            if item.get or item.default_get:
                continue
            candidates.extend(self.find_item_price_candidates(item, price, price_kind))
        return candidates

    def find_item_price_candidates(self, item, price, price_kind):
        candidates = []
        for candidate_price, detail in self.iter_item_prices(item, price_kind):
            if candidate_price == price:
                candidates.append((item, detail, ""))
            if candidate_price * 2 == price:
                candidates.append((item, detail, "祝福"))
            if candidate_price * 87 // 100 == price:
                candidates.append((item, detail, "呪い"))
        return candidates

    def iter_item_prices(self, item, price_kind):
        attr = "sell" if price_kind == "sell" else "buy"
        unit_attr = "sell_unit" if price_kind == "sell" else "buy_unit"
        base = getattr(item, attr, 0)
        if item.category.name in ("buki", "tate"):
            unit = EQUIPMENT_SELL_CORRECTION_UNIT if price_kind == "sell" else EQUIPMENT_BUY_CORRECTION_UNIT
            correction_min = -self.get_equipment_base_power(item)
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

    def get_equipment_base_power(self, item):
        try:
            return max(0, int(item.raw_data.get("基礎値", 0)))
        except (TypeError, ValueError):
            return 0

    def format_shop_candidate(self, candidate):
        item, detail, price_state = candidate
        price_state_text = f"({price_state})" if price_state else ""
        return f"{item.name}{detail}{price_state_text}"

    def shop_candidate_payload(self, candidate):
        item, detail, price_state = candidate
        return {
            "name": item.name,
            "category": item.category.name,
            "category_label": ITEM_CATEGORY_LABELS.get(item.category.name, item.category.ja),
            "buy": item.buy,
            "sell": item.sell,
            "detail": detail,
            "price_state": price_state,
            "label": self.format_shop_candidate(candidate),
        }

    def broadcast_shop_price_state(self, result, category, candidates, exact_item=None):
        if not self.websocket_server:
            return

        price_label = "買取価格" if result.price_kind == "sell" else "販売価格"
        category_label = ITEM_CATEGORY_LABELS.get(category, category or "判定不可")
        self.websocket_server.update_shop_price_data({
            "item_text": result.item_text,
            "price": result.price,
            "price_kind": result.price_kind,
            "price_label": price_label,
            "category": category,
            "category_label": category_label,
            "exact_item": exact_item.name if exact_item else "",
            "raw_texts": list(result.raw_texts),
            "candidates": [self.shop_candidate_payload(candidate) for candidate in candidates],
            "updated_at": datetime.datetime.now().strftime("%H:%M:%S"),
        })

    def select_items_in_table(self, category, items):
        table = self.item_tables.get(category)
        if not table:
            return

        self.top_tabs.setCurrentIndex(1)
        self.dungeon_data_tabs.setCurrentIndex(0)
        tab_index = ITEM_CATEGORIES.index(category)
        self.identify_tabs.setCurrentIndex(tab_index)

        table.clearSelection()
        target = self.get_target_items(category)
        selected_rows = []
        for item in items:
            try:
                row = target.index(item)
            except ValueError:
                continue
            for column in range(table.columnCount()):
                cell = table.item(row, column)
                if cell:
                    cell.setSelected(True)
            selected_rows.append(row)
        if selected_rows:
            table.scrollToItem(table.item(selected_rows[0], 0))

    def broadcast_capture_state(self):
        if not self.websocket_server:
            return
        self.websocket_server.update_capture_data(
            {
                "capture_count": self.capture_count,
                "last_capture_time": self.last_capture_time,
                "status": self.capture_status,
                "monitor_source_name": self.config.monitor_source_name,
            }
        )

    def execute_obs_triggers(self, trigger: str):
        """指定されたトリガーのOBS制御を実行"""
        if not self.config.obs_enabled:
            return

        try:
            from src.obs_control import OBSControlData

            control_data = OBSControlData()
            control_data.set_config(self.config)
            settings = control_data.get_settings_by_trigger(trigger)
            if not settings or not self.obs_manager.is_connected:
                return

            for setting in settings:
                try:
                    action = setting["action"]

                    if action == "switch_scene":
                        target_scene = setting.get("scene")
                        if target_scene:
                            self.obs_manager.change_scene(target_scene)

                    elif action in ("show_source", "hide_source"):
                        scene_name = setting.get("scene")
                        source_name = setting.get("source")
                        if scene_name and source_name:
                            mod_scene_name, scene_item_id = self.obs_manager.search_itemid(scene_name, source_name)
                            if scene_item_id:
                                if action == "show_source":
                                    self.obs_manager.enable_source(mod_scene_name, scene_item_id)
                                else:
                                    self.obs_manager.disable_source(mod_scene_name, scene_item_id)

                    elif action == "autosave_source":
                        scene_name = setting.get("scene")
                        source_name = setting.get("source")
                        if scene_name and source_name:
                            _, scene_item_id = self.obs_manager.search_itemid(scene_name, source_name)
                            if scene_item_id:
                                filename = os.path.splitext(source_name)[0]
                                filename += f"_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.png"
                                dst = Path(self.config.image_save_path).resolve() / filename
                                self.obs_manager.save_screenshot_dst(source_name, str(dst), disable_wh=True)
                except Exception as e:
                    logger.error(f"制御実行エラー (trigger: {trigger}, setting: {setting}): {e}")
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"トリガー実行エラー ({trigger}): {e}")

    def closeEvent(self, event):
        self.execute_obs_triggers("app_end")
        self.remove_global_hotkeys()
        self.main_timer.stop()
        self.display_timer.stop()
        if self.capture_worker and self.capture_worker.is_alive():
            self.capture_worker.join(timeout=3.0)
        if self.config.obs_enabled:
            self.obs_manager.disconnect()
        self.save_identification_settings()
        self.save_window_geometry()

        self.stop_websocket_server()

        logger.info("アプリケーション終了")
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.setWindowIcon(QIcon("src/icon.ico"))
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    updater = GitHubUpdater(
        github_author="dj-kata",
        github_repo="siren5_helper",
        zipfile_basename="siren6_helper",
        current_version=SWVER,
        main_exe_name="siren6_helper.exe",
        updator_exe_name="siren6_helper.exe",
    )
    updater.check_and_update()
    main()
