#!/bin/zsh
cd /Users/wansangryu/finance
source .venv/bin/activate
python -u run_comparison.py > run_comparison.log 2>&1
