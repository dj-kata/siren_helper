"""座標など固定のデータをここに記載
"""
from src.classes import *

class DetectOnShop:
    '''店において買取価格表示があるかどうかを判定'''
    CROP_XYWH = (780,580,700,50)
    target = '識別されていないのでよくわからない'

class PosMyItemPrice:
    '''手持ちアイテムの買取価格部分の切り取り'''
    CROP_XYWH = (808,530,620,50)

class PosShopItemPrice:
    '''店売りアイテムの買取価格部分の切り取り'''
    CROP_XYWH = (200,240,550,50)

class PosMyItems:
    '''所持品一覧の切り取り(type1)'''
    CROP_XYWH = (1600,0,320,1080)

class PosIsPlayHash:
    '''プレー画面判定用のハッシュ'''
    HASH = '105f487f5effb700'