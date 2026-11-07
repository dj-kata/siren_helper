"""ゲーム画面上に表示するクリック透過の小型オーバーレイ。"""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from src.define import (
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
    LIVE_EXPLORATION_MODE_NONE,
    normalize_live_exploration_mode,
)
from src.logger import get_logger

logger = get_logger(__name__)

# すべて1920x1080のゲームクライアント領域を基準とするxywh。
# type1は添付画像の赤枠・緑枠に合わせた値。他モードは既存OCR cropの
# 画面倍率から算出した初期値で、実機画像に合わせてここだけ調整できる。
OVERLAY_RECTS = {
    LIVE_EXPLORATION_MODE_NONE: {
        "monsters": (0, 133, 1227, 93),
        "shop_price": (1147, 241, 755, 419),
    },
    LIVE_EXPLORATION_MODE_1: {
        "monsters": (0, 100, 918, 70),
        "shop_price": (861, 181, 565, 313),
    },
    LIVE_EXPLORATION_MODE_2: {
        "monsters": (0, 111, 1002, 78),
        "shop_price": (937, 201, 617, 349),
    },
    LIVE_EXPLORATION_MODE_3: {
        "monsters": (0, 123, 1125, 86),
        "shop_price": (1052, 223, 692, 387),
    },
}


def scaled_rect(rect, game_bbox):
    """FullHD基準のxywhをゲームクライアントのデスクトップ座標へ変換する。"""
    x, y, width, height = rect
    left, top, right, bottom = game_bbox
    scale_x = (right - left) / 1920
    scale_y = (bottom - top) / 1080
    return (
        round(left + x * scale_x),
        round(top + y * scale_y),
        max(1, round(width * scale_x)),
        max(1, round(height * scale_y)),
    )


def overlay_rect(live_mode, item):
    mode = normalize_live_exploration_mode(live_mode)
    return OVERLAY_RECTS[mode][item]


class OverlayWindow(QWidget):
    def __init__(self, title):
        super().__init__(
            None,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self._desktop_rect = None
        if sys.platform == "win32":
            affinity = ctypes.windll.user32.SetWindowDisplayAffinity
            affinity.argtypes = (wintypes.HWND, wintypes.DWORD)
            affinity.restype = wintypes.BOOL
            if not affinity(int(self.winId()), 0x11):  # WDA_EXCLUDEFROMCAPTURE
                logger.warning("ゲーム内オーバーレイを画面取得から除外できませんでした")

    def present(self, rect):
        if self._desktop_rect == rect and self.isVisible():
            return
        self._desktop_rect = rect
        if sys.platform != "win32":
            self.setGeometry(*rect)
        else:
            dpr = self.devicePixelRatioF()
            self.resize(
                max(1, round(rect[2] / dpr)),
                max(1, round(rect[3] / dpr)),
            )
        self.show()
        if sys.platform == "win32":
            set_pos = ctypes.windll.user32.SetWindowPos
            set_pos.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            set_pos.restype = wintypes.BOOL
            if not set_pos(int(self.winId()), wintypes.HWND(-1), *rect, 0x0010):
                logger.warning("ゲーム内オーバーレイの配置に失敗しました: %s", rect)


class MonsterOverlayWindow(OverlayWindow):
    def __init__(self, asset_root=None):
        super().__init__("Siren 6 monster overlay")
        self.data = {}
        self.asset_root = Path(asset_root or Path(__file__).resolve().parents[1])
        self._pixmap_cache = {}

    def set_data(self, data):
        data = data or {}
        if data != self.data:
            self.data = data
            self.update()

    def _pixmap(self, monster):
        for source in monster.get("icon_sources", []):
            source_path = Path(source)
            candidates = (
                self.asset_root / "template" / source_path,
                self.asset_root / source_path,
            )
            for candidate in candidates:
                try:
                    path = candidate.resolve()
                except OSError:
                    continue
                key = str(path)
                if key not in self._pixmap_cache:
                    self._pixmap_cache[key] = QPixmap(key) if path.is_file() else QPixmap()
                pixmap = self._pixmap_cache[key]
                if not pixmap.isNull():
                    return pixmap
        return QPixmap()

    @staticmethod
    def _floor_monsters(floor_data):
        monsters = []
        for group in floor_data.get("groups", []):
            if group.get("key") == "dekkai" and group.get("monsters"):
                monsters.append({"name": "デッ怪", "group": "dekkai"})
                continue
            monsters.extend(group.get("monsters", []))
        return monsters

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        floors = [self.data]
        if self.data.get("next_floor"):
            floors.append(self.data["next_floor"])
        row_height = self.height() / max(1, len(floors))
        label_width = max(32, min(58, round(self.width() * 0.065)))

        for row, floor_data in enumerate(floors[:2]):
            top = row * row_height
            painter.setFont(QFont("Meiryo", max(8, round(row_height * 0.28)), QFont.Bold))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(3, top, label_width - 6, row_height),
                Qt.AlignRight | Qt.AlignVCenter,
                floor_data.get("floor_label", ""),
            )

            monsters = self._floor_monsters(floor_data)
            icon_size = max(12, min(round(row_height - 6), 42))
            gap = max(1, round(icon_size * 0.08))
            x = label_width + gap
            for monster in monsters:
                if x + icon_size > self.width():
                    break
                icon_rect = QRectF(x, top + (row_height - icon_size) / 2, icon_size, icon_size)
                if monster.get("group") == "dekkai":
                    painter.setPen(QPen(QColor("#ffffff"), 1))
                    painter.setBrush(QColor("#3b0b67"))
                    painter.drawEllipse(icon_rect.adjusted(1, 1, -1, -1))
                    painter.setFont(QFont("Meiryo", max(7, round(icon_size * 0.27)), QFont.Bold))
                    painter.setPen(QColor("#ffffff"))
                    painter.drawText(icon_rect, Qt.AlignCenter, "デッ")
                else:
                    pixmap = self._pixmap(monster)
                    if pixmap.isNull():
                        painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                        painter.setBrush(QColor(255, 255, 255, 28))
                        painter.drawEllipse(icon_rect.adjusted(1, 1, -1, -1))
                        painter.setFont(QFont("Meiryo", max(6, round(icon_size * 0.24)), QFont.Bold))
                        painter.setPen(QColor("#ffffff"))
                        painter.drawText(
                            icon_rect,
                            Qt.AlignCenter,
                            str(monster.get("name", "?"))[:2],
                        )
                    else:
                        scaled = pixmap.scaled(
                            icon_rect.size().toSize(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        draw_rect = QRectF(
                            icon_rect.center().x() - scaled.width() / 2,
                            icon_rect.center().y() - scaled.height() / 2,
                            scaled.width(),
                            scaled.height(),
                        )
                        painter.drawPixmap(draw_rect.toRect(), scaled)
                x += icon_size + gap


class ShopPriceOverlayWindow(OverlayWindow):
    def __init__(self):
        super().__init__("Siren 6 shop price overlay")
        self.data = {}

    def set_data(self, data):
        data = data or {}
        if data != self.data:
            self.data = data
            self.update()

    @staticmethod
    def _elide(painter, text, width):
        return painter.fontMetrics().elidedText(
            str(text or ""),
            Qt.ElideRight,
            max(1, round(width)),
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 18, 185))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 7, 7)

        margin = max(6, round(self.width() * 0.02))
        header_height = max(38, round(self.height() * 0.2))
        price = self.data.get("price")
        price_text = f"{price:,}G" if isinstance(price, int) else "--"
        price_width = max(80, round(self.width() * 0.25))

        painter.setFont(QFont("Meiryo", max(10, round(header_height * 0.3)), QFont.Bold))
        painter.setPen(QColor("#ffffff"))
        item_rect = QRectF(margin, 2, self.width() - price_width - margin * 2, header_height * 0.58)
        painter.drawText(item_rect, Qt.AlignLeft | Qt.AlignVCenter, self._elide(painter, self.data.get("item_text", ""), item_rect.width()))
        painter.setPen(QColor("#ffd43b"))
        painter.drawText(
            QRectF(self.width() - price_width - margin, 2, price_width, header_height * 0.58),
            Qt.AlignRight | Qt.AlignVCenter,
            price_text,
        )
        painter.setFont(QFont("Meiryo", max(8, round(header_height * 0.2)), QFont.Bold))
        painter.setPen(QColor(220, 220, 220))
        meta = f'{self.data.get("category_label", "")} / {self.data.get("price_label", "")}'
        painter.drawText(
            QRectF(margin, header_height * 0.55, self.width() - margin * 2, header_height * 0.4),
            Qt.AlignLeft | Qt.AlignVCenter,
            meta,
        )

        candidates = self.data.get("candidates", [])
        columns = 2 if self.width() >= 360 else 1
        gap = max(5, round(self.width() * 0.012))
        card_width = (self.width() - margin * 2 - gap * (columns - 1)) / columns
        rows = max(1, (min(len(candidates), 10) + columns - 1) // columns)
        available_height = self.height() - header_height - margin
        card_height = min(
            max(28, (available_height - gap * (rows - 1)) / rows),
            max(40, self.height() * 0.18),
        )

        for index, candidate in enumerate(candidates[: columns * rows]):
            row, column = divmod(index, columns)
            x = margin + column * (card_width + gap)
            y = header_height + row * (card_height + gap)
            rect = QRectF(x, y, card_width, card_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(10, 10, 35, 220))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setBrush(QColor("#69db7c"))
            painter.drawRoundedRect(QRectF(x, y, max(4, card_width * 0.025), card_height), 2, 2)
            painter.setFont(QFont("Meiryo", max(9, round(card_height * 0.28)), QFont.Bold))
            painter.setPen(QColor("#ffffff"))
            text_rect = rect.adjusted(10, 2, -5, -2)
            name = candidate.get("label") or candidate.get("name", "")
            painter.drawText(
                text_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                self._elide(painter, name, text_rect.width()),
            )


class WarningOverlayWindow(OverlayWindow):
    """上下端に黄黒の警告帯とループ文字を描画する。"""

    BAND_HEIGHT_FULLHD = 58

    def __init__(self):
        super().__init__("Siren 6 warning overlay")
        self.messages = ()
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def set_messages(self, messages):
        normalized = tuple(str(message).strip() for message in messages if str(message).strip())
        if normalized != self.messages:
            self.messages = normalized
            self._offset = 0.0
            self.update()

    def _advance(self):
        self._offset += max(2.0, self.width() / 640)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _draw_stripes(self, painter, rect):
        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor("#ffd400"))
        stripe_width = max(18.0, rect.height() * 0.82)
        slant = rect.height() * 0.58
        phase = self._offset % (stripe_width * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#141414"))
        x = rect.left() - stripe_width * 3 + phase
        while x < rect.right() + stripe_width:
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x + slant, rect.top()),
                        QPointF(x + stripe_width + slant, rect.top()),
                        QPointF(x + stripe_width - slant, rect.bottom()),
                        QPointF(x - slant, rect.bottom()),
                    ]
                )
            )
            x += stripe_width * 2
        painter.restore()

    @staticmethod
    def _draw_warning_text(painter, rect, text):
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            painter.setPen(QColor("#180000"))
            painter.drawText(rect.translated(dx, dy), Qt.AlignCenter, text)
        painter.setPen(QColor("#e60012"))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _draw_marquee(self, painter, rect, reverse=False):
        message = "　◆ WARNING ◆　" + "　／　".join(self.messages)
        painter.setFont(
            QFont(
                "Meiryo",
                max(10, round(rect.height() * 0.38)),
                QFont.Black,
            )
        )
        text_width = max(1, painter.fontMetrics().horizontalAdvance(message))
        pitch = text_width + max(90, round(rect.height() * 2.2))
        phase = self._offset % pitch
        x = (-pitch + phase) if reverse else -phase
        if reverse:
            while x > rect.left() - pitch:
                x -= pitch
        while x < rect.right() + pitch:
            text_rect = QRectF(x, rect.top(), text_width, rect.height())
            self._draw_warning_text(painter, text_rect, message)
            x += pitch

    def paintEvent(self, _event):
        if not self.messages:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        band_height = max(
            24,
            round(self.height() * self.BAND_HEIGHT_FULLHD / 1080),
        )
        top = QRectF(0, 0, self.width(), band_height)
        bottom = QRectF(0, self.height() - band_height, self.width(), band_height)
        for rect in (top, bottom):
            self._draw_stripes(painter, rect)
            painter.setPen(QPen(QColor("#e60012"), max(2, round(band_height * 0.06))))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        self._draw_marquee(painter, top)
        self._draw_marquee(painter, bottom, reverse=True)


class GameOverlay:
    def __init__(self, config, asset_root=None):
        self.config = config
        self.asset_root = asset_root
        self.monster_window = None
        self.shop_window = None
        self.warning_window = None
        self._game_bbox = None
        self._next_target_check = 0.0
        self._closed = False

    def set_config(self, config):
        self.config = config
        if not config.game_overlay_enabled:
            self._hide_all()

    def _target_bbox(self):
        if sys.platform != "win32":
            return None
        now = time.monotonic()
        if now >= self._next_target_check:
            self._next_target_check = now + 0.5
            try:
                from src.direct_capture import get_shiren_window_bbox

                self._game_bbox = get_shiren_window_bbox()
            except Exception:
                self._game_bbox = None
        return self._game_bbox

    def update(
        self,
        live_mode,
        monster_data,
        shop_data,
        alert_messages=(),
        capture_ready=True,
    ):
        if self._closed:
            return
        if not self.config.game_overlay_enabled or not capture_ready:
            self._hide_all()
            return
        bbox = self._target_bbox()
        if not bbox or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            self._hide_all()
            return

        mode = normalize_live_exploration_mode(live_mode)
        if self.config.game_overlay_monsters_enabled and monster_data:
            if self.monster_window is None:
                self.monster_window = MonsterOverlayWindow(self.asset_root)
            self.monster_window.set_data(monster_data)
            self.monster_window.present(scaled_rect(overlay_rect(mode, "monsters"), bbox))
        elif self.monster_window is not None:
            self.monster_window.hide()

        shop_visible = bool(
            self.config.game_overlay_shop_price_enabled
            and shop_data
            and shop_data.get("visible")
            and shop_data.get("candidates")
        )
        if shop_visible:
            if self.shop_window is None:
                self.shop_window = ShopPriceOverlayWindow()
            self.shop_window.set_data(shop_data)
            self.shop_window.present(scaled_rect(overlay_rect(mode, "shop_price"), bbox))
        elif self.shop_window is not None:
            self.shop_window.hide()

        if self.config.game_overlay_alerts_enabled and alert_messages:
            if self.warning_window is None:
                self.warning_window = WarningOverlayWindow()
            self.warning_window.set_messages(alert_messages)
            self.warning_window.present(
                (bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
            )
        elif self.warning_window is not None:
            self.warning_window.hide()

    def _hide_all(self):
        for window in (self.monster_window, self.shop_window, self.warning_window):
            if window is not None:
                window.hide()

    def close(self):
        self._closed = True
        for window in (self.monster_window, self.shop_window, self.warning_window):
            if window is not None:
                window.close()
                window.deleteLater()
        self.monster_window = None
        self.shop_window = None
        self.warning_window = None
        self._game_bbox = None
        self._next_target_check = 0.0
