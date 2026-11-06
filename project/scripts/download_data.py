"""Fetch the raw NASA PCoE and CALCE CS2 battery datasets.

The NASA .mat files ship with the project in data/raw/nasa. The CALCE Excel
files (about 170 MB) are fetched from a public GitHub mirror with git:

    python scripts/download_data.py

Requires git on PATH. Alternatively download the CS2_35..CS2_38 folders by hand
from https://calce.umd.edu/battery-data and place them in data/raw/calce/.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MIRROR = "https://github.com/XiuzeZhou/RUL"


def main() -> int:
    need_nasa = len(list((RAW / "nasa").glob("B00*.mat"))) < 4
    need_calce = any(len(list((RAW / "calce" / c).glob("*.xlsx"))) < 20
                     for c in ("CS2_35", "CS2_36", "CS2_37", "CS2_38"))
    if not (need_nasa or need_calce):
        print("Raw data already present.")
        return 0
    if shutil.which("git") is None:
        print("git not found. Download the data manually (see this file's docstring).")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        print(f"Cloning {MIRROR} (shallow) ...")
        subprocess.run(["git", "clone", "--depth", "1", MIRROR, tmp + "/src"], check=True)
        src = Path(tmp) / "src" / "datasets"
        if need_nasa:
            (RAW / "nasa").mkdir(parents=True, exist_ok=True)
            for f in (src / "NASA").glob("B00*.mat"):
                shutil.copy2(f, RAW / "nasa" / f.name)
        if need_calce:
            for d in (src / "CALCE").glob("CS2_3*"):
                shutil.copytree(d, RAW / "calce" / d.name, dirs_exist_ok=True)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
