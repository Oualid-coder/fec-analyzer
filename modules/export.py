import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, PieChart, LineChart, Reference

BLEU      = "2471A3"
VERT      = "1E8449"
ROUGE     = "C0392B"
ORANGE    = "D35400"
VIOLET    = "6C3483"
TEAL      = "117A65"
GRIS_FOND = "EAF2FF"
GRIS_TOT  = "D5E8D4"
JAUNE_TOT = "FFF2CC"
BLANC     = "FFFFFF"

def _fill(c): return PatternFill("solid", fgColor=c)
def _font(bold=False, color="000000", size=11): return Font(bold=bold, color=color, size=size)
def _center(): return Alignment(horizontal="center", vertical="center")
def _right():  return Alignment(horizontal="right",  vertical="center")
def _left():   return Alignment(horizontal="left",   vertical="center", wrap_text=False)
def _border():
    s = Side(style="thin", color="BDBDBD")
    return Border(left=s, right=s, top=s, bottom=s)


def _write_df(ws, df, start_row=1, start_col=1, header_color=BLEU,
              total_color=GRIS_TOT, total_label="TOTAL"):
    cols = list(df.columns)

    for j, col in enumerate(cols, start_col):
        c = ws.cell(row=start_row, column=j, value=col)
        c.fill = _fill(header_color); c.font = _font(True, BLANC)
        c.alignment = _center(); c.border = _border()

    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        is_tot  = str(row[0]).strip().upper().startswith(total_label.upper())
        is_sous = str(row[0]).strip().lower().startswith("sous-total")
        for j, val in enumerate(row, start_col):
            c = ws.cell(row=i, column=j, value=val)
            c.border = _border()
            if is_tot:
                c.fill = _fill(GRIS_TOT); c.font = _font(True)
            elif is_sous:
                c.fill = _fill(JAUNE_TOT); c.font = _font(True)
            elif (i - start_row) % 2 == 0:
                c.fill = _fill(GRIS_FOND)
            c.alignment = _right() if isinstance(val, (int, float)) else _left()

    for j, col in enumerate(cols, start_col):
        mx = max(len(str(col)), df[col].astype(str).str.len().max() if len(df) > 0 else 8)
        ws.column_dimensions[get_column_letter(j)].width = min(mx + 4, 45)

    return start_row + len(df) + 2


def _titre(ws, row, texte, color=BLEU):
    c = ws.cell(row=row, column=1, value=f"  {texte}")
    c.font = _font(True, BLANC, 12); c.fill = _fill(color)
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 22
    return row + 1


def _bar(ws, title, data_rows, cat_rows, col_data, col_cat, anchor,
         color="2471A3", w=18, h=11):
    bar = BarChart()
    bar.type = "col"; bar.title = title; bar.style = 2
    bar.width = w; bar.height = h
    bar.y_axis.numFmt = '#,##0'; bar.y_axis.majorGridlines = None
    dr = Reference(ws, min_col=col_data, min_row=data_rows[0], max_row=data_rows[1])
    cr = Reference(ws, min_col=col_cat,  min_row=cat_rows[0],  max_row=cat_rows[1])
    bar.add_data(dr); bar.set_categories(cr)
    bar.series[0].graphicalProperties.solidFill = color
    bar.series[0].graphicalProperties.line.solidFill = color
    ws.add_chart(bar, anchor)


def _line(ws, title, data_rows, cat_rows, col_data, col_cat, anchor,
          color="2471A3", w=22, h=12):
    lc = LineChart()
    lc.title = title; lc.style = 2
    lc.width = w; lc.height = h
    lc.y_axis.numFmt = '#,##0'; lc.y_axis.majorGridlines = None
    dr = Reference(ws, min_col=col_data, min_row=data_rows[0], max_row=data_rows[1])
    cr = Reference(ws, min_col=col_cat,  min_row=cat_rows[0],  max_row=cat_rows[1])
    lc.add_data(dr); lc.set_categories(cr)
    lc.series[0].graphicalProperties.line.solidFill = color
    lc.series[0].graphicalProperties.line.width = 20000
    ws.add_chart(lc, anchor)


def _pie(ws, title, data_rows, cat_rows, col_data, col_cat, anchor, w=16, h=12):
    pie = PieChart()
    pie.title = title; pie.style = 10; pie.width = w; pie.height = h
    dr = Reference(ws, min_col=col_data, min_row=data_rows[0], max_row=data_rows[1])
    cr = Reference(ws, min_col=col_cat,  min_row=cat_rows[0],  max_row=cat_rows[1])
    pie.add_data(dr); pie.set_categories(cr)
    ws.add_chart(pie, anchor)


# ════════════════════════════════════════════════════════════════
def export_rapport(data: dict, output_path: str):
    wb = Workbook()
    wb.remove(wb.active)

    risque  = data["risque"]
    ca_mens = data["ca_mensuel"]
    ca_total = ca_mens[ca_mens["Mois"] != "TOTAL"]["CA_HT"].sum()
    CR = {"CRITIQUE": ROUGE, "ÉLEVÉ": ORANGE, "MODÉRÉ": ORANGE, "FAIBLE": VERT}

    # ── 1. RÉSUMÉ ────────────────────────────────────────────────
    ws = wb.create_sheet("📊 Résumé")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 38
    ws.column_dimensions["C"].width = 28
    row = 2
    ws.cell(row=row, column=2, value="ANALYSE FEC 2024 — RÉSUMÉ EXÉCUTIF").font = _font(True, BLEU, 15)
    row += 2

    nb_rupt = len(data["anomalies"]["ruptures_sequence"])
    nb_manq = int(data["anomalies"]["tableau_sequentialite"][
        data["anomalies"]["tableau_sequentialite"]["Période"] == "TOTAL"]["Nb manquant"].iloc[0]) \
        if len(data["anomalies"]["tableau_sequentialite"]) > 0 else 0

    kpis = [
        ("CA Total HT 2024",          f"{ca_total:,.2f} €",                    BLEU),
        ("Nombre de clients",          str(risque["nb_clients"]),               BLEU),
        ("Client principal",           risque["top1_client"],                   BLEU),
        ("Part client principal",      f"{risque['top1_part']:.1f}%",           CR[risque["niveau_risque"]]),
        ("Top 3 clients",              f"{risque['top3_part']:.1f}% du CA",     BLEU),
        ("Risque dépendance",          risque["niveau_risque"],                 CR[risque["niveau_risque"]]),
        ("Immobilisations brutes fin", f"{data['immo']['solde_final']:,.2f} €", BLEU),
        ("Amortissements cumulés fin", f"{data['amort']['solde_final']:,.2f} €",BLEU),
        ("Capitaux propres fin",       f"{data['cp']['total_fin']:,.2f} €",     BLEU),
        ("Doublons détectés",          str(len(data["anomalies"]["doublons"])), ROUGE if len(data["anomalies"]["doublons"]) > 0 else VERT),
        ("Écritures déséquilibrées",   str(len(data["anomalies"]["desequilibres"])), ROUGE if len(data["anomalies"]["desequilibres"]) > 0 else VERT),
        ("Montants aberrants",         str(len(data["anomalies"]["montants_aberrants"])), ROUGE if len(data["anomalies"]["montants_aberrants"]) > 0 else VERT),
        ("Ruptures de séquence VE",    f"{nb_manq} facture(s) manquante(s)",   ROUGE if nb_manq > 0 else VERT),
    ]

    for label, valeur, col in kpis:
        lbl = ws.cell(row=row, column=2, value=label)
        lbl.font = _font(True); lbl.fill = _fill(GRIS_FOND)
        lbl.border = _border(); lbl.alignment = _left()
        val = ws.cell(row=row, column=3, value=valeur)
        val.font = _font(True, col); val.border = _border(); val.alignment = _left()
        row += 1

    if data.get("analyse_ia"):
        row += 1
        _titre(ws, row, "ANALYSE IA"); row += 1
        c = ws.cell(row=row, column=2, value=data["analyse_ia"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 180
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)

    # ── 2. CA CLIENTS ────────────────────────────────────────────
    ws2 = wb.create_sheet("💰 CA Clients")
    ws2.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws2, row, "CHIFFRE D'AFFAIRES PAR CLIENT 2024")
    ts = row
    ca_st = data["ca_clients"]
    nb_cl = len(ca_st[ca_st["Client"] != "TOTAL"])
    row = _write_df(ws2, ca_st, start_row=ts)
    _pie(ws2, "Répartition CA par client (Top 10)",
         data_rows=(ts+1, ts+min(10,nb_cl)), cat_rows=(ts+1, ts+min(10,nb_cl)),
         col_data=2, col_cat=1, anchor="F2")

    # ── 3. CA MENSUEL ────────────────────────────────────────────
    ws3 = wb.create_sheet("📅 CA Mensuel")
    ws3.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws3, row, "CHIFFRE D'AFFAIRES MENSUEL 2024")
    ts = row
    nm = len(ca_mens[ca_mens["Mois"] != "TOTAL"])
    row = _write_df(ws3, ca_mens, start_row=ts)
    _bar(ws3, "CA Mensuel HT 2024 (€)",
         data_rows=(ts+1, ts+nm), cat_rows=(ts+1, ts+nm),
         col_data=2, col_cat=1, anchor="D2", color=BLEU, w=22, h=13)

    # ── 4. CA JOURNALIER ─────────────────────────────────────────
    ws4 = wb.create_sheet("📆 CA Journalier")
    ws4.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws4, row, "CHIFFRE D'AFFAIRES JOURNALIER 2024")
    ts = row
    caj = data["ca_journalier"]
    nb_j = len(caj[caj["Date"] != "TOTAL"])
    row = _write_df(ws4, caj, start_row=ts)
    _line(ws4, "CA Journalier HT 2024 (€)",
          data_rows=(ts+1, ts+nb_j), cat_rows=(ts+1, ts+nb_j),
          col_data=4, col_cat=1, anchor="F2", color=TEAL, w=26, h=14)

    # ── 5. CA WEEKENDS ───────────────────────────────────────────
    ws5 = wb.create_sheet("🗓️ CA Weekends")
    ws5.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws5, row, "CHIFFRE D'AFFAIRES ENREGISTRÉ LES WEEKENDS 2024", VIOLET)
    ts = row
    caw = data["ca_weekends"]
    nb_w = len(caw[(caw["Date"] != "TOTAL WEEKENDS") & (~caw["Date"].astype(str).str.startswith("Sous-total"))])
    row = _write_df(ws5, caw, start_row=ts, header_color=VIOLET, total_label="TOTAL WEEKENDS")
    _bar(ws5, "CA Weekends par jour (€)",
         data_rows=(ts+1, ts+nb_w), cat_rows=(ts+1, ts+nb_w),
         col_data=4, col_cat=1, anchor="F2", color=VIOLET, w=22, h=13)

    # ── 6. IMMOBILISATIONS ───────────────────────────────────────
    ws6 = wb.create_sheet("🏭 Immobilisations")
    ws6.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws6, row, "TABLEAU DE VARIATION DES IMMOBILISATIONS BRUTES")
    synt = pd.DataFrame([
        {"": "Solde initial (début exercice)", "Montant (€)": data["immo"]["solde_initial"]},
        {"": "+ Acquisitions",                 "Montant (€)": data["immo"]["acquisitions"]},
        {"": "- Sorties / Cessions",           "Montant (€)": -data["immo"]["sorties"]},
        {"": "= Solde final (fin exercice)",   "Montant (€)": data["immo"]["solde_final"]},
    ])
    row = _write_df(ws6, synt, start_row=row, total_label="= Solde final")

    row = _titre(ws6, row, "DÉTAIL PAR COMPTE", color="1A5276")
    ts = row
    imd = data["immo"]["detail"]
    nb_i = len(imd[imd["Libellé"] != "TOTAL"])
    row = _write_df(ws6, imd, start_row=ts)
    _bar(ws6, "Immobilisations : Solde Initial vs Final",
         data_rows=(ts, ts+nb_i), cat_rows=(ts+1, ts+nb_i),
         col_data=2, col_cat=1, anchor=f"G{ts}", color="1A5276", w=22, h=14)

    # ── 7. AMORTISSEMENTS ────────────────────────────────────────
    ws7 = wb.create_sheet("📉 Amortissements")
    ws7.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws7, row, "TABLEAU DE VARIATION DES AMORTISSEMENTS")
    synt_a = pd.DataFrame([
        {"": "Solde initial (cumul début)",  "Montant (€)": data["amort"]["solde_initial"]},
        {"": "+ Dotations exercice",         "Montant (€)": data["amort"]["dotations"]},
        {"": "- Reprises exercice",          "Montant (€)": -data["amort"]["reprises"]},
        {"": "= Solde final (cumul fin)",    "Montant (€)": data["amort"]["solde_final"]},
    ])
    row = _write_df(ws7, synt_a, start_row=row, total_label="= Solde final")

    row = _titre(ws7, row, "DÉTAIL PAR COMPTE", color="1A5276")
    ts = row
    amd = data["amort"]["detail"]
    nb_a = len(amd[amd["Libellé"] != "TOTAL"])
    row = _write_df(ws7, amd, start_row=ts)
    _bar(ws7, "Dotations aux amortissements par compte",
         data_rows=(ts+1, ts+nb_a), cat_rows=(ts+1, ts+nb_a),
         col_data=3, col_cat=1, anchor=f"G{ts}", color="884EA0", w=22, h=14)

    # ── 8. CAPITAUX PROPRES ──────────────────────────────────────
    ws8 = wb.create_sheet("💼 Capitaux Propres")
    ws8.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws8, row, "TABLEAU DE VARIATION DES CAPITAUX PROPRES")
    var = data["cp"]["variation"]
    synt_cp = pd.DataFrame([
        {"": "Capitaux propres début d'exercice", "Montant (€)": data["cp"]["total_debut"]},
        {"": "+ Augmentations",                   "Montant (€)": var if var >= 0 else 0},
        {"": "- Diminutions",                     "Montant (€)": -var if var < 0 else 0},
        {"": "= Capitaux propres fin d'exercice", "Montant (€)": data["cp"]["total_fin"]},
    ])
    row = _write_df(ws8, synt_cp, start_row=row, total_label="= Capitaux propres fin")

    row = _titre(ws8, row, "DÉTAIL PAR CATÉGORIE", color="1A5276")
    ts = row
    cpd = data["cp"]["detail"]
    nb_cp = len(cpd[cpd["Catégorie"] != "TOTAL"])
    row = _write_df(ws8, cpd, start_row=ts)
    _bar(ws8, "Capitaux propres : Solde Initial vs Final",
         data_rows=(ts, ts+nb_cp), cat_rows=(ts+1, ts+nb_cp),
         col_data=2, col_cat=1, anchor=f"G{ts}", color=VERT, w=22, h=14)

    # ── 9. SÉQUENTIALITÉ DES VENTES ──────────────────────────────
    ws9 = wb.create_sheet("🔢 Séquentialité VE")
    ws9.sheet_view.showGridLines = False
    row = 2
    row = _titre(ws9, row, "TABLEAU DE SÉQUENTIALITÉ DES FACTURES DE VENTE", TEAL)
    ts = row
    seq = data["anomalies"]["tableau_sequentialite"]
    nb_seq = len(seq[seq["Période"] != "TOTAL"])
    row = _write_df(ws9, seq, start_row=ts, header_color=TEAL)

    # Graphique nb attendu vs présent par mois
    _bar(ws9, "Factures attendues vs présentes par mois",
         data_rows=(ts, ts+nb_seq), cat_rows=(ts+1, ts+nb_seq),
         col_data=4, col_cat=1, anchor=f"J{ts}", color=TEAL, w=22, h=13)

    row += 2
    rupt = data["anomalies"]["ruptures_sequence"]
    row = _titre(ws9, row, f"DÉTAIL DES RUPTURES — {len(rupt[rupt['Période'] != 'FORMAT ABERRANT']) if len(rupt) > 0 else 0} numéro(s) manquant(s)", ROUGE)
    if len(rupt) > 0:
        row = _write_df(ws9, rupt, start_row=row, header_color=ROUGE)
    else:
        ws9.cell(row=row, column=1, value="  ✅ Aucune rupture détectée").font = _font(True, VERT)

    # ── 10. ANOMALIES ────────────────────────────────────────────
    ws10 = wb.create_sheet("⚠️ Anomalies")
    ws10.sheet_view.showGridLines = False
    row = 2

    sections = [
        ("doublons",               f"DOUBLONS DÉTECTÉS",          ROUGE),
        ("desequilibres",          f"ÉCRITURES DÉSÉQUILIBRÉES",    ORANGE),
        ("montants_aberrants",     f"MONTANTS ABERRANTS (> {data['anomalies']['seuil_aberrant']:,.0f}€)", ORANGE),
        ("soldes_negatifs_suspects","SOLDES NÉGATIFS SUSPECTS",    ORANGE),
    ]
    for key, label, color in sections:
        df_a = data["anomalies"][key]
        nb = len(df_a)
        row = _titre(ws10, row, f"{label} — {nb} élément(s)", color)
        if nb > 0:
            row = _write_df(ws10, df_a, start_row=row, header_color=color)
        else:
            ws10.cell(row=row, column=1, value="  ✅ Aucune anomalie").font = _font(True, VERT)
            row += 2

    wb.save(output_path)
    print(f"✅ Rapport exporté : {output_path}")
