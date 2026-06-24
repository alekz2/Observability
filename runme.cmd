@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"
set "REMOTE_QUERY_POLICY_PATH=%ROOT%config\policy.json"

python -m uvicorn remote_query_service.main:app --app-dir "%ROOT%src"
