"""Tableau de variation des capitaux propres (comptes 10 à 14) et résultat calculé."""
import pandas as pd

from modules.loader import masque_a_nouveaux

CATEGORIES = [
    ("101", "Capital"), ("104", "Primes d'émission / fusion"), ("105", "Écarts de réévaluation"),
    ("106", "Réserves"), ("108", "Compte de l'exploitant"), ("109", "Capital souscrit non appelé"),
    ("110", "Report à nouveau (créditeur)"), ("119", "Report à nouveau (débiteur)"),
    ("120", "Résultat de l'exercice précédent (bénéfice)"), ("129", "Résultat de l'exercice précédent (perte)"),
    ("13", "Subventions d'investissement"), ("14", "Provisions réglementées"),
]


def _categorie(compte: str) -> str:
    for prefixe, lib in CATEGORIES:
        if compte.startswith(prefixe):
            return lib
    return "Autres capitaux propres"


def resultat_calcule(df: pd.DataFrame) -> float:
    """Produits (classe 7) - charges (classe 6), hors à-nouveaux."""
    x = df[~masque_a_nouveaux(df)]
    c = x["CompteNum"]
    produits = (x.loc[c.str.startswith("7"), "Credit"] - x.loc[c.str.startswith("7"), "Debit"]).sum()
    charges = (x.loc[c.str.startswith("6"), "Debit"] - x.loc[c.str.startswith("6"), "Credit"]).sum()
    return round(float(produits - charges), 2)


def variation_capitaux_propres(df: pd.DataFrame) -> dict:
    cp = df[df["CompteNum"].str.match(r"^1[0-4]")].copy()
    an = masque_a_nouveaux(cp)
    cp["Catégorie"] = cp["CompteNum"].map(_categorie)
    net = cp["Credit"] - cp["Debit"]
    cp["Solde Initial"] = net.where(an, 0.0)
    cp["Augmentations"] = cp["Credit"].where(~an, 0.0)
    cp["Diminutions"] = cp["Debit"].where(~an, 0.0)
    cols = ["Solde Initial", "Augmentations", "Diminutions"]
    detail = cp.groupby("Catégorie", sort=True)[cols].sum().reset_index()
    detail["Solde Final"] = detail["Solde Initial"] + detail["Augmentations"] - detail["Diminutions"]
    cols.append("Solde Final")
    detail[cols] = detail[cols].round(2)
    totaux = {c: round(float(detail[c].sum()), 2) for c in cols}
    detail = pd.concat([detail, pd.DataFrame([{"Catégorie": "TOTAL", **totaux}])], ignore_index=True)
    return {
        "total_debut": totaux["Solde Initial"], "total_fin": totaux["Solde Final"],
        "variation": round(totaux["Solde Final"] - totaux["Solde Initial"], 2),
        "resultat_calcule": resultat_calcule(df), "detail": detail,
    }
