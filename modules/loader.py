import pandas as pd

def load_fec(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [c.strip() for c in df.columns]
    df["EcritureDate"] = pd.to_datetime(df["EcritureDate"], errors="coerce")
    df["CompteNum"] = df["CompteNum"].astype(str).str.strip()
    df["Debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0)
    df["Credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    df["CompAuxLib"] = df["CompAuxLib"].fillna("").astype(str).str.strip()
    df["Mois"] = df["EcritureDate"].dt.to_period("M")
    return df
