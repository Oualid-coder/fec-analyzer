import pandas as pd

JOURS_FR = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']


def ca_par_client(df: pd.DataFrame) -> pd.DataFrame:
    clients = df[
        (df["JournalCode"] == "VE") &
        (df["CompteNum"].str.startswith("411")) &
        (df["CompAuxLib"] != "")
    ]
    ca = (
        clients.groupby("CompAuxLib")["Debit"]
        .sum().sort_values(ascending=False).reset_index()
    )
    ca.columns = ["Client", "CA_HT"]
    ca["CA_HT"] = ca["CA_HT"].round(2)
    total = ca["CA_HT"].sum()
    ca["Part_%"] = (ca["CA_HT"] / total * 100).round(2)
    ca["CA_Cumulé_%"] = ca["Part_%"].cumsum().round(2)
    total_row = pd.DataFrame([{"Client": "TOTAL", "CA_HT": round(total, 2), "Part_%": 100.0, "CA_Cumulé_%": 100.0}])
    return pd.concat([ca, total_row], ignore_index=True)


def risque_dependance(ca_df: pd.DataFrame) -> dict:
    d = ca_df[ca_df["Client"] != "TOTAL"]
    total = d["CA_HT"].sum()
    top1 = d.iloc[0]
    top3 = d.head(3)["CA_HT"].sum()
    top5 = d.head(5)["CA_HT"].sum()
    niveau = "FAIBLE"
    if top1["Part_%"] > 50: niveau = "CRITIQUE"
    elif top1["Part_%"] > 30: niveau = "ÉLEVÉ"
    elif top1["Part_%"] > 20: niveau = "MODÉRÉ"
    return {
        "total_ca": round(total, 2), "nb_clients": len(d),
        "top1_client": top1["Client"], "top1_part": top1["Part_%"],
        "top3_part": round(top3 / total * 100, 2),
        "top5_part": round(top5 / total * 100, 2),
        "niveau_risque": niveau,
    }


def ca_mensuel(df: pd.DataFrame) -> pd.DataFrame:
    ca = df[df["CompteNum"].str.startswith("706")].copy()
    mensuel = ca.groupby("Mois")["Credit"].sum().reset_index()
    mensuel.columns = ["Mois", "CA_HT"]
    mensuel["CA_HT"] = mensuel["CA_HT"].round(2)
    mensuel["Mois"] = mensuel["Mois"].astype(str)
    total_row = pd.DataFrame([{"Mois": "TOTAL", "CA_HT": mensuel["CA_HT"].sum().round(2)}])
    return pd.concat([mensuel, total_row], ignore_index=True)


def ca_journalier(df: pd.DataFrame) -> pd.DataFrame:
    ca = df[df["CompteNum"].str.startswith("706")].copy()
    ca["EcritureDate"] = pd.to_datetime(ca["EcritureDate"])
    ca["DowNum"] = ca["EcritureDate"].dt.dayofweek
    ca["Jour"] = ca["DowNum"].map(lambda x: JOURS_FR[x])
    ca["Weekend"] = ca["DowNum"].apply(lambda x: "✅" if x >= 5 else "")

    journalier = (
        ca.groupby(["EcritureDate", "Jour", "Weekend"])["Credit"]
        .sum().reset_index()
    )
    journalier.columns = ["Date", "Jour", "Weekend", "CA_HT"]
    journalier["CA_HT"] = journalier["CA_HT"].round(2)
    journalier = journalier.sort_values("Date").reset_index(drop=True)

    total_row = pd.DataFrame([{"Date": "TOTAL", "Jour": "", "Weekend": "", "CA_HT": journalier["CA_HT"].sum().round(2)}])
    return pd.concat([journalier, total_row], ignore_index=True)


def ca_weekends(df: pd.DataFrame) -> pd.DataFrame:
    ca = df[df["CompteNum"].str.startswith("706")].copy()
    ca["EcritureDate"] = pd.to_datetime(ca["EcritureDate"])
    ca["DowNum"] = ca["EcritureDate"].dt.dayofweek
    ca["Jour"] = ca["DowNum"].map(lambda x: JOURS_FR[x])
    ca["Mois"] = ca["EcritureDate"].dt.to_period("M").astype(str)

    weekends = ca[ca["DowNum"] >= 5].groupby(["EcritureDate", "Jour", "Mois"])["Credit"].sum().reset_index()
    weekends.columns = ["Date", "Jour", "Mois", "CA_HT"]
    weekends["CA_HT"] = weekends["CA_HT"].round(2)
    weekends = weekends.sort_values("Date").reset_index(drop=True)

    # Sous-total par mois
    sous_totaux = weekends.groupby("Mois")["CA_HT"].sum().reset_index()
    sous_totaux["Date"] = sous_totaux["Mois"].apply(lambda m: f"Sous-total {m}")
    sous_totaux["Jour"] = ""
    sous_totaux = sous_totaux[["Date", "Jour", "Mois", "CA_HT"]]

    result = pd.concat([weekends, sous_totaux]).sort_values(["Mois", "Date"]).reset_index(drop=True)
    total_row = pd.DataFrame([{"Date": "TOTAL WEEKENDS", "Jour": "", "Mois": "", "CA_HT": weekends["CA_HT"].sum().round(2)}])
    return pd.concat([result, total_row], ignore_index=True)
