import json
from pathlib import Path

# 元のJSONパス（環境に合わせて変更）
SRC_PATH = Path(r"C:\Users\miyos\OneDrive\Desktop\auto_menu\recipes.json")
DST_PATH = Path(r"C:\Users\miyos\OneDrive\Desktop\auto_menu\recipes_with_display.json")


def g_to_spoon_for_powder(g):
    """粉末系を大さじ・小さじにざっくり換算"""
    # ざっくり: 小さじ1=3g, 大さじ1=9g
    if g <= 0:
        return f"{g}g"
    tbsp = g / 9
    tsp = g / 3

    # 9g以上なら大さじ優先でざっくり
    if g >= 9:
        return f"大さじ{round(tbsp, 1)}杯（約{g}g）"
    else:
        return f"小さじ{round(tsp, 1)}杯（約{g}g）"


def g_to_spoon_for_liquid(g):
    """液体系を大さじ・小さじにざっくり換算（1ml≒1g前提）"""
    if g <= 0:
        return f"{g}g"
    tbsp = g / 15  # 大さじ1=15ml
    tsp = g / 5   # 小さじ1=5ml

    if g >= 15:
        return f"大さじ{round(tbsp, 1)}杯（約{g}ml）"
    else:
        return f"小さじ{round(tsp, 1)}杯（約{g}ml）"


def g_to_cup_rice(g):
    """米を合に換算（生米150g=1合くらいと仮定）"""
    if g <= 0:
        return f"{g}g"
    cups = g / 150
    return f"{round(cups, 1)}合（約{g}g）"


def g_to_leaf_portion(g, whole_weight=800):
    """キャベツなど葉物: 1玉=whole_weight g として何分の1か表現"""
    if g <= 0:
        return f"{g}g"
    ratio = g / whole_weight  # 0.25なら1/4玉
    # よくある分数に丸める
    candidates = [(1/8, "1/8玉"), (1/6, "1/6玉"), (1/4, "1/4玉"), (1/3, "1/3玉"), (1/2, "1/2玉")]
    best = min(candidates, key=lambda x: abs(ratio - x[0]))
    return f"{best[1]}（約{g}g）"


def g_to_piece_carrot(g, one_piece=150):
    """にんじんを本数に換算（1本=150gくらい）"""
    if g <= 0:
        return f"{g}g"
    pieces = g / one_piece
    return f"{round(pieces, 1)}本（約{g}g）"


def format_amount_friendly(name, amount, unit):
    """
    name/amount/unit から、家庭的な単位を含む表示用文字列を返す。
    """
    # g以外はそのまま返す（ここは必要なら拡張）
    if unit != "g":
        return f"{amount}{unit}"

    # name でざっくり分類（包含マッチ）
    n = str(name)

    # 米・ご飯
    if "米" in n:
        return g_to_cup_rice(amount)
    if "ご飯" in n or "ごはん" in n or "白ご飯" in n:
        # 炊きあがり1膳=150gくらい
        if amount <= 0:
            return f"{amount}g"
        bowls = amount / 150
        return f"{round(bowls, 1)}膳（約{amount}g）"

    # キャベツ・白菜・レタスなど葉物
    if "キャベツ" in n or "白菜" in n or "レタス" in n:
        return g_to_leaf_portion(amount, whole_weight=800)

    # にんじん
    if "にんじん" in n or "人参" in n:
        return g_to_piece_carrot(amount, one_piece=150)

    # 粉末・だし
    if any(key in n for key in ["だし", "出汁", "コンソメ", "粉末", "顆粒", "小麦粉", "片栗粉"]):
        return g_to_spoon_for_powder(amount)

    # 液体調味料
    if any(key in n for key in ["しょうゆ", "醤油", "みりん", "酒", "酢", "油", "オリーブオイル", "ごま油"]):
        return g_to_spoon_for_liquid(amount)

    # 卵
    if "卵" in n:
        # 1個=50gくらい
        pieces = amount / 50 if amount > 0 else 0
        return f"{round(pieces, 1)}個（約{amount}g）"

    # 鶏むね肉・豚こま等（とりあえずgのまま or 100g単位）
    if any(key in n for key in ["鶏むね", "鶏もも", "豚こま", "豚バラ", "牛こま", "ひき肉"]):
        if amount >= 100:
            return f"{round(amount/100, 1)}枚分（約{amount}g）"
        else:
            return f"{amount}g"

    # デフォルト: gのまま
    return f"{amount}g"


def add_display_amount_to_recipes(src_path: Path, dst_path: Path):
    with src_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # トップレベルが {"recipes": [...]} か、リストか、どちらも対応
    if isinstance(data, dict) and "recipes" in data:
        recipes = data["recipes"]
        wrapper = True
    elif isinstance(data, list):
        recipes = data
        wrapper = False
    else:
        raise ValueError("Unexpected JSON structure")

    for recipe in recipes:
        details = recipe.get("ingredients_detail") or recipe.get("ingredientsDetail") or []
        for ing in details:
            name = ing.get("name", "")
            amount = ing.get("amount", 0)
            unit = ing.get("unit", "g")
            try:
                # amount が文字列でも動くようにfloat化
                amount_val = float(amount)
            except (TypeError, ValueError):
                amount_val = 0
            display = format_amount_friendly(name, amount_val, unit)
            ing["display_amount"] = display

    # 新しいJSONとして保存
    if wrapper:
        out_data = {"recipes": recipes}
    else:
        out_data = recipes

    with dst_path.open("w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"変換完了: {dst_path}")


if __name__ == "__main__":
    add_display_amount_to_recipes(SRC_PATH, DST_PATH)
