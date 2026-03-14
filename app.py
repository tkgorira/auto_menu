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

# ==== コンテナローカル SQLite（永続なし）====
DB_DIR = BASE_DIR  # Render では /opt/render/project/src 相当
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "favorites.db")
print("=== DB_PATH ===", DB_PATH, flush=True)
# ============================================

# display_amount を含むJSON
RECIPES_JSON_PATH = os.path.join(BASE_DIR, "recipes_with_display.json")

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
    display = ing.get("display_amount")
    if display:
        return f"{name} {display}"
    return f"{name} {amount}{unit}"


def build_share_text_for_recipe(recipe):
    lines = [recipe.get("name", "メニュー")]
    details = recipe.get("ingredients_detail", []) or []
    for ing in details:
        lines.append("- " + format_ingredient_line(ing))
    return "\\\\n".join(lines)


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

