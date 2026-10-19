"""Regression checks for Dungeon Report Viewer imports (no GUI or network)."""

import base64
import json
import unittest
import zlib
from pathlib import Path

from misc.fetch_siren6_report_dungeons import (
    DUNGEONS, convert_items, convert_monsters, decode_export,
)


class ReportImportTests(unittest.TestCase):
    def test_decode_data_without_executing_javascript(self):
        values = [[], {}, {"ja": "沈黙の神髄"}]
        source = "throw new Error('must not execute');\n"
        for name, value in zip(("Reports", "Dicts", "Localization"), values):
            encoded = base64.b64encode(zlib.compress(json.dumps(value).encode())).decode()
            source += f'const compressed{name} = "{encoded}";\n'
        self.assertEqual(decode_export(source), tuple(values))
        with self.assertRaises(ValueError):
            decode_export("invalid export")

    def test_active_item_tables_weights_and_sacred_variants(self):
        # Type 0 uses table 7, type 1 uses table 3; IDs do not imply methods.
        def entry(item_id, category_id=1, weight=1):
            return {"item_id": item_id, "category_id": category_id, "weight": weight}

        def table(items):
            return {"categories": [{"category_id": 1, "weight": 1}, {"category_id": 432758880, "weight": 0}, {"category_id": 1045712042, "weight": 1}], "items": items}

        report = {
            "floors": {"1": {"item": {"item_tables": [7, 3]}}},
            "dungeon": {
                "item_tables": {
                    "7": table([entry(1), entry(2, weight=0), entry(5, 432758880)]),
                    "3": table([entry(3)]), "9": table([entry(4)]),
                },
                "item_attach": {"attach_info": {"0": {"item_id": 6, "floors": [1]}}},
            },
        }
        dictionaries = {"item_data": {str(i): {"rarity": int(i == 5)} for i in range(1, 7)}}
        localization = {"item_name": {str(i): {"ja": name} for i, name in enumerate(["", "薬草", "無効", "復活の草", "未使用", "木刀", "固定品"])}}
        result = {i["name"]: i for i in convert_items(report, dictionaries, localization, {"薬草": "kusa_tane"})["items"]}
        self.assertEqual(set(result), {"薬草", "復活の草", "木刀", "固定品"})
        self.assertTrue(result["薬草"]["available"]["floor"])
        self.assertFalse(result["薬草"]["shop_only"])
        self.assertTrue(result["復活の草"]["shop_only"])
        self.assertEqual(result["木刀"]["table_ids"], [7])
        self.assertEqual(result["固定品"]["other_methods"], "確定出現")

    def test_monsters_exclude_npcs_and_conditional_spawns(self):
        creatures = {
            "1": {"creature_kind_str": "monster", "is_behemoth": False},
            "2": {"creature_kind_str": "wandering_npc", "is_behemoth": False},
            "3": {"creature_kind_str": "monster", "is_behemoth": True},
            "4": {"creature_kind_str": "monster", "is_behemoth": False},
            "5": {"creature_kind_str": "monster", "is_behemoth": False},
        }
        entries = [{"creature_id": i, "weight": 1} for i in range(1, 6)]
        entries[-1]["flag"] = {"MH_only": True}
        floor = {"dungeon": {"floor_type": 14}, "monster": {"monster_table": entries, "behemoth_prob": 0}}
        report = {"dungeon": {"dungeon_id": "test"}, "floors": {"1": floor}}
        localization = {"creature_name": {"1": {"ja": "マムル"}, "4": {"ja": "マゼルン"}, "5": {"ja": "タベラレルー"}}}
        result = convert_monsters(report, {"creature_data": creatures}, localization)["floors"][0]
        self.assertEqual(result["monsters"], ["マムル"])
        self.assertEqual(result["maze_monsters"], ["マゼルン"])
        self.assertFalse(result["dekkai"])
        self.assertEqual(result["visibility"], "暗")
        floor["monster"]["behemoth_prob"] = 10
        self.assertEqual(convert_monsters(report, {"creature_data": creatures}, localization)["floors"][0]["dekkai_monsters"], ["デッ怪"])

    def test_bundled_dungeons_are_complete_and_match_item_master(self):
        root = Path(__file__).resolve().parents[1]
        master = json.loads((root / "data/6_items.json").read_text(encoding="utf-8"))
        categories = {key: {i["名前"] for i in category["items"]} for key, category in master["categories"].items()}
        for key, name in DUNGEONS.values():
            with self.subTest(dungeon=name):
                data = json.loads((root / f"data/6_dungeons/{key}.json").read_text(encoding="utf-8"))
                self.assertEqual(data["name"], name)
                floors = data["monster_table"]["floors"]
                self.assertEqual([f["floor"] for f in floors], list(range(1, 100)))
                self.assertTrue(all(f["monsters"] for f in floors))
                self.assertGreater(len(data["items"]["items"]), 100)
                for item in data["items"]["items"]:
                    if item["category"]:
                        self.assertIn(item["name"], categories[item["category"]])


if __name__ == "__main__":
    unittest.main()
