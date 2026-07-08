from pathlib import Path

from src.define import (
    DEFAULT_LIVE_EXPLORATION_MODE,
    LIVE_EXPLORATION_MODE_1,
    LIVE_EXPLORATION_MODE_2,
    LIVE_EXPLORATION_MODE_3,
    LIVE_EXPLORATION_MODE_NONE,
    normalize_live_exploration_mode,
)


def detect_live_exploration_mode(screen, source_path=None):
    """ゲーム内のライブ探索表示タイプを判定する。

    具体的な画像判定条件は後でここに追加する。テスト画像は type0.png
    のようなファイル名でも仮判定できるようにしている。
    """
    if source_path:
        name = Path(source_path).name.lower()
        if "type0" in name:
            return LIVE_EXPLORATION_MODE_NONE
        if "type1" in name:
            return LIVE_EXPLORATION_MODE_1
        if "type2" in name:
            return LIVE_EXPLORATION_MODE_2
        if "type3" in name:
            return LIVE_EXPLORATION_MODE_3

    # TODO: captures/type0.png, type1.png, type2.png, type3.png を見ながら
    # 画面内の固定領域や色などで判定条件を書く。
    _ = screen
    return DEFAULT_LIVE_EXPLORATION_MODE


def is_live_exploration_mode(value):
    return normalize_live_exploration_mode(value) == value
