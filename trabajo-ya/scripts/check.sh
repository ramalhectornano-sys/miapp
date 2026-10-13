#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/backend"
python -m unittest discover -s tests -v
python -m compileall -q app
cd "$project_dir"
python scripts/build_database_install.py --check
python -m unittest discover -s deploy/google-cloud -p 'test_*.py' -v
cd "$project_dir/mobile"
npm run test
npm run typecheck
EXPO_PUBLIC_DEMO_MODE=true npm run export:android
cd "$project_dir/supabase"
npm test
