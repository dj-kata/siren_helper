"""
メインウィンドウUI
OBSから取得したゲーム画面を監視するための最小構成。
"""

import base64
import time

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import keyboard

    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

from src.funcs import load_ui_text
from src.logger import get_logger

logger = get_logger(__name__)


class MainWindowUI(QMainWindow):
    """メインウィンドウのUIレイアウトを担当するクラス"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.ui = load_ui_text(self.config)

        self.obs_status_label = None
        self.capture_status_label = None
        self.uptime_label = None
        self.capture_count_label = None
        self.last_capture_label = None
        self.save_image_button = None
        self.top_tabs = None
        self.dungeon_data_tabs = None
        self.identify_tabs = None
        self.dungeon_combo = None
        self.monster_floor_combo = None
        self.monster_table = None
        self.item_tables = {}
        self.item_count_labels = {}
        self.mark_identified_button = None
        self.mark_unknown_button = None
        self.reset_button = None
        self.memo_edit = None
        self.memo_const_edit = None

    def init_ui(self):
        self.setWindowTitle(self.ui.window.main_title)
        self.restore_window_geometry()
        self.create_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        self.top_tabs = QTabWidget()
        main_layout.addWidget(self.top_tabs)

        obs_tab = QWidget()
        obs_tab_layout = QVBoxLayout(obs_tab)

        obs_group = QGroupBox(self.ui.obs.connection_state)
        obs_layout = QHBoxLayout()
        self.obs_status_label = QLabel(self.ui.obs.not_connected)
        self.obs_status_label.setStyleSheet("color: red; font-weight: bold;")
        obs_layout.addWidget(self.obs_status_label)
        obs_group.setLayout(obs_layout)
        obs_tab_layout.addWidget(obs_group)

        status_group = QGroupBox(self.ui.main.other_info)
        status_layout = QGridLayout()

        status_layout.addWidget(QLabel(self.ui.main.capture_state), 0, 0)
        self.capture_status_label = QLabel(self.ui.main.waiting_capture)
        status_layout.addWidget(self.capture_status_label, 0, 1)

        status_layout.addWidget(QLabel(self.ui.main.ontime), 1, 0)
        self.uptime_label = QLabel("00:00:00")
        status_layout.addWidget(self.uptime_label, 1, 1)

        status_layout.addWidget(QLabel(self.ui.main.capture_count), 2, 0)
        self.capture_count_label = QLabel("0")
        status_layout.addWidget(self.capture_count_label, 2, 1)

        status_layout.addWidget(QLabel(self.ui.main.last_capture), 3, 0)
        self.last_capture_label = QLabel("---")
        self.last_capture_label.setWordWrap(True)
        status_layout.addWidget(self.last_capture_label, 3, 1)

        status_group.setLayout(status_layout)
        obs_tab_layout.addWidget(status_group)

        save_button_layout = QHBoxLayout()
        self.save_image_button = QPushButton(self.ui.main.save_image)
        self.save_image_button.clicked.connect(self.save_image)
        save_button_layout.addWidget(self.save_image_button)
        obs_tab_layout.addLayout(save_button_layout)

        obs_tab_layout.addStretch()
        self.top_tabs.addTab(obs_tab, "OBS")
        self.top_tabs.addTab(self.create_identification_tab(), "ダンジョン")
        self.top_tabs.addTab(self.create_memo_tab(), "メモ")

        self.statusBar().showMessage(self.ui.main.status_ready)

    def create_identification_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        dungeon_layout = QHBoxLayout()
        dungeon_layout.addWidget(QLabel("ダンジョン:"))
        self.dungeon_combo = QComboBox()
        self.dungeon_combo.setMinimumWidth(220)
        dungeon_layout.addWidget(self.dungeon_combo)
        dungeon_layout.addStretch()
        layout.addLayout(dungeon_layout)

        self.dungeon_data_tabs = QTabWidget()
        item_tab = QWidget()
        item_layout = QVBoxLayout(item_tab)

        self.identify_tabs = QTabWidget()
        table_specs = [
            ("kusa", "草"),
            ("makimono", "巻物"),
            ("udewa", "腕輪"),
            ("tubo", "壺"),
            ("okou", "お香"),
            ("tue", "杖"),
            ("buki", "武器(Lv1)"),
            ("tate", "盾(Lv1)"),
        ]
        for key, label in table_specs:
            headers = self.itemlist.get_table_headers(key)
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setWordWrap(False)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
            table.horizontalHeader().setStretchLastSection(True)
            table.setAlternatingRowColors(False)
            table.setSortingEnabled(False)
            for column, header in enumerate(headers):
                width = 220 if header == "簡単な説明" else 90
                if header == "名前":
                    width = 170
                elif header in ("+1", "下限", "上限", "Lv", "基礎値", "印数"):
                    width = 60
                table.setColumnWidth(column, width)
            self.item_tables[key] = table
            self.identify_tabs.addTab(table, label)

        item_layout.addWidget(self.identify_tabs)

        button_layout = QHBoxLayout()
        self.mark_identified_button = QPushButton("識別済にする")
        self.mark_unknown_button = QPushButton("未識別に戻す")
        self.reset_button = QPushButton("リセット")
        button_layout.addWidget(self.mark_identified_button)
        button_layout.addWidget(self.mark_unknown_button)
        button_layout.addStretch()
        button_layout.addWidget(self.reset_button)
        item_layout.addLayout(button_layout)

        count_layout = QHBoxLayout()
        for key, label in [
            ("kusa", "草"),
            ("makimono", "巻物"),
            ("udewa", "腕輪"),
            ("tubo", "壺"),
            ("okou", "お香"),
            ("tue", "杖"),
        ]:
            count_layout.addWidget(QLabel(f"{label}:"))
            count = QLabel("0/0")
            self.item_count_labels[key] = count
            count_layout.addWidget(count)
        count_layout.addStretch()
        item_layout.addLayout(count_layout)

        monster_tab = QWidget()
        monster_layout = QVBoxLayout(monster_tab)
        monster_filter_layout = QHBoxLayout()
        monster_filter_layout.addWidget(QLabel("表示開始階:"))
        self.monster_floor_combo = QComboBox()
        self.monster_floor_combo.setMinimumWidth(100)
        monster_filter_layout.addWidget(self.monster_floor_combo)
        monster_filter_layout.addStretch()
        monster_layout.addLayout(monster_filter_layout)

        self.monster_table = QTableWidget(0, 5)
        self.monster_table.setHorizontalHeaderLabels(["階", "視界", "出現モンスター", "デッ怪", "マゼ種"])
        self.monster_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.monster_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.monster_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.monster_table.setWordWrap(False)
        self.monster_table.verticalHeader().setVisible(False)
        self.monster_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.monster_table.horizontalHeader().setStretchLastSection(True)
        self.monster_table.setColumnWidth(0, 60)
        self.monster_table.setColumnWidth(1, 60)
        self.monster_table.setColumnWidth(2, 520)
        self.monster_table.setColumnWidth(3, 180)
        monster_layout.addWidget(self.monster_table)

        self.dungeon_data_tabs.addTab(item_tab, "アイテム")
        self.dungeon_data_tabs.addTab(monster_tab, "モンスター")
        layout.addWidget(self.dungeon_data_tabs)

        return tab

    def create_memo_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("メモ(冒険用)"))
        self.memo_edit = QPlainTextEdit()
        layout.addWidget(self.memo_edit)

        layout.addWidget(QLabel("メモ(リセット時に削除されない)"))
        self.memo_const_edit = QPlainTextEdit()
        layout.addWidget(self.memo_const_edit)

        return tab

    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu(self.ui.menu.file)

        config_action = QAction(self.ui.menu.base_config, self)
        config_action.triggered.connect(self.open_config_dialog)
        file_menu.addAction(config_action)

        obs_action = QAction(self.ui.menu.obs_config, self)
        obs_action.triggered.connect(self.open_obs_dialog)
        file_menu.addAction(obs_action)

        file_menu.addSeparator()

        save_image_action = QAction(self.ui.menu.save_image, self)
        save_image_action.setShortcut("F6")
        save_image_action.triggered.connect(self.save_image)
        file_menu.addAction(save_image_action)

        file_menu.addSeparator()

        exit_action = QAction(self.ui.menu.exit, self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        language_menu = menubar.addMenu(self.ui.menu.language)
        language_group = QActionGroup(self)
        language_group.setExclusive(True)

        action_ja = QAction(self.ui.menu.japanese, self)
        action_ja.setCheckable(True)
        action_ja.setChecked(self.config.language == "ja")
        action_ja.triggered.connect(lambda: self.change_language("ja"))
        language_group.addAction(action_ja)
        language_menu.addAction(action_ja)

        action_en = QAction(self.ui.menu.english, self)
        action_en.setCheckable(True)
        action_en.setChecked(self.config.language == "en")
        action_en.triggered.connect(lambda: self.change_language("en"))
        language_group.addAction(action_en)
        language_menu.addAction(action_en)

        help_menu = menubar.addMenu(self.ui.menu.help)
        about_action = QAction(self.ui.menu.about, self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def restore_window_geometry(self):
        self.setMinimumSize(900, 600)
        if self.config.main_window_geometry:
            geometry_bytes = base64.b64decode(self.config.main_window_geometry)
            self.restoreGeometry(QByteArray(geometry_bytes))
        else:
            self.setGeometry(
                self.config.main_window_x,
                self.config.main_window_y,
                self.config.main_window_width,
                self.config.main_window_height,
            )

    def save_window_geometry(self):
        geometry_str = base64.b64encode(self.saveGeometry().data()).decode("ascii")
        self.config.main_window_geometry = geometry_str
        self.config.save_config()

    def setup_global_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey("f6", self.save_image, suppress=False)
                logger.info("グローバルホットキー (F6) を登録しました")
            except Exception as e:
                logger.error(f"グローバルホットキー登録エラー: {e}")
        else:
            logger.warning("keyboardライブラリが利用できません。グローバルホットキーは無効です。")

    def remove_global_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.remove_hotkey("f6")
                logger.info("グローバルホットキー (F6) を解除しました")
            except Exception as e:
                logger.error(f"グローバルホットキー解除エラー: {e}")

    def update_display(self):
        try:
            status_msg, is_connected = self.obs_manager.get_status()
            self.obs_status_label.setText(status_msg)
            self.obs_status_label.setStyleSheet(
                "color: green; font-weight: bold;" if is_connected else "color: red; font-weight: bold;"
            )

            elapsed = int(time.time() - self.start_time)
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.uptime_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

            self.capture_count_label.setText(str(self.capture_count))
            self.last_capture_label.setText(self.last_capture_time or "---")
            self.capture_status_label.setText(self.capture_status)
        except Exception:
            logger.exception("表示更新エラー")

    def change_language(self, language: str):
        if language == self.config.language:
            return

        self.config.language = language
        self.config.save_config()

        if language == "en":
            QMessageBox.information(
                self,
                "Language Changed",
                "The new language will be applied when you restart the application.",
            )
        else:
            QMessageBox.information(
                self,
                "言語設定変更",
                "言語設定を変更しました。\n次回起動時に反映されます。",
            )

    def open_config_dialog(self):
        raise NotImplementedError

    def open_obs_dialog(self):
        raise NotImplementedError

    def show_about(self):
        raise NotImplementedError

    def save_image(self):
        raise NotImplementedError
