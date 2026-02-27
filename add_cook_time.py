import json

# 1. 読み込み
with open("recipes.json", "r", encoding="utf-8") as f:
    data = json.load(f)

recipes = data.get("recipes", [])

# 2. 適当なルールで cook_time_min を自動付与
#    ここでは role と tags でざっくり決める例
for r in recipes:
    # 既に cook_time_min がある場合はスキップ（再実行しても安全）
    if "cook_time_min" in r:
        continue

    role = r.get("role", "main")
    tags = r.get("tags", [])

    # ザックリ決め（好きに変えてOK）
    if "簡単" in tags or "時短" in tags:
        base = 10
    elif role == "side":
        base = 15
    else:
        base = 25

    # 必要なら微調整してもOK
    r["cook_time_min"] = base

# 3. 書き戻し
with open("recipes.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("done")
