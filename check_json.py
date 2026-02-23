import json

with open("recipes.json", encoding="utf-8") as f:
    data = json.load(f)

print("OK! レシピ件数:", len(data["recipes"]))
