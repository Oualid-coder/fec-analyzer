# 📊 FEC Analyzer

> Automated French accounting FEC file analyzer — generates Excel + PDF reports with financial tables, charts and anomaly detection

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green)
![pandas](https://img.shields.io/badge/pandas-2.x-orange)

## 🎯 What it does

Upload a French FEC file and get in 30 seconds:
- **Excel report** — 10 styled sheets with charts
- **PDF report** — 5 pages ready to print/share

All processing is **100% local** — no data ever leaves the machine.

## 📋 Generated Reports

| Sheet | Content |
|---|---|
| 📊 Résumé | Executive summary + KPIs |
| 💰 CA Clients | Revenue by client + pie chart + dependency risk |
| 📅 CA Mensuel | Monthly revenue + bar chart |
| 📆 CA Journalier | Daily revenue + weekend flag |
| 🏭 Immobilisations | Fixed assets variation table |
| 📉 Amortissements | Depreciation variation table |
| 💼 Capitaux Propres | Equity variation table |
| 🔢 Séquentialité VE | Invoice sequence check (article L123-22) |
| ⚠️ Anomalies | Duplicates, imbalanced entries, abnormal amounts |

## 🚀 Quick Start

```bash
git clone https://github.com/oualid-coder/fec-analyzer.git
cd fec-analyzer
pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

Open http://localhost:8000, upload your FEC file, download the report.

## 🏗️ Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + Python 3.9 |
| Data | pandas |
| Excel | openpyxl |
| PDF | reportlab + matplotlib |
| AI (optional) | OpenAI GPT-4o |

## 🔒 Privacy

All data stays local. No FEC data sent externally unless OpenAI key provided.

## 👤 Author

**Oualid** — Full-stack developer (Go / Python / React)
