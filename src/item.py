#!/usr/bin/python3
from enum import Enum
import json
from pathlib import Path

class item_category(Enum):
    kusa     = (1, "草")
    makimono = (2, "巻物")
    udewa    = (3, "腕輪")
    tubo     = (4, "壺")
    tue      = (5, "杖")
    buki     = (6, "武器")
    tate     = (7, "盾")
    okou     = (8, "お香")

    def __init__(self, id, ja):
        self.id = id
        self.ja = ja

class Item:
    def __init__(self, name, category:item_category, buy:str, sell:str, bin:str, tin:str, demerit:bool=False, 
                normal_shop:bool=False, vip_shop:bool=False, memo:str='', default_get:bool=False):
        self.name = name
        self.category = category
        self.buy = int(buy)
        self.sell = int(sell)
        self.bin = bin
        self.tin=tin

        self.demerit = demerit # 完全なるデメリットアイテムのみ
        self.default_get = default_get
        self.get = default_get
        self.normal_shop = normal_shop
        self.vip_shop    = vip_shop
        self.memo = memo

    def disp(self):
        str_demerit = ''
        if self.demerit:
            str_demerit = "(デメリット) " 
        print(f"{self.name} {str_demerit}({self.category.ja}), 買値:{self.buy:,}, 売値:{self.sell:,}")

class Tue(Item):
    def __init__(self, name, buy:str, sell:str, buy_unit:str, sell_unit:str, capa_min:str, capa_max:str, bin:str, tin:str,
                 demerit:bool=False, normal_shop:bool=False, vip_shop:bool=False, memo:str='', default_get:bool=False):
        super().__init__(name, item_category.tue, buy, sell, bin, tin, demerit, normal_shop, vip_shop, memo, default_get)
        self.buy_unit  = int(buy_unit)
        self.sell_unit = int(sell_unit)
        self.capa_min  = int(capa_min)
        self.capa_max  = int(capa_max)
        self.buy_max   = int(buy)+int(buy_unit)*int(capa_max)
        self.sell_max  = int(sell)+int(sell_unit)*int(capa_max)

    def disp(self):
        str_demerit = ''
        if self.demerit:
            str_demerit = "(デメリット) " 
        print(f"{self.name}[{self.capa_min}-{self.capa_max}] {str_demerit}({self.category.ja}), 買値:{self.buy:,}-{self.buy_max:,}, 売値:{self.sell:,}-{self.sell_max:,}")

class Tubo(Item):
    def __init__(self, name, buy:str, sell:str, buy_unit:str, sell_unit:str, capa_min:str, capa_max:str, bin:str, tin:str,
                 demerit:bool=False, normal_shop:bool=False, vip_shop:bool=False, memo:str='', default_get:bool=False):
        super().__init__(name, item_category.tubo, buy, sell, bin, tin, demerit, normal_shop, vip_shop, memo, default_get)
        self.buy_unit  = int(buy_unit)
        self.sell_unit = int(sell_unit)
        self.capa_min  = int(capa_min)
        self.capa_max  = int(capa_max)
        self.buy_max   = int(buy)+int(buy_unit)*int(capa_max)
        self.sell_max  = int(sell)+int(sell_unit)*int(capa_max)

    def disp(self):
        str_demerit = ''
        if self.demerit:
            str_demerit = "(デメリット) " 
        print(f"{self.name}[{self.capa_min}-{self.capa_max}] {str_demerit}({self.category.ja}), 買値:{self.buy:,}-{self.buy_max:,}, 売値:{self.sell:,}-{self.sell_max:,}")

class ItemList:
    data_path = Path(__file__).resolve().parent.parent / "data" / "6_items.json"
    category_json_keys = {
        "kusa": "kusa_tane",
        "makimono": "makimono",
        "udewa": "udewa",
        "tubo": "tubo",
        "okou": "okou",
        "tue": "tue",
        "buki": "buki",
        "tate": "tate",
    }

    def __init__(self, data_path=None):
        self.data_path = Path(data_path) if data_path else self.data_path
        data = self._load_json()

        self.kusa = self._load_simple_items(data, "kusa", item_category.kusa, synthesis_key="異種合成")
        self.makimono = self._load_simple_items(data, "makimono", item_category.makimono, synthesis_key="異種")
        self.udewa = self._load_simple_items(data, "udewa", item_category.udewa)
        self.tubo = self._load_capacity_items(data, "tubo", item_category.tubo)
        self.okou = self._load_capacity_items(data, "okou", item_category.okou, extra_key="エフェクト")
        self.tue = self._load_capacity_items(data, "tue", item_category.tue, synthesis_key="異種合成")
        self.buki = self._load_equipment_items(data, "buki", item_category.buki)
        self.tate = self._load_equipment_items(data, "tate", item_category.tate)

    def _load_json(self):
        with self.data_path.open(encoding="utf-8") as f:
            return json.load(f)["categories"]

    def _json_items(self, data, category):
        return data[self.category_json_keys[category]]["items"]

    def _first_int(self, value, default=0):
        if isinstance(value, int):
            return value
        digits = ""
        for char in str(value):
            if char.isdigit() or (char == "-" and not digits):
                digits += char
            elif digits:
                break
        return int(digits) if digits else default

    def _load_simple_items(self, data, category, enum_value, synthesis_key=None):
        items = []
        for row in self._json_items(data, category):
            bin_value = row.get(synthesis_key, "") if synthesis_key else ""
            tin_value = row.get("2つ装備時", "") if category == "udewa" else ""
            items.append(Item(
                row.get("名前", ""),
                enum_value,
                row.get("買値", 0),
                row.get("売値", 0),
                bin_value,
                tin_value,
                memo=row.get("簡単な説明", ""),
            ))
        return items

    def _load_equipment_items(self, data, category, enum_value):
        items = []
        for row in self._json_items(data, category):
            items.append(Item(
                row.get("名前", ""),
                enum_value,
                row.get("買値", 0),
                row.get("売値", 0),
                row.get("印", ""),
                "",
                memo=row.get("共鳴", "") or row.get("簡単な説明", ""),
            ))
        return items

    def _load_capacity_items(self, data, category, enum_value, synthesis_key=None, extra_key=None):
        items = []
        cls = Tue if enum_value == item_category.tue else Tubo
        for row in self._json_items(data, category):
            bin_value = row.get(synthesis_key, "") if synthesis_key else ""
            tin_value = row.get(extra_key, "") if extra_key else ""
            items.append(cls(
                row.get("名前", ""),
                row.get("買基", 0),
                row.get("売基", 0),
                row.get("+1", 0),
                row.get("+1_2", 0),
                self._first_int(row.get("下限", 0)),
                self._first_int(row.get("上限", 0)),
                bin_value,
                tin_value,
                memo=row.get("簡単な説明", ""),
            ))
        return items

    def load(self, params):
        """ユーザデータのjsonからチェック済みの状態を読み込む

        Args:
            params (dict): settings.jsonの内容
        """
        for i,tmp in enumerate(self.kusa):
            tmp.get = bool(params.get('kusa', [])[i]) if i < len(params.get('kusa', [])) else tmp.default_get
        for i,tmp in enumerate(self.makimono):
            tmp.get = bool(params.get('makimono', [])[i]) if i < len(params.get('makimono', [])) else tmp.default_get
        for i,tmp in enumerate(self.udewa):
            tmp.get = bool(params.get('udewa', [])[i]) if i < len(params.get('udewa', [])) else tmp.default_get
        for i,tmp in enumerate(self.tubo):
            tmp.get = bool(params.get('tubo', [])[i]) if i < len(params.get('tubo', [])) else tmp.default_get
        for i,tmp in enumerate(self.okou):
            tmp.get = bool(params.get('okou', [])[i]) if i < len(params.get('okou', [])) else tmp.default_get
        for i,tmp in enumerate(self.tue):
            tmp.get = bool(params.get('tue', [])[i]) if i < len(params.get('tue', [])) else tmp.default_get
        for i,tmp in enumerate(self.buki):
            tmp.get = bool(params.get('buki', [])[i]) if i < len(params.get('buki', [])) else tmp.default_get
        for i,tmp in enumerate(self.tate):
            tmp.get = bool(params.get('tate', [])[i]) if i < len(params.get('tate', [])) else tmp.default_get

    def save(self, params):
        """チェック済みかどうかの状態をdictへ出力

        Args:
            params (dict): 出力先となるsettings.jsonの内容
        """
        for key in ["kusa", "makimono", "udewa", "tubo", "okou", "tue", "buki", "tate"]:
            params[key] = [False] * len(getattr(self, key))
        for i,tmp in enumerate(self.kusa):
            params['kusa'][i] = tmp.get
        for i,tmp in enumerate(self.makimono):
            params['makimono'][i] = tmp.get
        for i,tmp in enumerate(self.udewa):
            params['udewa'][i] = tmp.get
        for i,tmp in enumerate(self.tubo):
            params['tubo'][i] = tmp.get
        for i,tmp in enumerate(self.okou):
            params['okou'][i] = tmp.get
        for i,tmp in enumerate(self.tue):
            params['tue'][i] = tmp.get
        for i,tmp in enumerate(self.buki):
            params['buki'][i] = tmp.get
        for i,tmp in enumerate(self.tate):
            params['tate'][i] = tmp.get

    def reset(self):
        for i in self.kusa:
            i.get = i.default_get
        for i in self.makimono:
            i.get = i.default_get
        for i in self.udewa:
            i.get = i.default_get
        for i in self.tubo:
            i.get = i.default_get
        for i in self.okou:
            i.get = i.default_get
        for i in self.tue:
            i.get = i.default_get
        for i in self.buki:
            i.get = i.default_get
        for i in self.tate:
            i.get = i.default_get

    def get_stat(self):
        cnt = [0,0,0,0,0,0,  0,0,0] # 草、巻物、腕輪、壺、お香、杖、100,300,500草
        total = [0,0,0,0,0,0, 0,0,0] # 分母

        for i,tmp in enumerate(self.kusa):
            total[0] += 1
            if tmp.get:
                cnt[0] += 1
            if tmp.buy == 100:
                total[5] += 1
                if tmp.get:
                    cnt[5] += 1
            if tmp.buy == 300:
                total[6] += 1
                if tmp.get:
                    cnt[6] += 1
            if tmp.buy == 500:
                total[7] += 1
                if tmp.get:
                    cnt[7] += 1
        for i,tmp in enumerate(self.makimono):
            if not tmp.default_get:
                total[1] += 1
                if tmp.get:
                    cnt[1] += 1
        for i,tmp in enumerate(self.udewa):
            total[2] += 1
            if tmp.get:
                cnt[2] += 1
        for i,tmp in enumerate(self.tubo):
            if not tmp.default_get:
                total[3] += 1
                if tmp.get:
                    cnt[3] += 1
        for i,tmp in enumerate(self.okou):
            total[4] += 1
            if tmp.get:
                cnt[4] += 1
        for i,tmp in enumerate(self.tue):
            total[5] += 1
            if tmp.get:
                cnt[5] += 1
        return cnt, total

if __name__ == '__main__':
    a = ItemList()
    for i in a.makimono:
        i.disp()
    for i in a.tue:
        i.disp()
    print(a.get_stat())
