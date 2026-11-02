"""Réseau personnel de navigation et annotations (outils HyWebMap).

Inspiré de HyWebMap (Saleh, Papy, Bouhaï, Paris 8, 2001) :
  * l'historique n'est pas une simple liste mais un GRAPHE de navigation
    (nœuds = pages, liens = passages d'une page à l'autre) ;
  * l'utilisateur peut ajouter ses propres liens nommés entre deux pages
    (« liens personnels »), sans modifier les sites d'origine ;
  * il peut annoter les pages (passage, note, mots-clés, date) ;
  * le réseau personnel peut être exporté en site HTML consultable
    par n'importe quel navigateur ;
  * le réseau peut accueillir un site exploré par l'agent Web, des nœuds
    libres, et des propositions de l'agent de profil (marquées « NP ») ;
  * un dictionnaire personnel de mots-clés et de synonymes aide à chercher
    dans les annotations.

Tout est enregistré localement dans ~/.navigateur_maison/reseau.json
(aucun service extérieur).
"""

import json
import os
import re
from collections import Counter
from datetime import datetime

from .analyseur_html import Element, analyser_html, parcourir
from .reseau import ErreurReseau, URL, pourcent_decoder, pourcent_encoder


def maintenant():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


HOTES_IGNORES = ("duckduckgo.com", "mojeek.com")


def _liste(texte):
    if isinstance(texte, list):
        return texte
    return [m.strip() for m in (texte or "").split(",") if m.strip()]


def _hote(url):
    if not url or "://" not in url:
        return ""
    return url.split("://", 1)[1].split("/", 1)[0].split(":")[0].lower()


def _rompu(statut):
    return statut is not None and (statut == 0 or statut >= 400)


def lier_urls(texte_echappe):
    """Rend cliquables les adresses écrites dans une note (une annotation peut contenir des liens)."""
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', texte_echappe)


class ReseauPersonnel:
    def __init__(self, dossier):
        self.fichier = os.path.join(dossier, "reseau.json")
        self.historique = []     # [{url, titre, date}] : visites datées (navigation par date)
        self.noeuds = {}         # url -> {titre, visites, premiere, niveau, statut}
        self.liens = []          # [{de, vers, nom, perso}]
        self.annotations = []    # [{url, titre, passage, note, mots_cles, date, numero}]
        self.racine = None       # premier nœud du réseau (nœud racine HyWebMap)
        self.dictionnaire = {}   # mot-clé -> [synonymes] (dictionnaire personnel, § 2.9)
        self.parametres = {"surveillance_auto": False, "minutes_surveillance": 30}
        self.charger()

    # -- persistance --------------------------------------------------------
    def charger(self):
        try:
            with open(self.fichier, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        self.historique = d.get("historique", [])
        self.noeuds = d.get("noeuds", {})
        self.liens = d.get("liens", [])
        self.annotations = d.get("annotations", [])
        self.racine = d.get("racine")
        self.dictionnaire = d.get("dictionnaire", {})
        self.parametres.update(d.get("parametres", {}))

    def enregistrer(self):
        try:
            os.makedirs(os.path.dirname(self.fichier), exist_ok=True)
            tmp = self.fichier + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"historique": self.historique[-2000:],
                           "noeuds": self.noeuds, "liens": self.liens,
                           "annotations": self.annotations, "racine": self.racine,
                           "dictionnaire": self.dictionnaire, "parametres": self.parametres},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.fichier)
        except OSError:
            pass  # stockage indisponible : on continue sans sauvegarder

    # -- navigation ---------------------------------------------------------
    def visite(self, url, titre, depuis=None, texte_lien=None, code_http=200):
        """Enregistre une visite et met à jour le graphe de navigation."""
        if url.startswith(("about:", "view-source:", "data:")):
            return
        if any(_hote(url).endswith(h) for h in HOTES_IGNORES):
            return    # pages de moteurs de recherche, captchas, redirections : pas des documents du réseau
        self.historique.append({"url": url, "titre": titre, "date": maintenant()})
        n = self.noeuds.get(url)
        if n is None:
            niveau = 0
            if depuis in self.noeuds:
                niveau = self.noeuds[depuis]["niveau"] + 1
            n = self.noeuds[url] = {"titre": titre, "visites": 0, "premiere": maintenant(),
                                    "niveau": niveau, "statut": "ok"}
            if self.racine is None:
                self.racine = url
        n["visites"] += 1
        n["derniere"] = maintenant()
        n["titre"] = titre or n["titre"]
        n["statut"] = "rompu" if code_http >= 400 else "ok"
        n.pop("np", None)                 # une proposition visitée n'est plus « nouvelle »
        if depuis and depuis in self.noeuds and depuis != url:
            existant = next((l for l in self.liens if l["de"] == depuis and l["vers"] == url), None)
            if existant is None:
                self.liens.append({"de": depuis, "vers": url, "nom": (texte_lien or "")[:60],
                                   "perso": False, "parcouru": True})
            else:
                existant["parcouru"] = True   # lien de l'agent maintenant parcouru (§ 2.8)
        self.enregistrer()

    def historique_entre(self, debut, fin):
        """Pages visitées entre deux dates (AAAA-MM-JJ), sans doublons."""
        vus, res = set(), []
        for h in reversed(self.historique):
            jour = h["date"][:10]
            if debut <= jour <= fin and h["url"] not in vus:
                vus.add(h["url"])
                res.append(h)
        return res

    # -- liens personnels ---------------------------------------------------
    def ajouter_lien_perso(self, de, vers, nom):
        for u in (de, vers):
            if u not in self.noeuds:
                self.noeuds[u] = {"titre": u, "visites": 0, "premiere": maintenant(),
                                  "niveau": 0, "statut": "ok"}
        self.liens.append({"de": de, "vers": vers, "nom": nom, "perso": True})
        self.enregistrer()

    def type_noeud(self, url):
        """Typologie des nœuds de HyWebMap (§ 2.5) : racine, parent, fils, orphelin, externe.
        Un nœud libre (sans ressource Web) est signalé comme « libre »."""
        if url == self.racine:
            return "racine"
        n = self.noeuds.get(url, {})
        if n.get("libre") and not n.get("ressource"):
            return "libre"
        sortants = any(l["de"] == url and not l["perso"] for l in self.liens)
        entrants = any(l["vers"] == url for l in self.liens) or any(l["de"] == url for l in self.liens)
        hote_racine = _hote(self.racine)
        if hote_racine and _hote(url) and _hote(url) != hote_racine:
            return "externe"
        if not sortants and not entrants:
            return "orphelin"
        return "parent" if sortants else "fils"

    def type_lien(self, lien):
        """Typologie des liens explicites de HyWebMap (§ 2.5)."""
        if lien.get("perso"):
            return "référence"
        if lien.get("type"):
            return lien["type"]           # type calculé par l'agent Web
        de, vers = self.noeuds.get(lien["de"], {}), self.noeuds.get(lien["vers"], {})
        if lien["de"] == lien["vers"]:
            return "interne"
        if vers.get("statut") == "rompu":
            return "externe rompu" if _hote(lien["de"]) != _hote(lien["vers"]) else "interne rompu"
        if _hote(lien["de"]) != _hote(lien["vers"]):
            return "externe"
        if vers.get("niveau", 0) != de.get("niveau", 0) + 1:
            return "référence"
        if lien["de"] == self.racine:
            return "ancêtre"
        return "fils" if self.type_noeud(lien["vers"]) == "fils" else "parent"

    # -- nœuds libres et ressources (§ 2.5, « Déclaration de nœuds ») ---------
    def ajouter_noeud_libre(self, nom, ressource="", mots_cles="", annotation="", relier_a=None, nom_lien=""):
        """Nœud libre : un nom, une ressource Web facultative, des mots-clés, une annotation."""
        ressource = ressource.strip()
        if ressource and "://" not in ressource and not ressource.startswith("about:"):
            ressource = "https://" + ressource
        cle = ressource or "libre:%d" % (1 + max([int(u[6:]) for u in self.noeuds
                                                   if u.startswith("libre:") and u[6:].isdigit()] or [0]))
        niveau = self.noeuds[relier_a]["niveau"] + 1 if relier_a in self.noeuds else 0
        self.noeuds[cle] = {"titre": nom.strip() or ressource or cle, "visites": 0, "premiere": maintenant(),
                            "niveau": niveau, "statut": "ok", "libre": True, "ressource": ressource,
                            "mots_cles": _liste(mots_cles)}
        if self.racine is None:
            self.racine = cle
        if annotation.strip():
            self.annoter(cle, nom, "", annotation, mots_cles)
        if relier_a in self.noeuds:
            self.liens.append({"de": relier_a, "vers": cle, "nom": nom_lien, "perso": True})
        self.enregistrer()
        return cle

    def affecter_ressource(self, cle, ressource):
        """Affecte une adresse Web à un nœud libre : la clé du nœud devient cette adresse."""
        ressource = ressource.strip()
        if "://" not in ressource:
            ressource = "https://" + ressource
        if cle not in self.noeuds or cle == ressource:
            return cle
        noeud = self.noeuds.pop(cle)
        noeud["ressource"] = ressource
        self.noeuds[ressource] = noeud
        for l in self.liens:
            l["de"] = ressource if l["de"] == cle else l["de"]
            l["vers"] = ressource if l["vers"] == cle else l["vers"]
        for a in self.annotations:
            a["url"] = ressource if a["url"] == cle else a["url"]
        if self.racine == cle:
            self.racine = ressource
        self.enregistrer()
        return ressource

    def remplacer_noeud(self, ancien, nouveau, titre=""):
        """Remplace un nœud disparu par une autre page : liens et annotations sont conservés (§ 2.6)."""
        if ancien not in self.noeuds or nouveau == ancien:
            return ancien
        noeud = self.noeuds.pop(ancien)
        noeud.update({"titre": titre or nouveau, "statut": "ok", "visites": 0})
        noeud.pop("vide", None)
        if nouveau in self.noeuds:
            noeud = self.noeuds[nouveau]
        self.noeuds[nouveau] = noeud
        for l in self.liens:
            l["de"] = nouveau if l["de"] == ancien else l["de"]
            l["vers"] = nouveau if l["vers"] == ancien else l["vers"]
        self.liens = [l for l in self.liens if l["de"] != l["vers"]]
        for a in self.annotations:
            a["url"] = nouveau if a["url"] == ancien else a["url"]
        if self.racine == ancien:
            self.racine = nouveau
        self.enregistrer()
        return nouveau

    def enrichir(self, url, proprietes):
        """Garde les métadonnées d'une page visitée (auteur, mots-clés, date) pour l'export (§ 2.10)."""
        n = self.noeuds.get(url)
        if n is None:
            return
        for cle_source, cle in (("auteur", "auteur"), ("mots_cles", "meta_mots_cles"),
                                ("date_creation", "date_creation"), ("description", "description")):
            if proprietes.get(cle_source):
                n[cle] = proprietes[cle_source]

    def mots_cles(self, url):
        """Mots-clés d'un nœud : les siens, ceux de ses annotations et des balises meta."""
        n = self.noeuds.get(url, {})
        mots = list(n.get("mots_cles", [])) + _liste(n.get("meta_mots_cles", ""))
        for a in self.annotations_de(url):
            mots += a["mots_cles"]
        vus, resultat = set(), []
        for m in mots:
            if m.lower() not in vus:
                vus.add(m.lower())
                resultat.append(m)
        return resultat

    # -- site exploré par l'agent Web (§ 2.3 : le réseau virtuel présente l'espace du site) --
    def importer_exploration(self, noeuds, liaisons):
        """Ajoute au réseau le site exploré par l'agent (base SQLite) : les pages analysées et
        les liens rompus trouvés. Les milliers de liens simplement répertoriés restent dans la
        base (fenêtre de l'agent) pour que la carte reste lisible."""
        retenus = [n for n in noeuds if n.get("explore") or _rompu(n.get("statut"))]
        urls = {n["url"] for n in retenus}
        ajoutes = 0
        for n in retenus:
            url = n["url"]
            if url not in self.noeuds:
                ajoutes += 1
                self.noeuds[url] = {"titre": n.get("titre") or url, "visites": 0, "premiere": maintenant(),
                                    "niveau": n["niveau"], "statut": "rompu" if _rompu(n.get("statut")) else "ok",
                                    "agent": True}
            noeud = self.noeuds[url]
            for cle_base, cle in (("auteur", "auteur"), ("mots_cles", "meta_mots_cles"),
                                  ("date_creation", "date_creation"), ("description", "description"),
                                  ("copie", "copie")):
                if n.get(cle_base):
                    noeud[cle] = n[cle_base]
        if self.racine is None and retenus:
            self.racine = retenus[0]["url"]
        existants = {(l["de"], l["vers"]) for l in self.liens}
        for l in liaisons:
            cle = (l["de"], l["vers"])
            if l["de"] == l["vers"] or cle in existants or l["de"] not in urls or l["vers"] not in urls:
                continue
            existants.add(cle)
            self.liens.append({"de": l["de"], "vers": l["vers"], "nom": (l.get("texte") or "")[:60],
                               "perso": False, "agent": True, "parcouru": False, "type": l.get("type", "")})
        self.enregistrer()
        return ajoutes

    def niveaux(self):
        return sorted({n.get("niveau", 0) for n in self.noeuds.values()})

    def voisins(self, url):
        """Le nœud et tous les nœuds qui lui sont attachés (navigation locale, § 2.8)."""
        return {url} | {l["vers"] for l in self.liens if l["de"] == url} | {l["de"] for l in self.liens if l["vers"] == url}

    # -- agents de surveillance (§ 2.6) ---------------------------------------
    def decision_surveillance(self, url):
        """Que faire d'un nœud devenu indisponible, selon son type (§ 2.6)."""
        t = self.type_noeud(url)
        if t == "racine":
            return "changer_racine"       # alerter l'auteur : choisir un autre nœud racine
        if t == "parent":
            # solution semi-automatique si le nœud a des mots-clés, sinon manuelle
            return "rechercher_remplacant" if self.mots_cles(url) else "garder_vide"
        if t == "fils":
            return "supprimer"            # suppression locale sans réorganisation
        return "signaler"

    def marquer_vide(self, url):
        if url in self.noeuds:
            self.noeuds[url]["vide"] = True
            self.enregistrer()

    # -- agent de gestion de profils : propositions « NP » (§ 2.6) -----------
    def mots_cles_frequents(self, nombre=3):
        compteur = Counter()
        for a in self.annotations:
            compteur.update(m.lower() for m in a["mots_cles"])
        for n in self.noeuds.values():
            compteur.update(m.lower() for m in n.get("mots_cles", []))
        return [m for m, _ in compteur.most_common(nombre)]

    def ajouter_proposition(self, url, titre, mot_cle, relier_a=None):
        if url in self.noeuds:
            return False
        niveau = self.noeuds[relier_a]["niveau"] + 1 if relier_a in self.noeuds else 0
        self.noeuds[url] = {"titre": titre or url, "visites": 0, "premiere": maintenant(), "niveau": niveau,
                            "statut": "ok", "np": True, "mots_cles": [mot_cle] if mot_cle else []}
        if relier_a in self.noeuds:
            self.liens.append({"de": relier_a, "vers": url, "nom": mot_cle, "perso": True})
        self.enregistrer()
        return True

    # -- dictionnaire personnel (§ 2.9) ----------------------------------------
    def definir_synonymes(self, mot, synonymes):
        mot = mot.strip().lower()
        if mot:
            self.dictionnaire[mot] = [s.strip().lower() for s in synonymes if s.strip()]
            self.enregistrer()

    def dictionnaire_texte(self):
        return "\n".join("%s : %s" % (m, ", ".join(s)) for m, s in sorted(self.dictionnaire.items()))

    def charger_dictionnaire_texte(self, texte):
        self.dictionnaire = {}
        for ligne in texte.splitlines():
            if ":" in ligne:
                mot, _, reste = ligne.partition(":")
                if mot.strip():
                    self.dictionnaire[mot.strip().lower()] = _liste(reste.lower())
        self.enregistrer()

    def etendre(self, mot):
        """Le mot et ses synonymes, dans les deux sens."""
        mot = mot.strip().lower()
        termes = {mot} | set(self.dictionnaire.get(mot, []))
        for cle, synonymes in self.dictionnaire.items():
            if mot in synonymes:
                termes |= {cle} | set(synonymes)
        return termes

    def vider(self):
        """Repart d'un réseau vide (les annotations, le dictionnaire et les réglages sont gardés)."""
        self.noeuds, self.liens, self.historique, self.racine = {}, [], [], None
        self.enregistrer()

    def supprimer_noeud(self, url):
        self.noeuds.pop(url, None)
        self.liens = [l for l in self.liens if l["de"] != url and l["vers"] != url]
        if self.racine == url:
            self.racine = next(iter(self.noeuds), None)
        self.enregistrer()

    # -- annotations --------------------------------------------------------
    def annoter(self, url, titre, passage, note, mots_cles):
        numero = 1 + max((a["numero"] for a in self.annotations), default=0)
        self.annotations.append({"url": url, "titre": titre, "passage": passage.strip(),
                                 "note": note.strip(), "date": maintenant(),
                                 "mots_cles": [m.strip() for m in mots_cles.split(",") if m.strip()],
                                 "numero": numero})
        self.enregistrer()

    def annotations_de(self, url):
        return [a for a in self.annotations if a["url"].split("#")[0] == url.split("#")[0]]

    CHAMPS = {"tout": None, "date": ("date",), "titre": ("titre",), "url": ("url",),
              "passage": ("passage",), "note": ("note",), "mots-clés": ("mots_cles",)}

    def chercher_annotations(self, requete, champ="tout"):
        """Recherche plein texte ou par attribut (date, titre, URL, passage surligné…).
        Les synonymes du dictionnaire personnel sont pris en compte."""
        termes = self.etendre(requete) if requete.strip() else {""}
        cles = self.CHAMPS.get(champ) or ("note", "passage", "titre", "url", "mots_cles", "date")

        def texte(a):
            return " ".join(" ".join(a[c]) if isinstance(a[c], list) else str(a.get(c, "")) for c in cles).lower()

        return [a for a in self.annotations if any(t in texte(a) for t in termes)]

    def regrouper_par_document(self, annotations):
        """[(url, titre, [annotations], résumé)] : le résumé fusionne les passages surlignés (§ 2.9)."""
        groupes = {}
        for a in annotations:
            groupes.setdefault(a["url"], []).append(a)
        resultat = []
        for url, liste in groupes.items():
            liste.sort(key=lambda a: a["numero"])
            resume = " […] ".join(a["passage"] for a in liste if a["passage"])
            resultat.append((url, liste[0]["titre"] or url, liste, resume))
        return resultat

    def supprimer_annotation(self, numero):
        self.annotations = [a for a in self.annotations if a["numero"] != numero]
        self.enregistrer()

    # -- export du réseau personnel en site HTML (HyWebMap § 2.10) ----------
    def exporter_html(self, chemin, nom_reseau="Mon réseau personnel"):
        """Génère un site HTML du réseau virtuel, comme HyWebMap (§ 2.10) :

        * ``chemin`` : page d'entrée en deux cadres — à gauche la navigation (sommaire
          actif, avec le nom des liens entre nœuds), à droite le profil de la page ;
        * un dossier ``<nom>_fichiers`` : navigation.html et une fiche par nœud
          (nom du réseau, titre, URL source, mots-clés, auteur, date de création,
          puis les annotations personnelles en bas de page).
        Pour les navigateurs sans cadres (dont le nôtre), la page d'entrée contient
        aussi tout le réseau sur une seule page.
        """
        def esc(t):
            return (str(t) if t is not None else "").replace("&", "&amp;").replace("<", "&lt;") \
                .replace(">", "&gt;").replace('"', "&quot;")

        base_nom = os.path.splitext(os.path.basename(chemin))[0]
        dossier = os.path.join(os.path.dirname(os.path.abspath(chemin)), base_nom + "_fichiers")
        os.makedirs(dossier, exist_ok=True)
        rel = base_nom + "_fichiers/"
        ids = {u: k for k, u in enumerate(self.noeuds)}
        enfants = {}
        for l in self.liens:
            enfants.setdefault(l["de"], []).append(l)

        # Sommaire actif : arbre depuis la racine, chaque entrée précédée du nom du lien
        def sommaire(prefixe, cible):
            lignes, vus = [], set()

            def arbre(url, profondeur, nom_lien):
                if url in vus or url not in self.noeuds:
                    return
                vus.add(url)
                n = self.noeuds[url]
                lien = '<i>%s</i> → ' % esc(nom_lien) if nom_lien else ""
                lignes.append('%s%s%s<a href="%sn%d.html"%s>%s</a><br>' % (
                    "&nbsp;" * 5 * profondeur, "└ " if profondeur else "", lien, prefixe, ids[url],
                    ' target="%s"' % cible if cible else "", esc(n.get("titre") or url)))
                for l in enfants.get(url, []):
                    arbre(l["vers"], profondeur + 1, l.get("nom", ""))

            if self.racine:
                arbre(self.racine, 0, "")
            for u in self.noeuds:
                arbre(u, 0, "")
            return "".join(lignes)

        style = ("<style>body{font-family:Georgia,serif;color:#222;margin:1em 1.5em}a{color:#1a55c2}"
                 "h1{color:#b03a2e}table{border-collapse:collapse}td{padding:3px 10px;vertical-align:top}"
                 ".annot{background:#f2fbf2;border-left:4px solid #2e7d32;padding:6px 10px;margin:8px 0}</style>")

        def fiche(url):
            n = self.noeuds[url]
            source = n.get("ressource") or ("" if url.startswith("libre:") else url)
            lignes = [("Nom du réseau", esc(nom_reseau)), ("Titre de la page", esc(n.get("titre") or url)),
                      ("URL de la page source", '<a href="%s">%s</a>' % (esc(source), esc(source)) if source else "—")]
            mots = self.mots_cles(url)
            for etiquette, valeur in (("Mots-clés", ", ".join(mots)), ("Auteur", n.get("auteur")),
                                      ("Date de création", n.get("date_creation"))):
                if valeur:                       # affichés seulement si la page les fournit
                    lignes.append((etiquette, esc(valeur)))
            lignes.append(("Type de nœud", self.type_noeud(url)))
            sortants = "".join('<li>%s <i>(%s)</i> : <a href="n%d.html">%s</a></li>' % (
                esc(l.get("nom") or "→"), self.type_lien(l), ids[l["vers"]],
                esc(self.noeuds.get(l["vers"], {}).get("titre") or l["vers"]))
                for l in enfants.get(url, []) if l["vers"] in ids)
            notes = "".join('<div class="annot"><b>n° %d</b> — %s<br>%s%s%s</div>' % (
                a["numero"], esc(a["date"]), lier_urls(esc(a["note"])),
                "<br><i>« %s »</i>" % esc(a["passage"]) if a["passage"] else "",
                "<br>Mots-clés : %s" % esc(", ".join(a["mots_cles"])) if a["mots_cles"] else "")
                for a in self.annotations_de(url))
            return ("<h1>%s</h1><table>%s</table>" % (esc(n.get("titre") or url), "".join(
                    "<tr><td><b>%s</b></td><td>%s</td></tr>" % l for l in lignes))
                    + ("<h2>Liens</h2><ul>%s</ul>" % sortants if sortants else "")
                    + ("<h2>Annotations personnelles</h2>%s" % notes if notes else ""))

        entete = '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>%s</title>' + style + "</head>"
        for url in self.noeuds:
            with open(os.path.join(dossier, "n%d.html" % ids[url]), "w", encoding="utf-8") as f:
                f.write(entete % esc(self.noeuds[url].get("titre") or url) + "<body>" + fiche(url) + "</body></html>")
        resume = "%d nœuds, %d liens, %d annotations — généré le %s" % (
            len(self.noeuds), len(self.liens), len(self.annotations), maintenant())
        with open(os.path.join(dossier, "navigation.html"), "w", encoding="utf-8") as f:
            f.write(entete % "Navigation" + "<body><h2>%s</h2><p><small>%s</small></p>%s</body></html>"
                    % (esc(nom_reseau), resume, sommaire("", "fiche")))
        premiere = "n%d.html" % ids[self.racine] if self.racine in ids else "navigation.html"
        une_page = "".join('<hr><a name="n%d"></a>%s' % (ids[u], fiche(u)) for u in self.noeuds)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write((entete % esc(nom_reseau)).replace("</head>", "</head>\n")
                    + '<frameset cols="32%%,*"><frame name="navigation" src="%snavigation.html">'
                      '<frame name="fiche" src="%s%s"><noframes><body><h1>%s</h1><p>%s</p>'
                      '<h2>Sommaire</h2>%s%s</body></noframes></frameset></html>'
                    % (rel, rel, premiere, esc(nom_reseau), resume,
                       re.sub(r'href="[^"]*?n(\d+)\.html"', r'href="#n\1"', sommaire(rel, "")),
                       re.sub(r'href="n(\d+)\.html"', r'href="#n\1"', une_page)))
        return chemin


# ---------------------------------------------------------------------------
# Analyse d'une page (sans interface graphique, donc testable)
# ---------------------------------------------------------------------------

def verifier_lien(client, adresse):
    """Code HTTP d'une page (requête HEAD, puis GET si HEAD est refusé), None si injoignable."""
    try:
        url = URL(adresse)
        if url.schema not in ("http", "https"):
            return 200
        statut = client.charger(url, methode="HEAD").statut
        if statut in (403, 405, 501):
            statut = client.charger(url).statut
        return statut
    except (ErreurReseau, ValueError, OSError):
        return None


META_DATES = ("date", "dcterms.created", "dc.date", "dc.date.created", "created",
              "article:published_time", "dcterms.date")


def proprietes_dom(dom):
    """Seulement les propriétés (titre, auteur, mots-clés, date, description) : rapide, car on ne
    parcourt que l'en-tête <head> de la page."""
    tete = next((n for n in dom.enfants if isinstance(n, Element) and n.balise == "head"), dom)
    titre, metas = "", {}
    for n in parcourir(tete):
        if isinstance(n, Element):
            if n.balise == "title" and not titre:
                titre = " ".join(n.texte_contenu().split())
            elif n.balise == "meta":
                nom = (n.attributs.get("name") or n.attributs.get("property") or "").lower()
                metas.setdefault(nom, n.attributs.get("content", "").strip())
    premier = lambda *noms: next((metas[m] for m in noms if metas.get(m)), "")
    return {"titre": titre, "auteur": premier("author", "dc.creator", "dcterms.creator"),
            "mots_cles": premier("keywords", "news_keywords"),
            "description": premier("description", "og:description"), "date_creation": premier(*META_DATES)}


ZONES_MENU = {"nav", "header", "footer", "aside"}
IDS_CONTENU = {"mw-content-text", "bodycontent", "content", "main", "contenu"}


def _dans_le_contenu(noeud):
    """Vrai si le lien est dans le texte principal de la page plutôt que dans un menu."""
    n, contenu = noeud.parent, False
    while isinstance(n, Element):
        if n.balise in ZONES_MENU or n.attributs.get("role") in ("navigation", "banner", "contentinfo"):
            return False
        if n.balise in ("main", "article") or n.attributs.get("id", "").lower() in IDS_CONTENU \
                or n.attributs.get("role") == "main":
            contenu = True
        n = n.parent
    return contenu


def caracteristiques_dom(dom, url, base=None):
    """Profil, propriétés et liens d'une page (relations « Profils » et « Propriété » de HyWebMap).

    Renvoie {"profil": {...}, "proprietes": {...}, "liens": [(texte, href, adresse, type)]}
    où type vaut « interne », « externe » ou « ancre » (lien vers la même page).
    """
    elements = [n for n in parcourir(dom) if isinstance(n, Element)]

    def meta(*noms):
        for n in elements:
            if n.balise == "meta":
                nom = (n.attributs.get("name") or n.attributs.get("property") or "").lower()
                if nom in noms:
                    return n.attributs.get("content", "").strip()
        return ""

    titre = ""
    for n in elements:
        if n.balise == "title":
            titre = " ".join(n.texte_contenu().split())
            break
        if n.balise == "base" and n.attributs.get("href") and base is None:
            try:
                base = url.resoudre(n.attributs["href"])
            except ValueError:
                pass
    base = base or url
    liens, vus, contenu = [], set(), []
    for n in elements:
        if n.balise != "a" or not n.attributs.get("href"):
            continue
        href = n.attributs["href"].strip()
        if href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        try:
            cible = base.resoudre(href)
        except ValueError:
            continue
        adresse = str(cible)
        if adresse in vus:
            continue
        vus.add(adresse)
        if str(cible.sans_fragment()) == str(url.sans_fragment()):
            genre = "ancre"
        elif cible.hote == url.hote:
            genre = "interne"
        else:
            genre = "externe"
        liens.append((" ".join(n.texte_contenu().split()) or adresse, href, adresse, genre))
        contenu.append(_dans_le_contenu(n))

    corps = next((n for n in elements if n.balise == "body"), dom)
    texte = " ".join(_texte_visible(corps).split())
    compte = lambda *balises: sum(1 for n in elements if n.balise in balises)
    return {
        "profil": {"caracteres": len(texte), "images": compte("img"),
                   "liens_externes": sum(1 for l in liens if l[3] == "externe"),
                   "liens_internes": sum(1 for l in liens if l[3] == "interne"),
                   "scripts": compte("script")},
        "proprietes": {"titre": titre, "auteur": meta("author", "dc.creator", "dcterms.creator"),
                       "mots_cles": meta("keywords", "news_keywords"),
                       "description": meta("description", "og:description"),
                       "date_creation": meta(*META_DATES)},
        "liens": liens,
        "contenu": contenu,   # pour chaque lien : True s'il est dans le texte de la page (pas dans un menu)
        "texte": texte,       # texte visible de la page
        "autres": {"styles": compte("style") + sum(1 for n in elements if n.balise == "link"
                                                   and "stylesheet" in n.attributs.get("rel", "").lower()),
                   "tableaux": compte("table"), "formulaires": compte("form"),
                   "titres": compte("h1", "h2", "h3")},
    }


def profil_page(page, url, reseau=None):
    """Caractéristiques d'une page affichée, pour la fenêtre « Analyse »."""
    c = caracteristiques_dom(page.dom, url, getattr(page, "base", None))
    p, q, a = c["profil"], c["proprietes"], c["autres"]
    adresse = str(url.sans_fragment())
    return [
        ("Titre", page.titre or q["titre"] or "—"),
        ("Adresse", str(url)),
        ("Auteur (meta)", q["auteur"] or "—"),
        ("Mots-clés (meta)", q["mots_cles"] or "—"),
        ("Date de création (meta)", q["date_creation"] or "—"),
        ("Description (meta)", (q["description"] or "—")[:120]),
        ("Nombre de caractères", "{:,}".format(p["caracteres"]).replace(",", " ")),
        ("Nombre de liens internes", p["liens_internes"]),
        ("Nombre de liens externes", p["liens_externes"]),
        ("Nombre d'images", p["images"]),
        ("Nombre de scripts", p["scripts"]),
        ("Nombre de feuilles de style", a["styles"]),
        ("Nombre de tableaux", a["tableaux"]),
        ("Nombre de formulaires", a["formulaires"]),
        ("Nombre de titres (h1-h3)", a["titres"]),
        ("Code HTTP", getattr(page, "statut", "—")),
        ("Type de nœud (réseau)", reseau.type_noeud(adresse) if reseau and adresse in reseau.noeuds else "—"),
    ]


def texte_visible(dom):
    """Texte lisible d'une page (sans scripts ni styles)."""
    corps = next((n for n in parcourir(dom) if isinstance(n, Element) and n.balise == "body"), dom)
    return " ".join(_texte_visible(corps).split())


def _texte_visible(noeud):
    morceaux = []
    for n in parcourir(noeud):
        if isinstance(n, Element):
            continue
        parent = n.parent
        if isinstance(parent, Element) and parent.balise in ("script", "style", "title"):
            continue
        morceaux.append(n.texte)
    return " ".join(morceaux)


def liens_page(page, url):
    """[(texte, adresse absolue, type)] avec type = interne / externe / ancre, sans doublons."""
    c = caracteristiques_dom(page.dom, url, getattr(page, "base", None))
    return [(texte, adresse, genre) for texte, _, adresse, genre in c["liens"]]


# ---------------------------------------------------------------------------
# Méta-recherche (HyWebMap utilisait le méta-chercheur Copernic, qui n'existe plus).
# Ici : Wikipédia, puis Mojeek, puis DuckDuckGo si un moteur ne répond pas. Jamais Google.
# ---------------------------------------------------------------------------

MOTEURS_META = (
    ("Wikipédia", "https://fr.wikipedia.org/w/index.php?fulltext=1&search="),
    ("Mojeek", "https://www.mojeek.com/search?q="),
    ("DuckDuckGo", "https://lite.duckduckgo.com/lite/?q="),
)


def meta_recherche(client, requete, nombre=3):
    """Les ``nombre`` premières pages trouvées pour ``requete`` : [(titre, adresse)].
    Si un moteur refuse ou ne donne rien (test anti-robot…), on passe au suivant."""
    derniere_erreur = None
    for nom, adresse in MOTEURS_META:
        try:
            reponse = client.charger(URL(adresse + pourcent_encoder(requete).replace("%20", "+")))
        except (ErreurReseau, ValueError, OSError) as erreur:
            derniere_erreur = erreur
            continue
        if reponse.statut >= 400:
            continue
        resultats = analyser_resultats(reponse.texte(), reponse.url)
        if resultats:
            return resultats[:nombre]
    if derniere_erreur is not None:
        raise ErreurReseau("Aucun moteur n'a répondu (%s)" % derniere_erreur)
    return []


def analyser_resultats(html, base):
    """Extrait les résultats d'une page de résultats Mojeek, Wikipédia ou DuckDuckGo."""
    hote = base.hote
    resultats, vus = [], set()
    for n in parcourir(analyser_html(html)):
        if not (isinstance(n, Element) and n.balise == "a" and n.attributs.get("href")):
            continue
        href = n.attributs["href"]
        classes = n.attributs.get("class", "").split()
        parent = n.parent if isinstance(n.parent, Element) else None
        if "mojeek" in hote:
            # Mojeek : <ul class="results-standard"><li><h2><a class="title" href="…">Titre</a></h2>
            if not ("title" in classes and parent is not None and parent.balise == "h2"):
                continue
        elif "wikipedia" in hote:
            # Wikipédia : <div class="mw-search-result-heading"><a href="/wiki/…" title="…">
            if not (parent is not None and "mw-search-result-heading" in parent.attributs.get("class", "")):
                continue
        elif "uddg=" in href:
            href = pourcent_decoder(href.split("uddg=", 1)[1].split("&", 1)[0])
        elif "result-link" not in classes and "result__a" not in classes:
            continue
        try:
            adresse = str(base.resoudre(href))
        except ValueError:
            continue
        domaine = adresse.split("/")[2] if adresse.count("/") >= 2 else ""
        if not adresse.startswith(("http://", "https://")) or "duckduckgo.com" in domaine or "mojeek.com" in domaine:
            continue
        if adresse not in vus:
            vus.add(adresse)
            resultats.append((" ".join(n.texte_contenu().split()) or adresse, adresse))
    return resultats
