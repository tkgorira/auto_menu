import json

RECIPES_JSON_PATH = "recipes.json"
OUTPUT_TXT_PATH = "ingredients_list.txt"

with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

recipes = data.get("recipes", [])

ingredients_set = set()

for r in recipes:
    for ing in r.get("ingredients", []):
        ingredients_set.add(ing)

# ソートしてテキストファイルに書き出し
with open(OUTPUT_TXT_PATH, "w", encoding="utf-8") as f:
    for ing in sorted(ingredients_set):
        f.write(ing + "\n")

print(f"食材一覧を {OUTPUT_TXT_PATH} に書き出しました。")
