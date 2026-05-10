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
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
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
from src.funcs import escape_for_filename
from src.item import ItemList
from src.logger import get_logger
from src.main_window import MainWindowUI
from src.obs_dialog import OBSControlDialog
from src.obs_websocket_manager import OBSWebSocketManager
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

        self.websocket_server = None
        self.websocket_loop = None
        self.websocket_thread = None
        self.start_websocket_server()

        self.init_ui()
        self.apply_main_font()
        self.init_identification_ui()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.config.keep_on_top)

        self.obs_manager.connect()
        QTimer.singleShot(1000, self.check_obs_configuration)
        self.execute_obs_triggers("app_start")

        self.main_timer = QTimer()
        self.main_timer.timeout.connect(self.main_loop)
        self.main_timer.start(250)

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
        self.config.load_config()
        self.obs_manager.set_config(self.config)

        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.config.keep_on_top)
        self.apply_main_font()
        if self.item_tables:
            self.update_item_tables()
        self.show()

        if old_port != self.config.websocket_data_port:
            self.stop_websocket_server()
            self.start_websocket_server()
            self.broadcast_monster_floor_state()

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
        self.monster_floor_combo.currentIndexChanged.connect(self.update_monster_table)
        self.reset_monster_floor_filter()

    def on_dungeon_changed(self, *_args):
        self.selected_dungeon_key = self.dungeon_combo.currentData() or ""
        self.reset_monster_floor_filter()
        self.update_item_tables()
        self.update_monster_table()
        name = self.dungeon_combo.currentText()
        if name:
            self.statusBar().showMessage(f"ダンジョンを変更しました: {name}", 3000)

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

    def reset_monster_floor_filter(self):
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
        self.monster_floor_combo.setCurrentIndex(0 if self.monster_floor_combo.count() else -1)
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
        for floor in floors:
            if floor.get("floor") == selected_floor:
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
        selected_floor = self.monster_floor_combo.currentData() if self.monster_floor_combo else 1
        if not isinstance(selected_floor, int):
            selected_floor = 1
        floor = self.selected_monster_floor()

        groups = [
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

        return {
            "dungeon_key": dungeon.get("key", "") if dungeon else "",
            "dungeon_name": dungeon.get("name", "") if dungeon else "",
            "floor": selected_floor,
            "floor_label": self.format_floor_label(selected_floor),
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
            if not self.obs_manager.is_connected or not self.config.monitor_source_name:
                self.capture_status = self.ui.main.waiting_capture
                return

            self.obs_manager.screenshot()
            if self.obs_manager.screen is None:
                self.capture_status = self.ui.main.capture_failed
                return

            self.latest_screen = self.obs_manager.screen
            self.capture_count += 1
            self.last_capture_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.capture_status = self.ui.main.capture_ok
            self.broadcast_capture_state()
        except Exception:
            logger.error(f"メインループエラー: {traceback.format_exc()}")

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
        self.obs_manager.disconnect()
        self.save_identification_settings()
        self.save_window_geometry()

        self.main_timer.stop()
        self.display_timer.stop()
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
