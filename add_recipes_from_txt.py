#!/usr/bin/env python3
import json
from pathlib import Path

RECIPES_JSON_PATH = Path("recipes.json")
NEW_RECIPES_TXT_PATH = Path("new_recipes.txt")


def parse_line_to_recipe(line: str, next_id: int) -> dict:
    """
    1行のテキストをパースしてレシピdictを返す。
    フォーマット:
    name,meal_type,role,tags,months,ingredients,allergy,kcal,protein,fat,carbs,cook_time
    """
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 12:
        raise ValueError(f"項目数が12個ではありません: {len(parts)}個\nline={line}")

    (
        name,
        meal_type,
        role,
        tags_str,
        months_str,
        ingredients_str,
        allergy_str,
        kcal_str,
        protein_str,
        fat_str,
        carbs_str,
        cook_time_str,
    ) = parts

    tags = [t for t in tags_str.split() if t]
    months = [int(m) for m in months_str.split() if m]
    ingredients = [i for i in ingredients_str.split() if i]
    allergy_flags = [a for a in allergy_str.split() if a]

    def to_float(s):
        return float(s) if s else 0.0

    kcal = to_float(kcal_str)
    protein = to_float(protein_str)
    fat = to_float(fat_str)
    carbs = to_float(carbs_str)
    cook_time_min = int(to_float(cook_time_str))

    recipe = {
        "id": next_id,
        "name": name,
        "meal_type": [meal_type],
        "role": role,
        "tags": tags,
        "months": months,
        "ingredients": ingredients,
        "allergy_flags": allergy_flags,
        "nutrition": {
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
        },
        "cook_time_min": cook_time_min,
    }
    return recipe


def load_recipes():
    if RECIPES_JSON_PATH.exists():
        data = json.loads(RECIPES_JSON_PATH.read_text(encoding="utf-8"))
    else:
        data = {"recipes": []}
    recipes = data.get("recipes", [])
    return data, recipes


def save_recipes(data):
    RECIPES_JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def main():
    if not NEW_RECIPES_TXT_PATH.exists():
        print(f"{NEW_RECIPES_TXT_PATH} が見つかりません。")
        return

    raw = NEW_RECIPES_TXT_PATH.read_text(encoding="utf-8").splitlines()

    lines = []
    for l in raw:
        s = l.strip()
        if not s:
            continue          # 空行はスキップ
        if s.startswith("#"):
            continue          # コメント行はスキップ
        lines.append(s)

    if not lines:
        print("new_recipes.txt に有効な行がありません。")
        return

    data, recipes = load_recipes()
    max_id = max((r.get("id", 0) for r in recipes), default=0)
    next_id = max_id + 1

    added = 0
    for line in lines:
        try:
            recipe = parse_line_to_recipe(line, next_id)
        except Exception as e:
            print(f"この行の追加に失敗しました: {line}")
            print(f"理由: {e}")
            continue

        recipes.append(recipe)
        next_id += 1
        added += 1

    data["recipes"] = recipes
    save_recipes(data)

    print(f"{added} 件のレシピを追加しました。")

    # 取り込み後に new_recipes.txt を空にしたい場合は以下を有効化
    # NEW_RECIPES_TXT_PATH.write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
