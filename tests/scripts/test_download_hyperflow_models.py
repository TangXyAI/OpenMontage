import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "download_hyperflow_models.py"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_dry_run_lists_modelscope_sources_and_sizes():
    result = run("--variant", "gguf", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "VideoRebirthAI/hyperflow-h3-flash" in result.stdout
    assert "9.05 GB" in result.stdout and "9.22 GB" in result.stdout
    assert "Comfy-Org/MiniMax-H3" in result.stdout
    assert "1.99 GB" in result.stdout


def test_real_run_requires_license_acceptance():
    result = run("--variant", "gguf")
    assert result.returncode == 2
    assert "accept-license" in result.stderr.lower()
