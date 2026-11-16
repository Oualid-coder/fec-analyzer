"""Chiffre d'affaires : par client, par mois, par jour, week-ends.

Règles (valables pour tout dossier, plus rien n'est propre à un client) :
- CA HT = comptes 70x, crédit - débit (les avoirs et le 709 viennent en moins),
  hors journaux d'à-nouveaux.
- Facturation par client = débits - crédits des comptes clients 411 dans les
  journaux qui mouvementent des comptes 70x. C'est un montant TTC.
"""
import pandas as pd

from modules.loader import masque_a_nouveaux

JOURS_FR = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']


def lignes_ca(df: pd.DataFrame) -> pd.DataFrame:
    ca = df[df["CompteNum"].str.startswith("70") & ~masque_a_nouveaux(df)].copy()
    ca["CA"] = ca["Credit"] - ca["Debit"]
    return ca


def journaux_de_vente(df: pd.DataFrame) -> list[str]:
    return sorted(lignes_ca(df)["JournalCode"].unique())


def ca_par_client(df: pd.DataFrame) -> pd.DataFrame:
    ventes = df[df["JournalCode"].isin(journaux_de_vente(df)) & df["CompteNum"].str.startswith("411")].copy()
    ventes["Client"] = ventes["CompAuxLib"].where(ventes["CompAuxLib"] != "", ventes["CompteLib"])
    ventes["Client"] = ventes["Client"].where(ventes["Client"] != "", ventes["CompteNum"])
    ventes["TTC"] = ventes["Debit"] - ventes["Credit"]
    ca = ventes.groupby("Client")["TTC"].sum().round(2).reset_index()
    ca = ca.sort_values(["TTC", "Client"], ascending=[False, True], kind="stable").reset_index(drop=True)
    ca.columns = ["Client", "Facturé_TTC"]
    total = round(ca["Facturé_TTC"].sum(), 2)
    ca["Part_%"] = (ca["Facturé_TTC"] / total * 100).round(2) if total else 0.0
    ca["Cumul_%"] = ca["Part_%"].cumsum().round(2)
    total_row = pd.DataFrame([{"Client": "TOTAL", "Facturé_TTC": total,
                               "Part_%": 100.0 if total else 0.0, "Cumul_%": 100.0 if total else 0.0}])
    return pd.concat([ca, total_row], ignore_index=True)


def risque_dependance(ca_df: pd.DataFrame) -> dict:
    d = ca_df[ca_df["Client"] != "TOTAL"]
    total = d["Facturé_TTC"].sum()
    if d.empty or total <= 0:
        return {"total_ca": 0.0, "nb_clients": 0, "top1_client": "—", "top1_part": 0.0,
                "top3_part": 0.0, "top5_part": 0.0, "niveau_risque": "NON CALCULÉ"}
    top1 = d.iloc[0]
    niveau = "FAIBLE"
    if top1["Part_%"] > 50: niveau = "CRITIQUE"
    elif top1["Part_%"] > 30: niveau = "ÉLEVÉ"
    elif top1["Part_%"] > 20: niveau = "MODÉRÉ"
    return {
        "total_ca": round(total, 2), "nb_clients": len(d),
        "top1_client": top1["Client"], "top1_part": float(top1["Part_%"]),
        "top3_part": round(d.head(3)["Facturé_TTC"].sum() / total * 100, 2),
        "top5_part": round(d.head(5)["Facturé_TTC"].sum() / total * 100, 2),
        "niveau_risque": niveau,
    }


def ca_mensuel(df: pd.DataFrame) -> pd.DataFrame:
    ca = lignes_ca(df).dropna(subset=["EcritureDate"])
    mensuel = ca.groupby("Mois")["CA"].sum().round(2).reset_index()
    mensuel.columns = ["Mois", "CA_HT"]
    mensuel["Mois"] = mensuel["Mois"].astype(str)
    total_row = pd.DataFrame([{"Mois": "TOTAL", "CA_HT": round(mensuel["CA_HT"].sum(), 2)}])
    return pd.concat([mensuel, total_row], ignore_index=True)


def _par_jour(df: pd.DataFrame) -> pd.DataFrame:
    ca = lignes_ca(df).dropna(subset=["EcritureDate"])
    j = ca.groupby("EcritureDate")["CA"].sum().round(2).reset_index().sort_values("EcritureDate")
    j["DowNum"] = j["EcritureDate"].dt.dayofweek
    j["Jour"] = j["DowNum"].map(lambda x: JOURS_FR[x])
    return j


def ca_journalier(df: pd.DataFrame) -> pd.DataFrame:
    j = _par_jour(df)
    out = pd.DataFrame({
        "Date": j["EcritureDate"].dt.strftime("%d/%m/%Y"), "Jour": j["Jour"],
        "Weekend": j["DowNum"].map(lambda x: "Oui" if x >= 5 else ""), "CA_HT": j["CA"]})
    total_row = pd.DataFrame([{"Date": "TOTAL", "Jour": "", "Weekend": "", "CA_HT": round(j["CA"].sum(), 2)}])
    return pd.concat([out, total_row], ignore_index=True)


def ca_weekends(df: pd.DataFrame) -> pd.DataFrame:
    j = _par_jour(df)
    w = j[j["DowNum"] >= 5].copy()
    w["Mois"] = w["EcritureDate"].dt.to_period("M").astype(str)
    lignes = []
    for mois, g in w.groupby("Mois", sort=True):
        for r in g.itertuples():
            lignes.append({"Date": f"{r.EcritureDate:%d/%m/%Y}", "Jour": r.Jour, "Mois": mois, "CA_HT": r.CA})
        lignes.append({"Date": f"Sous-total {mois}", "Jour": "", "Mois": mois, "CA_HT": round(g["CA"].sum(), 2)})
    lignes.append({"Date": "TOTAL WEEKENDS", "Jour": "", "Mois": "", "CA_HT": round(w["CA"].sum(), 2)})
    return pd.DataFrame(lignes, columns=["Date", "Jour", "Mois", "CA_HT"])
