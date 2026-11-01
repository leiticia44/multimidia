"""Agent Web et base de données de HyWebMap (§ 2.1 et 2.2 de l'article).

Saleh, Papy, Bouhaï, « HyWebMap : un outil d'agrégation, d'organisation et de
veille technologique pour le Web », ISKO 2001, Paris 8.

§ 2.1 — L'agent part d'une adresse choisie par le lecteur et explore le site
par phases (parcours en largeur) :
    phase 1 : il analyse la page de départ et répertorie tous ses liens ;
    phase 2 : il explore les pages trouvées et répertorie leurs liens ;
    phase 3 : il recommence avec la page suivante de la liste, etc.
Le nombre de pages croît en k^n (k liens par page, profondeur n) : l'agent est
donc paramétrable en PROFONDEUR (nombre de niveaux) et en LARGEUR (nombre de
liens suivis par page). Il détecte les liens internes et externes et ceux qui
sont rompus (obsolètes).

§ 2.2 — Le résultat est rangé dans une base de données relationnelle (SQLite,
inclus dans Python) dont les tables reprennent le modèle de l'article :
    noeud      les pages (nœuds) et leur type (racine, parent, fils, orphelin, externe)
    ancre      les liens <a> trouvés dans chaque page (texte et adresse)
    liaison    la relation liaison(Document-A, Document-B, Lien-L) et son type
    profil     nombre de caractères, d'images, de liens externes et internes, de scripts
    propriete  titre, date de création, mots-clés, auteur, description
"""

import hashlib
import os
import sqlite3
import threading
from collections import deque
from datetime import datetime

from .analyseur_html import analyser_html
from .reseau import ErreurReseau, URL
from .reseau_personnel import caracteristiques_dom

TYPES_HTML = ("text/html", "application/xhtml+xml", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS exploration (
    id INTEGER PRIMARY KEY, url_depart TEXT, date TEXT,
    profondeur INTEGER, largeur INTEGER, meme_site INTEGER, nb_pages INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS noeud (
    id INTEGER PRIMARY KEY, exploration INTEGER REFERENCES exploration(id) ON DELETE CASCADE,
    url TEXT, site TEXT, niveau INTEGER, statut INTEGER, explore INTEGER DEFAULT 0,
    type TEXT DEFAULT '', parent INTEGER, copie TEXT, date_analyse TEXT,
    UNIQUE(exploration, url));
CREATE TABLE IF NOT EXISTS ancre (
    id INTEGER PRIMARY KEY, noeud INTEGER REFERENCES noeud(id) ON DELETE CASCADE,
    texte TEXT, href TEXT, cible TEXT);
CREATE TABLE IF NOT EXISTS liaison (
    id INTEGER PRIMARY KEY, exploration INTEGER REFERENCES exploration(id) ON DELETE CASCADE,
    document_a INTEGER REFERENCES noeud(id), document_b INTEGER REFERENCES noeud(id),
    ancre INTEGER REFERENCES ancre(id), type TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS profil (
    noeud INTEGER PRIMARY KEY REFERENCES noeud(id) ON DELETE CASCADE,
    nb_caracteres INTEGER, nb_images INTEGER, nb_liens_externes INTEGER,
    nb_liens_internes INTEGER, nb_scripts INTEGER);
CREATE TABLE IF NOT EXISTS propriete (
    noeud INTEGER PRIMARY KEY REFERENCES noeud(id) ON DELETE CASCADE,
    titre TEXT, date_creation TEXT, mots_cles TEXT, auteur TEXT, description TEXT);
"""


def maintenant():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Base de données (§ 2.2)
# ---------------------------------------------------------------------------

class BaseHyWebMap:
    """Base relationnelle des sites analysés par l'agent (un fichier SQLite)."""

    def __init__(self, chemin):
        dossier = os.path.dirname(chemin)
        if dossier:
            os.makedirs(dossier, exist_ok=True)
        self.chemin = chemin
        self.verrou = threading.Lock()
        self.cnx = sqlite3.connect(chemin, check_same_thread=False)
        self.cnx.row_factory = sqlite3.Row
        self.cnx.execute("PRAGMA foreign_keys = ON")
        self.cnx.executescript(SCHEMA)
        self.cnx.commit()

    def fermer(self):
        self.cnx.close()

    def _ecrire(self, requete, valeurs=(), valider=True):
        with self.verrou:
            curseur = self.cnx.execute(requete, valeurs)
            if valider:
                self.cnx.commit()
            return curseur.lastrowid

    def valider(self):
        """Enregistre sur le disque les écritures en attente (une fois par page analysée :
        un enregistrement par lien serait très lent avec les pages de plus de 1 000 liens)."""
        with self.verrou:
            self.cnx.commit()

    def _lire(self, requete, valeurs=()):
        with self.verrou:
            return [dict(ligne) for ligne in self.cnx.execute(requete, valeurs).fetchall()]

    # -- écriture -----------------------------------------------------------
    def nouvelle_exploration(self, url, profondeur, largeur, meme_site):
        return self._ecrire("INSERT INTO exploration (url_depart, date, profondeur, largeur, meme_site) "
                            "VALUES (?, ?, ?, ?, ?)", (url, maintenant(), profondeur, largeur, int(meme_site)))

    def noeud(self, exploration, url, niveau, parent=None, valider=True):
        """Renvoie l'identifiant du nœud ``url`` (créé s'il n'existe pas encore)."""
        lignes = self._lire("SELECT id FROM noeud WHERE exploration = ? AND url = ?", (exploration, url))
        if lignes:
            return lignes[0]["id"]
        try:
            site = URL(url).hote if "://" in url else ""
        except ValueError:
            site = ""
        return self._ecrire("INSERT INTO noeud (exploration, url, site, niveau, parent) VALUES (?, ?, ?, ?, ?)",
                            (exploration, url, site, niveau, parent), valider)

    def maj_noeud(self, ident, valider=True, **champs):
        if champs:
            cles = ", ".join("%s = ?" % c for c in champs)
            self._ecrire("UPDATE noeud SET %s WHERE id = ?" % cles, tuple(champs.values()) + (ident,), valider)

    def ajouter_ancre(self, noeud, texte, href, cible, valider=True):
        return self._ecrire("INSERT INTO ancre (noeud, texte, href, cible) VALUES (?, ?, ?, ?)",
                            (noeud, texte, href, cible), valider)

    def ajouter_liaison(self, exploration, document_a, document_b, ancre, valider=True):
        return self._ecrire("INSERT INTO liaison (exploration, document_a, document_b, ancre) VALUES (?, ?, ?, ?)",
                            (exploration, document_a, document_b, ancre), valider)

    def enregistrer_profil(self, noeud, p):
        self._ecrire("INSERT OR REPLACE INTO profil VALUES (?, ?, ?, ?, ?, ?)",
                     (noeud, p["caracteres"], p["images"], p["liens_externes"], p["liens_internes"], p["scripts"]))

    def enregistrer_propriete(self, noeud, p):
        self._ecrire("INSERT OR REPLACE INTO propriete VALUES (?, ?, ?, ?, ?, ?)",
                     (noeud, p["titre"], p["date_creation"], p["mots_cles"], p["auteur"], p["description"]))

    def supprimer_exploration(self, exploration):
        self._ecrire("DELETE FROM exploration WHERE id = ?", (exploration,))

    # -- lecture ------------------------------------------------------------
    def explorations(self):
        return self._lire("SELECT * FROM exploration ORDER BY id DESC")

    def noeuds(self, exploration):
        return self._lire(
            "SELECT n.*, p.titre, p.auteur, p.mots_cles, p.date_creation, p.description, "
            "f.nb_caracteres, f.nb_images, f.nb_liens_externes, f.nb_liens_internes, f.nb_scripts "
            "FROM noeud n LEFT JOIN propriete p ON p.noeud = n.id LEFT JOIN profil f ON f.noeud = n.id "
            "WHERE n.exploration = ? ORDER BY n.niveau, n.id", (exploration,))

    def liaisons(self, exploration):
        return self._lire(
            "SELECT l.id, l.type, a.url AS de, b.url AS vers, c.texte AS texte "
            "FROM liaison l JOIN noeud a ON a.id = l.document_a JOIN noeud b ON b.id = l.document_b "
            "LEFT JOIN ancre c ON c.id = l.ancre WHERE l.exploration = ? ORDER BY l.id", (exploration,))

    def compter(self, exploration):
        """Nombre de nœuds de chaque type et de liens de chaque type."""
        noeuds = self._lire("SELECT type, COUNT(*) AS n FROM noeud WHERE exploration = ? GROUP BY type",
                            (exploration,))
        liens = self._lire("SELECT type, COUNT(*) AS n FROM liaison WHERE exploration = ? GROUP BY type",
                           (exploration,))
        return {l["type"]: l["n"] for l in noeuds}, {l["type"]: l["n"] for l in liens}

    # -- typologie (§ 2.5) ----------------------------------------------------
    def typer(self, exploration):
        """Calcule le type de chaque nœud puis de chaque lien de l'exploration."""
        exp = self._lire("SELECT url_depart FROM exploration WHERE id = ?", (exploration,))[0]
        depart = exp["url_depart"]
        site_depart = URL(depart).hote
        noeuds = {n["id"]: n for n in self._lire("SELECT * FROM noeud WHERE exploration = ?", (exploration,))}
        enfants = {}
        for n in noeuds.values():
            if n["parent"] is not None:
                enfants.setdefault(n["parent"], []).append(n["id"])
        liaisons = self._lire("SELECT * FROM liaison WHERE exploration = ?", (exploration,))
        relies = {l["document_a"] for l in liaisons} | {l["document_b"] for l in liaisons}
        types = {}
        for ident, n in noeuds.items():
            if n["url"] == depart:
                t = "racine"
            elif n["site"] != site_depart:
                t = "externe"
            elif ident not in relies:
                t = "orphelin"
            elif enfants.get(ident):
                t = "parent"
            else:
                t = "fils"
            types[ident] = t
        with self.verrou:
            self.cnx.executemany("UPDATE noeud SET type = ? WHERE id = ?", [(t, i) for i, t in types.items()])
            mises_a_jour = []
            for l in liaisons:
                a, b = noeuds[l["document_a"]], noeuds[l["document_b"]]
                mises_a_jour.append((type_lien(a, b, types[a["id"]], types[b["id"]]), l["id"]))
            self.cnx.executemany("UPDATE liaison SET type = ? WHERE id = ?", mises_a_jour)
            self.cnx.commit()


def est_rompu(statut):
    return statut is not None and (statut == 0 or statut >= 400)


def type_lien(a, b, type_a, type_b):
    """Typologie des liens explicites de HyWebMap (§ 2.5).

    a, b : lignes « noeud » de départ et d'arrivée ; type_a, type_b : leurs types.
    """
    if a["url"] == b["url"]:
        return "interne"                                   # ancre dans la même page (région)
    if est_rompu(b["statut"]):
        return "externe rompu" if a["site"] != b["site"] else "interne rompu"
    if a["site"] != b["site"]:
        return "externe"
    if b["parent"] != a["id"]:
        return "référence"                                 # lien libre « aller à » (retour, transversal)
    if type_a == "racine":
        return "ancêtre"
    if type_b == "fils":
        return "fils"
    return "parent"


# ---------------------------------------------------------------------------
# Agent Web (§ 2.1)
# ---------------------------------------------------------------------------

class AgentWeb:
    def __init__(self, client, base, dossier_copies=None):
        self.client = client
        self.base = base
        self.dossier_copies = dossier_copies     # « rapatrier les ressources » (§ 2.6)

    def explorer(self, depart, profondeur=1, largeur=10, meme_site=True, max_pages=60,
                 verifier_liens=True, rappel=lambda message: None, annule=lambda: False):
        """Explore le site à partir de ``depart`` et renvoie l'identifiant de l'exploration."""
        depart = str(URL(depart).sans_fragment())
        site = URL(depart).hote
        exploration = self.base.nouvelle_exploration(depart, profondeur, largeur, meme_site)
        racine = self.base.noeud(exploration, depart, 0)
        identifiants = {depart: racine}       # adresse -> identifiant du nœud (évite de relire la base)
        file = deque([(depart, racine, 0)])
        explores = set()
        a_verifier = {}

        while file and len(explores) < max_pages and not annule():
            adresse, ident, niveau = file.popleft()
            if adresse in explores:
                continue
            explores.add(adresse)
            rappel("Niveau %d — page %d : %s" % (niveau, len(explores), adresse))
            a_verifier.pop(adresse, None)
            try:
                reponse = self.client.charger(URL(adresse))
                statut = reponse.statut
            except (ErreurReseau, ValueError, OSError) as erreur:
                self.base.maj_noeud(ident, statut=0, explore=1, date_analyse=maintenant())
                rappel("Page injoignable : %s (%s)" % (adresse, erreur))
                continue
            self.base.maj_noeud(ident, statut=statut, explore=1, date_analyse=maintenant())
            if statut >= 400 or reponse.type_mime not in TYPES_HTML:
                continue

            texte = reponse.texte()
            if self.dossier_copies:
                self.base.maj_noeud(ident, copie=self._rapatrier(adresse, texte))
            dom = analyser_html(texte)
            finale = reponse.url
            car = caracteristiques_dom(dom, finale)
            self.base.enregistrer_profil(ident, car["profil"])
            self.base.enregistrer_propriete(ident, car["proprietes"])

            # Phase 1 : tous les liens de la page sont rangés dans la base (un seul enregistrement par page).
            suivis = 0
            for texte_lien, href, cible, genre in car["liens"]:
                id_ancre = self.base.ajouter_ancre(ident, texte_lien[:200], href, cible, valider=False)
                cible_page = cible.split("#")[0]
                if genre == "ancre":
                    self.base.ajouter_liaison(exploration, ident, ident, id_ancre, valider=False)
                    continue
                autre = identifiants.get(cible_page)
                if autre is None:
                    autre = identifiants[cible_page] = self.base.noeud(exploration, cible_page, niveau + 1, ident,
                                                                       valider=False)
                self.base.ajouter_liaison(exploration, ident, autre, id_ancre, valider=False)
                # Phases 2 et 3 : on suit les « largeur » premiers liens, jusqu'à la profondeur choisie.
                hors_site = URL(cible_page).hote != site
                if (niveau < profondeur and suivis < largeur and cible_page not in explores
                        and not (meme_site and hors_site)
                        and cible_page.startswith(("http://", "https://"))):
                    suivis += 1
                    file.append((cible_page, autre, niveau + 1))
                elif cible_page not in explores:
                    a_verifier[cible_page] = autre
            self.base.valider()

        # Liens non explorés : on vérifie seulement qu'ils existent encore (liens obsolètes).
        # Plusieurs vérifications en parallèle, avec un délai court : un site qui ne répond pas
        # ne doit pas bloquer l'agent.
        if verifier_liens and not annule():
            liste = [(a, i) for a, i in a_verifier.items()
                     if a not in explores and a.startswith(("http://", "https://"))][:max(30, max_pages * 2)]
            rappel("Vérification de %d lien(s) non exploré(s)…" % len(liste))
            codes = {}

            def verifier(lot):
                client = type(self.client)()
                client.delai = 6
                for adresse, ident in lot:
                    if annule():
                        return
                    codes[ident] = _code(client, adresse)

            fils = [threading.Thread(target=verifier, args=(liste[k::8],), daemon=True) for k in range(8)]
            for f in fils:
                f.start()
            for f in fils:
                f.join()
            for ident, code in codes.items():
                self.base.maj_noeud(ident, valider=False, statut=code)
            self.base.valider()

        self.base._ecrire("UPDATE exploration SET nb_pages = ? WHERE id = ?", (len(explores), exploration))
        self.base.typer(exploration)
        rappel("Exploration terminée : %d page(s) analysée(s)." % len(explores))
        return exploration

    def _rapatrier(self, adresse, texte):
        os.makedirs(self.dossier_copies, exist_ok=True)
        nom = hashlib.sha1(adresse.encode("utf-8")).hexdigest()[:16] + ".html"
        chemin = os.path.join(self.dossier_copies, nom)
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        return chemin


def _code(client, adresse):
    try:
        statut = client.charger(URL(adresse), methode="HEAD").statut
        if statut in (403, 405, 501):
            statut = client.charger(URL(adresse)).statut
        return statut
    except (ErreurReseau, ValueError, OSError):
        return 0
