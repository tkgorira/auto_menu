# scripts/ingredient_master.py

INGREDIENT_CATEGORY = {
    "ご飯": "staple_rice",
    "白ご飯": "staple_rice",
    "ごはん": "staple_rice",
    "食パン": "staple_bread",
    "ライ麦パン": "staple_bread",
    "バターロール": "staple_roll",

    "鶏むね肉": "meat",
    "鶏もも肉": "meat",
    "豚こま切れ": "meat",
    "豚バラ薄切り": "meat",
    "牛こま切れ": "meat",
    "ベーコン": "meat",
    "ハム": "meat",
    "ウインナー": "meat",

    "鮭": "fish",
    "鮭切り身": "fish",
    "サバ": "fish",
    "サバ缶": "fish",

    "卵": "egg",
    "牛乳": "dairy",
    "チーズ": "dairy",
    "粉チーズ": "dairy",
    "ヨーグルト": "dairy",

    "キャベツ": "leaf",
    "レタス": "leaf",
    "白菜": "leaf",
    "ほうれん草": "leaf",
    "小松菜": "leaf",

    "大根": "root",
    "にんじん": "root",
    "じゃがいも": "root",
    "玉ねぎ": "root",
    "かぼちゃ": "root",

    "きゅうり": "salad",
    "トマト": "salad",
    "ミニトマト": "salad",

    "塩": "seasoning",
    "砂糖": "seasoning",
    "しょうゆ": "seasoning",
    "みりん": "seasoning",
    "酒": "seasoning",
    "酢": "seasoning",
    "コンソメ": "seasoning",
    "顆粒だし": "seasoning",
    "バター": "seasoning",
    "マヨネーズ": "seasoning",
}

DEFAULT_AMOUNT_BY_CATEGORY = {
    "staple_rice": 150,
    "staple_bread": 60,
    "staple_roll": 35,

    "meat": 80,
    "fish": 80,
    "egg": 50,
    "dairy": 100,

    "leaf": 80,
    "root": 60,
    "salad": 40,

    "seasoning": 5,
    "other": 10,
}
