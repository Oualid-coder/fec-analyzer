#!/bin/bash
# Lancement depuis les sources, pour le développement.
# Les utilisateurs installent l'application (voir README) : rien à installer à la main.
cd "$(dirname "$0")"
exec python3 lanceur.py
