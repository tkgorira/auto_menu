@echo off
REM ==============================
REM recipes.json 専用 git push スクリプト
REM ==============================

REM この .bat ファイルがあるディレクトリに移動
cd /d %~dp0

REM 変更状況を表示
echo ==== git status ====
git status

echo.
echo コミットメッセージを入力してください (例: update recipes):
set /p MSG=>

REM recipes.json だけステージング
git add recipes.json

REM 他に add したくなければここで確認
echo.
echo ==== git diff --cached ====
git diff --cached

echo.
echo この内容でコミットしてよいですか？ (y/n):
set /p ANS=>

if /I not "%ANS%"=="y" (
    echo 中止しました。
    pause
    goto :EOF
)

REM コミット
git commit -m "%MSG%"

REM push
git push

echo.
echo ==== 完了しました ====
pause
