import sqlite3

def main():
    # favorites.db というファイル名でSQLite DBを作成／接続
    conn = sqlite3.connect("favorites.db")
    cur = conn.cursor()

    # users テーブル（ニックネームでユーザー管理）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT UNIQUE NOT NULL
    )
    """)

    # favorites テーブル（ユーザーごとのお気に入りレシピID）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        recipe_id INTEGER NOT NULL,
        UNIQUE(user_id, recipe_id)
    )
    """)

    # user_recipes テーブル（ユーザーが手動で追加するレシピ）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_recipes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        name          TEXT NOT NULL,
        meal_type     TEXT NOT NULL,  -- "breakfast,lunch" などカンマ区切り
        role          TEXT NOT NULL,  -- "main" or "side"
        tags          TEXT,           -- 将来用
        months        TEXT,           -- "1,2,3" など（空なら通年）
        ingredients   TEXT,           -- "鮭切り身, 塩" など
        allergy_flags TEXT,           -- "卵,乳" など
        kcal          REAL,
        protein       REAL,
        fat           REAL,
        carbs         REAL
    )
    """)

    conn.commit()
    conn.close()
    print("favorites.db を初期化しました。")

if __name__ == "__main__":
    main()
