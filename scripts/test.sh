#!/usr/bin/env bash
set -euo pipefail

pushd backend
pytest
ruff check .
mypy app tests
popd

pushd frontend
npm run test
npm run typecheck
npm run build
popd
