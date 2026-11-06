# User Guide

## 1. Set up (once)

1. Open **Anaconda Prompt** (Start menu). It already has Python and almost every library the project needs.
2. Go to the project folder:
   ```
   cd "%USERPROFILE%\OneDrive\Documents\ai battery lifecycle"
   ```
3. Install anything missing (Anaconda usually has it all):
   ```
   pip install -r requirements.txt
   ```

## 2. Open the dashboard

Double-click **`run_dashboard.bat`**, or in Anaconda Prompt:
```
python dashboard\app.py
```
Then open **http://127.0.0.1:8050** in your browser. Press `Ctrl+C` in the prompt window to stop it.

The results are already included, so the dashboard opens immediately. It needs no internet connection.

| Page | Use it to |
| --- | --- |
| Overview | See every battery's lifecycle at a glance and the headline accuracy |
| Cells | Pick a cell; compare estimated and measured health, remaining life, and decisions |
| Models | Compare the five SOH models and three RUL methods |
| Second life | Move sliders to grade any battery; see how often grades match the lab |
| Passports | Read a passport, switch to the public view, press **Verify**, try **Simulate tampering** |

## 2b. Hosted version (no Python needed)

`site/index.html` is a self-contained copy of the dashboard for sharing. The data is built in, and grading, passport verification and the tampering demo all run in the browser with SHA-256 and Ed25519. To rebuild it after re-running the analysis:
```
python scripts\export_static.py
```

## 3. Re-run the analysis

| Command | Time | What it does |
| --- | --- | --- |
| `python -m batterylife run --fast` | 2 s | Rebuilds grading, passports and summary from saved model results |
| `python -m batterylife run` | about 5 min | Re-trains every model from the cleaned data |
| `python -m batterylife run --refresh` | about 6 min | Also re-reads the raw files (needs the CALCE data, see below) |

## 4. Other commands

```
python -m batterylife verify                         # check every passport
python -m batterylife tamper-demo DBP-CALCE-CS2_36   # show tampering being caught
python -m batterylife assess --soh 0.78 --soh-lo 0.74 --resistance 1.2 --cycles 250
python -m batterylife passport DBP-NASA-B0005 --public
python -m pytest -q                                  # run the 61 tests
python scripts\make_figures.py                       # regenerate report figures
```

## 5. Raw data
- The NASA files are in `data\raw\nasa`.
- The CALCE files (about 170 MB) are only needed for `--refresh`. Run `python scripts\download_data.py` (requires git), or download CS2_35 to CS2_38 from the CALCE website into `data\raw\calce`.

## 6. Sprint history
The code was built in 10 sprints. The complete git history, with a tag per sprint, is in **`sprint-history.bundle`**. With git installed:
```
git clone sprint-history.bundle sprint-history
cd sprint-history
git log --oneline --decorate     # 10 sprint commits, tags sprint-01 ... sprint-10, v1.0
git checkout sprint-04           # the project as it was after Sprint 4
git checkout main                # back to the final version
```

## 7. Troubleshooting

| Message | Fix |
| --- | --- |
| `python is not recognized` | Use Anaconda Prompt, not the plain Command Prompt |
| `results/summary.json not found` | Run `python -m batterylife run --fast` |
| `Raw calce data missing` | Only for `--refresh`; see section 5 |
| Port 8050 in use | `set PORT=8060` then `python dashboard\app.py` |
