"""Historique et favoris, enregistrés en JSON dans le dossier de l'utilisateur."""

import json
import os
import time

DOSSIER = os.path.join(os.path.expanduser("~"), ".navigateur_maison")
MAX_HISTORIQUE = 2000


class Stockage:
    def __init__(self, dossier=DOSSIER):
        self.dossier = dossier
        self.historique = self._lire("historique.json", [])
        self.favoris = self._lire("favoris.json", [])

    def _chemin(self, nom):
        return os.path.join(self.dossier, nom)

    def _lire(self, nom, defaut):
        try:
            with open(self._chemin(nom), encoding="utf-8") as fichier:
                return json.load(fichier)
        except (OSError, ValueError):
            return defaut

    def _ecrire(self, nom, donnees):
        try:
            os.makedirs(self.dossier, exist_ok=True)
            temporaire = self._chemin(nom + ".tmp")
            with open(temporaire, "w", encoding="utf-8") as fichier:
                json.dump(donnees, fichier, ensure_ascii=False, indent=1)
            os.replace(temporaire, self._chemin(nom))
        except OSError:
            pass  # stockage indisponible : on continue sans sauvegarder

    # -- historique ----------------------------------------------------------

    def ajouter_historique(self, url, titre):
        if url.startswith(("about:", "view-source:", "data:")):
            return
        self.historique.append({"url": url, "titre": titre or url, "date": time.time()})
        del self.historique[:-MAX_HISTORIQUE]
        self._ecrire("historique.json", self.historique)

    def effacer_historique(self):
        self.historique = []
        self._ecrire("historique.json", self.historique)

    # -- favoris -------------------------------------------------------------

    def est_favori(self, url):
        return any(f["url"] == url for f in self.favoris)

    def basculer_favori(self, url, titre):
        if self.est_favori(url):
            self.favoris = [f for f in self.favoris if f["url"] != url]
            ajoute = False
        else:
            self.favoris.append({"url": url, "titre": titre or url})
            ajoute = True
        self._ecrire("favoris.json", self.favoris)
        return ajoute

    def supprimer_favori(self, url):
        self.favoris = [f for f in self.favoris if f["url"] != url]
        self._ecrire("favoris.json", self.favoris)
