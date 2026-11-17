"""Essai de l'application construite : démarrage, contrôle d'un FEC, arrêt.

    python tests/essai_executable.py "dist/FEC Analyzer.exe"
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.fabrique import ecrire  # noqa: E402

BASE = "http://127.0.0.1:8765"


def appel(chemin, donnees=None, entetes=None):
    req = urllib.request.Request(BASE + chemin, data=donnees, headers={"X-FEC-Analyzer": "1", **(entetes or {})})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as r:
        return json.load(r)


def main(executable: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "FEC_ANALYZER_HOME": str(Path(tmp) / "espace"), "FEC_ANALYZER_SANS_NAVIGATEUR": "1"}
        proc = subprocess.Popen([executable], env=env)
        try:
            for _ in range(120):
                try:
                    infos = appel("/api/infos")
                    break
                except Exception:
                    if proc.poll() is not None:
                        print("L'application s'est arrêtée au démarrage, code", proc.returncode)
                        return 1
                    time.sleep(0.5)
            else:
                print("L'application n'a pas démarré en 60 s")
                return 1
            print("Démarrée :", infos)
            assert infos["conditions"] is False
            appel("/api/conditions", b"{}", {"Content-Type": "application/json"})
            demo = appel("/api/demo", b"{}", {"Content-Type": "application/json"})["resultats"][0]
            print("Démo :", demo.get("verdict"), demo.get("erreur"))
            assert demo["ok"] and demo["verdict"] == "NON CONFORME", demo
            fec = ecrire(tmp)
            limite = "----essai"
            corps = (f"--{limite}\r\nContent-Disposition: form-data; name=\"fec\"; filename=\"{fec.name}\"\r\n"
                     "Content-Type: text/plain\r\n\r\n").encode() + fec.read_bytes() + f"\r\n--{limite}--\r\n".encode()
            res = appel("/api/analyser", corps, {"Content-Type": f"multipart/form-data; boundary={limite}"})
            r = res["resultats"][0]
            print("Contrôle :", r.get("verdict"), r.get("erreur"))
            assert r["ok"] and r["verdict"] == "CONFORME", r
            for cle in ("excel", "pdf"):
                assert (Path(infos["espace"]) / r[cle]).stat().st_size > 2000
            appel("/api/quitter", b"{}", {"Content-Type": "application/json"})
            proc.wait(timeout=30)
            print("Arrêt propre, code", proc.returncode)
            return 0
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
