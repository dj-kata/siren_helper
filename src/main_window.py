"""
メインウィンドウUI
OBSから取得したゲーム画面を監視するための最小構成。
"""

import base64

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QActionGroup, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QRadioButton,
    QSplitter,
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
from src.config import CAPTURE_MODE_DIRECT, CAPTURE_MODE_FULLSCREEN, CAPTURE_MODE_OBS

logger = get_logger(__name__)


class MainWindowUI(QMainWindow):
    """メインウィンドウのUIレイアウトを担当するクラス"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.ui = load_ui_text(self.config)

        self.obs_status_label = None
        self.top_tabs = None
        self.dungeon_data_tabs = None
        self.identify_tabs = None
        self.item_monster_identify_tabs = None
        self.dungeon_combo = None
        self.monster_floor_combo = None
        self.monster_table_wrap_checkbox = None
        self.monster_table_icon_only_checkbox = None
        self.monster_table_icon_size_combo = None
        self.monster_table = None
        self.item_monster_monster_table = None
        self.shop_candidate_table = None
        self.item_tables = {}
        self.item_monster_item_tables = {}
        self.item_count_labels = {}
        self.item_monster_item_count_labels = {}
        self.mark_identified_button = None
        self.mark_unknown_button = None
        self.item_monster_mark_identified_button = None
        self.item_monster_mark_unknown_button = None
        self.manual_shop_category_combo = None
        self.manual_shop_price_edit = None
        self.manual_shop_price_kind_group = None
        self.manual_shop_price_kind_none = None
        self.manual_shop_price_kind_buy = None
        self.manual_shop_price_kind_sell = None
        self.manual_shop_name_edit = None
        self.manual_shop_add_button = None
        self.item_monster_manual_shop_category_combo = None
        self.item_monster_manual_shop_price_edit = None
        self.item_monster_manual_shop_price_kind_group = None
        self.item_monster_manual_shop_price_kind_none = None
        self.item_monster_manual_shop_price_kind_buy = None
        self.item_monster_manual_shop_price_kind_sell = None
        self.item_monster_manual_shop_name_edit = None
        self.item_monster_manual_shop_add_button = None
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

        main_layout.addWidget(self.create_identification_tab())

        self.obs_status_label = QLabel(self.ui.obs.not_connected)
        self.update_obs_status_label(False)
        self.statusBar().addPermanentWidget(self.obs_status_label)
        self.statusBar().showMessage(self.ui.main.status_ready)

    def update_obs_status_label(self, is_connected: bool):
        if self.config.capture_mode == CAPTURE_MODE_OBS:
            status = self.ui.obs.connected if is_connected else self.ui.obs.not_connected
            color = "green" if is_connected else "red"
            self.obs_status_label.setText(f"OBS: {status}")
        elif self.config.capture_mode == CAPTURE_MODE_DIRECT:
            color = "green"
            self.obs_status_label.setText(f"取得: {self.ui.feature.capture_mode_direct}")
        elif self.config.capture_mode == CAPTURE_MODE_FULLSCREEN:
            color = "green"
            self.obs_status_label.setText(f"取得: {self.ui.feature.capture_mode_fullscreen}")
        else:
            color = "gray"
            self.obs_status_label.setText(f"取得: {self.ui.feature.capture_mode_none}")
        self.obs_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def create_identification_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        dungeon_layout = QHBoxLayout()
        dungeon_layout.addWidget(QLabel("ダンジョン:"))
        self.dungeon_combo = QComboBox()
        self.dungeon_combo.setMinimumWidth(220)
        dungeon_layout.addWidget(self.dungeon_combo)
        dungeon_layout.addWidget(QLabel("表示開始階:"))
        self.monster_floor_combo = QComboBox()
        self.monster_floor_combo.setMinimumWidth(100)
        dungeon_layout.addWidget(self.monster_floor_combo)
        self.reset_button = QPushButton("リセット")
        dungeon_layout.addWidget(self.reset_button)
        self.monster_table_wrap_checkbox = QCheckBox("多段表示")
        dungeon_layout.addWidget(self.monster_table_wrap_checkbox)
        self.monster_table_icon_only_checkbox = QCheckBox("アイコンのみ")
        dungeon_layout.addWidget(self.monster_table_icon_only_checkbox)
        dungeon_layout.addWidget(QLabel("アイコンサイズ:"))
        self.monster_table_icon_size_combo = QComboBox()
        self.monster_table_icon_size_combo.addItem("小", "small")
        self.monster_table_icon_size_combo.addItem("中", "medium")
        self.monster_table_icon_size_combo.addItem("大", "large")
        self.monster_table_icon_size_combo.setMaximumWidth(70)
        dungeon_layout.addWidget(self.monster_table_icon_size_combo)
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
            table = self.create_item_table(key)
            self.item_tables[key] = table
            self.identify_tabs.addTab(table, label)

        item_layout.addWidget(self.identify_tabs)

        button_layout = QHBoxLayout()
        self.mark_identified_button = QPushButton("識別済にする")
        self.mark_unknown_button = QPushButton("未識別に戻す")
        button_layout.addWidget(self.mark_identified_button)
        button_layout.addWidget(self.mark_unknown_button)
        button_layout.addStretch()
        item_layout.addLayout(button_layout)

        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("手動サーチ:"))
        self.manual_shop_category_combo = QComboBox()
        for key, label in [
            ("kusa", "草"),
            ("makimono", "巻物"),
            ("udewa", "腕輪"),
            ("tubo", "壺"),
            ("okou", "お香"),
            ("tue", "杖"),
        ]:
            self.manual_shop_category_combo.addItem(label, key)
        manual_layout.addWidget(self.manual_shop_category_combo)
        manual_layout.addWidget(QLabel("値段:"))
        self.manual_shop_price_edit = QLineEdit()
        self.manual_shop_price_edit.setValidator(QIntValidator(0, 999999))
        self.manual_shop_price_edit.setPlaceholderText("G")
        self.manual_shop_price_edit.setMaximumWidth(110)
        manual_layout.addWidget(self.manual_shop_price_edit)
        manual_layout.addWidget(QLabel("価格種別:"))
        self.manual_shop_price_kind_group = QButtonGroup(self)
        self.manual_shop_price_kind_none = QRadioButton("指定なし")
        self.manual_shop_price_kind_buy = QRadioButton("買値")
        self.manual_shop_price_kind_sell = QRadioButton("売値")
        self.manual_shop_price_kind_none.setChecked(True)
        for button, price_kind in [
            (self.manual_shop_price_kind_none, "manual"),
            (self.manual_shop_price_kind_buy, "buy"),
            (self.manual_shop_price_kind_sell, "sell"),
        ]:
            self.manual_shop_price_kind_group.addButton(button)
            button.setProperty("price_kind", price_kind)
            manual_layout.addWidget(button)
        manual_layout.addWidget(QLabel("未識別名:"))
        self.manual_shop_name_edit = QLineEdit()
        self.manual_shop_name_edit.setMaximumWidth(180)
        manual_layout.addWidget(self.manual_shop_name_edit)
        self.manual_shop_add_button = QPushButton("識別候補に追加")
        manual_layout.addWidget(self.manual_shop_add_button)
        manual_layout.addStretch()
        item_layout.addLayout(manual_layout)

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

        self.monster_table = self.create_monster_table()
        monster_layout.addWidget(self.monster_table)

        self.dungeon_data_tabs.addTab(item_tab, "アイテム")
        self.dungeon_data_tabs.addTab(monster_tab, "モンスター")
        self.dungeon_data_tabs.addTab(self.create_item_monster_tab(table_specs), "アイテム+モンスター")

        candidate_tab = QWidget()
        candidate_layout = QVBoxLayout(candidate_tab)
        self.shop_candidate_table = QTableWidget(0, 3)
        self.shop_candidate_table.setHorizontalHeaderLabels(["未識別名", "種別", "候補"])
        self.shop_candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.shop_candidate_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.shop_candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.shop_candidate_table.setWordWrap(False)
        self.shop_candidate_table.verticalHeader().setVisible(False)
        self.shop_candidate_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.shop_candidate_table.horizontalHeader().setStretchLastSection(True)
        self.shop_candidate_table.setColumnWidth(0, 170)
        self.shop_candidate_table.setColumnWidth(1, 70)
        candidate_layout.addWidget(self.shop_candidate_table)
        self.dungeon_data_tabs.addTab(candidate_tab, "識別候補")
        self.dungeon_data_tabs.addTab(self.create_memo_tab(), "メモ")
        layout.addWidget(self.dungeon_data_tabs)

        return tab

    def create_item_table(self, key):
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
            elif header in ("異種", "異種合成"):
                width = 270
            elif header in ("+1", "下限", "上限", "Lv", "基礎値", "印数"):
                width = 60
            table.setColumnWidth(column, width)
        return table

    def create_monster_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["階", "出現モンスター", "デッ怪", "マゼ種"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 60)
        table.setColumnWidth(1, 520)
        table.setColumnWidth(2, 180)
        return table

    def create_item_monster_tab(self, table_specs):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        item_panel = QWidget()
        item_layout = QVBoxLayout(item_panel)
        item_layout.setContentsMargins(0, 0, 6, 0)
        self.item_monster_identify_tabs = QTabWidget()
        for key, label in table_specs:
            table = self.create_item_table(key)
            self.item_monster_item_tables[key] = table
            self.item_monster_identify_tabs.addTab(table, label)
        item_layout.addWidget(self.item_monster_identify_tabs)

        button_layout = QHBoxLayout()
        self.item_monster_mark_identified_button = QPushButton("識別済にする")
        self.item_monster_mark_unknown_button = QPushButton("未識別に戻す")
        button_layout.addWidget(self.item_monster_mark_identified_button)
        button_layout.addWidget(self.item_monster_mark_unknown_button)
        button_layout.addStretch()
        item_layout.addLayout(button_layout)

        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("手動サーチ:"))
        self.item_monster_manual_shop_category_combo = QComboBox()
        for key, label in [
            ("kusa", "草"),
            ("makimono", "巻物"),
            ("udewa", "腕輪"),
            ("tubo", "壺"),
            ("okou", "お香"),
            ("tue", "杖"),
        ]:
            self.item_monster_manual_shop_category_combo.addItem(label, key)
        manual_layout.addWidget(self.item_monster_manual_shop_category_combo)
        manual_layout.addWidget(QLabel("値段:"))
        self.item_monster_manual_shop_price_edit = QLineEdit()
        self.item_monster_manual_shop_price_edit.setValidator(QIntValidator(0, 999999))
        self.item_monster_manual_shop_price_edit.setPlaceholderText("G")
        self.item_monster_manual_shop_price_edit.setMaximumWidth(110)
        manual_layout.addWidget(self.item_monster_manual_shop_price_edit)
        manual_layout.addWidget(QLabel("価格種別:"))
        self.item_monster_manual_shop_price_kind_group = QButtonGroup(self)
        self.item_monster_manual_shop_price_kind_none = QRadioButton("指定なし")
        self.item_monster_manual_shop_price_kind_buy = QRadioButton("買値")
        self.item_monster_manual_shop_price_kind_sell = QRadioButton("売値")
        self.item_monster_manual_shop_price_kind_none.setChecked(True)
        for button, price_kind in [
            (self.item_monster_manual_shop_price_kind_none, "manual"),
            (self.item_monster_manual_shop_price_kind_buy, "buy"),
            (self.item_monster_manual_shop_price_kind_sell, "sell"),
        ]:
            self.item_monster_manual_shop_price_kind_group.addButton(button)
            button.setProperty("price_kind", price_kind)
            manual_layout.addWidget(button)
        manual_layout.addWidget(QLabel("未識別名:"))
        self.item_monster_manual_shop_name_edit = QLineEdit()
        self.item_monster_manual_shop_name_edit.setMaximumWidth(180)
        manual_layout.addWidget(self.item_monster_manual_shop_name_edit)
        self.item_monster_manual_shop_add_button = QPushButton("識別候補に追加")
        manual_layout.addWidget(self.item_monster_manual_shop_add_button)
        manual_layout.addStretch()
        item_layout.addLayout(manual_layout)

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
            self.item_monster_item_count_labels[key] = count
            count_layout.addWidget(count)
        count_layout.addStretch()
        item_layout.addLayout(count_layout)

        monster_panel = QWidget()
        monster_layout = QVBoxLayout(monster_panel)
        monster_layout.setContentsMargins(6, 0, 0, 0)
        self.item_monster_monster_table = self.create_monster_table()
        monster_layout.addWidget(self.item_monster_monster_table)

        splitter.addWidget(item_panel)
        splitter.addWidget(monster_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
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
        self.ensure_window_visible()

    def ensure_window_visible(self):
        frame = self.frameGeometry()
        screens = QApplication.screens()
        if any(screen.availableGeometry().intersects(frame) for screen in screens):
            return

        screen = QApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def save_window_geometry(self):
        geometry_str = base64.b64encode(self.saveGeometry().data()).decode("ascii")
        self.config.main_window_geometry = geometry_str
        self.config.save_config()

    def setup_global_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                hotkeys = {
                    "f6": self.save_image,
                    "ctrl+shift+alt+p": lambda: self.global_hotkey_pressed.emit("item_tab_next"),
                    "ctrl+shift+alt+n": lambda: self.global_hotkey_pressed.emit("item_tab_previous"),
                    "ctrl+shift+alt+d": lambda: self.global_hotkey_pressed.emit("item_scroll_down"),
                    "ctrl+shift+alt+u": lambda: self.global_hotkey_pressed.emit("item_scroll_up"),
                }
                for hotkey, callback in hotkeys.items():
                    keyboard.add_hotkey(hotkey, callback, suppress=False)
                logger.info("グローバルホットキーを登録しました: " + ", ".join(hotkeys.keys()))
            except Exception as e:
                logger.error(f"グローバルホットキー登録エラー: {e}")
        else:
            logger.warning("keyboardライブラリが利用できません。グローバルホットキーは無効です。")

    def remove_global_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                for hotkey in (
                    "f6",
                    "ctrl+shift+alt+p",
                    "ctrl+shift+alt+n",
                    "ctrl+shift+alt+d",
                    "ctrl+shift+alt+u",
                ):
                    keyboard.remove_hotkey(hotkey)
                logger.info("グローバルホットキーを解除しました")
            except Exception as e:
                logger.error(f"グローバルホットキー解除エラー: {e}")

    def update_display(self):
        try:
            self.update_obs_status_label(self.obs_manager.is_connected)
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
