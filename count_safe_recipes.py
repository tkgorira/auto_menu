import json
from pathlib import Path

INPUT_PATH = Path("recipes.json")

# NG食材リスト（必要に応じて追加・調整）
NG_INGREDIENTS = [
    "卵",
    "乳",
    "小麦",
    "玉ねぎ",
    "ピーマン",
    "にんじん",
    "しいたけ",
    "えのき",
    "しめじ",
    "まいたけ",
    "エリンギ",
    "魚",
    "鮭",
    "鮭切り身",
    "鮭フレーク",
]

def recipe_has_ng_ingredient(recipe) -> bool:
    ingredients = recipe.get("ingredients", [])
    for ing in ingredients:
        for ng in NG_INGREDIENTS:
            if ng in ing:  # 部分一致でNG判定
                return True
    return False

def main():
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    recipes = data["recipes"]

    breakfast_side_ok = 0
    lunch_side_ok = 0

    for r in recipes:
        # side だけ対象
        if r.get("role") != "side":
            continue
        if recipe_has_ng_ingredient(r):
            continue

        meal_types = r.get("meal_type", [])
        if "breakfast" in meal_types:
            breakfast_side_ok += 1
        if "lunch" in meal_types:
            lunch_side_ok += 1

    print(f"NG食材なしの朝食 side レシピ数: {breakfast_side_ok}")
    print(f"NG食材なしの昼食 side レシピ数: {lunch_side_ok}")

if __name__ == "__main__":
    main()
