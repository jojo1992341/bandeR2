"""Test de non-régression du pipeline : le pipeline doit échouer si un lint error est introduit."""

import subprocess
import tempfile
import os
from pathlib import Path


def test_pipeline_fails_on_lint_error():
    # Créer temporairement un fichier avec erreur de lint ( ligne trop longue, indentation incorrecte )
    bad_file = Path("backend/bad_regression_test.py")
    bad_content = "def bad(x):\n\tpass\n    y=1+2\n"  # indentation mix + spacing
    bad_file.write_text(bad_content, encoding="utf-8")
    try:
        result = subprocess.run(
            ["black", "--check", "--diff", str(bad_file)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        # Le pipeline doit échouer (code non nul) sur erreur de lint
        assert (
            result.returncode != 0
        ), "Pipeline doit échouer sur erreur de lint (test de régression)"
    finally:
        if bad_file.exists():
            bad_file.unlink()
