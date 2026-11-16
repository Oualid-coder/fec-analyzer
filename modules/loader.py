"""Lecture d'un FEC.

Deux étapes volontairement séparées :

1. `lire_fec`   -> lit le fichier tel quel (tout en texte, rien n'est corrigé)
                   et note ce qui a été détecté : encodage, séparateur, en-tête.
                   C'est sur ces données brutes que tournent les contrôles de
                   conformité (article A47 A-1 du LPF).
2. `normaliser` -> produit un tableau typé (dates, montants) pour les analyses.

Formats acceptés : fichier à plat .txt/.csv (tabulation ou barre verticale,
UTF-8 ou ISO 8859-15) et, par tolérance, export Excel .xlsx/.xls.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

CHAMPS_FEC = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum",
    "CompteLib", "CompAuxNum", "CompAuxLib", "PieceRef", "PieceDate",
    "EcritureLib", "Debit", "Credit", "EcritureLet", "DateLet", "ValidDate",
    "Montantdevise", "Idevise",
]
# Variante autorisée par l'article A47 A-1 : Montant + Sens à la place de Debit/Credit.
CHAMPS_FEC_MONTANT_SENS = [
    "Montant" if c == "Debit" else "Sens" if c == "Credit" else c for c in CHAMPS_FEC
]
CHAMPS_DATE = ["EcritureDate", "PieceDate", "DateLet", "ValidDate"]
SEPARATEURS_CONFORMES = {"\t": "tabulation", "|": "barre verticale (|)"}
SEPARATEURS_TOLERES = {";": "point-virgule", ",": "virgule"}

_NOM_FEC = re.compile(r"^(\d{9})FEC(\d{8})", re.IGNORECASE)
_CANON = {c.lower(): c for c in CHAMPS_FEC + ["Montant", "Sens"]}


class FecIllisible(Exception):
    """Le fichier ne peut pas être lu comme un FEC (message destiné à l'utilisateur)."""


@dataclass
class FecBrut:
    chemin: Path
    nom_fichier: str
    type_fichier: str                 # "plat" ou "excel"
    encodage: str | None              # None pour Excel
    bom: bool
    separateur: str | None            # None pour Excel
    entete: list[str]                 # en-tête tel que lu dans le fichier
    lignes: pd.DataFrame              # tout en texte, colonnes renommées en noms canoniques
    lignes_mal_formees: list[tuple[int, int]] = field(default_factory=list)  # (n° ligne, nb champs)
    siren: str | None = None
    cloture: str | None = None        # AAAAMMJJ, tiré du nom de fichier
    sha256: str = ""
    variante_montant_sens: bool = False

    @property
    def nb_lignes(self) -> int:
        return len(self.lignes)


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _decoder(octets: bytes) -> tuple[str, str, bool]:
    """Retourne (texte, encodage, présence d'un BOM)."""
    if octets.startswith(b"\xef\xbb\xbf"):
        return octets[3:].decode("utf-8", errors="replace"), "UTF-8", True
    try:
        texte = octets.decode("utf-8")
        return texte, ("ASCII" if octets.isascii() else "UTF-8"), False
    except UnicodeDecodeError:
        # ISO 8859-15 décode n'importe quel octet : c'est le repli prévu par le texte.
        return octets.decode("iso-8859-15"), "ISO 8859-15", False


def _detecter_separateur(premiere_ligne: str) -> str:
    comptes = {s: premiere_ligne.count(s) for s in ("\t", "|", ";", ",")}
    sep, nb = max(comptes.items(), key=lambda kv: kv[1])
    if nb == 0:
        raise FecIllisible(
            "Aucun séparateur de champs reconnu sur la première ligne. "
            "Un FEC utilise une tabulation ou une barre verticale (|)."
        )
    return sep


def _renommer_canonique(entete: list[str]) -> list[str]:
    noms, vus = [], set()
    for brut in entete:
        nom = _CANON.get(brut.strip().lower(), brut.strip())
        while nom in vus:            # colonne en double : on la garde sans écraser la première
            nom += "_bis"
        vus.add(nom)
        noms.append(nom)
    return noms


def _lire_plat(chemin: Path) -> FecBrut:
    octets = chemin.read_bytes()
    if not octets.strip():
        raise FecIllisible("Le fichier est vide.")
    texte, encodage, bom = _decoder(octets)
    lignes = [l for l in texte.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lignes and lignes[-1] == "":
        lignes.pop()
    sep = _detecter_separateur(lignes[0])
    entete = lignes[0].split(sep)
    nb_champs = len(entete)

    enregistrements, mal_formees = [], []
    for i, ligne in enumerate(lignes[1:], start=2):      # n° de ligne tel qu'affiché dans un éditeur
        if ligne.strip() == "":
            mal_formees.append((i, 0))
            continue
        champs = ligne.split(sep)
        if len(champs) != nb_champs:
            mal_formees.append((i, len(champs)))
            champs = (champs + [""] * nb_champs)[:nb_champs]
        enregistrements.append([i] + champs)

    noms = _renommer_canonique(entete)
    df = pd.DataFrame(enregistrements, columns=["Ligne"] + noms, dtype=object)
    for c in noms:
        df[c] = df[c].astype(str).str.strip()
    df["Ligne"] = df["Ligne"].astype("int64")
    return FecBrut(chemin=chemin, nom_fichier=chemin.name, type_fichier="plat",
                   encodage=encodage, bom=bom, separateur=sep, entete=entete,
                   lignes=df, lignes_mal_formees=mal_formees)


def _texte_cellule(v) -> str:
    """Convertit une cellule Excel en texte au format FEC (dates AAAAMMJJ, décimale virgule)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return ""
    if isinstance(v, pd.Timestamp) or hasattr(v, "strftime"):
        return v.strftime("%Y%m%d")
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v).replace(".", ",")
    return str(v).strip()


def _lire_excel(chemin: Path) -> FecBrut:
    try:
        df = pd.read_excel(chemin, dtype=object)
    except Exception as e:  # fichier corrompu, mauvais format...
        raise FecIllisible(f"Fichier Excel illisible : {e}") from e
    if df.empty and len(df.columns) == 0:
        raise FecIllisible("Le classeur Excel est vide.")
    entete = [str(c) for c in df.columns]
    noms = _renommer_canonique(entete)
    df.columns = noms
    for c in noms:
        df[c] = df[c].map(_texte_cellule)
    df.insert(0, "Ligne", range(2, len(df) + 2))
    return FecBrut(chemin=chemin, nom_fichier=chemin.name, type_fichier="excel",
                   encodage=None, bom=False, separateur=None, entete=entete, lignes=df)


def lire_fec(chemin: str | Path) -> FecBrut:
    chemin = Path(chemin)
    if not chemin.is_file():
        raise FecIllisible(f"Fichier introuvable : {chemin}")
    ext = chemin.suffix.lower()
    brut = _lire_excel(chemin) if ext in (".xlsx", ".xls", ".xlsm") else _lire_plat(chemin)

    m = _NOM_FEC.match(chemin.name)
    if m:
        brut.siren, brut.cloture = m.group(1), m.group(2)
    brut.sha256 = empreinte(chemin)
    cols = set(brut.lignes.columns)
    brut.variante_montant_sens = {"Montant", "Sens"} <= cols and not {"Debit", "Credit"} <= cols

    indispensables = {"JournalCode", "EcritureNum", "EcritureDate", "CompteNum"}
    manquants = sorted(indispensables - cols)
    if manquants:
        raise FecIllisible(
            "Ce fichier ne ressemble pas à un FEC : colonne(s) introuvable(s) "
            + ", ".join(manquants) + ". En-tête lu : " + " | ".join(brut.entete[:20])
        )
    if not ({"Debit", "Credit"} <= cols or brut.variante_montant_sens):
        raise FecIllisible("Colonnes de montants introuvables : il faut Debit et Credit, ou Montant et Sens.")
    return brut


# ── Conversions tolérantes pour les analyses ────────────────────────────────

def montant(serie: pd.Series) -> pd.Series:
    """Texte -> nombre. Accepte virgule ou point décimal, espaces. Invalide -> NaN."""
    s = serie.astype(str).str.replace(" ", "", regex=False).str.replace(" ", "", regex=False)
    s = s.str.replace(",", ".", regex=False)
    return pd.to_numeric(s.where(s != "", "0"), errors="coerce")


def date_fec(serie: pd.Series) -> pd.Series:
    """Texte -> date. Format FEC AAAAMMJJ, avec repli sur JJ/MM/AAAA et AAAA-MM-JJ."""
    s = serie.astype(str).str.strip()
    d = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        manquantes = d.isna() & (s != "")
        if not manquantes.any():
            break
        d = d.where(~manquantes, pd.to_datetime(s.where(manquantes), format=fmt, errors="coerce"))
    return d


def normaliser(brut: FecBrut) -> pd.DataFrame:
    """Tableau typé pour les analyses. Les 18 champs existent toujours (vides si absents)."""
    df = brut.lignes.copy()
    for c in CHAMPS_FEC:
        if c not in df.columns and c not in ("Debit", "Credit"):
            df[c] = ""
    if brut.variante_montant_sens:
        m = montant(df["Montant"]).fillna(0)
        sens = df["Sens"].astype(str).str.upper().str.strip()
        df["Debit"] = m.where(sens.isin(["D", "+1", "1", "+"]), 0.0)
        df["Credit"] = m.where(sens.isin(["C", "-1", "-"]), 0.0)
    else:
        df["Debit"] = montant(df["Debit"]).fillna(0)
        df["Credit"] = montant(df["Credit"]).fillna(0)
    for c in CHAMPS_DATE:
        df[c] = date_fec(df[c])
    for c in ("JournalCode", "JournalLib", "EcritureNum", "CompteNum", "CompteLib",
              "CompAuxNum", "CompAuxLib", "PieceRef", "EcritureLib", "EcritureLet"):
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["Mois"] = df["EcritureDate"].dt.to_period("M")
    # Identifiant entier de l'écriture (journal + numéro) : regroupements bien plus rapides que sur du texte.
    df["EcrId"] = pd.factorize(df["JournalCode"] + "\x1f" + df["EcritureNum"])[0]
    return df


def load_fec(path: str) -> pd.DataFrame:
    """Compatibilité avec l'ancien code : lit et normalise en une fois."""
    return normaliser(lire_fec(path))


# ── Repères comptables partagés par les modules d'analyse ───────────────────

_CODES_AN = {"AN", "RAN", "ANO", "ANX", "ANV", "AND", "RN", "REPORT", "A-NOUVEAUX", "ANOUVEAUX"}


def masque_a_nouveaux(df: pd.DataFrame) -> pd.Series:
    """Lignes des journaux d'à-nouveaux (reprise des soldes de l'exercice précédent)."""
    code = df["JournalCode"].str.upper().str.strip()
    lib = df["JournalLib"].str.lower()
    return code.isin(_CODES_AN) | lib.str.contains("nouveau", na=False) | lib.str.contains("report a", na=False)


def exercice(df: pd.DataFrame, cloture: str | None = None) -> dict:
    """Bornes de l'exercice déduites des dates d'écriture (et du nom de fichier si disponible)."""
    dates = df["EcritureDate"].dropna()
    debut = dates.min() if len(dates) else pd.NaT
    fin = dates.max() if len(dates) else pd.NaT
    if cloture:
        c = pd.to_datetime(cloture, format="%Y%m%d", errors="coerce")
        if pd.notna(c):
            fin = c
    lib = "Exercice non daté"
    if pd.notna(debut) and pd.notna(fin):
        lib = f"Exercice du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"
    return {"debut": debut, "fin": fin, "libelle": lib}
