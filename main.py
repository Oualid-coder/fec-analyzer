import sys
from pathlib import Path
from modules.loader import load_fec
from modules.ca import ca_par_client, risque_dependance, ca_mensuel, ca_journalier, ca_weekends
from modules.immobilisations import variation_immobilisations, variation_amortissements
from modules.capitaux import variation_capitaux_propres
from modules.anomalies import detect_anomalies
from modules.export import export_rapport


def construire_resume_ia(data):
    risque = data["risque"]
    ca_total = data["ca_mensuel"][data["ca_mensuel"]["Mois"] != "TOTAL"]["CA_HT"].sum()
    top5 = data["ca_clients"].head(5)[["Client","CA_HT","Part_%"]].to_string(index=False)
    nb_manq = int(data["anomalies"]["tableau_sequentialite"][
        data["anomalies"]["tableau_sequentialite"]["Période"] == "TOTAL"]["Nb manquant"].iloc[0]) \
        if len(data["anomalies"]["tableau_sequentialite"]) > 0 else 0
    return f"""
DONNÉES FEC 2024 :
CA Total HT : {ca_total:,.2f} €  |  Clients : {risque['nb_clients']}
Top 5 clients :
{top5}
Risque dépendance : {risque['niveau_risque']} ({risque['top1_client']} = {risque['top1_part']:.1f}%)
Immos brutes fin : {data['immo']['solde_final']:,.2f} €  |  Acquisitions : {data['immo']['acquisitions']:,.2f} €
Amort. cumulés fin : {data['amort']['solde_final']:,.2f} €  |  Dotations : {data['amort']['dotations']:,.2f} €
Capitaux propres : {data['cp']['total_debut']:,.2f} € → {data['cp']['total_fin']:,.2f} €
Doublons : {len(data['anomalies']['doublons'])}  |  Déséquilibres : {len(data['anomalies']['desequilibres'])}  |  Aberrants : {len(data['anomalies']['montants_aberrants'])}
Factures VE manquantes : {nb_manq}
"""


def appeler_ia(resume, api_key):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu es expert-comptable français senior. Analyse ces données FEC et produis un rapport structuré : 1) Points positifs, 2) Risques, 3) Anomalies à investiguer, 4) Recommandations. Sois direct, parle en chiffres. Max 400 mots."},
                {"role": "user", "content": resume},
            ], max_tokens=600,
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"[Analyse IA non disponible : {e}]"


def run(fec_path, avec_ia=False, api_key=None):
    print(f"📂 Chargement : {fec_path}")
    df = load_fec(fec_path)
    print(f"   → {len(df)} lignes")

    print("📊 CA clients, mensuel, journalier, weekends...")
    ca_cl   = ca_par_client(df)
    risque  = risque_dependance(ca_cl)
    ca_mens = ca_mensuel(df)
    ca_jour = ca_journalier(df)
    ca_wk   = ca_weekends(df)

    print("🏭 Immobilisations & amortissements...")
    immo  = variation_immobilisations(df)
    amort = variation_amortissements(df)

    print("💼 Capitaux propres...")
    cp = variation_capitaux_propres(df)

    print("⚠️  Anomalies & séquentialité...")
    anom = detect_anomalies(df)

    data = {
        "ca_clients": ca_cl, "risque": risque,
        "ca_mensuel": ca_mens, "ca_journalier": ca_jour, "ca_weekends": ca_wk,
        "immo": immo, "amort": amort, "cp": cp,
        "anomalies": anom, "analyse_ia": None,
    }

    if avec_ia and api_key:
        print("🤖 Analyse IA...")
        data["analyse_ia"] = appeler_ia(construire_resume_ia(data), api_key)

    output = Path(fec_path).stem + "_rapport.xlsx"
    print("📝 Export Excel...")
    export_rapport(data, output)

    seq_tot = data["anomalies"]["tableau_sequentialite"]
    nb_manq = int(seq_tot[seq_tot["Période"]=="TOTAL"]["Nb manquant"].iloc[0]) if len(seq_tot) > 0 else 0

    print(f"\n{'='*52}")
    print(f"CA Total 2024        : {ca_mens[ca_mens['Mois']!='TOTAL']['CA_HT'].sum():>14,.2f} €")
    print(f"Nb clients           : {risque['nb_clients']:>14}")
    print(f"Client principal     : {risque['top1_client']:>14} ({risque['top1_part']:.1f}%)")
    print(f"Risque dépendance    : {risque['niveau_risque']:>14}")
    print(f"Immos brutes fin     : {immo['solde_final']:>14,.2f} €")
    print(f"Amort. cumulés fin   : {amort['solde_final']:>14,.2f} €")
    print(f"Capitaux propres fin : {cp['total_fin']:>14,.2f} €")
    print(f"Doublons             : {len(anom['doublons']):>14}")
    print(f"Factures manquantes  : {nb_manq:>14}")
    print(f"\n✅ Rapport : {output}")
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <fec.xlsx> [--ia OPENAI_API_KEY]")
        sys.exit(1)
    fec = sys.argv[1]
    ia  = "--ia" in sys.argv
    key = sys.argv[sys.argv.index("--ia") + 1] if ia and len(sys.argv) > sys.argv.index("--ia") + 1 else None
    run(fec, avec_ia=ia, api_key=key)
