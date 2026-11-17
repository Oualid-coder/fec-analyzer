"""Espace de travail local : tout reste sur le disque de l'utilisateur.

    ~/FEC Analyzer/
        dossiers/<SIREN>/                      un dossier par client
            dossier.json                       nom du client (facultatif)
            <clôture AAAA-MM-JJ>/              un sous-dossier par exercice
                fec/<fichier d'origine>        copie du FEC analysé
                rapports/<AAAA-MM-JJ_HHhMMmSS>/
                    rapport.xlsx  synthese.pdf  controles.json  analyse.log
        recapitulatifs/                        tableaux de synthèse des traitements en masse
        journaux/application.log               journal technique de l'application
        historique.json                        index des analyses

L'emplacement se change avec la variable d'environnement FEC_ANALYZER_HOME.
Le dossier est volontairement hors de « Documents », souvent synchronisé vers
un cloud (OneDrive, iCloud) sans que l'utilisateur le sache.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

NOM_ESPACE = "FEC Analyzer"
MAX_HISTORIQUE = 5000


def racine() -> Path:
    r = Path(os.environ.get("FEC_ANALYZER_HOME") or Path.home() / NOM_ESPACE)
    for sous in ("dossiers", "recapitulatifs", "journaux"):
        (r / sous).mkdir(parents=True, exist_ok=True)
    return r


def nom_sur(texte: str, defaut: str = "sans-nom") -> str:
    """Nom de fichier/dossier sans caractère dangereux (ni séparateur, ni '..')."""
    s = re.sub(r"[^\w.\- ]+", "_", Path(str(texte)).name, flags=re.UNICODE).strip(" .")
    return s[:120] or defaut


def horodatage() -> str:
    return datetime.now().strftime("%Y-%m-%d_%Hh%Mm%S")


def preparer_analyse(siren: str | None, cloture: str | None, nom_fichier: str) -> dict:
    """Crée les dossiers d'une nouvelle analyse et retourne leurs chemins."""
    client = siren if siren else "sans-siren_" + nom_sur(Path(nom_fichier).stem)
    exo = f"{cloture[:4]}-{cloture[4:6]}-{cloture[6:]}" if cloture else "exercice-non-date"
    base = racine() / "dossiers" / nom_sur(client) / exo
    rapports = base / "rapports" / horodatage()
    n = 1
    while rapports.exists():                      # deux analyses dans la même seconde
        n += 1
        rapports = base / "rapports" / f"{horodatage()}_{n}"
    (base / "fec").mkdir(parents=True, exist_ok=True)
    rapports.mkdir(parents=True)
    return {"client": nom_sur(client), "exercice": exo, "base": base, "fec": base / "fec", "rapports": rapports}


def archiver_fec(source: Path, dossier_fec: Path, nom_origine: str) -> Path:
    cible = dossier_fec / nom_sur(nom_origine, "fec.txt")
    if source.resolve() != cible.resolve():
        shutil.copy2(source, cible)
    return cible


def relatif(chemin: Path) -> str:
    return chemin.resolve().relative_to(racine().resolve()).as_posix()


def resoudre(rel: str) -> Path:
    """Chemin relatif à l'espace de travail -> chemin absolu, en refusant toute sortie de l'espace."""
    base = racine().resolve()
    cible = (base / rel).resolve()
    if cible != base and base not in cible.parents:
        raise PermissionError("Chemin hors de l'espace de travail")
    return cible


# ── Historique ──────────────────────────────────────────────────────────────

def _fichier_historique() -> Path:
    return racine() / "historique.json"


def lire_historique() -> list[dict]:
    f = _fichier_historique()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Index abîmé : on le met de côté plutôt que de le perdre, les rapports restent sur le disque.
        f.replace(f.with_name(f"historique_illisible_{horodatage()}.json"))
        return []


def ajouter_historique(entree: dict) -> None:
    hist = [entree] + lire_historique()
    f = _fichier_historique()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(hist[:MAX_HISTORIQUE], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


# ── Nom des clients ─────────────────────────────────────────────────────────

def nom_client(client: str) -> str:
    f = racine() / "dossiers" / nom_sur(client) / "dossier.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("nom", "")
    except (OSError, json.JSONDecodeError):
        return ""


def nommer_client(client: str, nom: str) -> None:
    d = racine() / "dossiers" / nom_sur(client)
    if not d.is_dir():
        raise FileNotFoundError(client)
    (d / "dossier.json").write_text(json.dumps({"nom": nom.strip()[:120]}, ensure_ascii=False), encoding="utf-8")


def ouvrir_dans_explorateur(chemin: Path) -> None:
    """Ouvre un dossier dans le Finder (Mac), l'Explorateur (Windows) ou le gestionnaire de fichiers (Linux)."""
    chemin = chemin if chemin.is_dir() else chemin.parent
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(chemin)])
    elif os.name == "nt":
        os.startfile(str(chemin))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(chemin)])


# ── Configuration locale ────────────────────────────────────────────────────

def lire_config() -> dict:
    try:
        return json.loads((racine() / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def ecrire_config(**valeurs) -> None:
    config = {**lire_config(), **valeurs}
    f = racine() / "config.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
