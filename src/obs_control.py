"""
OBS制御設定データ
OBS制御設定ダイアログで保存した設定を、アプリ本体から実行するための薄いラッパー。
"""

import json
import os
from typing import Any

from src.config import Config


class OBSControlData:
    """OBS制御設定のデータ管理クラス"""

    def __init__(self):
        self.config = None

    def set_config(self, config: Config):
        self.config = config

    def add_setting(self, setting: dict[str, Any]):
        self.config.obs_control_settings.append(setting)
        self.config.save_config()

    def remove_setting(self, index: int):
        if 0 <= index < len(self.config.obs_control_settings):
            del self.config.obs_control_settings[index]
            self.config.save_config()

    def get_settings_by_trigger(self, trigger: str) -> list[dict[str, Any]]:
        if not self.config:
            return []
        return [
            setting
            for setting in self.config.obs_control_settings
            if setting.get("timing") == trigger
        ]

    def set_monitor_source(self, source_name: str):
        self.config.monitor_source_name = source_name
        self.config.save_config()

    def get_monitor_source(self) -> str:
        return self.config.monitor_source_name if self.config else ""

    @staticmethod
    def get_monitor_source_name(config_file="config.json") -> str:
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("monitor_source_name", "")
            except Exception:
                return ""
        return ""
