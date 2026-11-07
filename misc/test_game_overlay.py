"""Run: QT_QPA_PLATFORM=offscreen uv run python -B -m unittest misc.test_game_overlay"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from src.config import Config
from src.define import (
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
    LIVE_EXPLORATION_MODE_NONE,
)
from src.game_overlay import (
    GameOverlay,
    MonsterOverlayWindow,
    OVERLAY_RECTS,
    ShopPriceOverlayWindow,
    WarningOverlayWindow,
    overlay_rect,
    scaled_rect,
)


class GameOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Config(str(Path(temp.name) / "config.json"))
        self.monster_data = {
            "floor_label": "25F",
            "groups": [
                {
                    "key": "normal",
                    "monsters": [{"name": "マムル", "icon_sources": []}],
                }
            ],
            "next_floor": {
                "floor_label": "26F",
                "groups": [
                    {
                        "key": "dekkai",
                        "monsters": [{"name": "デッ怪"}],
                    }
                ],
            },
        }
        self.shop_data = {
            "visible": True,
            "item_text": "オーラサイトの腕輪",
            "price": 6500,
            "price_label": "販売価格",
            "category_label": "腕輪",
            "candidates": [
                {"name": "毒消しの腕輪", "label": "毒消しの腕輪"},
                {"name": "忍び足の腕輪", "label": "忍び足の腕輪"},
            ],
        }

    def test_config_defaults_round_trip_and_dialog_label(self):
        self.assertFalse(self.config.game_overlay_enabled)
        self.assertTrue(self.config.game_overlay_monsters_enabled)
        self.assertTrue(self.config.game_overlay_shop_price_enabled)
        self.assertTrue(self.config.game_overlay_alerts_enabled)
        self.config.game_overlay_enabled = True
        self.config.game_overlay_shop_price_enabled = False
        self.config.save_config()
        loaded = Config(self.config.config_file)
        self.assertTrue(loaded.game_overlay_enabled)
        self.assertTrue(loaded.game_overlay_monsters_enabled)
        self.assertFalse(loaded.game_overlay_shop_price_enabled)
        self.assertTrue(loaded.game_overlay_alerts_enabled)

        from src.config_dialog import ConfigDialog

        dialog = ConfigDialog(loaded)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.game_overlay_enabled_check.isChecked())
        tabs = dialog.findChild(QTabWidget)
        self.assertIn("オーバーレイ", [tabs.tabText(i) for i in range(tabs.count())])
        self.assertTrue(dialog.game_overlay_items_group.isEnabled())
        self.assertTrue(dialog.game_overlay_item_checks["monsters"].isChecked())
        self.assertFalse(dialog.game_overlay_item_checks["shop_price"].isChecked())
        self.assertTrue(dialog.game_overlay_item_checks["alerts"].isChecked())
        dialog.game_overlay_enabled_check.setChecked(False)
        self.assertFalse(dialog.game_overlay_items_group.isEnabled())
        self.assertTrue(dialog.game_overlay_item_checks["monsters"].isChecked())

    def test_fullhd_profiles_exist_for_every_live_mode(self):
        for mode in (
            LIVE_EXPLORATION_MODE_NONE,
            LIVE_EXPLORATION_MODE_1,
            LIVE_EXPLORATION_MODE_2,
            LIVE_EXPLORATION_MODE_3,
        ):
            self.assertIn(mode, OVERLAY_RECTS)
            for item in ("monsters", "shop_price"):
                x, y, width, height = overlay_rect(mode, item)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertLessEqual(x + width, 1920)
                self.assertLessEqual(y + height, 1080)
        self.assertEqual(
            overlay_rect(LIVE_EXPLORATION_MODE_1, "monsters"),
            (0, 100, 918, 70),
        )
        self.assertEqual(
            overlay_rect(LIVE_EXPLORATION_MODE_1, "shop_price"),
            (861, 181, 565, 313),
        )

    def test_geometry_tracks_resized_and_negative_origin_game_window(self):
        rect = (100, 200, 400, 300)
        self.assertEqual(scaled_rect(rect, (0, 0, 1920, 1080)), rect)
        self.assertEqual(
            scaled_rect(rect, (-1280, -720, 0, 0)),
            (-1213, -587, 267, 200),
        )

    def test_windows_are_click_through_and_draw(self):
        monster = MonsterOverlayWindow()
        shop = ShopPriceOverlayWindow()
        warning = WarningOverlayWindow()
        self.addCleanup(monster.close)
        self.addCleanup(shop.close)
        self.addCleanup(warning.close)
        monster.set_data(self.monster_data)
        shop.set_data(self.shop_data)
        monster.resize(918, 70)
        shop.resize(565, 313)
        warning.set_messages(("満腹度が減少しています", "遠投状態です"))
        warning.resize(1920, 1080)
        monster_image = monster.grab().toImage()
        self.assertFalse(monster_image.isNull())
        self.assertEqual(monster_image.pixelColor(900, 10).alpha(), 0)
        self.assertEqual(monster_image.pixelColor(900, 35).alpha(), 0)
        self.assertFalse(shop.grab().toImage().isNull())
        warning_image = warning.grab().toImage()
        self.assertFalse(warning_image.isNull())
        self.assertEqual(warning_image.pixelColor(960, 540).alpha(), 0)
        self.assertGreater(warning_image.pixelColor(960, 10).alpha(), 0)
        for window in (monster, shop, warning):
            self.assertTrue(window.windowFlags() & Qt.WindowTransparentForInput)
            self.assertTrue(window.windowFlags() & Qt.WindowDoesNotAcceptFocus)
            self.assertTrue(window.testAttribute(Qt.WA_ShowWithoutActivating))

    def test_manager_shows_monsters_and_only_visible_shop_candidates(self):
        self.config.game_overlay_enabled = True
        overlay = GameOverlay(self.config)
        self.addCleanup(overlay.close)
        with patch.object(
            overlay,
            "_target_bbox",
            return_value=(100, 200, 2020, 1280),
        ):
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                ("満腹度が減少しています",),
            )
            self.assertTrue(overlay.monster_window.isVisible())
            self.assertTrue(overlay.shop_window.isVisible())
            self.assertTrue(overlay.warning_window.isVisible())
            self.assertEqual(
                overlay.warning_window._desktop_rect,
                (100, 200, 1920, 1080),
            )
            self.assertEqual(
                overlay.monster_window._desktop_rect,
                (100, 300, 918, 70),
            )
            hidden_shop = dict(self.shop_data, visible=False)
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                hidden_shop,
                (),
            )
            self.assertTrue(overlay.monster_window.isVisible())
            self.assertFalse(overlay.shop_window.isVisible())
            self.assertFalse(overlay.warning_window.isVisible())

    def test_individual_part_toggles_hide_only_the_selected_part(self):
        self.config.game_overlay_enabled = True
        overlay = GameOverlay(self.config)
        self.addCleanup(overlay.close)
        with patch.object(overlay, "_target_bbox", return_value=(0, 0, 1920, 1080)):
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                ("遠投状態です",),
            )
            self.config.game_overlay_monsters_enabled = False
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                ("遠投状態です",),
            )
            self.assertFalse(overlay.monster_window.isVisible())
            self.assertTrue(overlay.shop_window.isVisible())
            self.assertTrue(overlay.warning_window.isVisible())

            self.config.game_overlay_shop_price_enabled = False
            self.config.game_overlay_alerts_enabled = False
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                ("遠投状態です",),
            )
            self.assertFalse(overlay.shop_window.isVisible())
            self.assertFalse(overlay.warning_window.isVisible())

    def test_disabled_or_stale_capture_hides_windows(self):
        self.config.game_overlay_enabled = True
        overlay = GameOverlay(self.config)
        self.addCleanup(overlay.close)
        with patch.object(overlay, "_target_bbox", return_value=(0, 0, 1920, 1080)):
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                ("遠投状態です",),
            )
            overlay.update(
                LIVE_EXPLORATION_MODE_1,
                self.monster_data,
                self.shop_data,
                capture_ready=False,
            )
            self.assertFalse(overlay.monster_window.isVisible())
            self.assertFalse(overlay.shop_window.isVisible())
            self.assertFalse(overlay.warning_window.isVisible())


if __name__ == "__main__":
    unittest.main()
