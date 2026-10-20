@echo off
title Push to GitHub
cls
echo.
echo  ========================================================
echo    PUSH TO GITHUB
echo    Repo: https://github.com/rowanchanner/Movie-scraper-vidsc-ect-
echo  ========================================================
echo.

cd /d "%~dp0"

:: 1. Ensure Git repository initialized
if not exist ".git" (
    echo  [*] Initializing local Git repository...
    git init
)

:: 2. Set remote origin
git remote remove origin 2>nul
git remote add origin https://github.com/rowanchanner/Movie-scraper-vidsc-ect-.git

:: 3. Configure branch to main
git branch -M main

:: 4. Stage all files (api_key.txt is protected by .gitignore)
echo  [*] Staging files...
git add .

:: 5. Commit
set /p commit_msg="Enter commit message (Press Enter for 'Initial release'): "
if "%commit_msg%"=="" set commit_msg=Initial release

echo  [*] Committing changes...
git commit -m "%commit_msg%" 2>nul
if errorlevel 1 (
    echo  [*] No new changes to commit.
)

:: 6. Sync remote license/readme if present
echo.
echo  [*] Syncing with remote repository...
git pull origin main --rebase --allow-unrelated-histories 2>nul

:: 7. Push to GitHub
echo  [*] Pushing to GitHub (origin/main)...
echo.
git push -u origin main

if errorlevel 1 (
    echo.
    echo  [!] Standard push rejected. Forcing push to remote...
    git push -u origin main --force
)

if errorlevel 1 (
    echo.
    echo  [X] Push failed. Make sure you have git credentials configured.
) else (
    echo.
    echo  ========================================================
    echo    [✓] Successfully pushed to GitHub!
    echo    View online: https://github.com/rowanchanner/Movie-scraper-vidsc-ect-
    echo  ========================================================
)

echo.
pause
