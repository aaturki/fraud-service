"""scripts/regen_golden.py refuses the three ways a golden file gets silently corrupted."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/regen_golden.py")
GOLDEN = Path("data/golden_scores_v3.csv")

pytestmark = pytest.mark.integration


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)


def test_a_reason_is_mandatory():
    result = _run("--reason", "too short")
    assert result.returncode == 2
    assert "Refused" in result.stdout


@pytest.mark.slow                     # rescores all 5,000 rows: runs with the golden test
def test_same_model_and_same_scores_means_nothing_to_do():
    before = GOLDEN.read_bytes()
    result = _run("--reason", "checking that the served model still reproduces the file")
    assert result.returncode == 0
    assert "Nothing to regenerate" in result.stdout
    assert GOLDEN.read_bytes() == before                     # untouched


@pytest.mark.slow
def test_changed_scores_under_the_same_version_are_skew_not_a_new_model(tmp_path):
    altered = tmp_path / "golden.csv"
    shutil.copy(GOLDEN, altered)
    lines = altered.read_text(encoding="utf-8").splitlines()
    first = lines[1].rsplit(",", 1)
    lines[1] = f"{first[0]},0.999999999"                      # one score moved
    altered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = _run("--reason", "simulated change under the same model version", "--golden",
                  str(altered))
    assert result.returncode == 3
    assert "skew" in result.stdout
    assert altered.read_text(encoding="utf-8").splitlines()[1].endswith("0.999999999")
