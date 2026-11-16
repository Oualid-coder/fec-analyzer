# FEC Analyzer

> Local, deterministic compliance check and analysis of French accounting FEC files
> (*Fichier des Écritures Comptables*, article A47 A-1 of the *Livre des procédures fiscales*).

- **100 % local** — the app only listens on `127.0.0.1`. No cloud, no telemetry, no outbound call.
- **No AI** — fixed rules only. The same file always gives the same result; every report carries the SHA-256 of the file it was computed from.
- **Batch** — drop dozens of FEC files at once, get one report per file plus a firm-wide summary.
- **Mac and Windows** — one installable app, nothing else to set up.

## What it checks

Each control has a stable code, a legal reference, a status (OK / info / warning / error) and a line-by-line detail with the cause.

| Code | Control |
|---|---|
| S01 | File name `SIREN` + `FEC` + closing date `AAAAMMJJ` |
| S02 | Flat file, encoding (UTF-8 / ISO 8859-15 / ASCII), separator (tab or `\|`) |
| S03 | Header: the 18 mandatory fields, names and order (Debit/Credit or Montant/Sens) |
| S04 | Same number of fields on every line |
| C01 | Mandatory fields filled in |
| C02 | Dates in `AAAAMMJJ` format and existing in the calendar |
| C03 | Numeric amounts, decimal comma |
| C04 | Debit = credit for every entry |
| C05 | One date per entry |
| C06 | Entry dates inside the financial year |
| C07 | Validation date not before entry date |
| C08 | Continuous entry numbering |
| C09 | Account numbers and labels |
| C10 | Auxiliary accounts (number and label together) |
| C11 | Lettering (code, date, balanced groups) |
| C12 | Foreign currency amount and code |
| C13 | Opening balance entries |
| C14 | Strictly identical lines |

Verdict: **CONFORME**, **CONFORME AVEC RÉSERVES** (warnings only) or **NON CONFORME** (at least one error).

This is a pre-check tool. It does not issue a certificate of compliance; the official tool remains the DGFiP's *Test Compta Demat* (Windows only).

## What it reports

For each FEC: `rapport.xlsx` (compliance, line-by-line detail, revenue per client / month / day, fixed assets, depreciation, equity, sales invoice numbering gaps, anomalies), `synthese.pdf` (printable summary), `controles.json` (machine-readable result) and `analyse.log` (what ran, how long, what failed).

## Where the data lives

Everything stays on the user's disk, in a folder they can open from the app:

```
~/FEC Analyzer/
  dossiers/<SIREN>/<closing date>/
      fec/<original file>
      rapports/<date_time>/rapport.xlsx  synthese.pdf  controles.json  analyse.log
  recapitulatifs/        batch summaries
  journaux/              application log
  historique.json        index shown in the app
```

Set `FEC_ANALYZER_HOME` to use another location (for example a shared drive of the firm).
The folder is deliberately outside `Documents`, which is often synced to a cloud without the user knowing.

## Install

Download the build for your system from the **Actions** tab (workflow *Tests et exécutables* → latest run → Artifacts):

- **Windows** — `FEC Analyzer.exe`. Double-click it.
- **macOS** — unzip, drag `FEC Analyzer.app` to *Applications*, open it.

The app opens in your browser. Use **Quitter** in the top-right corner to stop it.

The builds are **not code-signed yet**. Until they are:
- Windows SmartScreen shows "Windows protected your PC" → *More info* → *Run anyway*.
- macOS refuses the first launch → right-click the app → *Open* → *Open*.

Removing these warnings requires a paid certificate (Windows code-signing certificate, Apple Developer ID + notarization).

## Command line

```bash
python main.py /path/to/folder/of/fec      # or one or several files
```

Exit code `0` if every file is compliant, `2` otherwise.

## Development

Python 3.11+ (built and tested with 3.13). Dependencies are pinned to exact versions.

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q        # synthetic FEC files only, no real data
python lanceur.py                # run the app from sources
python build.py                  # build the installable app for the current platform
```

| Layer | Tech |
|---|---|
| Local server | FastAPI + uvicorn, bound to 127.0.0.1 |
| Data | pandas |
| Excel / PDF | openpyxl / reportlab |
| Packaging | PyInstaller (GitHub Actions matrix: Windows, macOS Apple Silicon, macOS Intel) |

## Known limits

- Flat files only for a real compliance verdict; `.xlsx` input is analysed but flagged as a non-receivable format.
- XML FEC and the BIC/BNC/BA-specific extra fields are not checked.
- Memory use is roughly 15–20× the file size (a 50 MB FEC needs about 1 GB of RAM).

## Author

**Oualid** — Full-stack developer (Go / Python / React)
