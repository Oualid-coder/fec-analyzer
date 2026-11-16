"""Rapport Excel : conformité + analyses, une feuille par sujet."""
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from modules.conformite import AVERT, ERREUR, INFO, NA, OK, tableau_details, tableau_synthese

BLEU      = "2471A3"
VERT      = "1E8449"
ROUGE     = "C0392B"
ORANGE    = "D35400"
VIOLET    = "6C3483"
TEAL      = "117A65"
GRIS      = "7F8C8D"
GRIS_FOND = "EAF2FF"
GRIS_TOT  = "D5E8D4"
JAUNE_TOT = "FFF2CC"
BLANC     = "FFFFFF"

COULEUR_STATUT = {OK: VERT, INFO: BLEU, AVERT: ORANGE, ERREUR: ROUGE, NA: GRIS}
COULEUR_VERDICT = {"CONFORME": VERT, "CONFORME AVEC RÉSERVES": ORANGE, "NON CONFORME": ROUGE}
COULEUR_RISQUE = {"CRITIQUE": ROUGE, "ÉLEVÉ": ORANGE, "MODÉRÉ": ORANGE, "FAIBLE": VERT, "NON CALCULÉ": GRIS}

def _fill(c): return PatternFill("solid", fgColor=c)
def _font(bold=False, color="000000", size=11): return Font(bold=bold, color=color, size=size)
def _center(): return Alignment(horizontal="center", vertical="center")
def _right():  return Alignment(horizontal="right",  vertical="center")
def _left(wrap=False): return Alignment(horizontal="left", vertical="center", wrap_text=wrap)
def _border():
    s = Side(style="thin", color="BDBDBD")
    return Border(left=s, right=s, top=s, bottom=s)


def eur(x) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def _valeur(v):
    """Valeur écrite dans une cellule : types Python simples uniquement."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return ""
    if hasattr(v, "item"):
        v = v.item()
    return v


def _cellule(ws, row, column, value):
    c = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str) and value.startswith("="):
        c.data_type = "s"       # un libellé du FEC ne doit jamais être interprété comme une formule
    return c


def _write_df(ws, df, start_row=1, start_col=1, header_color=BLEU, total_label="TOTAL",
              col_statut=None, largeur_max=45, wrap=()):
    cols = list(df.columns)
    for j, col in enumerate(cols, start_col):
        c = ws.cell(row=start_row, column=j, value=col)
        c.fill = _fill(header_color); c.font = _font(True, BLANC)
        c.alignment = _center(); c.border = _border()

    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        premier = str(row[0]).strip()
        is_tot  = premier.upper().startswith(total_label.upper())
        is_sous = premier.lower().startswith("sous-total")
        for j, val in enumerate(row, start_col):
            val = _valeur(val)
            c = _cellule(ws, i, j, val)
            c.border = _border()
            if is_tot:
                c.fill = _fill(GRIS_TOT); c.font = _font(True)
            elif is_sous:
                c.fill = _fill(JAUNE_TOT); c.font = _font(True)
            elif (i - start_row) % 2 == 0:
                c.fill = _fill(GRIS_FOND)
            nom = cols[j - start_col]
            if isinstance(val, float):
                c.number_format = '#,##0.00'
            c.alignment = _right() if isinstance(val, (int, float)) else _left(nom in wrap)
            if col_statut and nom == col_statut and val in COULEUR_STATUT:
                c.font = _font(True, COULEUR_STATUT[val])

    for j, col in enumerate(cols, start_col):
        mx = max(len(str(col)), int(df[col].astype(str).str.len().max()) if len(df) > 0 else 8)
        lettre = get_column_letter(j)
        ws.column_dimensions[lettre].width = max(ws.column_dimensions[lettre].width or 0,
                                                 min(mx + 4, 90 if col in wrap else largeur_max))
    return start_row + len(df) + 2


def _titre(ws, row, texte, color=BLEU):
    c = ws.cell(row=row, column=1, value=f"  {texte}")
    c.font = _font(True, BLANC, 12); c.fill = _fill(color)
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 22
    return row + 1


def _graphique(ws, genre, title, premiere, nb, col_data, col_cat, anchor, color=BLEU, w=20, h=12,
               avec_entete=False):
    """Ajoute un graphique sur `nb` lignes de données à partir de la ligne `premiere`. Rien si nb = 0."""
    if nb <= 0:
        return
    g = {"bar": BarChart, "line": LineChart, "pie": PieChart}[genre]()
    g.title = title; g.width = w; g.height = h
    debut = premiere - 1 if avec_entete else premiere
    g.add_data(Reference(ws, min_col=col_data, min_row=debut, max_row=premiere + nb - 1),
               titles_from_data=avec_entete)
    g.set_categories(Reference(ws, min_col=col_cat, min_row=premiere, max_row=premiere + nb - 1))
    if genre == "pie":
        g.style = 10
    else:
        g.style = 2
        g.y_axis.numFmt = '#,##0'; g.y_axis.majorGridlines = None
        g.legend = None
        s = g.series[0].graphicalProperties
        s.line.solidFill = color
        if genre == "bar":
            g.type = "col"; s.solidFill = color
        else:
            s.line.width = 20000
    ws.add_chart(g, anchor)


def _feuille(wb, nom):
    ws = wb.create_sheet(nom)
    ws.sheet_view.showGridLines = False
    return ws


def _lignes_cle_valeur(ws, row, paires):
    for label, valeur, couleur in paires:
        lbl = ws.cell(row=row, column=2, value=label)
        lbl.font = _font(True); lbl.fill = _fill(GRIS_FOND)
        lbl.border = _border(); lbl.alignment = _left()
        val = _cellule(ws, row, 3, _valeur(valeur))
        val.font = _font(True, couleur); val.border = _border(); val.alignment = _left(True)
        row += 1
    return row


# ════════════════════════════════════════════════════════════════
def export_rapport(data: dict, output_path: str):
    wb = Workbook()
    wb.remove(wb.active)

    meta, conf, anom, risque = data["meta"], data["conformite"], data["anomalies"], data["risque"]
    ca_mens = data["ca_mensuel"]
    ca_total = float(ca_mens.loc[ca_mens["Mois"] == "TOTAL", "CA_HT"].iloc[0])
    exo = meta["exercice"]

    # ── 1. CONFORMITÉ ────────────────────────────────────────────
    ws = _feuille(wb, "✅ Conformité")
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["C"].width = 70
    ws.cell(row=2, column=2, value="CONTRÔLE DE CONFORMITÉ DU FEC").font = _font(True, BLEU, 15)
    v = ws.cell(row=3, column=2, value=conf["verdict"])
    v.font = _font(True, COULEUR_VERDICT[conf["verdict"]], 14)
    row = _lignes_cle_valeur(ws, 5, [
        ("Fichier contrôlé",         meta["fichier"], BLEU),
        ("Empreinte SHA-256",        meta["sha256"], BLEU),
        ("SIREN",                    meta["siren"] or "non indiqué dans le nom du fichier", BLEU),
        ("Exercice",                 exo, BLEU),
        ("Lignes d'écriture",        meta["nb_lignes"], BLEU),
        ("Contrôles en erreur",      conf["nb_erreurs"], ROUGE if conf["nb_erreurs"] else VERT),
        ("Contrôles en avertissement", conf["nb_avertissements"], ORANGE if conf["nb_avertissements"] else VERT),
        ("Analyse réalisée le",      meta["date_analyse"], BLEU),
        ("Outil",                    f"FEC Analyzer {meta['version']} — traitement local, sans IA", BLEU),
    ])
    row += 1
    row = _titre(ws, row, "RÉSULTAT DES CONTRÔLES")
    row = _write_df(ws, tableau_synthese(conf), start_row=row, col_statut="Statut", wrap=("Constat",))
    n = ws.cell(row=row, column=1, value=(
        "Ce rapport est une aide au contrôle : il ne vaut pas attestation de conformité et n'engage pas "
        "l'administration. Les mêmes données donnent toujours le même résultat (empreinte ci-dessus)."))
    n.font = Font(italic=True, color=GRIS, size=9)

    wsd = _feuille(wb, "🔎 Détail contrôles")
    row = _titre(wsd, 2, "DÉTAIL LIGNE PAR LIGNE (numéro de ligne dans le fichier FEC)")
    det = tableau_details(conf)
    if len(det):
        _write_df(wsd, det, start_row=row, col_statut="Statut", wrap=("Cause",))
        wsd.freeze_panes = wsd.cell(row=row + 1, column=1)
    else:
        wsd.cell(row=row, column=1, value="  Aucun écart relevé.").font = _font(True, VERT)

    # ── 2. RÉSUMÉ ────────────────────────────────────────────────
    ws = _feuille(wb, "📊 Résumé")
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 38
    ws.column_dimensions["C"].width = 44
    ws.cell(row=2, column=2, value="RÉSUMÉ DE L'EXERCICE").font = _font(True, BLEU, 15)
    ws.cell(row=3, column=2, value=exo).font = _font(False, GRIS)
    def rv(n): return ROUGE if n > 0 else VERT
    _lignes_cle_valeur(ws, 5, [
        ("Conformité du FEC",          conf["verdict"], COULEUR_VERDICT[conf["verdict"]]),
        ("Chiffre d'affaires HT",      eur(ca_total), BLEU),
        ("Résultat calculé (7 - 6)",   eur(data["cp"]["resultat_calcule"]), VERT if data["cp"]["resultat_calcule"] >= 0 else ROUGE),
        ("Nombre de clients facturés", risque["nb_clients"], BLEU),
        ("Client principal",           risque["top1_client"], BLEU),
        ("Part du client principal",   f"{risque['top1_part']:.1f} %", COULEUR_RISQUE[risque["niveau_risque"]]),
        ("Part des 3 premiers clients", f"{risque['top3_part']:.1f} %", BLEU),
        ("Risque de dépendance",       risque["niveau_risque"], COULEUR_RISQUE[risque["niveau_risque"]]),
        ("Immobilisations brutes fin", eur(data["immo"]["solde_final"]), BLEU),
        ("Amortissements cumulés fin", eur(data["amort"]["solde_final"]), BLEU),
        ("Capitaux propres fin (hors résultat)", eur(data["cp"]["total_fin"]), BLEU),
        ("Doublons probables",         anom["nb_doublons"], rv(anom["nb_doublons"])),
        ("Écritures déséquilibrées",   anom["nb_desequilibres"], rv(anom["nb_desequilibres"])),
        ("Montants inhabituels",       anom["nb_montants_aberrants"], ORANGE if anom["nb_montants_aberrants"] else VERT),
        ("Soldes de sens anormal",     anom["nb_soldes_suspects"], ORANGE if anom["nb_soldes_suspects"] else VERT),
        ("Factures de vente manquantes", anom["nb_factures_manquantes"], rv(anom["nb_factures_manquantes"])),
    ])

    # ── 3. CA CLIENTS ────────────────────────────────────────────
    ws = _feuille(wb, "💰 CA Clients")
    ts = _titre(ws, 2, "FACTURATION PAR CLIENT (TTC, comptes 411 des journaux de vente)")
    ca_cl = data["ca_clients"]
    nb_cl = len(ca_cl) - 1
    _write_df(ws, ca_cl, start_row=ts)
    _graphique(ws, "pie", "Répartition par client (10 premiers)", ts + 1, min(10, nb_cl), 2, 1, "F2", w=16)

    # ── 4. CA MENSUEL ────────────────────────────────────────────
    ws = _feuille(wb, "📅 CA Mensuel")
    ts = _titre(ws, 2, "CHIFFRE D'AFFAIRES HT MENSUEL (comptes 70)")
    _write_df(ws, ca_mens, start_row=ts)
    _graphique(ws, "bar", "CA mensuel HT (€)", ts + 1, len(ca_mens) - 1, 2, 1, "D2", w=22, h=13)

    # ── 5. CA JOURNALIER ─────────────────────────────────────────
    ws = _feuille(wb, "📆 CA Journalier")
    ts = _titre(ws, 2, "CHIFFRE D'AFFAIRES HT JOURNALIER")
    caj = data["ca_journalier"]
    _write_df(ws, caj, start_row=ts)
    _graphique(ws, "line", "CA journalier HT (€)", ts + 1, len(caj) - 1, 4, 1, "F2", color=TEAL, w=26, h=14)

    # ── 6. CA WEEKENDS ───────────────────────────────────────────
    ws = _feuille(wb, "🗓️ CA Weekends")
    ts = _titre(ws, 2, "CHIFFRE D'AFFAIRES ENREGISTRÉ LE WEEK-END", VIOLET)
    _write_df(ws, data["ca_weekends"], start_row=ts, header_color=VIOLET, total_label="TOTAL WEEKENDS")

    # ── 7-9. TABLEAUX DE VARIATION ───────────────────────────────
    def variation(nom, titre, lignes, total_label, detail, cle, col_graph, titre_graph, couleur):
        ws = _feuille(wb, nom)
        row = _titre(ws, 2, titre)
        synt = pd.DataFrame([{"": lib, "Montant (€)": montant} for lib, montant in lignes])
        row = _write_df(ws, synt, start_row=row, total_label=total_label)
        ts = _titre(ws, row, "DÉTAIL", color="1A5276")
        _write_df(ws, detail, start_row=ts)
        col_cat = list(detail.columns).index(cle) + 1
        _graphique(ws, "bar", titre_graph, ts + 1, len(detail) - 1, col_graph, col_cat,
                   f"{get_column_letter(len(detail.columns) + 2)}{ts}", color=couleur, w=22, h=14)

    im, am, cp = data["immo"], data["amort"], data["cp"]
    variation("🏭 Immobilisations", "TABLEAU DE VARIATION DES IMMOBILISATIONS BRUTES (comptes 20 à 27)",
              [("Solde initial (début d'exercice)", im["solde_initial"]), ("+ Acquisitions", im["acquisitions"]),
               ("- Sorties / cessions", -im["sorties"]), ("= Solde final (fin d'exercice)", im["solde_final"])],
              "= Solde final", im["detail"], "Libellé", 6, "Immobilisations : solde final par compte", "1A5276")
    variation("📉 Amortissements", "TABLEAU DE VARIATION DES AMORTISSEMENTS (compte 28)",
              [("Solde initial (cumul début)", am["solde_initial"]), ("+ Dotations de l'exercice", am["dotations"]),
               ("- Reprises de l'exercice", -am["reprises"]), ("= Solde final (cumul fin)", am["solde_final"])],
              "= Solde final", am["detail"], "Libellé", 4, "Dotations aux amortissements par compte", "884EA0")
    variation("💼 Capitaux Propres", "TABLEAU DE VARIATION DES CAPITAUX PROPRES (comptes 10 à 14)",
              [("Capitaux propres début d'exercice", cp["total_debut"]),
               ("Variation de l'exercice", cp["variation"]),
               ("= Capitaux propres fin d'exercice (hors résultat)", cp["total_fin"]),
               ("Résultat calculé de l'exercice (produits - charges)", cp["resultat_calcule"])],
              "= Capitaux propres fin", cp["detail"], "Catégorie", 5, "Capitaux propres : solde final", VERT)

    # ── 10. SÉQUENTIALITÉ DES VENTES ─────────────────────────────
    ws = _feuille(wb, "🔢 Séquentialité VE")
    row = _titre(ws, 2, "CONTINUITÉ DE LA NUMÉROTATION DES FACTURES DE VENTE (art. 242 nonies A, ann. II CGI)", TEAL)
    seq, rupt = anom["tableau_sequentialite"], anom["ruptures_sequence"]
    if len(seq):
        row = _write_df(ws, seq, start_row=row, header_color=TEAL)
    else:
        ws.cell(row=row, column=1, value="  Aucune référence de facture numérotée trouvée dans les journaux de vente.").font = _font(True, GRIS)
        row += 2
    row = _titre(ws, row, f"DÉTAIL — {anom['nb_factures_manquantes']} numéro(s) manquant(s)",
                 ROUGE if anom["nb_factures_manquantes"] else VERT)
    if len(rupt):
        _write_df(ws, rupt, start_row=row, header_color=ROUGE)
    else:
        ws.cell(row=row, column=1, value="  Aucune rupture détectée").font = _font(True, VERT)

    # ── 11. ANOMALIES ────────────────────────────────────────────
    ws = _feuille(wb, "⚠️ Anomalies")
    row = 2
    sections = [
        ("doublons", "nb_doublons", "DOUBLONS PROBABLES (même compte, pièce, date et montant dans deux écritures)", ROUGE),
        ("desequilibres", "nb_desequilibres", "ÉCRITURES DÉSÉQUILIBRÉES", ROUGE),
        ("montants_aberrants", "nb_montants_aberrants", f"MONTANTS INHABITUELS (> {eur(anom['seuil_aberrant'])})", ORANGE),
        ("soldes_negatifs_suspects", "nb_soldes_suspects", "SOLDES DE SENS ANORMAL", ORANGE),
    ]
    for key, compteur, label, color in sections:
        df_a, nb = anom[key], anom[compteur]
        suffixe = f" — {nb} élément(s)" + (f", {len(df_a)} lignes affichées" if len(df_a) and len(df_a) != nb else "")
        row = _titre(ws, row, label + suffixe, color if nb else VERT)
        if len(df_a):
            row = _write_df(ws, df_a, start_row=row, header_color=color)
        else:
            ws.cell(row=row, column=1, value="  Aucune anomalie").font = _font(True, VERT)
            row += 2

    wb.save(output_path)
