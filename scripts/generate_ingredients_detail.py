import json
from ingredient_master import INGREDIENT_CATEGORY, DEFAULT_AMOUNT_BY_CATEGORY

INPUT = "recipes.json"
OUTPUT = "recipes_with_detail.json"

def classify_ingredient(name: str) -> str:
    return INGREDIENT_CATEGORY.get(name, "other")

def default_amount_for(name: str, servings: int = 1) -> int:
    category = classify_ingredient(name)
    base = DEFAULT_AMOUNT_BY_CATEGORY.get(category, DEFAULT_AMOUNT_BY_CATEGORY["other"])
    return base * servings

def generate_detail_for_recipe(recipe: dict) -> dict:
    if "ingredients_detail" in recipe:
        return recipe

    servings = recipe.get("servings", 1)

    details = []
    for ing in recipe.get("ingredients", []):
        details.append({
            "name": ing,
            "amount": default_amount_for(ing, servings),
            "unit": "g",
            "note": None,
        })
    recipe["ingredients_detail"] = details
    recipe.setdefault("servings", servings)
    return recipe

def main():
    with open(INPUT, encoding="utf-8") as f:
        data = json.load(f)

    # ★ ここでトップレベル構造を正規化する
    # パターン1: すでに「レシピのリスト」
    if isinstance(data, list):
        recipes = data

    # パターン2: {"recipes": [...]} のようなdict
    elif isinstance(data, dict):
        if "recipes" in data and isinstance(data["recipes"], list):
            recipes = data["recipes"]
        else:
            # それ以外のdict構造（id→レシピなど）の場合
            recipes = list(data.values())
    else:
        raise TypeError(f"Unexpected JSON root type: {type(data)}")

    # レシピ配列に対して処理
    new_recipes = [generate_detail_for_recipe(r) for r in recipes]

    # 元の構造に合わせて戻す（とりあえず配列で出力でOKなら new_recipes だけでもOK）
    out = new_recipes

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
