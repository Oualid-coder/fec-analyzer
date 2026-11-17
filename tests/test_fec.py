"""Tests de bout en bout sur des FEC fictifs : un fichier conforme, puis un défaut à la fois."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from modules import stockage
from modules.anomalies import sequentialite
from modules.conformite import AVERT, ERREUR, INFO, OK, controler
from modules.loader import CHAMPS_FEC, FecIllisible, lire_fec, normaliser
from tests.fabrique import COL, ecrire, lignes_conformes


@pytest.fixture(autouse=True)
def espace(tmp_path, monkeypatch):
    monkeypatch.setenv("FEC_ANALYZER_HOME", str(tmp_path / "espace"))
    return tmp_path


def statuts(chemin):
    brut = lire_fec(chemin)
    conf = controler(brut, normaliser(brut))
    return conf, {c.code: c for c in conf["controles"]}


def modifie(fonction):
    lignes = copy.deepcopy(lignes_conformes())
    fonction(lignes)
    return lignes


# ── Fichier conforme ────────────────────────────────────────────────────────

def test_fichier_conforme(espace):
    conf, c = statuts(ecrire(espace))
    assert conf["verdict"] == "CONFORME"
    assert all(x.statut in (OK, INFO) for x in conf["controles"]), [(x.code, x.statut, x.message) for x in conf["controles"]]


@pytest.mark.parametrize("sep,encodage", [("|", "utf-8"), ("\t", "iso-8859-15"), ("|", "iso-8859-15")])
def test_variantes_conformes(espace, sep, encodage):
    conf, c = statuts(ecrire(espace, sep=sep, encodage=encodage))
    assert conf["verdict"] == "CONFORME"
    assert "Matériel" in normaliser(lire_fec(ecrire(espace, sep=sep, encodage=encodage)))["CompteLib"].iloc[0]


def test_variante_montant_sens(espace):
    entete = ["Montant" if x == "Debit" else "Sens" if x == "Credit" else x for x in CHAMPS_FEC]
    def f(L):
        for l in L:
            debit = l[COL["Debit"]] != "0,00"
            l[COL["Debit"]], l[COL["Credit"]] = (l[COL["Debit"]], "D") if debit else (l[COL["Credit"]], "C")
    conf, c = statuts(ecrire(espace, modifie(f), entete=entete))
    assert conf["verdict"] == "CONFORME", [(x.code, x.statut, x.message) for x in conf["controles"]]


def test_meme_fichier_meme_resultat(espace):
    chemin = ecrire(espace)
    a, _ = statuts(chemin)
    b, _ = statuts(chemin)
    assert [(c.code, c.statut, c.nb, c.message) for c in a["controles"]] == [(c.code, c.statut, c.nb, c.message) for c in b["controles"]]


# ── Un défaut à la fois ─────────────────────────────────────────────────────

def test_nom_de_fichier(espace):
    _, c = statuts(ecrire(espace, nom="export_compta.txt"))
    assert c["S01"].statut == AVERT


def test_separateur_point_virgule(espace):
    conf, c = statuts(ecrire(espace, sep=";"))
    assert c["S02"].statut == ERREUR and conf["verdict"] == "NON CONFORME"


def test_entete_dans_le_desordre(espace):
    entete = list(CHAMPS_FEC)
    entete[0], entete[1] = entete[1], entete[0]
    _, c = statuts(ecrire(espace, entete=entete))
    assert c["S03"].statut == ERREUR and c["S03"].nb == 2


def test_ligne_tronquee(espace):
    chemin = ecrire(espace)
    lignes = chemin.read_bytes().decode("utf-8").split("\r\n")
    lignes[10] = "\t".join(lignes[10].split("\t")[:12])
    chemin.write_bytes("\r\n".join(lignes).encode("utf-8"))
    _, c = statuts(chemin)
    assert c["S04"].statut == ERREUR and c["S04"].details.iloc[0]["Ligne"] == 11


def test_champ_obligatoire_vide(espace):
    _, c = statuts(ecrire(espace, modifie(lambda L: L[7].__setitem__(COL["PieceRef"], ""))))
    assert c["C01"].statut == ERREUR and c["C01"].nb == 1
    assert c["C01"].details.iloc[0]["Ligne"] == 9 and c["C01"].details.iloc[0]["Champ"] == "PieceRef"


def test_date_mal_formee(espace):
    def f(L):
        L[3][COL["PieceDate"]] = "31/12/2024"
        L[4][COL["PieceDate"]] = "20240231"
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C02"].statut == ERREUR and c["C02"].nb == 2
    assert set(c["C02"].details["Cause"]) == {"Format attendu AAAAMMJJ (ex. 20241231)", "Date inexistante au calendrier"}


def test_montant_invalide_et_point_decimal(espace):
    def f(L):
        L[0][COL["Debit"]] = "12 000,00"
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C03"].statut == ERREUR
    _, c = statuts(ecrire(espace, modifie(lambda L: L[0].__setitem__(COL["Debit"], "12000.00"))))
    assert c["C03"].statut == AVERT and c["C04"].statut == OK      # le point est lu, mais signalé


def test_anomalies_relevees_par_l_outil_dgfip(espace):
    """Débit et crédit sur la même ligne, ligne à zéro, compte ne commençant pas par 3 chiffres."""
    def f(L):
        L[5][COL["Debit"]], L[5][COL["Credit"]] = "10,00", "10,00"
        L[6][COL["Debit"]], L[6][COL["Credit"]] = "0,00", "0,00"
        L[7][COL["CompteNum"]] = "4A1000"
    conf, c = statuts(ecrire(espace, modifie(f)))
    assert c["C03"].statut == ERREUR and c["C03"].nb == 2
    assert set(c["C03"].details["Ligne"]) == {7, 8}
    assert c["C09"].statut == ERREUR and c["C09"].details.iloc[0]["Ligne"] == 9
    assert conf["verdict"] == "NON CONFORME"


def test_ecriture_desequilibree(espace):
    conf, c = statuts(ecrire(espace, modifie(lambda L: L[5].__setitem__(COL["Debit"], "9999,00"))))
    assert c["C04"].statut == ERREUR and c["C04"].nb == 1 and conf["verdict"] == "NON CONFORME"
    assert "VE / 2" in c["C04"].details.iloc[0]["Valeur"]


def test_date_apres_cloture(espace):
    def f(L):
        for l in L[-2:]:
            l[COL["EcritureDate"]] = "20250105"
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C06"].statut == ERREUR and c["C06"].nb == 2


def test_validation_avant_ecriture(espace):
    _, c = statuts(ecrire(espace, modifie(lambda L: L[20].__setitem__(COL["ValidDate"], "20230101"))))
    assert c["C07"].statut == AVERT and c["C07"].nb == 1


def test_trou_dans_la_numerotation(espace):
    def f(L):
        for l in L:
            if int(l[COL["EcritureNum"]]) >= 30:
                l[COL["EcritureNum"]] = str(int(l[COL["EcritureNum"]]) + 2)
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C08"].statut == AVERT and c["C08"].nb == 2


def test_compte_invalide_et_libelles_multiples(espace):
    def f(L):
        L[0][COL["CompteNum"]] = "X1"
        L[30][COL["CompteLib"]] = "Autre libellé"
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C09"].statut == ERREUR and c["C09"].nb == 2


def test_lettrage_sans_date_et_non_solde(espace):
    def f(L):
        ventes = [l for l in L if l[COL["EcritureLet"]] == "A001"]
        ventes[0][COL["DateLet"]] = ""
        autre = [l for l in L if l[COL["EcritureLet"]] == "A002"][0]
        autre[COL["EcritureLet"]], autre[COL["DateLet"]] = "", ""
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C11"].statut == AVERT and c["C11"].nb == 2


def test_a_nouveaux_absents(espace):
    _, c = statuts(ecrire(espace, [l for l in lignes_conformes() if l[0] != "AN"]))
    assert c["C13"].statut == INFO


def test_ligne_en_double(espace):
    def f(L):
        L += [list(L[40]), list(L[41]), list(L[42])]
    _, c = statuts(ecrire(espace, modifie(f)))
    assert c["C14"].statut == AVERT and c["C14"].nb == 3


def test_fichier_qui_n_est_pas_un_fec(espace):
    p = espace / "notes.txt"
    p.write_text("bonjour\tle\tmonde\n1\t2\t3\n", encoding="utf-8")
    with pytest.raises(FecIllisible):
        lire_fec(p)
    vide = espace / "vide.txt"
    vide.write_text("", encoding="utf-8")
    with pytest.raises(FecIllisible):
        lire_fec(vide)


# ── Analyses ────────────────────────────────────────────────────────────────

def test_chiffres_cles(espace):
    from main import analyser_fichier
    r = analyser_fichier(ecrire(espace))
    attendu = sum(1000 + 100 * (i % 5) for i in range(1, 25))
    assert r["ok"] and r["ca_ht"] == attendu
    assert r["resultat"] == attendu - 12 * 800 - 2800
    assert r["anomalies"] == {"nb_doublons": 0, "nb_desequilibres": 0, "nb_montants_aberrants": 0,
                              "nb_soldes_suspects": 0, "nb_factures_manquantes": 0}
    racine = stockage.racine()
    for cle in ("excel", "pdf"):
        assert (racine / r[cle]).stat().st_size > 2000
    assert (racine / "dossiers/123456789/2024-12-31/fec/123456789FEC20241231.txt").is_file()
    assert json.loads((racine / r["dossier"] / "controles.json").read_text(encoding="utf-8"))["verdict"] == "CONFORME"
    assert "Verdict : CONFORME" in (racine / r["dossier"] / "analyse.log").read_text(encoding="utf-8")
    assert stockage.lire_historique()[0]["sha256"] == r["sha256"]


def test_facture_manquante(espace):
    lignes = [l for l in lignes_conformes() if l[COL["PieceRef"]] != "FA2024-0007"]
    brut = lire_fec(ecrire(espace, lignes))
    rupt, seq = sequentialite(normaliser(brut))
    assert list(rupt["N° manquant"]) == ["FA2024-0007"]
    assert int(seq.loc[seq["Série"] == "TOTAL", "Nb manquant"].iloc[0]) == 1


def test_numerotation_qui_repart_chaque_mois(espace):
    """Format AAMM + rang (ex. IND240101) : le changement de mois n'est pas un trou."""
    def f(L):
        rang = {}
        for l in L:
            if l[0] == "VE":
                mois = l[COL["EcritureDate"]][2:6]
                if l[COL["CompteNum"]] == "411000":
                    rang[mois] = rang.get(mois, 0) + 1
                l[COL["PieceRef"]] = f"IND{mois}{rang[mois]:02d}"
    rupt, seq = sequentialite(normaliser(lire_fec(ecrire(espace, modifie(f)))))
    assert len(rupt) == 0 and len(seq) == 13


def test_libelle_commencant_par_egal_reste_du_texte(espace):
    from openpyxl import load_workbook
    from main import analyser_fichier
    def f(L):
        for l in L:
            if l[COL["CompAuxNum"]] == "C001":
                l[COL["CompAuxLib"]] = "=CMD()"
    r = analyser_fichier(ecrire(espace, modifie(f)))
    ws = load_workbook(stockage.racine() / r["excel"])["💰 CA Clients"]
    cellules = [c for ligne in ws.iter_rows() for c in ligne if c.value == "=CMD()"]
    assert cellules and all(c.data_type == "s" for c in cellules)


# ── Interface locale ────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from app import app
    c = TestClient(app, headers={"X-FEC-Analyzer": "1"})
    assert c.post("/api/conditions").status_code == 200
    return c


def test_conditions_obligatoires_avant_tout_controle(espace):
    from app import app
    c = TestClient(app, headers={"X-FEC-Analyzer": "1"})
    assert c.get("/api/infos").json()["conditions"] is False
    texte = c.get("/api/conditions").json()["texte"]
    assert "ne vaut pas attestation" in texte and "aucune donnée" in texte
    fec = ecrire(espace)
    assert c.post("/api/analyser", files=[("fec", (fec.name, fec.read_bytes(), "text/plain"))]).status_code == 428
    assert c.post("/api/demo").status_code == 428
    assert c.post("/api/conditions").status_code == 200
    assert c.get("/api/infos").json()["conditions"] is True
    assert stockage.lire_config()["conditions_version"] == "1"


def test_demo(espace, client):
    rep = client.post("/api/demo")
    assert rep.status_code == 200, rep.text
    r = rep.json()["resultats"][0]
    assert r["ok"] and r["verdict"] == "NON CONFORME" and r["nom_client"].startswith("Exemple fictif")
    en_ecart = {c["code"] for c in r["controles"] if c["statut"] in ("ERREUR", "AVERTISSEMENT")}
    assert {"C01", "C02", "C04", "C07", "C14"} <= en_ecart
    assert r["anomalies"]["nb_factures_manquantes"] == 1
    assert client.get("/api/historique").json()[0]["nom_client"].startswith("Exemple fictif")


def test_api_traitement_en_masse(espace, client):
    a = ecrire(espace)
    b = ecrire(espace, modifie(lambda L: L[5].__setitem__(COL["Debit"], "1,00")), nom="987654321FEC20241231.txt")
    envoi = [("fec", (p.name, p.read_bytes(), "text/plain")) for p in (a, b)]
    envoi.append(("fec", ("photo.png", b"x", "image/png")))
    rep = client.post("/api/analyser", files=envoi)
    assert rep.status_code == 200, rep.text
    res = rep.json()
    assert [r.get("verdict") for r in res["resultats"]] == ["CONFORME", "NON CONFORME", None]
    assert res["recapitulatif"] and client.get("/api/fichier", params={"chemin": res["recapitulatif"]}).status_code == 200
    assert client.get("/api/fichier", params={"chemin": res["resultats"][0]["pdf"]}).content[:4] == b"%PDF"
    assert len(client.get("/api/historique").json()) == 2
    assert client.post("/api/client", json={"client": "123456789", "nom": "Atelier Test"}).status_code == 200
    assert client.get("/api/historique").json()[1]["nom_client"] == "Atelier Test"


def test_api_refuse_ce_qui_n_est_pas_local(espace, client):
    assert client.get("/api/infos", headers={"host": "exemple.com"}).status_code == 403
    assert TestClient(client.app).post("/api/client", json={"client": "a", "nom": "b"}).status_code == 403
    for chemin in ("../../etc/passwd", "/etc/passwd", "dossiers/../../x"):
        assert client.get("/api/fichier", params={"chemin": chemin}).status_code in (403, 404)
    assert client.post("/api/quitter").status_code == 409
