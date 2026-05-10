"""
設定ダイアログ
Configに残っている共通設定だけを編集する。
"""

import os

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.funcs import load_ui_text
from src.logger import get_logger

logger = get_logger(__name__)


class ConfigDialog(QDialog):
    """基本設定ダイアログ"""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.ui = load_ui_text(config)

        self.setWindowTitle(self.ui.window.settings_title)
        self.setMinimumWidth(520)

        self.init_ui()
        self.load_config_values()

    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        tab_widget = QTabWidget()
        tab_widget.addTab(self.create_general_tab(), self.ui.tab.feature)
        layout.addWidget(tab_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def create_general_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        general_group = QGroupBox(self.ui.feature.other_group)
        form = QFormLayout()
        general_group.setLayout(form)

        self.image_save_path_edit = QLineEdit()
        browse_button = QPushButton(self.ui.dialog.browse)
        browse_button.clicked.connect(self.on_browse_clicked)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.image_save_path_edit)
        path_layout.addWidget(browse_button)
        form.addRow(self.ui.feature.image_save_path, path_layout)

        self.websocket_data_port_edit = QLineEdit()
        self.websocket_data_port_edit.setValidator(QIntValidator(1000, 65535))
        form.addRow(self.ui.feature.websocket_port, self.websocket_data_port_edit)

        self.obs_enabled_check = QCheckBox(self.ui.feature.obs_enabled)
        form.addRow(self.obs_enabled_check)

        self.keep_on_top_check = QCheckBox(self.ui.feature.keep_on_top)
        form.addRow(self.keep_on_top_check)

        self.main_font_size_spin = QSpinBox()
        self.main_font_size_spin.setRange(8, 24)
        self.main_font_size_spin.setSuffix(" pt")
        form.addRow(self.ui.feature.main_font_size, self.main_font_size_spin)

        layout.addWidget(general_group)
        layout.addStretch()
        return widget

    def on_browse_clicked(self):
        current_dir = self.image_save_path_edit.text()
        if not os.path.exists(current_dir):
            current_dir = os.path.expanduser("~")

        dir_path = QFileDialog.getExistingDirectory(
            self, self.ui.dialog.select_image_path, current_dir
        )
        if dir_path:
            self.image_save_path_edit.setText(dir_path)

    def load_config_values(self):
        self.image_save_path_edit.setText(self.config.image_save_path)
        self.websocket_data_port_edit.setText(str(self.config.websocket_data_port))
        self.obs_enabled_check.setChecked(self.config.obs_enabled)
        self.keep_on_top_check.setChecked(self.config.keep_on_top)
        self.main_font_size_spin.setValue(self.config.main_font_size)

    def accept(self):
        self.config.image_save_path = self.image_save_path_edit.text().strip() or "captures"
        try:
            port = int(self.websocket_data_port_edit.text())
            if 1000 <= port <= 65535:
                self.config.websocket_data_port = port
        except ValueError:
            logger.warning("ポート番号の変換に失敗しました。既存値を使用します")

        self.config.obs_enabled = self.obs_enabled_check.isChecked()
        self.config.keep_on_top = self.keep_on_top_check.isChecked()
        self.config.main_font_size = self.main_font_size_spin.value()
        self.config.save_config()
        logger.info("設定を保存しました")
        super().accept()
