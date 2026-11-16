"""Tableaux de variation des immobilisations (comptes 20 à 27) et des amortissements (compte 28)."""
import pandas as pd

from modules.loader import masque_a_nouveaux


def _variation(df: pd.DataFrame, masque_comptes: pd.Series, sens_debit: bool,
               nom_plus: str, nom_moins: str) -> dict:
    """Solde initial (à-nouveaux) + augmentations - diminutions = solde final, par compte."""
    sel = df[masque_comptes].copy()
    an = masque_a_nouveaux(sel)
    plus, moins = ("Debit", "Credit") if sens_debit else ("Credit", "Debit")
    sel["_init"] = (sel[plus] - sel[moins]).where(an, 0.0)
    sel["_plus"] = sel[plus].where(~an, 0.0)
    sel["_moins"] = sel[moins].where(~an, 0.0)
    detail = sel.groupby("CompteNum", sort=True).agg(
        Libellé=("CompteLib", "first"), **{"Solde Initial": ("_init", "sum"),
                                           nom_plus: ("_plus", "sum"), nom_moins: ("_moins", "sum")}).reset_index()
    detail["Solde Final"] = detail["Solde Initial"] + detail[nom_plus] - detail[nom_moins]
    cols = ["Solde Initial", nom_plus, nom_moins, "Solde Final"]
    detail[cols] = detail[cols].round(2)
    detail = detail[detail[cols].abs().sum(axis=1) > 0].rename(columns={"CompteNum": "Compte"})
    totaux = {c: round(float(detail[c].sum()), 2) for c in cols}
    detail = pd.concat([detail, pd.DataFrame([{"Compte": "TOTAL", "Libellé": "", **totaux}])], ignore_index=True)
    return {"solde_initial": totaux["Solde Initial"], "plus": totaux[nom_plus],
            "moins": totaux[nom_moins], "solde_final": totaux["Solde Final"], "detail": detail}


def variation_immobilisations(df: pd.DataFrame) -> dict:
    c = df["CompteNum"]
    r = _variation(df, c.str.match(r"^2[0-7]"), True, "Acquisitions", "Sorties")
    return {"solde_initial": r["solde_initial"], "acquisitions": r["plus"],
            "sorties": r["moins"], "solde_final": r["solde_final"], "detail": r["detail"]}


def variation_amortissements(df: pd.DataFrame) -> dict:
    r = _variation(df, df["CompteNum"].str.startswith("28"), False, "Dotations", "Reprises")
    return {"solde_initial": r["solde_initial"], "dotations": r["plus"],
            "reprises": r["moins"], "solde_final": r["solde_final"], "detail": r["detail"]}
