"""
Siren 6 Helper - メインプログラム
OBS連携でゲーム画面を自動取得しながら識別情報を管理するための骨組み。
"""

import asyncio
import datetime
import json
import os
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QIcon
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
        self.show()

        if old_port != self.config.websocket_data_port:
            self.stop_websocket_server()
            self.start_websocket_server()

        if not self.obs_manager.is_connected:
            self.obs_manager.connect()

    def show_about(self):
        QMessageBox.about(
            self,
            self.ui.window.about_title,
            f"Siren 6 Helper {SWVER}\n\nauthor: dj-kata",
        )

    def init_identification_ui(self):
        self.memo_edit.setPlainText(self.siren_settings.params.get("memo", ""))
        self.memo_const_edit.setPlainText(self.siren_settings.params.get("memo_const", ""))
        self.mark_identified_button.clicked.connect(lambda: self.set_selected_items_identified(True))
        self.mark_unknown_button.clicked.connect(lambda: self.set_selected_items_identified(False))
        self.reset_button.clicked.connect(self.reset_identification)
        self.update_item_tables()

    def get_target_items(self, category):
        return getattr(self.itemlist, category)

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
        self.update_item_tables()
        self.statusBar().showMessage("リセットしました", 3000)

    def update_item_tables(self):
        for category in ITEM_CATEGORIES:
            self.update_item_table(category)

        counts = self.get_item_stats()
        for category, (count, total) in counts.items():
            self.item_count_labels[category].setText(f"{count}/{total}")

        self.write_stat_xml(counts)

    def update_item_table(self, category):
        table = self.item_tables[category]
        target = self.get_target_items(category)
        table.setRowCount(len(target))

        previous_buy = target[0].buy if target else None
        is_odd_price_group = False

        for row, item in enumerate(target):
            capacity = ""
            buy = f"{item.buy:,}"
            sell = f"{item.sell:,}"
            if category in ("tue", "tubo", "okou"):
                capacity = str(item.capa_max) if item.capa_min == item.capa_max else f"{item.capa_min}-{item.capa_max}"
                buy = f"{item.buy:,} - {item.buy_max:,}"
                sell = f"{item.sell:,} - {item.sell_max:,}"

            values = [item.name, capacity, buy, sell, item.bin, item.tin, item.memo]

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

        table.resizeRowsToContents()

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
