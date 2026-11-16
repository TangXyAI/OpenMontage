"""The installable package includes the tokenizer needed by Thai captions."""
import shutil
import subprocess
import sys
from pathlib import Path


def test_package_metadata_declares_thai_tokenizer(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copy(root / "setup.py", tmp_path / "setup.py")
    subprocess.run([sys.executable, "setup.py", "egg_info"], cwd=tmp_path, check=True, capture_output=True, text=True)
    requirements = (tmp_path / "openmontage.egg-info" / "requires.txt").read_text()
    assert "pythainlp>=5.0" in requirements
