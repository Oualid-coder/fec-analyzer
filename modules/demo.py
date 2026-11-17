"""FEC fictifs : un exercice conforme, et un exemple volontairement abîmé pour les démonstrations.

Aucune donnée réelle : société, clients et montants sont inventés.
Le même générateur sert aux tests automatiques (tests/fabrique.py).
"""
from __future__ import annotations

import copy
from pathlib import Path

from modules.loader import CHAMPS_FEC

CLIENTS = [("C001", "ATELIER DURAND"), ("C002", "GARAGE LEFEVRE"), ("C003", "BOULANGERIE PETIT")]


def _l(journal, lib_j, num, date, compte, lib_c, aux, lib_aux, piece, lib, debit, credit, let="", date_let=""):
    def m(x):
        return f"{x:.2f}".replace(".", ",")
    return [journal, lib_j, str(num), date, compte, lib_c, aux, lib_aux, piece, date, lib,
            m(debit), m(credit), let, date_let, date, "", ""]


def lignes_conformes() -> list[list[str]]:
    """Exercice 2024 d'une petite société de services : à-nouveaux, 24 ventes, achats, banque, dotation."""
    L, n = [], 0
    n += 1
    for compte, lib, d, c in [("218300", "Matériel de bureau", 12000, 0), ("281830", "Amort. matériel de bureau", 0, 4000),
                              ("512000", "Banque", 18000, 0), ("101000", "Capital", 0, 20000),
                              ("106100", "Réserve légale", 0, 6000)]:
        L.append(_l("AN", "A nouveaux", n, "20240101", compte, lib, "", "", "AN2024", "Reprise des soldes", d, c))
    facture = 0
    for mois in range(1, 13):
        for jour in (5, 20):
            facture += 1
            n += 1
            code, nom = CLIENTS[facture % 3]
            ht = 1000 + 100 * (facture % 5)
            date, piece = f"2024{mois:02d}{jour:02d}", f"FA2024-{facture:04d}"
            lettre = f"A{facture:03d}"
            L.append(_l("VE", "Ventes", n, date, "411000", "Clients", code, nom, piece, f"Facture {piece}", ht * 1.2, 0, lettre, date))
            L.append(_l("VE", "Ventes", n, date, "706000", "Prestations de services", "", "", piece, f"Facture {piece}", 0, ht))
            L.append(_l("VE", "Ventes", n, date, "445710", "TVA collectée", "", "", piece, f"Facture {piece}", 0, ht * 0.2))
            n += 1
            L.append(_l("BQ", "Banque", n, date, "512000", "Banque", "", "", f"RG{facture:04d}", f"Règlement {piece}", ht * 1.2, 0))
            L.append(_l("BQ", "Banque", n, date, "411000", "Clients", code, nom, f"RG{facture:04d}", f"Règlement {piece}", 0, ht * 1.2, lettre, date))
    for mois in range(1, 13):
        n += 1
        date, piece = f"2024{mois:02d}15", f"LOY{mois:02d}"
        L.append(_l("AC", "Achats", n, date, "613200", "Locations immobilières", "", "", piece, "Loyer", 800, 0))
        L.append(_l("AC", "Achats", n, date, "445660", "TVA déductible", "", "", piece, "Loyer", 160, 0))
        L.append(_l("AC", "Achats", n, date, "401000", "Fournisseurs", "F001", "SCI DU PARC", piece, "Loyer", 0, 960))
    n += 1
    L.append(_l("AC", "Achats", n, "20240610", "218300", "Matériel de bureau", "", "", "FOU77", "Ordinateur", 2000, 0))
    L.append(_l("AC", "Achats", n, "20240610", "445620", "TVA sur immobilisations", "", "", "FOU77", "Ordinateur", 400, 0))
    L.append(_l("AC", "Achats", n, "20240610", "404000", "Fournisseurs d'immobilisations", "F002", "INFO PRO", "FOU77", "Ordinateur", 0, 2400))
    n += 1
    L.append(_l("OD", "Opérations diverses", n, "20241231", "681120", "Dotations aux amortissements", "", "", "DOT2024", "Dotation 2024", 2800, 0))
    L.append(_l("OD", "Opérations diverses", n, "20241231", "281830", "Amort. matériel de bureau", "", "", "DOT2024", "Dotation 2024", 0, 2800))
    return L


def ecrire(dossier: Path, lignes=None, nom="123456789FEC20241231.txt", sep="\t", entete=None,
           encodage="utf-8", fin_ligne="\r\n") -> Path:
    lignes = lignes_conformes() if lignes is None else lignes
    entete = CHAMPS_FEC if entete is None else entete
    texte = fin_ligne.join(sep.join(l) for l in [entete] + lignes) + fin_ligne
    chemin = Path(dossier) / nom
    chemin.write_bytes(texte.encode(encodage))
    return chemin


COL = {c: i for i, c in enumerate(CHAMPS_FEC)}


SIREN_DEMO = "000000000"
NOM_DEMO = "Exemple fictif (démonstration)"
FICHIER_DEMO = f"{SIREN_DEMO}FEC20241231.txt"


def lignes_demo() -> list[list[str]]:
    """Le même exercice, avec six défauts typiques plantés à des endroits connus."""
    L = copy.deepcopy(lignes_conformes())
    L[5][COL["Debit"]] = "9999,00"                        # écriture de vente déséquilibrée
    L[7][COL["PieceRef"]] = ""                            # référence de pièce manquante
    L[3][COL["PieceDate"]] = "31/12/2024"                 # date au mauvais format
    L[20][COL["ValidDate"]] = "20230101"                  # validée avant d'être passée
    L = [l for l in L if l[COL["PieceRef"]] != "FA2024-0007"]   # une facture disparue
    L += [list(L[40]), list(L[41])]                       # deux lignes importées deux fois
    return L


def fec_demo(dossier: str | Path) -> Path:
    return ecrire(Path(dossier), lignes_demo(), nom=FICHIER_DEMO)
