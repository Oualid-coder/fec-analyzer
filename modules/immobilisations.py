import pandas as pd

COMPTES_IMMO = ["205", "206", "207", "213", "215", "218", "261", "267", "275"]
COMPTES_AMORT = ["280", "281", "282"]

def _is_immo(c): return any(c.startswith(p) for p in COMPTES_IMMO)
def _is_amort(c): return any(c.startswith(p) for p in COMPTES_AMORT)


def variation_immobilisations(df: pd.DataFrame) -> dict:
    immo = df[df["CompteNum"].apply(_is_immo)].copy()
    ran  = immo[immo["JournalCode"] == "RAN"]
    mvt  = immo[immo["JournalCode"] != "RAN"]

    solde_initial = round(ran["Debit"].sum() - ran["Credit"].sum(), 2)
    acquisitions  = round(mvt["Debit"].sum(), 2)
    sorties       = round(mvt["Credit"].sum(), 2)
    solde_final   = round(solde_initial + acquisitions - sorties, 2)

    # Début par libellé exact
    debut_lib = ran.groupby(["CompteNum", "CompteLib"]).apply(
        lambda x: round(x["Debit"].sum() - x["Credit"].sum(), 2)
    ).reset_index().rename(columns={0: "Solde Initial"})

    mvt_lib = mvt.groupby(["CompteNum", "CompteLib"])[["Debit", "Credit"]].sum().reset_index().rename(
        columns={"Debit": "Acquisitions", "Credit": "Sorties"}
    )

    detail = debut_lib.merge(mvt_lib, on=["CompteNum", "CompteLib"], how="outer").fillna(0)
    detail["Solde Final"] = (detail["Solde Initial"] + detail["Acquisitions"] - detail["Sorties"]).round(2)
    detail = detail[detail[["Solde Initial","Acquisitions","Sorties","Solde Final"]].abs().sum(axis=1) > 0]
    detail = detail.drop(columns=["CompteNum"]).rename(columns={"CompteLib": "Libellé"})

    # Nettoyer les libellés
    detail["Libellé"] = detail["Libellé"].str.replace(r'[^\x20-\x7E]', '?', regex=True).str.strip()

    for col in ["Solde Initial","Acquisitions","Sorties","Solde Final"]:
        detail[col] = detail[col].round(2)

    total_row = pd.DataFrame([{
        "Libellé": "TOTAL",
        "Solde Initial": detail["Solde Initial"].sum().round(2),
        "Acquisitions": detail["Acquisitions"].sum().round(2),
        "Sorties": detail["Sorties"].sum().round(2),
        "Solde Final": detail["Solde Final"].sum().round(2),
    }])
    detail = pd.concat([detail, total_row], ignore_index=True)

    return {
        "solde_initial": solde_initial, "acquisitions": acquisitions,
        "sorties": sorties, "solde_final": solde_final, "detail": detail,
    }


def variation_amortissements(df: pd.DataFrame) -> dict:
    amort = df[df["CompteNum"].apply(_is_amort)].copy()
    ran   = amort[amort["JournalCode"] == "RAN"]
    mvt   = amort[amort["JournalCode"] != "RAN"]

    solde_initial = round(ran["Credit"].sum() - ran["Debit"].sum(), 2)
    dotations     = round(mvt["Credit"].sum(), 2)
    reprises      = round(mvt["Debit"].sum(), 2)
    solde_final   = round(solde_initial + dotations - reprises, 2)

    debut_lib = ran.groupby(["CompteNum", "CompteLib"]).apply(
        lambda x: round(x["Credit"].sum() - x["Debit"].sum(), 2)
    ).reset_index().rename(columns={0: "Solde Initial"})

    mvt_lib = mvt.groupby(["CompteNum", "CompteLib"])[["Debit", "Credit"]].sum().reset_index().rename(
        columns={"Credit": "Dotations", "Debit": "Reprises"}
    )

    detail = debut_lib.merge(mvt_lib, on=["CompteNum", "CompteLib"], how="outer").fillna(0)
    detail["Solde Final"] = (detail["Solde Initial"] + detail["Dotations"] - detail["Reprises"]).round(2)
    detail = detail[detail[["Solde Initial","Dotations","Reprises","Solde Final"]].abs().sum(axis=1) > 0]
    detail = detail.drop(columns=["CompteNum"]).rename(columns={"CompteLib": "Libellé"})
    detail["Libellé"] = detail["Libellé"].str.replace(r'[^\x20-\x7E]', '?', regex=True).str.strip()

    for col in ["Solde Initial","Dotations","Reprises","Solde Final"]:
        detail[col] = detail[col].round(2)

    total_row = pd.DataFrame([{
        "Libellé": "TOTAL",
        "Solde Initial": detail["Solde Initial"].sum().round(2),
        "Dotations": detail["Dotations"].sum().round(2),
        "Reprises": detail["Reprises"].sum().round(2),
        "Solde Final": detail["Solde Final"].sum().round(2),
    }])
    detail = pd.concat([detail, total_row], ignore_index=True)

    return {
        "solde_initial": solde_initial, "dotations": dotations,
        "reprises": reprises, "solde_final": solde_final, "detail": detail,
    }
