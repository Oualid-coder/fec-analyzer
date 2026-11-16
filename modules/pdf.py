"""Synthèse PDF : verdict de conformité, contrôles, chiffres clés. Prête à imprimer ou à joindre au dossier."""
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from modules.conformite import AVERT, ERREUR, INFO, NA, OK
from modules.export import eur

BLEU, VERT, ROUGE, ORANGE, GRIS = (colors.HexColor(x) for x in ("#2471A3", "#1E8449", "#C0392B", "#D35400", "#7F8C8D"))
C_STATUT = {OK: VERT, INFO: BLEU, AVERT: ORANGE, ERREUR: ROUGE, NA: GRIS}
C_VERDICT = {"CONFORME": VERT, "CONFORME AVEC RÉSERVES": ORANGE, "NON CONFORME": ROUGE}
DETAILS_PAR_CONTROLE = 15


def _t(x) -> str:
    """Texte sûr pour les polices PDF standard (Latin-1) et pour le mini-HTML de reportlab."""
    s = str(x).replace("→", "->").replace(" ", " ").replace(" ", " ")
    s = s.encode("cp1252", errors="replace").decode("cp1252")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(donnees, largeurs, entete=BLEU, couleurs_col=None):
    t = Table(donnees, colWidths=largeurs, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), entete), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BDBDBD")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EAF2FF")]),
    ]
    for (col, ligne), couleur in (couleurs_col or {}).items():
        style += [("TEXTCOLOR", (col, ligne), (col, ligne), couleur), ("FONTNAME", (col, ligne), (col, ligne), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GRIS)
    canvas.drawString(15 * mm, 9 * mm, doc.pied)
    canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def export_pdf(data: dict, output_path: str):
    meta, conf, anom, risque = data["meta"], data["conformite"], data["anomalies"], data["risque"]
    st = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=st["Title"], textColor=BLEU, fontSize=18, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=st["Heading2"], textColor=BLEU, fontSize=12, spaceBefore=10, spaceAfter=4)
    p = ParagraphStyle("p", parent=st["BodyText"], fontSize=8, leading=10)
    petit = ParagraphStyle("petit", parent=p, textColor=GRIS, fontSize=7)

    doc = SimpleDocTemplate(output_path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Contrôle FEC - {meta['fichier']}", author="FEC Analyzer")
    doc.pied = _t(f"FEC Analyzer {meta['version']} - {meta['fichier']} - SHA-256 {meta['sha256'][:16]}... - traitement local, sans IA")
    e = []

    # Page 1 : conformité
    e.append(Paragraph("Contrôle de conformité du FEC", h1))
    verdict = ParagraphStyle("v", parent=st["Title"], textColor=C_VERDICT[conf["verdict"]], fontSize=15, alignment=0)
    e.append(Paragraph(_t(conf["verdict"]), verdict))
    ident = [["Fichier", _t(meta["fichier"])], ["Empreinte SHA-256", meta["sha256"]],
             ["SIREN", _t(meta["siren"] or "non indiqué dans le nom du fichier")],
             ["Exercice", _t(meta["exercice"])], ["Lignes d'écriture", str(meta["nb_lignes"])],
             ["Analyse réalisée le", _t(meta["date_analyse"])]]
    t = Table(ident, colWidths=[40 * mm, 140 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2FF")),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BDBDBD"))]))
    e += [t, Paragraph("Résultat des contrôles", h2)]

    lignes, couleurs = [["Code", "Contrôle", "Statut", "Nb", "Constat"]], {}
    for i, c in enumerate(conf["controles"], start=1):
        lignes.append([c.code, Paragraph(_t(c.titre), p), c.statut.capitalize(), str(c.nb), Paragraph(_t(c.message), p)])
        couleurs[(2, i)] = C_STATUT.get(c.statut, GRIS)
    e.append(_table(lignes, [11 * mm, 44 * mm, 26 * mm, 11 * mm, 88 * mm], couleurs_col=couleurs))
    e.append(Spacer(1, 4))
    e.append(Paragraph("Ce rapport est une aide au contrôle : il ne vaut pas attestation de conformité et n'engage pas "
                       "l'administration. Les mêmes données donnent toujours le même résultat.", petit))

    # Détail des écarts
    en_ecart = [c for c in conf["controles"] if len(c.details)]
    if en_ecart:
        e += [PageBreak(), Paragraph("Détail des écarts", h1),
              Paragraph(f"Les {DETAILS_PAR_CONTROLE} premières lignes de chaque contrôle. La liste complète est dans "
                        "la feuille « Détail contrôles » du rapport Excel.", petit)]
        for c in en_ecart:
            e.append(Paragraph(_t(f"{c.code} - {c.titre} ({c.nb})"), h2))
            lignes = [["Ligne", "Champ", "Valeur", "Cause"]]
            for r in c.details.head(DETAILS_PAR_CONTROLE).itertuples(index=False):
                lignes.append([str(r.Ligne), _t(r.Champ), Paragraph(_t(str(r.Valeur)[:60]), p), Paragraph(_t(r.Cause), p)])
            e.append(_table(lignes, [14 * mm, 28 * mm, 50 * mm, 88 * mm], entete=C_STATUT.get(c.statut, GRIS)))

    # Chiffres clés
    e += [PageBreak(), Paragraph("Chiffres clés de l'exercice", h1), Paragraph(_t(meta["exercice"]), petit), Spacer(1, 6)]
    ca_mens = data["ca_mensuel"]
    ca_total = float(ca_mens.loc[ca_mens["Mois"] == "TOTAL", "CA_HT"].iloc[0])
    cles = [["Indicateur", "Valeur"],
            ["Chiffre d'affaires HT (comptes 70)", _t(eur(ca_total))],
            ["Résultat calculé (produits - charges)", _t(eur(data["cp"]["resultat_calcule"]))],
            ["Clients facturés", str(risque["nb_clients"])],
            ["Client principal", Paragraph(_t(f"{risque['top1_client']} ({risque['top1_part']:.1f} %)"), p)],
            ["Risque de dépendance client", _t(risque["niveau_risque"].capitalize())],
            ["Immobilisations brutes en fin d'exercice", _t(eur(data["immo"]["solde_final"]))],
            ["Amortissements cumulés en fin d'exercice", _t(eur(data["amort"]["solde_final"]))],
            ["Capitaux propres en fin d'exercice (hors résultat)", _t(eur(data["cp"]["total_fin"]))],
            ["Doublons probables", str(anom["nb_doublons"])],
            ["Écritures déséquilibrées", str(anom["nb_desequilibres"])],
            ["Montants inhabituels", str(anom["nb_montants_aberrants"])],
            ["Soldes de sens anormal", str(anom["nb_soldes_suspects"])],
            ["Factures de vente manquantes dans la numérotation", str(anom["nb_factures_manquantes"])]]
    e.append(_table(cles, [100 * mm, 80 * mm]))

    mois = ca_mens[ca_mens["Mois"] != "TOTAL"]
    if 0 < len(mois) <= 24:
        e.append(Paragraph("Chiffre d'affaires HT par mois", h2))
        d = Drawing(180 * mm, 70 * mm)
        g = VerticalBarChart()
        g.x, g.y, g.width, g.height = 18 * mm, 10 * mm, 155 * mm, 52 * mm
        g.data = [[float(x) for x in mois["CA_HT"]]]
        g.categoryAxis.categoryNames = [str(m)[2:] for m in mois["Mois"]]
        g.categoryAxis.labels.fontSize = 6
        g.valueAxis.labels.fontSize = 6
        g.valueAxis.valueMin = min(0.0, min(g.data[0]))
        g.bars[0].fillColor = BLEU
        g.bars[0].strokeColor = BLEU
        d.add(g)
        e.append(d)

    doc.build(e, onFirstPage=_pied, onLaterPages=_pied)
