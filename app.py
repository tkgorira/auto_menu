import json
import random
import sqlite3
import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    g,
    flash,
)

app = Flask(__name__)

# セッション用のシークレットキー（本番では環境変数などで安全に管理）
app.secret_key = "change_this_to_random_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "favorites.db")
RECIPES_JSON_PATH = os.path.join(BASE_DIR, "recipes.json")


# ===================== DB 接続ヘルパ =====================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ===================== 栄養関連 =====================
def get_recipe_nutrition(recipe):
    """
    レシピ1品分の栄養 dict を返す。
    nutrition が無い場合・不足しているキーは 0 として扱う。
    """
    n = recipe.get("nutrition", {}) or {}
    return {
        "kcal": float(n.get("kcal", 0) or 0),
        "protein": float(n.get("protein", 0) or 0),
        "fat": float(n.get("fat", 0) or 0),
        "carbs": float(n.get("carbs", 0) or 0),
    }


def sum_nutrition(recipes):
    """
    レシピのリストを受け取り、栄養の合計値 dict を返す。
    """
    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for r in recipes:
        n = get_recipe_nutrition(r)
        total["kcal"] += n["kcal"]
        total["protein"] += n["protein"]
        total["fat"] += n["fat"]
        total["carbs"] += n["carbs"]
    # 小数第1位に丸め
    for k in total:
        total[k] = round(total[k], 1)
    return total


# ===================== 自作レシピ読み込みヘルパ =====================
def load_user_recipes(user_id):
    """
    user_recipes テーブルからログインユーザーのレシピを読み込み、
    recipes.json と同じ形の dict に変換して返す。
    """
    db = get_db()
    cur = db.execute(
        "SELECT * FROM user_recipes WHERE user_id = ?",
        (user_id,),
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        meal_type = [s.strip() for s in (row["meal_type"] or "").split(",") if s.strip()]
        ingredients = [s.strip() for s in (row["ingredients"] or "").split(",") if s.strip()]
        allergy_flags = [s.strip() for s in (row["allergy_flags"] or "").split(",") if s.strip()]
        months = [int(s) for s in (row["months"] or "").split(",") if s.strip().isdigit()]

        recipe = {
            "id": int(row["id"]),  # user_recipes の id をそのまま利用
            "name": row["name"],
            "meal_type": meal_type,
            "role": row["role"],
            "tags": [],  # 必要なら row["tags"] を分割して入れる
            "months": months,
            "ingredients": ingredients,
            "allergy_flags": allergy_flags,
            "nutrition": {
                "kcal": row["kcal"] or 0,
                "protein": row["protein"] or 0,
                "fat": row["fat"] or 0,
                "carbs": row["carbs"] or 0,
            },
        }
        result.append(recipe)
    return result


# ===================== 名前ベースの鍋/スープ判定 =====================
def is_nabe_by_name(recipe):
    """
    レシピ名に「鍋」が含まれていれば鍋扱い。
    """
    name = recipe.get("name", "")
    return "鍋" in name


def is_soup_by_name(recipe):
    """
    レシピ名に「スープ」または「汁」が含まれていればスープ扱い。
    """
    name = recipe.get("name", "")
    return ("スープ" in name) or ("汁" in name)


# ===================== ログイン関連 =====================
@app.route("/login", methods=["POST"])
def login():
    """
    ニックネームを使った簡易ログイン。
    users テーブルに存在しなければ INSERT。
    """
    nickname = request.form.get("nickname", "").strip()
    if not nickname:
        flash("ニックネームを入力してください。")
        return redirect(url_for("index"))

    db = get_db()
    # 既存ユーザーを検索
    cur = db.execute(
        "SELECT id FROM users WHERE nickname = ?",
        (nickname,),
    )
    row = cur.fetchone()

    if row is None:
        # なければ新規作成
        db.execute(
            "INSERT INTO users (nickname) VALUES (?)",
            (nickname,),
        )
        db.commit()
        cur = db.execute(
            "SELECT id FROM users WHERE nickname = ?",
            (nickname,),
        )
        row = cur.fetchone()

    session.clear()
    session["user_id"] = row["id"]
    session["nickname"] = nickname

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ===================== お気に入り機能 =====================
@app.route("/favorite/add", methods=["POST"])
def favorite_add():
    """
    結果画面からお気に入りに追加。
    favorites テーブルに (user_id, recipe_id) を INSERT OR IGNORE。
    """
    if "user_id" not in session:
        flash("お気に入り機能を使うには、ニックネームでログインしてください。")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    recipe_id = request.form.get("recipe_id")

    if not recipe_id:
        flash("レシピIDが指定されていません。")
        return redirect(url_for("index"))

    # INTEGER として扱う
    try:
        recipe_id_int = int(recipe_id)
    except ValueError:
        flash("レシピIDの形式が不正です。")
        return redirect(url_for("index"))

    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO favorites (user_id, recipe_id) VALUES (?, ?)",
        (user_id, recipe_id_int),
    )
    db.commit()

    flash("お気に入りに追加しました。")
    return redirect(url_for("index"))


@app.route("/favorite/list")
def favorite_list():
    """
    ログイン中ユーザーの favorites から recipe_id を取得し、
    recipes.json + 自作レシピから対応レシピを抽出して表示。
    """
    if "user_id" not in session:
        flash("お気に入り機能を使うには、ニックネームでログインしてください。")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    db = get_db()
    cur = db.execute(
        "SELECT recipe_id FROM favorites WHERE user_id = ?",
        (user_id,),
    )
    rows = cur.fetchall()

    favorite_ids = {int(row["recipe_id"]) for row in rows}

    # JSONレシピ
    with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    json_recipes = data.get("recipes", [])

    # 自作レシピ
    user_recipes = load_user_recipes(user_id)

    all_recipes = json_recipes + user_recipes

    favorite_recipes = [
        r for r in all_recipes
        if r.get("id") in favorite_ids
    ]

    return render_template(
        "favorites.html",
        recipes=favorite_recipes,
        nickname=session.get("nickname"),
    )


@app.route("/favorite/delete", methods=["POST"])
def favorite_delete():
    """
    お気に入り一覧から削除。
    """
    if "user_id" not in session:
        flash("お気に入り機能を使うには、ニックネームでログインしてください。")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    recipe_id = request.form.get("recipe_id")

    if not recipe_id:
        flash("レシピIDが指定されていません。")
        return redirect(url_for("favorite_list"))

    try:
        recipe_id_int = int(recipe_id)
    except ValueError:
        flash("レシピIDの形式が不正です。")
        return redirect(url_for("favorite_list"))

    db = get_db()
    db.execute(
        "DELETE FROM favorites WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id_int),
    )
    db.commit()

    flash("お気に入りから削除しました。")
    return redirect(url_for("favorite_list"))


# ===================== 自作レシピ登録 =====================
@app.route("/recipe/new", methods=["GET", "POST"])
def recipe_new():
    if "user_id" not in session:
        flash("レシピを登録するには、ニックネームでログインしてください。")
        return redirect(url_for("index"))

    if request.method == "POST":
        user_id = session["user_id"]

        name = request.form.get("name", "").strip()
        meal_types = request.form.getlist("meal_type")  # ["breakfast", "dinner"] など
        role = request.form.get("role", "main")
        ingredients = request.form.get("ingredients", "").strip()
        months_raw = request.form.get("months", "").strip()
        allergy_list = request.form.getlist("allergy_flags")

        # 栄養
        kcal = request.form.get("kcal") or "0"
        protein = request.form.get("protein") or "0"
        fat = request.form.get("fat") or "0"
        carbs = request.form.get("carbs") or "0"

        if not name:
            flash("レシピ名を入力してください。")
            return redirect(url_for("recipe_new"))

        meal_type_str = ",".join(meal_types)
        months_str = months_raw
        allergy_flags_str = ",".join(allergy_list)

        try:
            kcal_val = float(kcal)
            protein_val = float(protein)
            fat_val = float(fat)
            carbs_val = float(carbs)
        except ValueError:
            flash("栄養素は数字で入力してください。")
            return redirect(url_for("recipe_new"))

        db = get_db()
        db.execute(
            """
            INSERT INTO user_recipes (
                user_id, name, meal_type, role,
                tags, months, ingredients, allergy_flags,
                kcal, protein, fat, carbs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name,
                meal_type_str,
                role,
                "",
                months_str,
                ingredients,
                allergy_flags_str,
                kcal_val,
                protein_val,
                fat_val,
                carbs_val,
            ),
        )
        db.commit()
        flash("レシピを登録しました。")
        return redirect(url_for("index"))

    return render_template(
        "recipe_new.html",
        nickname=session.get("nickname"),
    )


# ===================== 画面ルート =====================
@app.route("/")
def index():
    return render_template(
        "index.html",
        nickname=session.get("nickname"),
    )


@app.route("/generate", methods=["POST"])
def generate():
    # フォームから値を取得
    meal_types = request.form.getlist("meal_types")
    diet = request.form.get("diet")
    seasonal = request.form.get("seasonal")
    month = request.form.get("month")

    ng_presets = request.form.getlist("ng_preset")
    ng_ingredients = request.form.get("ng_ingredients", "")

    days_str = request.form.get("days", "3")
    try:
        days = int(days_str)
    except ValueError:
        days = 3

    # ★ 追加: 手軽さ / 冷蔵庫の食材
    easy_level = request.form.get("easy_level", "normal")
    have_ingredients_raw = request.form.get("have_ingredients", "")
    have_ingredients = [
        s.strip() for s in have_ingredients_raw.split(",") if s.strip()
    ]

    # JSON
    with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    json_recipes = data.get("recipes", [])

    # 自作レシピ
    if "user_id" in session:
        user_recipes = load_user_recipes(session["user_id"])
        all_recipes = json_recipes + user_recipes
    else:
        all_recipes = json_recipes

    target_meal_types = meal_types or ["dinner"]

    filtered_recipes = [
        r for r in all_recipes
        if any(mt in r.get("meal_type", []) for mt in target_meal_types)
    ]

    # 1. ダイエット
    if diet:
        filtered_recipes = [
            r for r in filtered_recipes
            if "ダイエット" in r.get("tags", [])
        ]

    # 2. 季節
    month_int = None
    try:
        month_int = int(month)
    except (TypeError, ValueError):
        month_int = None

    if seasonal and month_int is not None:
        seasonal_recipes = [
            r for r in filtered_recipes
            if month_int in r.get("months", [])
        ]
        if seasonal_recipes:
            filtered_recipes = seasonal_recipes

    # 3. アレルギー
    allergy_flags = []
    if request.form.get("allergy_egg"):
        allergy_flags.append("卵")
    if request.form.get("allergy_milk"):
        allergy_flags.append("乳")
    if request.form.get("allergy_wheat"):
        allergy_flags.append("小麦")

    if allergy_flags:
        filtered_recipes = [
            r for r in filtered_recipes
            if not any(flag in r.get("allergy_flags", []) for flag in allergy_flags)
        ]

    # 4. NG食材
    free_ng_list = [
        s.strip() for s in ng_ingredients.split(",")
        if s.strip()
    ]
    ng_list = ng_presets + free_ng_list

    if ng_list:
        filtered_recipes = [
            r for r in filtered_recipes
            if not any(ng in r.get("ingredients", []) for ng in ng_list)
        ]

    # ★ 4.5 冷蔵庫の食材マッチ度でソート
    if have_ingredients:
        def match_score(r):
            ings = r.get("ingredients", [])
            return sum(1 for h in have_ingredients if h in ings)

        filtered_recipes = sorted(
            filtered_recipes,
            key=match_score,
            reverse=True,
        )

    # ★ 4.6 手軽メニューの優先
    if easy_level == "easy":
        def easy_score(r):
            tags = r.get("tags", [])
            score = 0
            if "時短" in tags or "簡単" in tags:
                score += 2
            if "フライパン1つ" in tags or "レンチン" in tags:
                score += 1
            return score

        filtered_recipes = sorted(
            filtered_recipes,
            key=easy_score,
            reverse=True,
        )

    # 5. メニュー生成（鍋とスープを同日にしない）
    menus_by_meal = {}
    daily_nutrition = []
    day_recipes = [[] for _ in range(days)]

    for mt in target_meal_types:
        mt_recipes = [
            r for r in filtered_recipes
            if mt in r.get("meal_type", [])
        ]

        main_recipes = [r for r in mt_recipes if r.get("role", "main") == "main"]
        side_recipes = [r for r in mt_recipes if r.get("role", "main") == "side"]

        day_menus = []

        if main_recipes and side_recipes:
            for day_index in range(days):
                # その日に既に鍋/スープがあるか名前から判定
                has_nabe = any(is_nabe_by_name(r) for r in day_recipes[day_index])
                has_soup = any(is_soup_by_name(r) for r in day_recipes[day_index])

                # メイン候補をフィルタして「鍋とスープが同日にならない」ようにする
                filtered_mains = main_recipes
                if has_nabe:
                    filtered_mains = [r for r in filtered_mains if not is_soup_by_name(r)]
                if has_soup:
                    filtered_mains = [r for r in filtered_mains if not is_nabe_by_name(r)]

                if filtered_mains:
                    main = random.choice(filtered_mains)
                else:
                    # どうしても無ければ制約なしで選ぶ
                    main = random.choice(main_recipes)

                # 副菜
                if len(side_recipes) >= 2:
                    sides = random.sample(side_recipes, k=2)
                else:
                    k = min(2, len(side_recipes))
                    sides = random.choices(side_recipes, k=k) if k > 0 else []

                day_menu = [main] + sides
                day_menus.append(day_menu)
                day_recipes[day_index].extend(day_menu)
        else:
            for day_index in range(days):
                day_menus.append([])

        menus_by_meal[mt] = day_menus

    # 6. 日ごとの栄養
    for d in range(days):
        total = sum_nutrition(day_recipes[d])
        daily_nutrition.append(total)

    nutrition_labels = {
        "protein": "たんぱく質",
        "fat": "脂質",
        "carbs": "炭水化物",
    }

    # 7. 買い物リスト
    ingredients_set = set()
    for day_menus in menus_by_meal.values():
        for day_menu in day_menus:
            for r in day_menu:
                for ing in r.get("ingredients", []):
                    ingredients_set.add(ing)
    shopping_list = sorted(ingredients_set)

    return render_template(
        "result.html",
        days=days,
        meal_types=target_meal_types,
        diet=diet,
        seasonal=seasonal,
        month=month,
        ng_ingredients=ng_ingredients,
        menus_by_meal=menus_by_meal,
        shopping_list=shopping_list,
        daily_nutrition=daily_nutrition,
        nutrition_labels=nutrition_labels,
        nickname=session.get("nickname"),
        easy_level=easy_level,             # ★ 追加
        have_ingredients=have_ingredients  # ★ 追加
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
