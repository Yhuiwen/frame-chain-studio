Push-Location backend
pytest
ruff check .
mypy app tests
Pop-Location

Push-Location frontend
npm.cmd run test
npm.cmd run typecheck
npm.cmd run build
Pop-Location
