import json
import os
import traceback

from src.logger import get_logger

logger = get_logger(__name__)


def clamp_int(value, default, minimum, maximum):
    try:
        return min(max(int(value), minimum), maximum)
    except (TypeError, ValueError):
        return default


class Config:
    """アプリ設定を管理するクラス"""

    def __init__(self, config_file="config.json"):
        self.config_file = config_file

        # OBS WebSocket
        self.websocket_host = "localhost"
        self.websocket_port = 4444
        self.websocket_password = ""

        # ウィンドウ
        self.main_window_geometry = None
        self.main_window_x = 100
        self.main_window_y = 100
        self.main_window_width = 500
        self.main_window_height = 300
        self.keep_on_top = False
        self.main_font_size = 10

        # OBS自動制御
        self.obs_control_settings = []
        self.monitor_source_name = ""
        self.obs_scene_collection = ""

        # 画像保存
        self.image_save_path = "captures"

        # WebSocketデータ配信
        self.websocket_data_port = 8767

        # UI
        self.language = "ja"

        self.load_config()
        self.save_config()

    def load_config(self):
        """設定ファイルから設定を読み込む"""
        if not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            self.websocket_host = config_data.get("websocket_host", self.websocket_host)
            self.websocket_port = config_data.get("websocket_port", self.websocket_port)
            self.websocket_password = config_data.get("websocket_password", self.websocket_password)
            self.keep_on_top = config_data.get("keep_on_top", self.keep_on_top)
            self.main_window_geometry = config_data.get("main_window_geometry", self.main_window_geometry)
            self.main_font_size = clamp_int(
                config_data.get("main_font_size", self.main_font_size),
                self.main_font_size,
                8,
                24,
            )

            window_config = config_data.get("window", {})
            self.main_window_x = window_config.get("x", self.main_window_x)
            self.main_window_y = window_config.get("y", self.main_window_y)
            self.main_window_width = window_config.get("width", self.main_window_width)
            self.main_window_height = window_config.get("height", self.main_window_height)

            self.obs_control_settings = config_data.get("obs_control_settings", self.obs_control_settings)
            self.monitor_source_name = config_data.get("monitor_source_name", self.monitor_source_name)
            self.obs_scene_collection = config_data.get("obs_scene_collection", self.obs_scene_collection)
            self.image_save_path = config_data.get("image_save_path", self.image_save_path)
            self.websocket_data_port = config_data.get("websocket_data_port", self.websocket_data_port)
            self.language = config_data.get("language", self.language)
        except Exception as e:
            logger.error(traceback.format_exc())
            print(f"設定ファイル読み込みエラー: {e}")

    def save_config(self):
        """設定ファイルに設定を保存する"""
        config_data = {
            "websocket_host": self.websocket_host,
            "websocket_port": self.websocket_port,
            "websocket_password": self.websocket_password,
            "keep_on_top": self.keep_on_top,
            "main_window_geometry": self.main_window_geometry,
            "main_font_size": self.main_font_size,
            "window": {
                "x": self.main_window_x,
                "y": self.main_window_y,
                "width": self.main_window_width,
                "height": self.main_window_height,
            },
            "obs_control_settings": self.obs_control_settings,
            "monitor_source_name": self.monitor_source_name,
            "obs_scene_collection": self.obs_scene_collection,
            "image_save_path": self.image_save_path,
            "websocket_data_port": self.websocket_data_port,
            "language": self.language,
        }

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(traceback.format_exc())
            print(f"設定ファイル保存エラー: {e}")

    def save_window_position(self, x, y, width, height):
        """ウィンドウ位置を保存"""
        self.main_window_x = x
        self.main_window_y = y
        self.main_window_width = width
        self.main_window_height = height
        self.save_config()

    def __str__(self):
        return json.dumps(
            {
                "websocket_host": self.websocket_host,
                "websocket_port": self.websocket_port,
                "monitor_source_name": self.monitor_source_name,
                "obs_scene_collection": self.obs_scene_collection,
                "image_save_path": self.image_save_path,
                "websocket_data_port": self.websocket_data_port,
                "language": self.language,
            },
            ensure_ascii=False,
            indent=2,
        )
