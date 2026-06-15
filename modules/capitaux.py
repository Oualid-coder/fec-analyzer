import pandas as pd

COMPTES_CP = {
    "101": "Capital",
    "104": "Primes d'émission / fusion",
    "106": "Réserves",
    "110": "Report à nouveau (créditeur)",
    "119": "Report à nouveau (débiteur)",
    "120": "Résultat exercice (bénéfice)",
    "129": "Résultat exercice (perte)",
}

def variation_capitaux_propres(df: pd.DataFrame) -> dict:
    cp = df[df["CompteNum"].str.match(r"^1[01269]")].copy()
    cp["Catégorie"] = cp["CompteNum"].str[:3].map(COMPTES_CP).fillna("Autres capitaux propres")

    ran = cp[cp["JournalCode"] == "RAN"]
    mvt = cp[cp["JournalCode"] != "RAN"]

    debut = ran.groupby("Catégorie").apply(
        lambda x: round(x["Credit"].sum() - x["Debit"].sum(), 2)
    ).reset_index().rename(columns={0: "Solde Initial"})

    augmentations = mvt[mvt["Credit"] > mvt["Debit"]].groupby("Catégorie").apply(
        lambda x: round(x["Credit"].sum() - x["Debit"].sum(), 2)
    ).reset_index().rename(columns={0: "Augmentations"})

    diminutions = mvt[mvt["Debit"] > mvt["Credit"]].groupby("Catégorie").apply(
        lambda x: round(x["Debit"].sum() - x["Credit"].sum(), 2)
    ).reset_index().rename(columns={0: "Diminutions"})

    detail = debut.merge(augmentations, on="Catégorie", how="outer")
    detail = detail.merge(diminutions, on="Catégorie", how="outer")
    detail = detail.fillna(0)
    detail["Solde Final"] = (
        detail["Solde Initial"] + detail["Augmentations"] - detail["Diminutions"]
    ).round(2)
    for col in ["Solde Initial", "Augmentations", "Diminutions", "Solde Final"]:
        detail[col] = detail[col].round(2)

    # Ligne total
    total_row = pd.DataFrame([{
        "Catégorie": "TOTAL",
        "Solde Initial": detail["Solde Initial"].sum(),
        "Augmentations": detail["Augmentations"].sum(),
        "Diminutions": detail["Diminutions"].sum(),
        "Solde Final": detail["Solde Final"].sum(),
    }])
    detail = pd.concat([detail, total_row], ignore_index=True)

    total_debut = detail[detail["Catégorie"] != "TOTAL"]["Solde Initial"].sum()
    total_fin   = detail[detail["Catégorie"] != "TOTAL"]["Solde Final"].sum()

    return {
        "total_debut": round(total_debut, 2),
        "total_fin": round(total_fin, 2),
        "variation": round(total_fin - total_debut, 2),
        "detail": detail,
    }
