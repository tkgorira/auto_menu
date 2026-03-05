import json
import random
import sqlite3
import os
import uuid
import tempfile
from collections import defaultdict

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

from google.cloud import vision

# ==== Render用: サービスアカウントJSONを環境変数からファイルに展開 ====
sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
if sa_json and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    tmp_path = os.path.join(tempfile.gettempdir(), "vision-key.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp_path
# =====================================================================

app = Flask(__name__)

print("=== APP STARTED WITH COST FEATURE ===", flush=True)

# セッション用のシークレットキー（本番では環境変数などで安全に管理）
app.secret_key = "change_this_to_random_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ==== DB を永続ディスクに置くための設定 ====
# 本番(Render)では DB_DIR=/var/data を環境変数で渡す
DB_DIR = os.environ.get("DB_DIR", BASE_DIR)
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "favorites.db")
print("=== DB_PATH ===", DB_PATH, flush=True)
# ============================================

RECIPES_JSON_PATH = os.path.join(BASE_DIR, "recipes.json")

# 単価マスタ
PRICE_MASTER_PATH = os.path.join(BASE_DIR, "prices.json")
if os.path.exists(PRICE_MASTER_PATH):
    with open(PRICE_MASTER_PATH, encoding="utf-8") as f:
        PRICE_MASTER = json.load(f)
else:
    PRICE_MASTER = {}


def get_price_per_100g(name: str):
    info = PRICE_MASTER.get(name)
    if not info:
        return None
    return info.get("price_per_100g")


def load_json_recipes():
    """recipes.json のトップレベルが list でも dict でも対応するローダー"""
    with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # パターンA: {"recipes": [...]} 形式
    if isinstance(data, dict) and "recipes" in data and isinstance(data["recipes"], list):
        return data["recipes"]

    # パターンB: すでにレシピのリスト
    if isinstance(data, list):
        return data

    # それ以外（id→レシピ dict など）は values を使う
    if isinstance(data, dict):
        return list(data.values())

    return []


# 画像アップロード用フォルダ
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Vision のラベル → recipes.json の ingredients 用キー
LABEL_TO_INGREDIENT = {
    # 肉類
    "chicken": "鶏むね肉",
    "chicken meat": "鶏むね肉",
    "chicken thigh": "鶏もも肉",
    "pork": "豚こま切れ肉",
    "pork belly": "豚バラブロック",
    "beef": "牛こま切れ肉",
    "ground beef": "牛ひき肉",
    "minced meat": "合い挽き肉",

    # 魚介
    "salmon": "鮭切り身",
    "salmon fillet": "鮭切り身",
    "fish": "白身魚切り身",
    "shrimp": "むきエビ",

    # 卵・乳製品
    "egg": "卵",
    "eggs": "卵",
    "milk": "牛乳",
    "cheese": "ピザ用チーズ",
    "cream cheese": "クリームチーズ",
    "butter": "バター",
    "yogurt": "ヨーグルト",

    # 主食
    "rice": "ご飯",
    "white rice": "ご飯",
    "bread": "食パン",
    "loaf": "食パン",
    "toast": "食パン",
    "noodles": "うどん",
    "udon": "うどん",
    "pasta": "スパゲッティ",
    "spaghetti": "スパゲッティ",

    # 野菜
    "cabbage": "キャベツ",
    "chinese cabbage": "白菜",
    "napa cabbage": "白菜",
    "lettuce": "レタス",
    "onion": "玉ねぎ",
    "green onion": "長ねぎ",
    "spring onion": "長ねぎ",
    "scallion": "長ねぎ",
    "leek": "長ねぎ",
    "carrot": "にんじん",
    "potato": "じゃがいも",
    "sweet potato": "さつまいも",
    "cucumber": "きゅうり",
    "tomato": "トマト",
    "cherry tomato": "ミニトマト",
    "eggplant": "なす",
    "aubergine": "なす",
    "bell pepper": "パプリカ",
    "green pepper": "ピーマン",
    "paprika": "パプリカ",
    "spinach": "ほうれん草",
    "broccoli": "ブロッコリー",
    "burdock": "ごぼう",
    "gobo": "ごぼう",
    "lotus root": "れんこん",
    "daikon": "大根",
    "radish": "大根",
    "mushroom": "しめじ",
    "shiitake": "しいたけ",
    "shimeji": "しめじ",
    "enoki": "えのきだけ",
    "corn": "コーン",

    # 大豆・豆製品・海藻など
    "tofu": "豆腐",
    "bean curd": "豆腐",
    "soybean": "大豆",
    "edamame": "枝豆",
    "seaweed": "わかめ",
    "wakame": "わかめ",
    "nori": "のり",

    # 加工品
    "bacon": "ベーコン",
    "sausage": "ソーセージ",
    "ham": "ハム",

    # 果物
    "banana": "バナナ",
    "apple": "りんご",
    "orange": "みかん",
}

# ===================== Vision 呼び出しヘルパ =====================
def map_labels_to_ingredients(labels):
    mapped = []
    for label in labels:
        key = LABEL_TO_INGREDIENT.get(label.lower())
        if key and key not in mapped:
            mapped.append(key)
    return mapped


def detect_ingredients_from_image(path):
    client = vision.ImageAnnotatorClient()
    with open(path, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    response = client.label_detection(image=image)
    annotations = response.label_annotations or []

    raw_labels = [a.description for a in annotations]
    print("Vision labels:", raw_labels)

    ingredients = map_labels_to_ingredients(raw_labels)
    return ingredients


# ===================== DB 接続ヘルパ =====================
def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT
        );

        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            recipe_id INTEGER,
            PRIMARY KEY (user_id, recipe_id)
        );

        CREATE TABLE IF NOT EXISTS user_recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            meal_type TEXT,
            role TEXT,
            tags TEXT,
            months TEXT,
            ingredients TEXT,
            allergy_flags TEXT,
            kcal REAL,
            protein REAL,
            fat REAL,
            carbs REAL,
            cook_time_min REAL
        );
        """
    )
    db.commit()
    db.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        init_db()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ===================== 匿名ユーザー管理 =====================
def ensure_anonymous_user():
    if "user_id" in session:
        return

    db = get_db()

    anon_id = session.get("anonymous_id")
    if anon_id:
        cur = db.execute(
            "SELECT id, nickname FROM users WHERE nickname = ?",
            (anon_id,),
        )
        row = cur.fetchone()
        if row:
            session["user_id"] = row["id"]
            session["nickname"] = ""
            return

    anon_id = "anon-" + uuid.uuid4().hex[:16]
    db.execute(
        "INSERT INTO users (nickname) VALUES (?)",
        (anon_id,),
    )
    db.commit()

    cur = db.execute(
        "SELECT id FROM users WHERE nickname = ?",
        (anon_id,),
    )
    row = cur.fetchone()

    session["anonymous_id"] = anon_id
    session["user_id"] = row["id"]
    session["nickname"] = ""


# ===================== 栄養関連 =====================
def get_recipe_nutrition(recipe):
    n = recipe.get("nutrition", {}) or {}
    return {
        "kcal": float(n.get("kcal", 0) or 0),
        "protein": float(n.get("protein", 0) or 0),
        "fat": float(n.get("fat", 0) or 0),
        "carbs": float(n.get("carbs", 0) or 0),
    }


def sum_nutrition(recipes):
    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for r in recipes:
        n = get_recipe_nutrition(r)
        total["kcal"] += n["kcal"]
        total["protein"] += n["protein"]
        total["fat"] += n["fat"]
        total["carbs"] += n["carbs"]
    for k in total:
        total[k] = round(total[k], 1)
    return total


# ===================== 材料集計・金額 =====================
def aggregate_ingredients(recipes):
    agg = defaultdict(lambda: {"total_amount": 0, "unit": "g"})
    for r in recipes:
        for ing in r.get("ingredients_detail", []):
            name = ing["name"]
            amount = ing["amount"]
            unit = ing.get("unit", "g")
            agg[name]["total_amount"] += amount
            agg[name]["unit"] = unit
    return dict(agg)


def estimate_cost(ingredients_agg):
    total = 0
    details = []
    for name, info in ingredients_agg.items():
        amount = info["total_amount"]
        unit = info["unit"]
        price_per_100g = get_price_per_100g(name)

        if price_per_100g is None or unit != "g":
            cost = 0
        else:
            cost = int(round(amount / 100 * price_per_100g))

        total += cost
        details.append({
            "name": name,
            "total_amount": amount,
            "unit": unit,
            "price_per_100g": price_per_100g,
            "cost": cost,
        })

    return {"total_cost": total, "details": details}


# ===================== レシピ単位の共有テキスト =====================
def format_ingredient_line(ing):
    name = ing.get("name")
    amount = ing.get("amount")
    unit = ing.get("unit", "")
    # recipes.json 側で display_amount が付いていれば優先
    display = ing.get("display_amount")
    if display:
        return f"{name} {display}"
    # なければ amount + unit そのまま
    return f"{name} {amount}{unit}"


def build_share_text_for_recipe(recipe):
    lines = [recipe.get("name", "メニュー")]
    details = recipe.get("ingredients_detail", []) or []
    for ing in details:
        lines.append("- " + format_ingredient_line(ing))
    return "\n".join(lines)


# ===================== 自作レシピ読み込みヘルパ =====================
def load_user_recipes(user_id):
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
            "id": int(row["id"]),
            "name": row["name"],
            "meal_type": meal_type,
            "role": row["role"],
            "tags": [],
            "months": months,
            "ingredients": ingredients,
            "allergy_flags": allergy_flags,
            "nutrition": {
                "kcal": row["kcal"] or 0,
                "protein": row["protein"] or 0,
                "fat": row["fat"] or 0,
                "carbs": row["carbs"] or 0,
            },
            "cook_time_min": row["cook_time_min"] if "cook_time_min" in row.keys() else 0,
        }
        result.append(recipe)
    return result


# ===================== 名前ベースの鍋/スープ判定 =====================
def is_nabe_by_name(recipe):
    name = recipe.get("name", "")
    return "鍋" in name


def is_soup_by_name(recipe):
    name = recipe.get("name", "")
    return ("スープ" in name) or ("汁" in name)


def is_soup_recipe(r):
    if is_soup_by_name(r):
        return True
    tags = r.get("tags", []) or []
    return "スープ" in tags


# ===================== お気に入り機能 =====================
@app.route("/favorite/add", methods=["POST"])
def favorite_add():
    ensure_anonymous_user()
    user_id = session["user_id"]
    recipe_id = request.form.get("recipe_id")

    if not recipe_id:
        flash("レシピIDが指定されていません。")
        return redirect(url_for("index"))

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

    return ("", 204)


@app.route("/favorite/list")
def favorite_list():
    ensure_anonymous_user()
    user_id = session["user_id"]

    db = get_db()
    cur = db.execute(
        "SELECT recipe_id FROM favorites WHERE user_id = ?",
        (user_id,),
    )
    rows = cur.fetchall()

    favorite_ids = {int(row["recipe_id"]) for row in rows}

    json_recipes = load_json_recipes()

    user_recipes = load_user_recipes(user_id)
    all_recipes = json_recipes + user_recipes

    favorite_recipes = [
        r for r in all_recipes
        if r.get("id") in favorite_ids
    ]

    return render_template(
        "favorites.html",
        recipes=favorite_recipes,
        nickname=None,
    )


@app.route("/favorite/delete", methods=["POST"])
def favorite_delete():
    ensure_anonymous_user()
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
    ensure_anonymous_user()

    if request.method == "POST":
        user_id = session["user_id"]

        name = request.form.get("name", "").strip()
        meal_types = request.form.getlist("meal_type")
        role = request.form.get("role", "main")
        ingredients = request.form.get("ingredients", "").strip()
        months_raw = request.form.get("months", "").strip()
        allergy_list = request.form.getlist("allergy_flags")

        kcal = request.form.get("kcal") or "0"
        protein = request.form.get("protein") or "0"
        fat = request.form.get("fat") or "0"
        carbs = request.form.get("carbs") or "0"

        cook_time_min = request.form.get("cook_time_min") or "0"

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
            cook_time_val = float(cook_time_min)
        except ValueError:
            flash("栄養素と調理時間は数字で入力してください。")
            return redirect(url_for("recipe_new"))

        db = get_db()
        db.execute(
            """
            INSERT INTO user_recipes (
                user_id, name, meal_type, role,
                tags, months, ingredients, allergy_flags,
                kcal, protein, fat, carbs, cook_time_min
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                cook_time_val,
            ),
        )
        db.commit()
        flash("レシピを登録しました。")
        return redirect(url_for("index"))

    return render_template(
        "recipe_new.html",
        nickname=None,
    )


# ===================== 画像アップロード → Vision → generate =====================
@app.route("/upload_photo", methods=["POST"])
def upload_photo():
    ensure_anonymous_user()

    file = request.files.get("fridge_photo_camera") or request.files.get("fridge_photo_file")
    if not file or file.filename == "":
        flash("画像が選択されていません。")
        return redirect(url_for("index"))

    filename = uuid.uuid4().hex + ".jpg"
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)

    ingredients = detect_ingredients_from_image(path)

    if not ingredients:
        flash("食材をうまく認識できませんでした。")
        return redirect(url_for("index"))

    session["vision_have_ingredients"] = ",".join(ingredients)
    session["vision_meal_types"] = request.form.getlist("meal_types") or ["dinner"]
    session["vision_days"] = request.form.get("days", "3")

    return redirect(url_for("generate_from_vision"))


@app.route("/generate_from_vision")
def generate_from_vision():
    ensure_anonymous_user()

    have_ingredients_raw = session.pop("vision_have_ingredients", "")
    meal_types = session.pop("vision_meal_types", ["dinner"])
    days_str = session.pop("vision_days", "3")

    try:
        days = int(days_str)
    except ValueError:
        days = 3

    json_recipes = load_json_recipes()

    user_recipes = load_user_recipes(session["user_id"])
    all_recipes = json_recipes + user_recipes

    target_meal_types = meal_types or ["dinner"]

    filtered_recipes = [
        r for r in all_recipes
        if any(mt in r.get("meal_type", []) for mt in target_meal_types)
    ]

    have_ingredients = [
        s.strip() for s in have_ingredients_raw.split(",") if s.strip()
    ]

    if have_ingredients:
        def match_score(r):
            ings = r.get("ingredients", [])
            return sum(1 for h in have_ingredients if h in ings)

        with_ingredients = [
            r for r in filtered_recipes
            if match_score(r) > 0
        ]
        if with_ingredients:
            filtered_recipes = sorted(
                with_ingredients,
                key=match_score,
                reverse=True,
            )

    diet = None
    seasonal = None
    month = None
    easy_level = "normal"
    ng_ingredients = ""

    menus_by_meal = {}
    daily_nutrition = []
    day_recipes = [[] for _ in range(days)]

    def meal_set_key(recipes_for_one_meal):
        main_id = None
        side_id = None
        soup_id = None
        for r in recipes_for_one_meal:
            if is_soup_recipe(r):
                soup_id = r.get("id")
            else:
                if r.get("role") == "side":
                    side_id = r.get("id")
                else:
                    main_id = r.get("id")
        return (main_id, side_id, soup_id)

    used_sets = set()
    used_side_ids_by_meal_type = {mt: set() for mt in target_meal_types}

    for mt in target_meal_types:
        mt_recipes = [
            r for r in filtered_recipes
            if mt in r.get("meal_type", [])
        ]

        soups = [r for r in mt_recipes if is_soup_recipe(r)]
        mains = [
            r for r in mt_recipes
            if r.get("role", "main") == "main" and not is_soup_recipe(r)
        ]
        sides = [
            r for r in mt_recipes
            if r.get("role", "main") == "side" and not is_soup_recipe(r)
        ]

        day_menus = []

        for day_index in range(days):
            max_retry = 100
            chosen_menu = None
            last_menu = None

            while max_retry > 0:
                max_retry -= 1

                menu = []

                if mains:
                    menu.append(random.choice(mains))

                if sides:
                    unused_sides = [
                        s for s in sides
                        if s.get("id") not in used_side_ids_by_meal_type[mt]
                    ]
                    if unused_sides:
                        side = random.choice(unused_sides)
                    else:
                        side = random.choice(sides)
                    menu.append(side)

                if soups:
                    menu.append(random.choice(soups))
                if not menu and mains:
                    menu.append(random.choice(mains))

                last_menu = menu
                key = (mt, meal_set_key(menu))

                if key not in used_sets:
                    used_sets.add(key)
                    chosen_menu = menu
                    break

            if chosen_menu is None:
                chosen_menu = last_menu

            for r in chosen_menu:
                if r.get("role") == "side":
                    used_side_ids_by_meal_type[mt].add(r.get("id"))

            day_menus.append(chosen_menu)
            day_recipes[day_index].extend(chosen_menu)

        menus_by_meal[mt] = day_menus

    for d in range(days):
        total = sum_nutrition(day_recipes[d])
        daily_nutrition.append(total)

    # 各レシピに share_text を付与
    for d in range(days):
        for r in day_recipes[d]:
            if r.get("ingredients_detail"):
                r["share_text"] = build_share_text_for_recipe(r)
            else:
                r["share_text"] = None

    daily_ingredients = []
    daily_costs = []
    for d in range(days):
        ing_agg = aggregate_ingredients(day_recipes[d])
        cost_info = estimate_cost(ing_agg)
        daily_ingredients.append(ing_agg)
        daily_costs.append(cost_info)

    nutrition_labels = {
        "protein": "たんぱく質",
        "fat": "脂質",
        "carbs": "炭水化物",
    }

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
        nickname=None,
        easy_level=easy_level,
        have_ingredients=have_ingredients,
        daily_ingredients=daily_ingredients,
        daily_costs=daily_costs,
    )


# ===================== 画面ルート =====================
@app.route("/")
def index():
    ensure_anonymous_user()
    return render_template(
        "index.html",
        nickname=None,
    )


@app.route("/generate", methods=["POST"])
def generate():
    ensure_anonymous_user()

    meal_types = request.form.getlist("meal_types")
    diet = request.form.get("diet")
    seasonal = request.form.get("seasonal")
    month = request.form.get("month")

    ng_presets = request.form.getlist("ng_preset")
    ng_ingredients = request.form.get("ng_ingredients", "")

    cuisine = request.form.get("cuisine", "")

    days_str = request.form.get("days", "3")
    try:
        days = int(days_str)
    except ValueError:
        days = 3

    easy_level = request.form.get("easy_level", "normal")
    have_ingredients_raw = request.form.get("have_ingredients", "")
    have_ingredients = [
        s.strip() for s in have_ingredients_raw.split(",") if s.strip()
    ]

    json_recipes = load_json_recipes()

    user_recipes = load_user_recipes(session["user_id"])
    all_recipes = json_recipes + user_recipes

    target_meal_types = meal_types or ["dinner"]

    filtered_recipes = [
        r for r in all_recipes
        if any(mt in r.get("meal_type", []) for mt in target_meal_types)
    ]

    if cuisine:
        filtered_recipes = [
            r for r in filtered_recipes
            if cuisine in (r.get("tags") or [])
        ]

    if diet:
        filtered_recipes = [
            r for r in filtered_recipes
            if "ダイエット" in r.get("tags", [])
        ]

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

    if have_ingredients:
        def match_score(r):
            ings = r.get("ingredients", [])
            return sum(1 for h in have_ingredients if h in ings)

        with_ingredients = [
            r for r in filtered_recipes
            if match_score(r) > 0
        ]

        if with_ingredients:
            filtered_recipes = sorted(
                with_ingredients,
                key=match_score,
                reverse=True,
            )

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

    if "breakfast" in target_meal_types:
        MAX_BREAKFAST_KCAL = 300.0

        def is_ok_breakfast(r):
            if "breakfast" not in r.get("meal_type", []):
                return True
            if r.get("role", "main") != "main":
                return True

            n = r.get("nutrition", {}) or {}
            try:
                kcal = float(n.get("kcal", 0) or 0)
            except (TypeError, ValueError):
                kcal = 0.0
            return kcal <= MAX_BREAKFAST_KCAL

        filtered_recipes = [
            r for r in filtered_recipes
            if is_ok_breakfast(r)
        ]

    menus_by_meal = {}
    daily_nutrition = []
    day_recipes = [[] for _ in range(days)]

    def meal_set_key(recipes_for_one_meal):
        main_id = None
        side_id = None
        soup_id = None
        for r in recipes_for_one_meal:
            if is_soup_recipe(r):
                soup_id = r.get("id")
            else:
                if r.get("role") == "side":
                    side_id = r.get("id")
                else:
                    main_id = r.get("id")
        return (main_id, side_id, soup_id)

    used_sets = set()
    used_side_ids_by_meal_type = {mt: set() for mt in target_meal_types}

    for mt in target_meal_types:
        mt_recipes = [
            r for r in filtered_recipes
            if mt in r.get("meal_type", [])
        ]

        soups = [r for r in mt_recipes if is_soup_recipe(r)]
        mains = [
            r for r in mt_recipes
            if r.get("role", "main") == "main" and not is_soup_recipe(r)
        ]
        sides = [
            r for r in mt_recipes
            if r.get("role", "main") == "side" and not is_soup_recipe(r)
        ]

        day_menus = []

        for day_index in range(days):
            max_retry = 100
            chosen_menu = None
            last_menu = None

            while max_retry > 0:
                max_retry -= 1

                menu = []

                if mains:
                    menu.append(random.choice(mains))

                if sides:
                    unused_sides = [
                        s for s in sides
                        if s.get("id") not in used_side_ids_by_meal_type[mt]
                    ]
                    if unused_sides:
                        side = random.choice(unused_sides)
                    else:
                        side = random.choice(sides)
                    menu.append(side)

                if soups:
                    menu.append(random.choice(soups))
                if not menu and mains:
                    menu.append(random.choice(mains))

                last_menu = menu
                key = (mt, meal_set_key(menu))

                if key not in used_sets:
                    used_sets.add(key)
                    chosen_menu = menu
                    break

            if chosen_menu is None:
                chosen_menu = last_menu

            for r in chosen_menu:
                if r.get("role") == "side":
                    used_side_ids_by_meal_type[mt].add(r.get("id"))

            day_menus.append(chosen_menu)
            day_recipes[day_index].extend(chosen_menu)

        menus_by_meal[mt] = day_menus

    for d in range(days):
        total = sum_nutrition(day_recipes[d])
        daily_nutrition.append(total)

    # 各レシピに share_text を付与
    for d in range(days):
        for r in day_recipes[d]:
            if r.get("ingredients_detail"):
                r["share_text"] = build_share_text_for_recipe(r)
            else:
                r["share_text"] = None

    daily_ingredients = []
    daily_costs = []
    for d in range(days):
        ing_agg = aggregate_ingredients(day_recipes[d])
        cost_info = estimate_cost(ing_agg)
        daily_ingredients.append(ing_agg)
        daily_costs.append(cost_info)

    nutrition_labels = {
        "protein": "たんぱく質",
        "fat": "脂質",
        "carbs": "炭水化物",
    }

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
        nickname=None,
        easy_level=easy_level,
        have_ingredients=have_ingredients,
        daily_ingredients=daily_ingredients,
        daily_costs=daily_costs,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
