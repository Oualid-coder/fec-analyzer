"""Interface locale de FEC Analyzer.

Le serveur n'écoute que sur cette machine (127.0.0.1) : rien n'est exposé sur le
réseau et aucune donnée n'est envoyée à l'extérieur.
"""
from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from datetime import datetime

from main import EXTENSIONS, analyser_fichier, configurer_journal, recapitulatif
from modules import VERSION, VERSION_CONDITIONS, stockage
from modules.demo import FICHIER_DEMO, NOM_DEMO, SIREN_DEMO, fec_demo

log = logging.getLogger("fec.app")
RESSOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
TAILLE_MAX = 500 * 1024 * 1024            # par fichier
HOTES_LOCAUX = {"127.0.0.1", "localhost", "testserver"}
TELECHARGEABLES = {".xlsx", ".pdf", ".json", ".log", ".txt", ".csv"}
_verrou = threading.Lock()                # une analyse à la fois : résultats et journaux lisibles

app = FastAPI(title="FEC Analyzer", docs_url=None, redoc_url=None, openapi_url=None)
app.state.arreter = None                  # renseigné par le lanceur pour permettre « Quitter »


@app.middleware("http")
async def local_uniquement(request: Request, call_next):
    """Refuse ce qui ne vient pas de l'interface locale (autre site web, autre machine)."""
    hote = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if hote not in HOTES_LOCAUX:
        return JSONResponse({"detail": "Accès local uniquement"}, status_code=403)
    if request.method != "GET" and request.headers.get("x-fec-analyzer") != "1":
        return JSONResponse({"detail": "Requête refusée"}, status_code=403)
    reponse = await call_next(request)
    reponse.headers["Cache-Control"] = "no-store"
    reponse.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'; connect-src 'self'"
    return reponse


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def index():
    return (RESSOURCES / "index.html").read_text(encoding="utf-8")


def conditions_acceptees() -> bool:
    return stockage.lire_config().get("conditions_version") == VERSION_CONDITIONS


def exiger_conditions() -> None:
    if not conditions_acceptees():
        raise HTTPException(428, "Les conditions d'utilisation doivent être acceptées avant le premier contrôle.")


@app.get("/api/infos")
def infos():
    return {"application": "fec-analyzer", "version": VERSION, "espace": str(stockage.racine()),
            "quitter": app.state.arreter is not None, "conditions": conditions_acceptees()}


@app.get("/api/conditions")
def conditions():
    return {"version": VERSION_CONDITIONS, "acceptees": conditions_acceptees(),
            "texte": (RESSOURCES / "conditions.txt").read_text(encoding="utf-8")}


@app.post("/api/conditions")
def accepter_conditions():
    stockage.ecrire_config(conditions_version=VERSION_CONDITIONS,
                           conditions_acceptees_le=datetime.now().isoformat(timespec="seconds"))
    log.info("Conditions d'utilisation version %s acceptées", VERSION_CONDITIONS)
    return {"ok": True}


@app.post("/api/demo")
def demo():
    """Contrôle un FEC fictif, volontairement abîmé : montre l'outil sans utiliser de données réelles."""
    exiger_conditions()
    configurer_journal()
    with tempfile.TemporaryDirectory(prefix="fec_analyzer_demo_") as tmp, _verrou:
        r = analyser_fichier(fec_demo(tmp), nom_origine=FICHIER_DEMO)
    if r.get("ok"):
        stockage.nommer_client(SIREN_DEMO, NOM_DEMO)
        r["nom_client"] = NOM_DEMO
    return {"resultats": [r], "recapitulatif": None}


@app.post("/api/analyser")
def analyser(fec: list[UploadFile] = File(...)):
    exiger_conditions()
    configurer_journal()
    resultats = []
    with tempfile.TemporaryDirectory(prefix="fec_analyzer_") as tmp, _verrou:
        for i, envoi in enumerate(fec):
            nom = stockage.nom_sur(envoi.filename or f"fec_{i}.txt", "fec.txt")
            if Path(nom).suffix.lower() not in EXTENSIONS:
                resultats.append({"ok": False, "fichier": nom,
                                  "erreur": "Type de fichier non pris en charge (attendu : .txt, .csv ou .xlsx)."})
                continue
            cible = Path(tmp) / f"{i}_{nom}"
            with open(cible, "wb") as f:
                shutil.copyfileobj(envoi.file, f, length=1 << 20)
            if cible.stat().st_size > TAILLE_MAX:
                resultats.append({"ok": False, "fichier": nom, "erreur": "Fichier trop volumineux (plus de 500 Mo)."})
                continue
            resultats.append(analyser_fichier(cible, nom_origine=nom))
        for r in resultats:
            if r.get("ok"):
                r["nom_client"] = stockage.nom_client(r["client"])
        return {"resultats": resultats, "recapitulatif": recapitulatif(resultats)}


@app.get("/api/historique")
def historique():
    hist = stockage.lire_historique()
    noms: dict[str, str] = {}
    for h in hist:
        c = h.get("client", "")
        if c not in noms:
            noms[c] = stockage.nom_client(c)
        h["nom_client"] = noms[c]
    return hist


@app.get("/api/fichier")
def fichier(chemin: str):
    try:
        cible = stockage.resoudre(chemin)
    except PermissionError:
        raise HTTPException(403, "Chemin refusé")
    if not cible.is_file() or cible.suffix.lower() not in TELECHARGEABLES:
        raise HTTPException(404, "Fichier introuvable")
    return FileResponse(cible, filename=cible.name)


class Chemin(BaseModel):
    chemin: str = ""


@app.post("/api/ouvrir")
def ouvrir(c: Chemin):
    """Ouvre le dossier dans le Finder / l'Explorateur de fichiers."""
    try:
        cible = stockage.resoudre(c.chemin)
    except PermissionError:
        raise HTTPException(403, "Chemin refusé")
    if not cible.exists():
        raise HTTPException(404, "Dossier introuvable")
    stockage.ouvrir_dans_explorateur(cible)
    return {"ok": True}


class NomClient(BaseModel):
    client: str
    nom: str


@app.post("/api/client")
def nommer(n: NomClient):
    try:
        stockage.nommer_client(n.client, n.nom)
    except FileNotFoundError:
        raise HTTPException(404, "Dossier client introuvable")
    return {"ok": True}


@app.post("/api/quitter")
def quitter():
    if app.state.arreter is None:
        raise HTTPException(409, "Arrêt indisponible dans ce mode de lancement")
    log.info("Arrêt demandé depuis l'interface")
    threading.Timer(0.3, app.state.arreter).start()
    return {"ok": True}
