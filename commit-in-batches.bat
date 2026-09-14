@echo off
setlocal enabledelayedexpansion

REM Configuration
set "MAX_FILES_PER_COMMIT=5"
set "SLEEP_SECONDS=10"
set "COMMIT_MESSAGE_PREFIX=Batch commit"

REM Ensure we're inside a git repo
git rev-parse --is-inside-work-tree >NUL 2>&1
if errorlevel 1 (
  echo This directory is not a git repository.
  exit /b 1
)

REM Switch to repo root (in case started in subdir)
for /f "usebackq delims=" %%R in (`git rev-parse --show-toplevel`) do set "REPO_ROOT=%%R"
cd /d "%REPO_ROOT%"

set /a COMMIT_INDEX=1

:LOOP
REM Collect up to MAX_FILES_PER_COMMIT changed paths (modified, untracked, deleted)
set "FILES_TO_COMMIT="
set /a COUNT=0

for /f "usebackq delims=" %%F in (`git ls-files -m -o -d --exclude-standard`) do (
  if !COUNT! lss %MAX_FILES_PER_COMMIT% (
    set "FILES_TO_COMMIT=!FILES_TO_COMMIT! ""%%F"""
    set /a COUNT+=1
  )
)

if !COUNT! EQU 0 (
  echo No more changed files to commit. Done.
  goto END
)

echo Committing !COUNT! file^(s^):
for %%X in (!FILES_TO_COMMIT!) do echo   %%~X

git add -A -- !FILES_TO_COMMIT!
if errorlevel 1 (
  echo Failed to add files.
  exit /b 1
)

git commit -m "%COMMIT_MESSAGE_PREFIX% #!COMMIT_INDEX!"
if errorlevel 1 (
  echo Commit failed.
  exit /b 1
)

set /a COMMIT_INDEX+=1

echo Waiting %SLEEP_SECONDS% seconds before next commit...
timeout /t %SLEEP_SECONDS% /nobreak >NUL

goto LOOP

:END
endlocal
exit /b 0


