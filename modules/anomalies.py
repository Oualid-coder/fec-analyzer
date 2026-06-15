import pandas as pd
import re


def detect_anomalies(df: pd.DataFrame) -> dict:
    anomalies = {}

    # 1. Doublons
    dupes = df[df.duplicated(subset=["PieceRef","Debit","Credit"], keep=False)]
    dupes = dupes[(dupes["Debit"] > 0) | (dupes["Credit"] > 0)]
    anomalies["doublons"] = dupes[
        ["EcritureDate","JournalCode","CompteLib","CompAuxLib","PieceRef","Debit","Credit"]
    ].drop_duplicates(subset=["PieceRef","Debit","Credit"]).head(20)

    # 2. Déséquilibres
    eq = df.groupby("EcritureNum").apply(lambda x: round(x["Debit"].sum() - x["Credit"].sum(), 2))
    anomalies["desequilibres"] = eq[eq.abs() > 0.05].reset_index().rename(columns={0: "Écart"}).head(20)

    # 3. Montants aberrants
    hors = df[~df["JournalCode"].isin(["RAN","OD","ODSTC"])]
    sd = hors["Debit"].mean() + 3 * hors["Debit"].std()
    sc = hors["Credit"].mean() + 3 * hors["Credit"].std()
    ab = hors[(hors["Debit"] > sd) | (hors["Credit"] > sc)]
    anomalies["montants_aberrants"] = ab[
        ["EcritureDate","JournalCode","CompteLib","CompAuxLib","Debit","Credit"]
    ].head(20)
    anomalies["seuil_aberrant"] = round(max(sd, sc), 2)

    # 4. Soldes négatifs suspects
    c4 = df[df["CompteNum"].str.startswith(("4","7")) & (df["Debit"] > 0)]
    sn = (c4.groupby(["CompteNum","CompteLib"])
          .apply(lambda x: round(x["Credit"].sum() - x["Debit"].sum(), 2))
          .reset_index().rename(columns={0: "Solde"}))
    anomalies["soldes_negatifs_suspects"] = sn[sn["Solde"] < -1000].head(20)

    # 5. Séquentialité complète des factures de vente
    anomalies["ruptures_sequence"] = detect_ruptures_sequence(df)
    anomalies["tableau_sequentialite"] = tableau_sequentialite(df)

    return anomalies


def _parse_ind(ref: str):
    m = re.match(r'^IND(\d{2})(\d{2})(\d+)$', str(ref).strip())
    if m:
        an, mo, nu = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            return an, mo, nu
    return None


def detect_ruptures_sequence(df: pd.DataFrame) -> pd.DataFrame:
    ve = df[df["JournalCode"] == "VE"].copy()
    pieces = ve[["EcritureDate","PieceRef"]].drop_duplicates("PieceRef")

    parsed = []
    for _, row in pieces.iterrows():
        r = _parse_ind(row["PieceRef"])
        if r:
            parsed.append({"PieceRef": row["PieceRef"], "EcritureDate": row["EcritureDate"],
                           "Annee": r[0], "Mois": r[1], "Num": r[2]})

    if not parsed:
        return pd.DataFrame(columns=["Période","N° manquant","Avant","Après","Écart"])

    dp = pd.DataFrame(parsed).sort_values(["Annee","Mois","Num"])
    ruptures = []

    for (an, mo), grp in dp.groupby(["Annee","Mois"]):
        nums = sorted(grp["Num"].tolist())
        for i in range(len(nums) - 1):
            ecart = nums[i+1] - nums[i]
            if ecart > 1:
                for manq in range(nums[i]+1, nums[i+1]):
                    ruptures.append({
                        "Période": f"20{an:02d}-{mo:02d}",
                        "N° manquant": f"IND{an:02d}{mo:02d}{manq:02d}",
                        "Avant": f"IND{an:02d}{mo:02d}{nums[i]:02d}",
                        "Après": f"IND{an:02d}{mo:02d}{nums[i+1]:02d}",
                        "Écart": ecart - 1,
                    })

    # Formats aberrants (mois > 12)
    for ref in ve["PieceRef"].dropna().unique():
        ref = str(ref).strip()
        if ref.startswith("IND"):
            m = re.match(r'^IND(\d{2})(\d{2})(\d+)$', ref)
            if m and int(m.group(2)) > 12:
                ruptures.append({"Période":"FORMAT ABERRANT","N° manquant":ref,"Avant":"—","Après":"—","Écart":0})

    if not ruptures:
        return pd.DataFrame(columns=["Période","N° manquant","Avant","Après","Écart"])
    return pd.DataFrame(ruptures)


def tableau_sequentialite(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tableau récapitulatif de séquentialité par mois :
    - 1ère facture, dernière facture, nb attendu, nb présent, nb manquant, taux de complétude
    """
    ve = df[df["JournalCode"] == "VE"].copy()
    pieces = ve[["EcritureDate","PieceRef"]].drop_duplicates("PieceRef")

    parsed = []
    for _, row in pieces.iterrows():
        r = _parse_ind(row["PieceRef"])
        if r:
            parsed.append({"PieceRef": row["PieceRef"], "Annee": r[0], "Mois": r[1], "Num": r[2]})

    if not parsed:
        return pd.DataFrame()

    dp = pd.DataFrame(parsed)
    rows = []
    for (an, mo), grp in dp.groupby(["Annee","Mois"]):
        nums = sorted(grp["Num"].tolist())
        premier = nums[0]
        dernier = nums[-1]
        nb_attendu = dernier - premier + 1
        nb_present = len(nums)
        nb_manquant = nb_attendu - nb_present
        taux = round(nb_present / nb_attendu * 100, 1) if nb_attendu > 0 else 100.0
        rows.append({
            "Période": f"20{an:02d}-{mo:02d}",
            "1ère facture": f"IND{an:02d}{mo:02d}{premier:02d}",
            "Dernière facture": f"IND{an:02d}{mo:02d}{dernier:02d}",
            "Nb attendu": nb_attendu,
            "Nb présent": nb_present,
            "Nb manquant": nb_manquant,
            "Complétude %": taux,
            "Statut": "✅ OK" if nb_manquant == 0 else f"⚠️ {nb_manquant} manquant(s)",
        })

    result = pd.DataFrame(rows)

    # Ligne total
    total_row = pd.DataFrame([{
        "Période": "TOTAL",
        "1ère facture": "",
        "Dernière facture": "",
        "Nb attendu": result["Nb attendu"].sum(),
        "Nb présent": result["Nb présent"].sum(),
        "Nb manquant": result["Nb manquant"].sum(),
        "Complétude %": round(result["Nb présent"].sum() / result["Nb attendu"].sum() * 100, 1),
        "Statut": "✅ OK" if result["Nb manquant"].sum() == 0 else f"⚠️ {result['Nb manquant'].sum()} manquant(s)",
    }])
    return pd.concat([result, total_row], ignore_index=True)
