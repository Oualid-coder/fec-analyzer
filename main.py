"""FEC Analyzer : contrôle de conformité et analyse d'un ou plusieurs FEC, 100 % en local.

Ligne de commande :
    python main.py <fichier FEC ou dossier> [<autre fichier>...]
    python main.py --demo          contrôle un FEC fictif volontairement abîmé

Les rapports sont rangés dans l'espace de travail (voir modules/stockage.py).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd

from modules import VERSION, stockage
from modules.anomalies import detect_anomalies
from modules.ca import ca_journalier, ca_mensuel, ca_par_client, ca_weekends, risque_dependance
from modules.capitaux import variation_capitaux_propres
from modules.conformite import controler
from modules.export import export_rapport
from modules.immobilisations import variation_amortissements, variation_immobilisations
from modules.loader import FecIllisible, exercice, lire_fec, normaliser
from modules.pdf import export_pdf

log = logging.getLogger("fec")
EXTENSIONS = {".txt", ".csv", ".xlsx", ".xls", ".xlsm"}
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def configurer_journal() -> None:
    """Journal technique de l'application (rotation : 5 fichiers de 1 Mo)."""
    if getattr(configurer_journal, "fait", False):
        return
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(stockage.racine() / "journaux" / "application.log",
                            maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter(_FORMAT))
    log.addHandler(h)
    configurer_journal.fait = True


def _etape(nom: str, fonction, *args):
    """Exécute une étape d'analyse en journalisant sa durée (ou son échec, avec la cause)."""
    t0 = time.perf_counter()
    try:
        r = fonction(*args)
    except Exception:
        log.exception("Étape « %s » en échec", nom)
        raise
    log.info("Étape « %s » : %.0f ms", nom, (time.perf_counter() - t0) * 1000)
    return r


def analyser_fichier(chemin: str | Path, nom_origine: str | None = None) -> dict:
    """Contrôle et analyse un FEC, écrit les rapports, retourne un résumé (toujours, même en cas d'échec)."""
    configurer_journal()
    chemin = Path(chemin)
    nom = nom_origine or chemin.name
    t0 = time.perf_counter()
    try:
        brut = lire_fec(chemin)
    except FecIllisible as e:
        log.warning("Fichier refusé %s : %s", nom, e)
        return {"ok": False, "fichier": nom, "erreur": str(e)}
    # Le SIREN et la clôture viennent du nom d'origine (le fichier a pu être renommé à l'envoi).
    if nom != chemin.name:
        from modules.loader import _NOM_FEC
        m = _NOM_FEC.match(nom)
        brut.siren, brut.cloture = (m.group(1), m.group(2)) if m else (None, None)
        brut.nom_fichier = nom

    dossiers = stockage.preparer_analyse(brut.siren, brut.cloture, nom)
    journal = logging.FileHandler(dossiers["rapports"] / "analyse.log", encoding="utf-8")
    journal.setFormatter(logging.Formatter(_FORMAT))
    log.addHandler(journal)
    try:
        log.info("=== Analyse de %s (FEC Analyzer %s) ===", nom, VERSION)
        log.info("SHA-256 %s | %d lignes | type %s | encodage %s | séparateur %r",
                 brut.sha256, brut.nb_lignes, brut.type_fichier, brut.encodage, brut.separateur)
        df = _etape("normalisation", normaliser, brut)
        exo = exercice(df, brut.cloture)
        conf = _etape("contrôles de conformité", controler, brut, df)
        ca_cl = _etape("CA par client", ca_par_client, df)
        data = {
            "meta": {"fichier": nom, "sha256": brut.sha256, "siren": brut.siren, "exercice": exo["libelle"],
                     "nb_lignes": brut.nb_lignes, "version": VERSION,
                     "date_analyse": datetime.now().strftime("%d/%m/%Y à %H:%M")},
            "conformite": conf,
            "ca_clients": ca_cl, "risque": risque_dependance(ca_cl),
            "ca_mensuel": _etape("CA mensuel", ca_mensuel, df),
            "ca_journalier": _etape("CA journalier", ca_journalier, df),
            "ca_weekends": _etape("CA week-ends", ca_weekends, df),
            "immo": _etape("immobilisations", variation_immobilisations, df),
            "amort": _etape("amortissements", variation_amortissements, df),
            "cp": _etape("capitaux propres", variation_capitaux_propres, df),
            "anomalies": _etape("anomalies", detect_anomalies, df),
        }
        rap = dossiers["rapports"]
        _etape("export Excel", export_rapport, data, str(rap / "rapport.xlsx"))
        _etape("export PDF", export_pdf, data, str(rap / "synthese.pdf"))
        stockage.archiver_fec(chemin, dossiers["fec"], nom)

        ca_m = data["ca_mensuel"]
        resume = {
            "ok": True, "fichier": nom, "sha256": brut.sha256,
            "client": dossiers["client"], "siren": brut.siren, "exercice": exo["libelle"],
            "exercice_dossier": dossiers["exercice"], "date": datetime.now().isoformat(timespec="seconds"),
            "nb_lignes": brut.nb_lignes, "verdict": conf["verdict"],
            "nb_erreurs": conf["nb_erreurs"], "nb_avertissements": conf["nb_avertissements"],
            "controles": [c.resume() for c in conf["controles"]],
            "ca_ht": float(ca_m.loc[ca_m["Mois"] == "TOTAL", "CA_HT"].iloc[0]),
            "resultat": data["cp"]["resultat_calcule"],
            "anomalies": {k: v for k, v in data["anomalies"].items() if k.startswith("nb_")},
            "dossier": stockage.relatif(rap), "excel": stockage.relatif(rap / "rapport.xlsx"),
            "pdf": stockage.relatif(rap / "synthese.pdf"),
            "duree_s": round(time.perf_counter() - t0, 2), "version": VERSION,
        }
        (rap / "controles.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
        stockage.ajouter_historique({k: v for k, v in resume.items() if k != "controles"})
        log.info("Analyse terminée en %.2f s : %s", resume["duree_s"], resume["verdict"])
        return resume
    except Exception as e:
        log.exception("Analyse interrompue pour %s", nom)
        return {"ok": False, "fichier": nom,
                "erreur": f"Analyse interrompue ({type(e).__name__} : {e}). Détail dans le journal.",
                "journal": stockage.relatif(dossiers["rapports"] / "analyse.log")}
    finally:
        log.removeHandler(journal)
        journal.close()


def recapitulatif(resultats: list[dict]) -> str | None:
    """Tableau de synthèse d'un traitement en masse : une ligne par FEC. Retourne son chemin relatif."""
    if len(resultats) < 2:
        return None
    lignes = []
    for r in resultats:
        if not r.get("ok"):
            lignes.append({"Fichier": r["fichier"], "Verdict": "ILLISIBLE", "Constat": r.get("erreur", "")})
            continue
        ligne = {"Fichier": r["fichier"], "Client": stockage.nom_client(r["client"]), "SIREN": r["siren"] or "",
                 "Exercice": r["exercice"], "Verdict": r["verdict"], "Contrôles en erreur": r["nb_erreurs"],
                 "Contrôles en avertissement": r["nb_avertissements"], "Lignes": r["nb_lignes"],
                 "CA HT": r["ca_ht"], "Résultat calculé": r["resultat"],
                 "Doublons": r["anomalies"]["nb_doublons"],
                 "Factures manquantes": r["anomalies"]["nb_factures_manquantes"]}
        ligne.update({f"{c['code']} {c['titre']}": c["statut"] for c in r["controles"]})
        ligne["Dossier du rapport"] = r["dossier"]
        lignes.append(ligne)
    chemin = stockage.racine() / "recapitulatifs" / f"recapitulatif_{stockage.horodatage()}.xlsx"
    from openpyxl import Workbook
    from modules.export import _titre, _write_df
    wb = Workbook()
    ws = wb.active
    ws.title = "Récapitulatif"
    row = _titre(ws, 1, f"RÉCAPITULATIF — {len(resultats)} FEC contrôlés")
    _write_df(ws, pd.DataFrame(lignes).fillna(""), start_row=row, col_statut=None, largeur_max=32)
    ws.freeze_panes = ws.cell(row=row + 1, column=2)
    wb.save(chemin)
    log.info("Récapitulatif écrit : %s", chemin)
    return stockage.relatif(chemin)


def lister_fec(cibles: list[str]) -> list[Path]:
    fichiers = []
    for c in cibles:
        p = Path(c)
        if p.is_dir():
            fichiers += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in EXTENSIONS
                               and not f.name.startswith(("~$", ".")))
        else:
            fichiers.append(p)
    return fichiers


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv == ["--demo"]:
        import tempfile
        from modules.demo import fec_demo
        dossier_demo = tempfile.mkdtemp(prefix="fec_analyzer_demo_")
        argv = [str(fec_demo(dossier_demo))]
    fichiers = lister_fec(argv)
    if not fichiers:
        print("Aucun fichier FEC trouvé.")
        return 1
    resultats = []
    for f in fichiers:
        r = analyser_fichier(f)
        resultats.append(r)
        if r["ok"]:
            print(f"{r['verdict']:<24} {r['fichier']}  ({r['nb_erreurs']} erreur(s), "
                  f"{r['nb_avertissements']} avertissement(s))  ->  {stockage.racine() / r['dossier']}")
        else:
            print(f"{'ILLISIBLE':<24} {r['fichier']}  ->  {r['erreur']}")
    recap = recapitulatif(resultats)
    if recap:
        print(f"\nRécapitulatif : {stockage.racine() / recap}")
    return 0 if all(r["ok"] and r["verdict"] != "NON CONFORME" for r in resultats) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
