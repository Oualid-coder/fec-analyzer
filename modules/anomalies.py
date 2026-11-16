"""Anomalies comptables et séquentialité des factures de vente.

Tout est déterministe : seuils fixes, tris stables, aucun tirage aléatoire.
"""
import re

import pandas as pd

from modules.ca import journaux_de_vente
from modules.loader import masque_a_nouveaux

MAX_LIGNES = 200            # lignes affichées par tableau d'anomalies (le total réel est conservé à part)
TROU_MAX = 100              # au-delà, un saut de numéro est traité comme un changement de série

COLS_RUPT = ["Série", "N° manquant", "Avant", "Après", "Écart"]
COLS_SEQ = ["Série", "1ère facture", "Dernière facture", "Nb attendu", "Nb présent",
            "Nb manquant", "Complétude %", "Statut"]


def _date(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%d/%m/%Y").fillna("")


def detect_anomalies(df: pd.DataFrame) -> dict:
    anomalies = {}
    an = masque_a_nouveaux(df)

    # 1. Doublons probables : même compte, même pièce, même date, même montant, dans des écritures différentes
    cle = ["CompteNum", "CompAuxNum", "PieceRef", "EcritureDate", "Debit", "Credit"]
    base = df[~an & (df["PieceRef"] != "") & ((df["Debit"] != 0) | (df["Credit"] != 0))]
    nb_ecr = base.groupby(cle, dropna=False)["EcrId"].transform("nunique")
    dupes = base[nb_ecr > 1].sort_values(cle + ["Ligne"], kind="stable")
    anomalies["nb_doublons"] = int(dupes.groupby(cle, dropna=False).ngroups)
    d = dupes[["Ligne", "EcritureDate", "JournalCode", "EcritureNum", "CompteNum", "CompAuxLib", "PieceRef", "Debit", "Credit"]].head(MAX_LIGNES).copy()
    d["EcritureDate"] = _date(d["EcritureDate"])
    anomalies["doublons"] = d

    # 2. Écritures déséquilibrées
    eq = df.groupby("EcrId", sort=False).agg(
        JournalCode=("JournalCode", "first"), EcritureNum=("EcritureNum", "first"),
        Ligne=("Ligne", "min"), Débit=("Debit", "sum"), Crédit=("Credit", "sum")).reset_index(drop=True)
    eq["Écart"] = (eq["Débit"] - eq["Crédit"]).round(2)
    eq[["Débit", "Crédit"]] = eq[["Débit", "Crédit"]].round(2)
    ko = eq[eq["Écart"].abs() > 0.005].sort_values("Ligne")
    anomalies["nb_desequilibres"] = len(ko)
    anomalies["desequilibres"] = ko.head(MAX_LIGNES).reset_index(drop=True)

    # 3. Montants inhabituels (moyenne + 3 écarts-types, hors à-nouveaux et opérations diverses)
    hors = df[~an & ~df["JournalCode"].str.upper().str.startswith("OD")]
    m = hors[["Debit", "Credit"]].max(axis=1)
    m = m[m > 0]
    seuil = round(float(m.mean() + 3 * m.std()), 2) if len(m) > 1 else 0.0
    ab = hors[(hors[["Debit", "Credit"]].max(axis=1) > seuil)] if seuil else hors.iloc[0:0]
    ab = ab.sort_values("Ligne")
    anomalies["nb_montants_aberrants"] = len(ab)
    a = ab[["Ligne", "EcritureDate", "JournalCode", "CompteNum", "CompteLib", "CompAuxLib", "Debit", "Credit"]].head(MAX_LIGNES).copy()
    a["EcritureDate"] = _date(a["EcritureDate"])
    anomalies["montants_aberrants"] = a
    anomalies["seuil_aberrant"] = seuil

    # 4. Comptes dont le solde est dans le sens inverse du sens normal
    soldes = df.groupby("CompteNum").agg(CompteLib=("CompteLib", "first"),
                                         D=("Debit", "sum"), C=("Credit", "sum")).reset_index()
    soldes["Solde"] = (soldes["D"] - soldes["C"]).round(2)
    n = soldes["CompteNum"]
    regles = [
        (n.str.startswith("411") & (soldes["Solde"] < -1), "Clients créditeurs (avoirs ou acomptes non soldés ?)"),
        (n.str.startswith("401") & (soldes["Solde"] > 1), "Fournisseurs débiteurs (acomptes ou double paiement ?)"),
        (n.str.startswith("512") & (soldes["Solde"] < -1), "Banque créditrice (découvert)"),
        (n.str.startswith("53") & (soldes["Solde"] < -1), "Caisse créditrice : impossible en pratique"),
        (n.str.startswith("6") & (soldes["Solde"] < -1), "Compte de charge créditeur"),
        (n.str.startswith("7") & (soldes["Solde"] > 1), "Compte de produit débiteur"),
        (n.str.startswith("47") & (soldes["Solde"].abs() > 1), "Compte d'attente non soldé"),
    ]
    morceaux = []
    for masque, constat in regles:
        if masque.any():
            x = soldes.loc[masque, ["CompteNum", "CompteLib", "Solde"]].copy()
            x["Constat"] = constat
            morceaux.append(x)
    sens = (pd.concat(morceaux, ignore_index=True).sort_values("CompteNum", kind="stable")
            if morceaux else pd.DataFrame(columns=["CompteNum", "CompteLib", "Solde", "Constat"]))
    anomalies["nb_soldes_suspects"] = len(sens)
    anomalies["soldes_negatifs_suspects"] = sens.head(MAX_LIGNES).reset_index(drop=True)

    # 5. Séquentialité des factures de vente
    anomalies["ruptures_sequence"], anomalies["tableau_sequentialite"] = sequentialite(df)
    seq = anomalies["tableau_sequentialite"]
    anomalies["nb_factures_manquantes"] = int(seq.loc[seq["Série"] == "TOTAL", "Nb manquant"].iloc[0]) if len(seq) else 0
    return anomalies


_REF = re.compile(r"^(.*?)(\d+)$")


def _series_factures(df: pd.DataFrame) -> dict:
    """Regroupe les références de factures de vente par série : {série: {numéro: référence}}.

    Une série = même préfixe et même nombre de chiffres (FA2024-0001 et AV2024-0001 sont
    deux séries). Si le numéro commence par AAMM ou AAAAMM, la période fait partie de la
    série : la numérotation qui repart à 1 chaque mois n'est pas vue comme un trou.
    """
    ventes = df[df["JournalCode"].isin(journaux_de_vente(df)) & df["CompteNum"].str.startswith("70")]
    refs = sorted(set(ventes["PieceRef"]) - {""})
    series: dict = {}
    for ref in refs:
        m = _REF.match(ref)
        if not m:
            continue
        prefixe, chiffres = m.group(1), m.group(2)
        cle, num = (prefixe, len(chiffres)), int(chiffres)
        series.setdefault(cle, {})[num] = ref
    resultat, sans_periode = {}, {}
    for (prefixe, largeur), nums in series.items():
        decoupe = None
        for nb_periode in (6, 4):                    # AAAAMM puis AAMM
            if largeur > nb_periode + 1:
                mois = [int(f"{n:0{largeur}d}"[nb_periode - 2:nb_periode]) for n in nums]
                if all(1 <= x <= 12 for x in mois) and len({f"{n:0{largeur}d}"[:nb_periode] for n in nums}) > 1:
                    decoupe = nb_periode
                    break
        if decoupe:
            for n, ref in nums.items():
                txt = f"{n:0{largeur}d}"
                resultat.setdefault(f"{prefixe}{txt[:decoupe]}", {})[int(txt[decoupe:])] = ref
        else:
            sans_periode.setdefault(prefixe, {})[largeur] = nums
    for prefixe, par_largeur in sans_periode.items():
        # Numéros sans zéros de remplissage (FA9, FA10...) : une seule série quelle que soit la longueur.
        remplis = any(ref[len(prefixe)] == "0" and len(ref) - len(prefixe) > 1
                      for nums in par_largeur.values() for ref in nums.values())
        if remplis:
            for largeur, nums in par_largeur.items():
                resultat[f"{prefixe}{'#' * largeur}"] = nums
        else:
            fusion = {}
            for nums in par_largeur.values():
                fusion.update(nums)
            resultat[f"{prefixe}#"] = fusion
    return resultat


def sequentialite(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (détail des numéros manquants, tableau récapitulatif par série)."""
    ruptures, recap = [], []
    for serie, nums in sorted(_series_factures(df).items()):
        ordonnes = sorted(nums)
        manquants = 0
        for avant, apres in zip(ordonnes, ordonnes[1:]):
            trou = apres - avant - 1
            if trou <= 0:
                continue
            if trou > TROU_MAX:
                ruptures.append({"Série": serie, "N° manquant": f"(saut de {trou} numéros)",
                                 "Avant": nums[avant], "Après": nums[apres], "Écart": 0})
                continue
            manquants += trou
            largeur = len(nums[avant]) - len(nums[avant].rstrip("0123456789"))
            racine = nums[avant][:len(nums[avant]) - largeur]
            for n in range(avant + 1, apres):
                ruptures.append({"Série": serie, "N° manquant": f"{racine}{n:0{largeur}d}",
                                 "Avant": nums[avant], "Après": nums[apres], "Écart": trou})
        present = len(ordonnes)
        attendu = present + manquants
        recap.append({
            "Série": serie, "1ère facture": nums[ordonnes[0]], "Dernière facture": nums[ordonnes[-1]],
            "Nb attendu": attendu, "Nb présent": present, "Nb manquant": manquants,
            "Complétude %": round(present / attendu * 100, 1) if attendu else 100.0,
            "Statut": "OK" if manquants == 0 else f"{manquants} manquant(s)"})
    rupt = pd.DataFrame(ruptures, columns=COLS_RUPT)
    if not recap:
        return rupt, pd.DataFrame(columns=COLS_SEQ)
    seq = pd.DataFrame(recap, columns=COLS_SEQ)
    att, pres, manq = int(seq["Nb attendu"].sum()), int(seq["Nb présent"].sum()), int(seq["Nb manquant"].sum())
    total = pd.DataFrame([{
        "Série": "TOTAL", "1ère facture": "", "Dernière facture": "", "Nb attendu": att,
        "Nb présent": pres, "Nb manquant": manq,
        "Complétude %": round(pres / att * 100, 1) if att else 100.0,
        "Statut": "OK" if manq == 0 else f"{manq} manquant(s)"}])
    return rupt, pd.concat([seq, total], ignore_index=True)
