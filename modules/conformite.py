"""Contrôles de conformité d'un FEC (article A47 A-1 du Livre des procédures fiscales).

Principes :
- 100 % déterministe : aucune IA, aucun appel réseau. Le même fichier donne
  toujours le même résultat.
- Chaque contrôle a un code stable, une référence, un statut, un nombre
  d'occurrences et le détail ligne par ligne avec la cause.
- Les contrôles tournent sur les données brutes (texte) : rien n'est corrigé
  avant d'être contrôlé.

Ce module n'émet pas d'attestation : il aide à repérer les défauts avant de
remettre le fichier. L'outil officiel de la DGFiP reste « Test Compta Demat ».
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import pandas as pd

from modules.loader import (
    CHAMPS_DATE, CHAMPS_FEC, CHAMPS_FEC_MONTANT_SENS, SEPARATEURS_CONFORMES,
    SEPARATEURS_TOLERES, FecBrut, date_fec, masque_a_nouveaux, montant,
)

log = logging.getLogger("fec.conformite")

OK, INFO, AVERT, ERREUR, NA = "OK", "INFO", "AVERTISSEMENT", "ERREUR", "NON APPLICABLE"
REF = "art. A47 A-1 LPF"
MAX_DETAILS = 1000          # lignes de détail conservées par contrôle (le compteur, lui, est exact)
TOLERANCE = 0.005           # écart débit/crédit toléré, en euros

COLS_DETAIL = ["Ligne", "Champ", "Valeur", "Cause"]
OBLIGATOIRES = ["JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum",
                "CompteLib", "PieceRef", "PieceDate", "EcritureLib", "ValidDate"]


@dataclass
class Controle:
    code: str
    titre: str
    reference: str
    statut: str
    nb: int = 0
    message: str = ""
    details: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLS_DETAIL))
    duree_ms: float = 0.0

    def resume(self) -> dict:
        return {"code": self.code, "titre": self.titre, "reference": self.reference,
                "statut": self.statut, "nb": int(self.nb), "message": self.message}


def _n(x) -> str:
    """Nombre au format français : 1 234,56."""
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def _details(lignes: list[dict] | pd.DataFrame) -> pd.DataFrame:
    df = lignes if isinstance(lignes, pd.DataFrame) else pd.DataFrame(lignes, columns=COLS_DETAIL)
    return df[COLS_DETAIL].head(MAX_DETAILS).reset_index(drop=True)


def _depuis_masque(df, masque, champ, cause) -> pd.DataFrame:
    sel = df.loc[masque, ["Ligne", champ]].head(MAX_DETAILS)
    return pd.DataFrame({"Ligne": sel["Ligne"].values, "Champ": champ,
                         "Valeur": sel[champ].astype(str).values, "Cause": cause},
                        columns=COLS_DETAIL)


def _a(df: pd.DataFrame, col: str) -> pd.Series:
    """Colonne en texte, vide si elle n'existe pas dans le fichier."""
    if col in df.columns:
        return df[col].fillna("").astype(str)
    return pd.Series("", index=df.index, dtype=object)


# ── Structure du fichier ────────────────────────────────────────────────────

def c_nom_fichier(b: FecBrut, _) -> Controle:
    c = Controle("S01", "Nom du fichier", f"{REF}, X", OK)
    if b.siren and b.cloture and pd.notna(pd.to_datetime(b.cloture, format="%Y%m%d", errors="coerce")):
        c.message = f"SIREN {b.siren}, clôture {b.cloture[6:]}/{b.cloture[4:6]}/{b.cloture[:4]}."
        return c
    c.statut, c.nb = AVERT, 1
    c.message = ("Le nom attendu est SIREN + « FEC » + date de clôture AAAAMMJJ "
                 "(exemple : 123456789FEC20241231.txt).")
    c.details = _details([{"Ligne": "", "Champ": "Nom du fichier", "Valeur": b.nom_fichier,
                           "Cause": "Ne respecte pas la nomenclature SIRENFECAAAAMMJJ"}])
    return c


def c_format(b: FecBrut, _) -> Controle:
    c = Controle("S02", "Format, encodage et séparateur", f"{REF}, IV et XII", OK)
    if b.type_fichier == "excel":
        c.statut, c.nb = ERREUR, 1
        c.message = ("Classeur Excel : format non recevable par l'administration. Le FEC doit être "
                     "un fichier à plat (.txt) exporté par le logiciel comptable. Les contrôles de "
                     "contenu ci-dessous restent valables à titre indicatif.")
        return c
    pb = []
    if b.separateur not in SEPARATEURS_CONFORMES:
        nom = SEPARATEURS_TOLERES.get(b.separateur, repr(b.separateur))
        pb.append({"Ligne": 1, "Champ": "Séparateur", "Valeur": nom,
                   "Cause": "Séparateur non admis : tabulation ou barre verticale (|) uniquement"})
    if pb:
        c.statut, c.nb, c.details = ERREUR, len(pb), _details(pb)
        c.message = "Séparateur de champs non conforme."
    else:
        c.message = f"Fichier à plat, encodage {b.encodage}, séparateur {SEPARATEURS_CONFORMES[b.separateur]}."
    if b.bom and c.statut == OK:
        c.statut, c.nb = INFO, 1
        c.message += " Marque d'ordre d'octets (BOM) en tête de fichier : tolérée, mais certains outils la refusent."
    return c


def c_entete(b: FecBrut, _) -> Controle:
    c = Controle("S03", "En-tête : 18 champs, noms et ordre", f"{REF}, VII et VIII", OK)
    attendu = CHAMPS_FEC_MONTANT_SENS if b.variante_montant_sens else CHAMPS_FEC
    lus = [e.strip() for e in b.entete]
    pb = []
    for i, nom in enumerate(attendu):
        lu = lus[i] if i < len(lus) else ""
        if lu == nom:
            continue
        if lu.lower() == nom.lower():
            continue                                  # casse différente : sans conséquence
        cause = (f"Champ n° {i + 1} attendu : {nom}" +
                 (" (présent ailleurs dans l'en-tête : ordre non respecté)"
                  if nom.lower() in [x.lower() for x in lus] else " (absent du fichier)"))
        pb.append({"Ligne": 1, "Champ": f"Position {i + 1}", "Valeur": lu or "(vide)", "Cause": cause})
    if pb:
        c.statut, c.nb, c.details = ERREUR, len(pb), _details(pb)
        c.message = f"{len(pb)} champ(s) de l'en-tête ne correspondent pas à la norme."
    else:
        extra = len(lus) - len(attendu)
        c.message = "Les 18 champs obligatoires sont présents et dans l'ordre"
        c.message += " (variante Montant/Sens)." if b.variante_montant_sens else "."
        if extra > 0:
            c.message += f" {extra} champ(s) supplémentaire(s) après le 18e : autorisé."
    return c


def c_nb_champs(b: FecBrut, _) -> Controle:
    c = Controle("S04", "Nombre de champs par ligne", f"{REF}, IV", OK)
    if b.type_fichier == "excel":
        c.statut, c.message = NA, "Sans objet pour un classeur Excel."
        return c
    if not b.lignes_mal_formees:
        c.message = f"Les {b.nb_lignes} lignes ont le même nombre de champs que l'en-tête ({len(b.entete)})."
        return c
    c.statut, c.nb = ERREUR, len(b.lignes_mal_formees)
    c.message = f"{c.nb} ligne(s) n'ont pas {len(b.entete)} champs."
    c.details = _details([
        {"Ligne": n, "Champ": "Ligne entière", "Valeur": f"{nb} champ(s)",
         "Cause": "Ligne vide" if nb == 0 else
                  f"{len(b.entete)} champs attendus : séparateur présent dans un libellé ou saut de ligne parasite"}
        for n, nb in b.lignes_mal_formees])
    return c


# ── Contenu ─────────────────────────────────────────────────────────────────

def c_obligatoires(b: FecBrut, _) -> Controle:
    c = Controle("C01", "Champs obligatoires renseignés", f"{REF}, VII", OK)
    df, morceaux, total = b.lignes, [], 0
    for champ in OBLIGATOIRES:
        vide = _a(df, champ).str.strip() == ""
        if champ not in df.columns:
            vide[:] = True
        n = int(vide.sum())
        if n:
            total += n
            tmp = df.assign(**{champ: _a(df, champ)})
            morceaux.append(_depuis_masque(tmp, vide, champ, f"{champ} est obligatoire et vide"))
    if total:
        c.statut, c.nb = ERREUR, total
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = f"{total} valeur(s) obligatoire(s) manquante(s)."
    else:
        c.message = "Tous les champs obligatoires sont renseignés sur toutes les lignes."
    return c


_DATE_FEC = re.compile(r"^\d{8}$")


def c_dates(b: FecBrut, _) -> Controle:
    c = Controle("C02", "Dates au format AAAAMMJJ", f"{REF}, IX", OK)
    df, morceaux, total = b.lignes, [], 0
    for champ in CHAMPS_DATE:
        if champ not in df.columns:
            continue
        s = _a(df, champ).str.strip()
        rempli = s != ""
        bon_format = s.str.match(_DATE_FEC)
        valide = pd.to_datetime(s.where(bon_format), format="%Y%m%d", errors="coerce").notna()
        mauvais_format = rempli & ~bon_format
        inexistante = rempli & bon_format & ~valide
        if b.type_fichier == "excel":
            mauvais_format &= date_fec(s).isna()      # Excel : seule une date illisible est signalée
        for masque, cause in ((mauvais_format, "Format attendu AAAAMMJJ (ex. 20241231)"),
                              (inexistante, "Date inexistante au calendrier")):
            n = int(masque.sum())
            if n:
                total += n
                morceaux.append(_depuis_masque(df, masque, champ, cause))
    if total:
        c.statut, c.nb = ERREUR, total
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = f"{total} date(s) invalide(s)."
    else:
        c.message = "Toutes les dates renseignées sont valides."
    return c


_MONTANT_FEC = re.compile(r"^-?\d+(,\d+)?$")
_MONTANT_POINT = re.compile(r"^-?\d+\.\d+$")


def c_montants(b: FecBrut, _) -> Controle:
    c = Controle("C03", "Montants numériques (virgule décimale)", f"{REF}, IX", OK)
    df = b.lignes
    champs = ["Montant"] if b.variante_montant_sens else ["Debit", "Credit"]
    morceaux, erreurs, avert = [], 0, 0
    for champ in champs + (["Montantdevise"] if "Montantdevise" in df.columns else []):
        s = _a(df, champ).str.strip()
        rempli = s != ""
        ok = s.str.match(_MONTANT_FEC)
        point = s.str.match(_MONTANT_POINT)
        invalide = rempli & ~ok & ~point
        if champ != "Montantdevise":
            vide = ~rempli
            n = int(vide.sum())
            if n:
                erreurs += n
                morceaux.append(_depuis_masque(df, vide, champ, "Montant vide : écrire 0,00"))
        n = int(invalide.sum())
        if n:
            erreurs += n
            morceaux.append(_depuis_masque(df, invalide, champ,
                                           "Valeur non numérique (ni espace, ni symbole, ni séparateur de milliers)"))
        n = int((rempli & point).sum())
        if n and b.type_fichier != "excel":
            avert += n
            morceaux.append(_depuis_masque(df, rempli & point, champ,
                                           "Point décimal : la virgule est le séparateur attendu"))
    if b.variante_montant_sens:
        sens = _a(df, "Sens").str.upper().str.strip()
        mauvais = ~sens.isin(["D", "C", "+1", "-1"])
        n = int(mauvais.sum())
        if n:
            erreurs += n
            morceaux.append(_depuis_masque(df, mauvais, "Sens", "Sens attendu : D ou C (ou +1 / -1)"))
    else:
        d, cr = montant(_a(df, "Debit")).fillna(0), montant(_a(df, "Credit")).fillna(0)
        les_deux = (d != 0) & (cr != 0)
        n = int(les_deux.sum())
        if n:
            avert += n
            tmp = df.assign(Debit=_a(df, "Debit") + " / " + _a(df, "Credit"))
            morceaux.append(_depuis_masque(tmp, les_deux, "Debit",
                                           "Débit et crédit renseignés sur la même ligne"))
    c.nb = erreurs + avert
    if c.nb:
        c.statut = ERREUR if erreurs else AVERT
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = f"{erreurs} montant(s) invalide(s), {avert} à vérifier."
    else:
        c.message = "Tous les montants sont numériques."
    return c


def c_equilibre(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C04", "Équilibre débit = crédit de chaque écriture", "art. 921-1 PCG ; " + REF, OK)
    g = df.groupby("EcrId", sort=False).agg(
        Ligne=("Ligne", "min"), J=("JournalCode", "first"), N=("EcritureNum", "first"),
        Debit=("Debit", "sum"), Credit=("Credit", "sum"))
    g["Ecart"] = (g["Debit"] - g["Credit"]).round(2)
    ko = g[g["Ecart"].abs() > TOLERANCE].sort_values("Ligne")
    total_d, total_c = round(df["Debit"].sum(), 2), round(df["Credit"].sum(), 2)
    if len(ko):
        c.statut, c.nb = ERREUR, len(ko)
        c.message = (f"{len(ko)} écriture(s) déséquilibrée(s). Total débit {_n(total_d)} / "
                     f"total crédit {_n(total_c)}.")
        c.details = _details([
            {"Ligne": int(r.Ligne), "Champ": "EcritureNum", "Valeur": f"{r.J} / {r.N}",
             "Cause": f"Débit {_n(r.Debit)} - crédit {_n(r.Credit)} = écart {_n(r.Ecart)}"}
            for r in ko.head(MAX_DETAILS).itertuples()])
    else:
        c.message = f"{len(g)} écriture(s) équilibrée(s). Total débit = total crédit = {_n(total_d)}."
    return c


def c_date_unique_par_ecriture(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C05", "Une seule date par écriture", REF, OK)
    g = df.dropna(subset=["EcritureDate"]).groupby("EcrId", sort=False).agg(
        Ligne=("Ligne", "min"), J=("JournalCode", "first"), N=("EcritureNum", "first"),
        mini=("EcritureDate", "min"), maxi=("EcritureDate", "max"))
    ko = g[g["mini"] != g["maxi"]].sort_values("Ligne")
    if len(ko):
        c.statut, c.nb = AVERT, len(ko)
        c.message = (f"{len(ko)} numéro(s) d'écriture portent plusieurs dates : numéro réutilisé "
                     "ou écriture à cheval sur plusieurs jours.")
        c.details = _details([
            {"Ligne": int(r.Ligne), "Champ": "EcritureNum", "Valeur": f"{r.J} / {r.N}",
             "Cause": f"Dates du {r.mini:%d/%m/%Y} au {r.maxi:%d/%m/%Y}"}
            for r in ko.head(MAX_DETAILS).itertuples()])
    else:
        c.message = "Chaque écriture porte une date unique."
    return c


def c_exercice(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C06", "Dates d'écriture dans l'exercice", REF, OK)
    dates = df["EcritureDate"].dropna()
    if dates.empty:
        c.statut, c.message = NA, "Aucune date d'écriture exploitable."
        return c
    debut, fin = dates.min(), dates.max()
    pb = []
    if b.cloture:
        clot = pd.to_datetime(b.cloture, format="%Y%m%d", errors="coerce")
        if pd.notna(clot):
            apres = df["EcritureDate"] > clot
            for _, r in df.loc[apres, ["Ligne", "EcritureDate"]].head(MAX_DETAILS).iterrows():
                pb.append({"Ligne": int(r.Ligne), "Champ": "EcritureDate", "Valeur": f"{r.EcritureDate:%Y%m%d}",
                           "Cause": f"Postérieure à la clôture du {clot:%d/%m/%Y} indiquée dans le nom du fichier"})
            c.nb = int(apres.sum())
    duree = (fin - debut).days + 1
    c.message = f"Écritures du {debut:%d/%m/%Y} au {fin:%d/%m/%Y} ({duree} jours)."
    if c.nb:
        c.statut, c.details = ERREUR, _details(pb)
        c.message += f" {c.nb} ligne(s) datée(s) après la clôture."
    elif duree > 731:
        c.statut, c.nb = AVERT, 1
        c.message += " Plus de 24 mois : le fichier couvre probablement plusieurs exercices (un FEC par exercice)."
    elif duree > 366:
        c.statut = INFO
        c.message += " Plus de 12 mois : normal seulement pour un exercice de durée exceptionnelle."
    return c


def c_validation(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C07", "Date de validation cohérente", f"{REF}, VII-16", OK)
    ko = df["ValidDate"].notna() & df["EcritureDate"].notna() & (df["ValidDate"] < df["EcritureDate"])
    n = int(ko.sum())
    if n:
        c.statut, c.nb = AVERT, n
        c.message = f"{n} ligne(s) validée(s) avant leur date d'écriture."
        sel = df.loc[ko, ["Ligne", "ValidDate", "EcritureDate"]].head(MAX_DETAILS)
        c.details = _details([
            {"Ligne": int(r.Ligne), "Champ": "ValidDate", "Valeur": f"{r.ValidDate:%Y%m%d}",
             "Cause": f"Antérieure à la date d'écriture ({r.EcritureDate:%Y%m%d})"} for r in sel.itertuples()])
    else:
        c.message = "Aucune validation antérieure à la date d'écriture."
    return c


def c_numerotation(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C08", "Numérotation continue des écritures", f"{REF}, VII-3", OK)
    ecr = df.groupby("EcrId", sort=False).agg(
        Ligne=("Ligne", "min"), JournalCode=("JournalCode", "first"), EcritureNum=("EcritureNum", "first")).reset_index(drop=True)
    ecr = ecr[ecr["EcritureNum"] != ""]
    num = ecr["EcritureNum"].str.extract(r"(\d+)\s*$")[0]
    if num.isna().mean() > 0.05 or ecr.empty:
        c.statut = INFO
        c.message = "Numéros d'écriture non numériques : continuité non vérifiable automatiquement."
        return c
    ecr = ecr.assign(n=pd.to_numeric(num, errors="coerce")).dropna(subset=["n"])
    ecr["n"] = ecr["n"].astype("int64")
    # La séquence est-elle globale au fichier ou propre à chaque journal ?
    par_journal = ecr["EcritureNum"].duplicated().any()
    groupes = ecr.groupby("JournalCode", sort=True) if par_journal else [("(tous journaux)", ecr)]
    pb, manquants = [], 0
    for journal, g in groupes:
        g = g.sort_values("n")
        ns, lignes = g["n"].tolist(), g["Ligne"].tolist()
        for i in range(len(ns) - 1):
            trou = ns[i + 1] - ns[i] - 1
            if trou > 0:
                manquants += trou
                pb.append({"Ligne": int(lignes[i + 1]), "Champ": "EcritureNum", "Valeur": f"{journal} : {ns[i]} → {ns[i + 1]}",
                           "Cause": f"{trou} numéro(s) manquant(s) entre ces deux écritures"})
    portee = "par journal" if par_journal else "sur l'ensemble du fichier"
    if pb:
        c.statut, c.nb = AVERT, manquants
        c.message = (f"{manquants} numéro(s) manquant(s) dans la séquence ({portee}). À justifier : "
                     "écritures supprimées, brouillard non validé ou numérotation propre au logiciel.")
        c.details = _details(sorted(pb, key=lambda d: d["Ligne"]))
    else:
        c.message = f"Séquence continue ({portee}), {len(ecr)} écritures."
    return c


def c_comptes(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C09", "Numéros et libellés de comptes", "PCG ; " + REF, OK)
    num = df["CompteNum"]
    rempli = num != ""
    mauvais = rempli & ~num.str.match(r"^[1-9][0-9A-Za-z]{2,}$")
    morceaux, n_err = [], int(mauvais.sum())
    if n_err:
        morceaux.append(_depuis_masque(df, mauvais, "CompteNum",
                                       "Numéro de compte attendu : au moins 3 caractères, commençant par un chiffre de 1 à 9"))
    libs = df[rempli & (df["CompteLib"] != "")].groupby("CompteNum").agg(
        Ligne=("Ligne", "min"), n=("CompteLib", "nunique"), ex=("CompteLib", lambda s: " / ".join(sorted(set(s))[:3])))
    multi = libs[libs["n"] > 1].sort_values("Ligne")
    if len(multi):
        morceaux.append(pd.DataFrame({
            "Ligne": multi["Ligne"].astype(int).values, "Champ": "CompteLib",
            "Valeur": [f"{k} : {v}" for k, v in multi["ex"].items()],
            "Cause": "Plusieurs libellés pour le même numéro de compte"}, columns=COLS_DETAIL))
    c.nb = n_err + len(multi)
    if c.nb:
        c.statut = ERREUR if n_err else AVERT
        c.details = _details(pd.concat(morceaux, ignore_index=True))
        c.message = f"{n_err} numéro(s) de compte invalide(s), {len(multi)} compte(s) à libellés multiples."
    else:
        c.message = f"{num[rempli].nunique()} comptes utilisés, numéros et libellés cohérents."
    return c


def c_auxiliaires(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C10", "Comptes auxiliaires", f"{REF}, VII-7 et 8", OK)
    num, lib = df["CompAuxNum"] != "", df["CompAuxLib"] != ""
    ko1, ko2 = num & ~lib, lib & ~num
    morceaux = []
    if ko1.any():
        morceaux.append(_depuis_masque(df, ko1, "CompAuxNum", "Numéro auxiliaire sans libellé"))
    if ko2.any():
        morceaux.append(_depuis_masque(df, ko2, "CompAuxLib", "Libellé auxiliaire sans numéro"))
    c.nb = int(ko1.sum() + ko2.sum())
    if c.nb:
        c.statut = AVERT
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = f"{c.nb} ligne(s) avec un compte auxiliaire incomplet."
    elif not num.any():
        c.statut, c.message = INFO, "Aucun compte auxiliaire dans le fichier."
    else:
        c.message = f"{df.loc[num, 'CompAuxNum'].nunique()} comptes auxiliaires, numéro et libellé toujours présents."
    return c


def c_lettrage(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C11", "Lettrage", f"{REF}, VII-14 et 15", OK)
    let, dat = df["EcritureLet"] != "", df["DateLet"].notna()
    if not let.any() and not dat.any():
        c.statut, c.message = INFO, "Aucun lettrage dans le fichier."
        return c
    morceaux = []
    sans_date, sans_code = let & ~dat, dat & ~let
    if sans_date.any():
        morceaux.append(_depuis_masque(df, sans_date, "EcritureLet", "Code de lettrage sans date de lettrage"))
    if sans_code.any():
        tmp = df.assign(DateLet=df["DateLet"].dt.strftime("%Y%m%d"))
        morceaux.append(_depuis_masque(tmp, sans_code, "DateLet", "Date de lettrage sans code de lettrage"))
    g = df[let].groupby(["CompteNum", "CompAuxNum", "EcritureLet"]).agg(
        Ligne=("Ligne", "min"), solde=("Debit", "sum"), cr=("Credit", "sum"))
    g["solde"] = (g["solde"] - g["cr"]).round(2)
    desq = g[g["solde"].abs() > TOLERANCE].sort_values("Ligne")
    if len(desq):
        morceaux.append(pd.DataFrame({
            "Ligne": desq["Ligne"].astype(int).values, "Champ": "EcritureLet",
            "Valeur": [f"{k[0]} {k[1]} [{k[2]}]".replace("  ", " ") for k in desq.index],
            "Cause": [f"Lettrage non soldé : reste {_n(s)}" for s in desq["solde"]]}, columns=COLS_DETAIL))
    c.nb = int(sans_date.sum() + sans_code.sum()) + len(desq)
    if c.nb:
        c.statut = AVERT
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = (f"{int(sans_date.sum() + sans_code.sum())} ligne(s) au lettrage incomplet, "
                     f"{len(desq)} lettrage(s) non soldé(s) (lettrage partiel possible).")
    else:
        c.message = f"{len(g)} lettrage(s), tous soldés et datés."
    return c


def c_devises(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C12", "Montant et code devise", f"{REF}, VII-17 et 18", OK)
    m = _a(b.lignes, "Montantdevise").str.strip()
    d = _a(b.lignes, "Idevise").str.strip()
    a_montant = (m != "") & (montant(m).fillna(1) != 0)
    a_devise = d != ""
    if not a_montant.any() and not a_devise.any():
        c.statut, c.message = INFO, "Aucune opération en devise."
        return c
    ko = a_montant & ~a_devise
    mauvais_code = a_devise & ~d.str.match(r"^[A-Za-z]{3}$")
    morceaux = []
    if ko.any():
        morceaux.append(_depuis_masque(b.lignes.assign(Montantdevise=m), ko, "Montantdevise", "Montant en devise sans code devise"))
    if mauvais_code.any():
        morceaux.append(_depuis_masque(b.lignes.assign(Idevise=d), mauvais_code, "Idevise", "Code devise attendu sur 3 lettres (ISO 4217, ex. USD)"))
    c.nb = int(ko.sum() + mauvais_code.sum())
    if c.nb:
        c.statut = AVERT
        c.details = _details(pd.concat(morceaux, ignore_index=True).sort_values("Ligne", kind="stable"))
        c.message = f"{c.nb} ligne(s) en devise incomplète(s)."
    else:
        c.message = f"{int(a_devise.sum())} ligne(s) en devise, montant et code cohérents."
    return c


def c_a_nouveaux(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C13", "Écritures d'à-nouveaux", f"{REF}, III", OK)
    an = masque_a_nouveaux(df)
    if not an.any():
        c.statut = INFO
        c.message = ("Aucun journal d'à-nouveaux détecté. Normal pour un premier exercice ; sinon la "
                     "reprise des soldes de l'exercice précédent doit figurer en tête de fichier.")
        return c
    solde = round(df.loc[an, "Debit"].sum() - df.loc[an, "Credit"].sum(), 2)
    journaux = ", ".join(sorted(df.loc[an, "JournalCode"].unique()))
    c.message = f"{int(an.sum())} ligne(s) d'à-nouveaux (journal {journaux})."
    if abs(solde) > TOLERANCE:
        c.statut, c.nb = ERREUR, 1
        c.message += f" Les à-nouveaux ne sont pas équilibrés : écart {_n(solde)}."
    return c


def c_doublons(b: FecBrut, df: pd.DataFrame) -> Controle:
    c = Controle("C14", "Lignes strictement identiques", "Contrôle de cohérence", OK)
    cols = [x for x in b.lignes.columns if x != "Ligne"]
    dup = b.lignes.duplicated(subset=cols, keep="first")
    n = int(dup.sum())
    if n:
        c.statut, c.nb = AVERT, n
        c.message = f"{n} ligne(s) répètent à l'identique une ligne précédente (double import possible)."
        c.details = _depuis_masque(b.lignes.assign(EcritureNum=_a(b.lignes, "JournalCode") + " / " + _a(b.lignes, "EcritureNum")),
                                   dup, "EcritureNum", "Ligne identique en tous points à une ligne précédente")
    else:
        c.message = "Aucune ligne en double."
    return c


CONTROLES = [c_nom_fichier, c_format, c_entete, c_nb_champs, c_obligatoires, c_dates, c_montants,
             c_equilibre, c_date_unique_par_ecriture, c_exercice, c_validation, c_numerotation,
             c_comptes, c_auxiliaires, c_lettrage, c_devises, c_a_nouveaux, c_doublons]


def controler(brut: FecBrut, df: pd.DataFrame) -> dict:
    """Lance tous les contrôles. `df` est le tableau normalisé de `loader.normaliser`."""
    resultats: list[Controle] = []
    for fonction in CONTROLES:
        t0 = time.perf_counter()
        try:
            c = fonction(brut, df)
        except Exception as e:                       # un contrôle en panne ne doit pas masquer les autres
            log.exception("Contrôle %s en échec", fonction.__name__)
            c = Controle(fonction.__name__, fonction.__name__, "", ERREUR, 1,
                         f"Le contrôle n'a pas pu s'exécuter : {type(e).__name__}: {e}")
        c.duree_ms = round((time.perf_counter() - t0) * 1000, 1)
        log.info("%-4s %-14s nb=%-6d %6.1f ms | %s | %s", c.code, c.statut, c.nb, c.duree_ms, c.titre, c.message)
        resultats.append(c)

    nb_err = sum(1 for c in resultats if c.statut == ERREUR)
    nb_av = sum(1 for c in resultats if c.statut == AVERT)
    verdict = "NON CONFORME" if nb_err else ("CONFORME AVEC RÉSERVES" if nb_av else "CONFORME")
    log.info("Verdict : %s (%d contrôle(s) en erreur, %d en avertissement)", verdict, nb_err, nb_av)
    return {"verdict": verdict, "nb_erreurs": nb_err, "nb_avertissements": nb_av, "controles": resultats}


def tableau_synthese(conf: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Code": c.code, "Contrôle": c.titre, "Statut": c.statut, "Nb": c.nb,
        "Constat": c.message, "Référence": c.reference} for c in conf["controles"]])


def tableau_details(conf: dict) -> pd.DataFrame:
    morceaux = []
    for c in conf["controles"]:
        if len(c.details):
            d = c.details.copy()
            d.insert(0, "Contrôle", c.titre)
            d.insert(0, "Code", c.code)
            d.insert(2, "Statut", c.statut)
            morceaux.append(d)
    if not morceaux:
        return pd.DataFrame(columns=["Code", "Contrôle", "Statut"] + COLS_DETAIL)
    return pd.concat(morceaux, ignore_index=True)
