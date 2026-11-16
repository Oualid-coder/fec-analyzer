"""Construit l'application installable pour la plateforme courante.

    python build.py

Windows : dist/FEC Analyzer.exe          (un seul fichier)
macOS   : dist/FEC Analyzer.app          (à glisser dans Applications)
Linux   : dist/fec-analyzer              (un seul fichier, pour les essais)
"""
import sys

import PyInstaller.__main__

EXCLUS = ["matplotlib", "tkinter", "scipy", "IPython", "pytest", "PIL.ImageTk", "pyarrow"]

args = [
    "lanceur.py",
    "--name", "fec-analyzer" if sys.platform.startswith("linux") else "FEC Analyzer",
    "--noconfirm", "--clean",
    "--add-data", "index.html:.",
    "--collect-submodules", "uvicorn",       # uvicorn charge ses protocoles par nom, à l'exécution
    "--collect-submodules", "modules",
]
for module in EXCLUS:
    args += ["--exclude-module", module]
if sys.platform == "darwin":
    args += ["--windowed", "--onedir", "--osx-bundle-identifier", "fr.fecanalyzer.app"]
elif sys.platform == "win32":
    args += ["--onefile", "--noconsole"]
else:
    args += ["--onefile"]

PyInstaller.__main__.run(args)
