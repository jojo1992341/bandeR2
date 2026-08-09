"""Test de non-régression du pipeline : le pipeline doit échouer si un lint error est introduit."""

import subprocess
import tempfile
import os
from pathlib import Path


def test_pipeline_fails_on_lint_error():
    # Le projet utilise `ruff` comme formateur/linleur (requirements-dev.txt) ;
    # `black` est désactivé. On vérifie donc la régression via ruff.
    repo_root = Path(__file__).resolve().parent.parent.parent
    bad_file = repo_root / "backend" / "bad_regression_test.py"
    bad_content = "def bad(x):\n\tpass\n    y=1+2\n"  # indentation mixte (tab + spaces)
    bad_file.write_text(bad_content, encoding="utf-8")
    try:
        # ruff format --check échoue (code non nul) si le fichier n'est pas formaté
        result = subprocess.run(
            ["ruff", "format", "--check", str(bad_file)],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        # Le pipeline doit échouer (code non nul) sur erreur de lint
        assert (
            result.returncode != 0
        ), "Pipeline doit échouer sur erreur de lint (test de régression)"
    finally:
        if bad_file.exists():
            bad_file.unlink()
