import json
import os
import traceback

from src.logger import get_logger, set_debug_logging_enabled
from src.voice_guidance import VOICE_DEFAULTS

logger = get_logger(__name__)

CAPTURE_MODE_NONE = "none"
CAPTURE_MODE_OBS = "obs"
CAPTURE_MODE_DIRECT = "direct"
CAPTURE_MODE_FULLSCREEN = "fullscreen"
CAPTURE_MODE_SPOUT = "spout"
DEFAULT_SPOUT_SENDER_NAME = "Spout_OBS_Filter"
CAPTURE_MODES = (
    CAPTURE_MODE_NONE,
    CAPTURE_MODE_OBS,
    CAPTURE_MODE_DIRECT,
    CAPTURE_MODE_FULLSCREEN,
    CAPTURE_MODE_SPOUT,
)
CAPTURE_RESOLUTION_FULLHD = "1920x1080"
CAPTURE_RESOLUTION_HALFHD = "960x540"
CAPTURE_RESOLUTIONS = (CAPTURE_RESOLUTION_HALFHD,)
CAPTURE_RESOLUTION_SIZES = {
    CAPTURE_RESOLUTION_FULLHD: (1920, 1080),
    CAPTURE_RESOLUTION_HALFHD: (960, 540),
}
OCR_CAPTURE_RESOLUTION = CAPTURE_RESOLUTION_HALFHD
OCR_CAPTURE_SIZE = CAPTURE_RESOLUTION_SIZES[OCR_CAPTURE_RESOLUTION]
IMAGE_SAVE_FORMAT_PNG = "png"
IMAGE_SAVE_FORMAT_JPG = "jpg"
IMAGE_SAVE_FORMATS = (IMAGE_SAVE_FORMAT_PNG, IMAGE_SAVE_FORMAT_JPG)
IMAGE_SAVE_JPEG_QUALITY = 70
AUTO_CAPTURE_FLOOR_INTERVAL_ALL = "all"
AUTO_CAPTURE_FLOOR_INTERVAL_5 = "5"
AUTO_CAPTURE_FLOOR_INTERVAL_10 = "10"
AUTO_CAPTURE_FLOOR_INTERVAL_25 = "25"
AUTO_CAPTURE_FLOOR_INTERVALS = (
    AUTO_CAPTURE_FLOOR_INTERVAL_ALL,
    AUTO_CAPTURE_FLOOR_INTERVAL_5,
    AUTO_CAPTURE_FLOOR_INTERVAL_10,
    AUTO_CAPTURE_FLOOR_INTERVAL_25,
)
ALERT_OUTPUT_SOUND = "sound"
ALERT_OUTPUT_VOICEVOX = "voicevox"
ALERT_OUTPUTS = (ALERT_OUTPUT_SOUND, ALERT_OUTPUT_VOICEVOX)


def clamp_int(value, default, minimum, maximum):
    try:
        return min(max(int(value), minimum), maximum)
    except (TypeError, ValueError):
        return default


def clamp_float(value, default, minimum, maximum):
    try:
        return min(max(float(value), minimum), maximum)
    except (TypeError, ValueError):
        return default


class Config:
    """アプリ設定を管理するクラス"""

    def __init__(self, config_file="config.json"):
        self.config_file = config_file

        # OBS WebSocket
        self.obs_enabled = False
        self.capture_mode = CAPTURE_MODE_NONE
        self.spout_sender_name = DEFAULT_SPOUT_SENDER_NAME
        self.websocket_host = "localhost"
        self.websocket_port = 4444
        self.websocket_password = ""

        # ウィンドウ
        self.main_window_geometry = None
        self.main_window_x = 100
        self.main_window_y = 100
        self.main_window_width = 700
        self.main_window_height = 500
        self.keep_on_top = False
        self.main_font_size = 12
        self.game_overlay_enabled = False
        self.game_overlay_monsters_enabled = True
        self.game_overlay_shop_price_enabled = True
        self.game_overlay_alerts_enabled = True

        # OBS自動制御
        self.obs_control_settings = []
        self.monitor_source_name = ""
        self.obs_scene_collection = ""
        self.obs_capture_interval_seconds = 1.0
        self.capture_resolution = OCR_CAPTURE_RESOLUTION

        # 画像保存
        self.image_save_path = "captures"
        self.image_save_format = IMAGE_SAVE_FORMAT_PNG
        self.auto_capture_enabled = False
        self.auto_capture_on_floor_change = False
        self.auto_capture_floor_interval = AUTO_CAPTURE_FLOOR_INTERVAL_ALL
        self.auto_capture_on_adventure_result = False

        # WebSocketデータ配信
        self.websocket_data_port = 8767

        # HTTPブラウザ表示
        self.http_server_enabled = False
        self.http_server_host = "0.0.0.0"
        self.http_server_port = 8787
        self.http_server_interface = ""

        # UI
        self.language = "ja"
        self.debug_mode = False
        self.dungeon_ocr_enabled = True
        self.shop_ocr_enabled = True
        self.dosukoi_alert_enabled = False
        self.alert_output = ALERT_OUTPUT_SOUND
        self.dosukoi_alert_volume = 100
        self.dosukoi_alert_threshold = 130
        self.entou_alert_enabled = False
        for key, default in VOICE_DEFAULTS.items():
            setattr(self, key, default)

        self.load_config()
        set_debug_logging_enabled(self.debug_mode)
        self.save_config()

    def load_config(self):
        """設定ファイルから設定を読み込む"""
        if not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            legacy_obs_enabled = bool(config_data.get("obs_enabled", self.obs_enabled))
            capture_mode = config_data.get("capture_mode")
            if capture_mode not in CAPTURE_MODES:
                capture_mode = CAPTURE_MODE_OBS if legacy_obs_enabled else CAPTURE_MODE_NONE
            self.capture_mode = capture_mode
            self.spout_sender_name = str(config_data.get("spout_sender_name") or "").strip() or DEFAULT_SPOUT_SENDER_NAME
            self.obs_enabled = self.capture_mode == CAPTURE_MODE_OBS
            self.websocket_host = config_data.get("websocket_host", self.websocket_host)
            self.websocket_port = config_data.get("websocket_port", self.websocket_port)
            self.websocket_password = config_data.get("websocket_password", self.websocket_password)
            self.keep_on_top = config_data.get("keep_on_top", self.keep_on_top)
            self.game_overlay_enabled = bool(
                config_data.get("game_overlay_enabled", self.game_overlay_enabled)
            )
            self.game_overlay_monsters_enabled = bool(
                config_data.get(
                    "game_overlay_monsters_enabled",
                    self.game_overlay_monsters_enabled,
                )
            )
            self.game_overlay_shop_price_enabled = bool(
                config_data.get(
                    "game_overlay_shop_price_enabled",
                    self.game_overlay_shop_price_enabled,
                )
            )
            self.game_overlay_alerts_enabled = bool(
                config_data.get(
                    "game_overlay_alerts_enabled",
                    self.game_overlay_alerts_enabled,
                )
            )
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
            self.obs_capture_interval_seconds = clamp_float(
                config_data.get("obs_capture_interval_seconds", self.obs_capture_interval_seconds),
                self.obs_capture_interval_seconds,
                1.0,
                30.0,
            )
            capture_resolution = config_data.get("capture_resolution", self.capture_resolution)
            if capture_resolution not in CAPTURE_RESOLUTIONS:
                capture_resolution = OCR_CAPTURE_RESOLUTION
            self.capture_resolution = capture_resolution
            self.image_save_path = config_data.get("image_save_path", self.image_save_path)
            image_save_format = config_data.get("image_save_format", self.image_save_format)
            if image_save_format not in IMAGE_SAVE_FORMATS:
                image_save_format = IMAGE_SAVE_FORMAT_PNG
            self.image_save_format = image_save_format
            self.auto_capture_enabled = bool(
                config_data.get("auto_capture_enabled", self.auto_capture_enabled)
            )
            self.auto_capture_on_floor_change = bool(
                config_data.get(
                    "auto_capture_on_floor_change",
                    self.auto_capture_on_floor_change,
                )
            )
            auto_capture_floor_interval = config_data.get(
                "auto_capture_floor_interval",
                self.auto_capture_floor_interval,
            )
            if auto_capture_floor_interval not in AUTO_CAPTURE_FLOOR_INTERVALS:
                auto_capture_floor_interval = AUTO_CAPTURE_FLOOR_INTERVAL_ALL
            self.auto_capture_floor_interval = auto_capture_floor_interval
            self.auto_capture_on_adventure_result = bool(
                config_data.get(
                    "auto_capture_on_adventure_result",
                    self.auto_capture_on_adventure_result,
                )
            )
            self.websocket_data_port = config_data.get("websocket_data_port", self.websocket_data_port)
            self.http_server_enabled = bool(
                config_data.get("http_server_enabled", self.http_server_enabled)
            )
            self.http_server_host = config_data.get("http_server_host", self.http_server_host)
            self.http_server_port = clamp_int(
                config_data.get("http_server_port", self.http_server_port),
                self.http_server_port,
                1000,
                65535,
            )
            self.http_server_interface = config_data.get(
                "http_server_interface", self.http_server_interface
            )
            self.language = config_data.get("language", self.language)
            self.debug_mode = bool(config_data.get("debug_mode", self.debug_mode))
            self.dungeon_ocr_enabled = bool(
                config_data.get("dungeon_ocr_enabled", self.dungeon_ocr_enabled)
            )
            self.shop_ocr_enabled = bool(
                config_data.get("shop_ocr_enabled", self.shop_ocr_enabled)
            )
            self.dosukoi_alert_enabled = bool(
                config_data.get("dosukoi_alert_enabled", self.dosukoi_alert_enabled)
            )
            alert_output = config_data.get("alert_output", self.alert_output)
            self.alert_output = (
                alert_output if alert_output in ALERT_OUTPUTS else ALERT_OUTPUT_SOUND
            )
            self.dosukoi_alert_volume = clamp_int(
                config_data.get("dosukoi_alert_volume", self.dosukoi_alert_volume),
                self.dosukoi_alert_volume,
                0,
                100,
            )
            self.dosukoi_alert_threshold = clamp_int(
                config_data.get("dosukoi_alert_threshold", self.dosukoi_alert_threshold),
                self.dosukoi_alert_threshold,
                120,
                200,
            )
            self.entou_alert_enabled = bool(
                config_data.get("entou_alert_enabled", self.entou_alert_enabled)
            )
            self.voice_startup = bool(
                config_data.get("voice_startup", self.voice_startup)
            )
            self.voice_shutdown = bool(
                config_data.get("voice_shutdown", self.voice_shutdown)
            )
            self.voice_errors = bool(
                config_data.get("voice_errors", self.voice_errors)
            )
            self.voice_dosukoi_alert = bool(
                config_data.get("voice_dosukoi_alert", self.voice_dosukoi_alert)
            )
            self.voice_entou_alert = bool(
                config_data.get("voice_entou_alert", self.voice_entou_alert)
            )
            self.voice_capture_saved = bool(
                config_data.get("voice_capture_saved", self.voice_capture_saved)
            )
            self.voice_shop_price = bool(
                config_data.get("voice_shop_price", self.voice_shop_price)
            )
            self.voicevox_url = (
                str(config_data.get("voicevox_url", self.voicevox_url)).strip()
                or VOICE_DEFAULTS["voicevox_url"]
            )
            self.voicevox_speaker_id = clamp_int(
                config_data.get("voicevox_speaker_id", self.voicevox_speaker_id),
                self.voicevox_speaker_id,
                0,
                2147483647,
            )
            self.voicevox_timeout_seconds = clamp_int(
                config_data.get(
                    "voicevox_timeout_seconds",
                    self.voicevox_timeout_seconds,
                ),
                self.voicevox_timeout_seconds,
                1,
                300,
            )
            self.voice_output_device = str(
                config_data.get("voice_output_device", self.voice_output_device) or ""
            )
            self.voice_volume = clamp_int(
                config_data.get("voice_volume", self.voice_volume),
                self.voice_volume,
                0,
                100,
            )
            self.voice_pan = clamp_int(
                config_data.get("voice_pan", self.voice_pan),
                self.voice_pan,
                -100,
                100,
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            print(f"設定ファイル読み込みエラー: {e}")

    def save_config(self):
        """設定ファイルに設定を保存する"""
        if self.capture_mode not in CAPTURE_MODES:
            self.capture_mode = CAPTURE_MODE_NONE
        self.spout_sender_name = str(self.spout_sender_name or "").strip() or DEFAULT_SPOUT_SENDER_NAME
        if self.capture_resolution not in CAPTURE_RESOLUTIONS:
            self.capture_resolution = OCR_CAPTURE_RESOLUTION
        if self.image_save_format not in IMAGE_SAVE_FORMATS:
            self.image_save_format = IMAGE_SAVE_FORMAT_PNG
        self.auto_capture_enabled = bool(self.auto_capture_enabled)
        self.auto_capture_on_floor_change = bool(self.auto_capture_on_floor_change)
        if self.auto_capture_floor_interval not in AUTO_CAPTURE_FLOOR_INTERVALS:
            self.auto_capture_floor_interval = AUTO_CAPTURE_FLOOR_INTERVAL_ALL
        self.auto_capture_on_adventure_result = bool(self.auto_capture_on_adventure_result)
        if self.alert_output not in ALERT_OUTPUTS:
            self.alert_output = ALERT_OUTPUT_SOUND
        self.obs_enabled = self.capture_mode == CAPTURE_MODE_OBS
        config_data = {
            "obs_enabled": self.obs_enabled,
            "capture_mode": self.capture_mode,
            "spout_sender_name": self.spout_sender_name,
            "websocket_host": self.websocket_host,
            "websocket_port": self.websocket_port,
            "websocket_password": self.websocket_password,
            "keep_on_top": self.keep_on_top,
            "game_overlay_enabled": self.game_overlay_enabled,
            "game_overlay_monsters_enabled": self.game_overlay_monsters_enabled,
            "game_overlay_shop_price_enabled": self.game_overlay_shop_price_enabled,
            "game_overlay_alerts_enabled": self.game_overlay_alerts_enabled,
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
            "obs_capture_interval_seconds": self.obs_capture_interval_seconds,
            "capture_resolution": self.capture_resolution,
            "image_save_path": self.image_save_path,
            "image_save_format": self.image_save_format,
            "auto_capture_enabled": self.auto_capture_enabled,
            "auto_capture_on_floor_change": self.auto_capture_on_floor_change,
            "auto_capture_floor_interval": self.auto_capture_floor_interval,
            "auto_capture_on_adventure_result": self.auto_capture_on_adventure_result,
            "websocket_data_port": self.websocket_data_port,
            "http_server_enabled": self.http_server_enabled,
            "http_server_host": self.http_server_host,
            "http_server_port": self.http_server_port,
            "http_server_interface": self.http_server_interface,
            "language": self.language,
            "debug_mode": self.debug_mode,
            "dungeon_ocr_enabled": self.dungeon_ocr_enabled,
            "shop_ocr_enabled": self.shop_ocr_enabled,
            "dosukoi_alert_enabled": self.dosukoi_alert_enabled,
            "alert_output": self.alert_output,
            "dosukoi_alert_volume": self.dosukoi_alert_volume,
            "dosukoi_alert_threshold": self.dosukoi_alert_threshold,
            "entou_alert_enabled": self.entou_alert_enabled,
            **{key: getattr(self, key, default) for key, default in VOICE_DEFAULTS.items()},
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
                "obs_enabled": self.obs_enabled,
                "capture_mode": self.capture_mode,
                "spout_sender_name": self.spout_sender_name,
                "capture_resolution": self.capture_resolution,
                "monitor_source_name": self.monitor_source_name,
                "obs_scene_collection": self.obs_scene_collection,
                "image_save_path": self.image_save_path,
                "image_save_format": self.image_save_format,
                "websocket_data_port": self.websocket_data_port,
                "http_server_enabled": self.http_server_enabled,
                "http_server_port": self.http_server_port,
                "http_server_interface": self.http_server_interface,
                "language": self.language,
                "debug_mode": self.debug_mode,
                "dungeon_ocr_enabled": self.dungeon_ocr_enabled,
                "shop_ocr_enabled": self.shop_ocr_enabled,
            },
            ensure_ascii=False,
            indent=2,
        )
