"""Point d'entrée de l'application installée (Mac et Windows).

Démarre le serveur local sur 127.0.0.1, ouvre le navigateur par défaut, et
s'arrête quand l'utilisateur clique sur « Quitter » dans l'interface.
Si l'application tourne déjà, on rouvre simplement son onglet.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

PORTS = range(8765, 8775)


def _deja_lancee(port: int) -> bool:
    try:
        # Sans proxy : sur un poste d'entreprise, un proxy système ne doit pas intercepter l'appel local.
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct.open(f"http://127.0.0.1:{port}/api/infos", timeout=0.5) as r:
            return json.load(r).get("application") == "fec-analyzer"
    except Exception:
        return False


def _port_libre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    for port in PORTS:
        if _deja_lancee(port):
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return 0
    port = next((p for p in PORTS if _port_libre(p)), None)
    if port is None:
        return 1

    import uvicorn
    from app import app
    from main import configurer_journal

    configurer_journal()
    log = logging.getLogger("fec.lanceur")
    # log_config=None : en mode fenêtré (sans console) il n'y a pas de sortie standard où écrire.
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    app.state.arreter = lambda: setattr(serveur, "should_exit", True)

    def ouvrir_navigateur():
        if os.environ.get("FEC_ANALYZER_SANS_NAVIGATEUR"):      # essais automatiques
            return
        for _ in range(100):
            if serveur.started:
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return
            time.sleep(0.1)

    threading.Thread(target=ouvrir_navigateur, daemon=True).start()
    log.info("Démarrage sur http://127.0.0.1:%d", port)
    serveur.run()
    log.info("Arrêt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
