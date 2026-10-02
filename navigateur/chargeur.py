"""Chargement complet d'une page : document, feuilles de style et images.

Ce module ne dépend pas de l'interface graphique : il peut tourner dans un
fil d'exécution secondaire pour ne pas bloquer la fenêtre.
"""

import os
import re

from . import pages_internes
from .analyseur_css import FEUILLE_PAR_DEFAUT, FeuilleDeStyle, calculer_styles
from .analyseur_html import Element, Texte, analyser_html, parcourir
from .reseau import ErreurReseau, URL, pourcent_decoder

MAX_FEUILLES = 15
MAX_IMAGES = 80
TAILLE_MAX_IMAGE = 4 * 1024 * 1024
TYPES_AFFICHABLES = ("text/html", "application/xhtml+xml", "")
TYPES_TEXTE = ("text/plain", "text/css", "text/csv", "text/markdown", "application/json",
               "application/javascript", "text/javascript", "application/xml", "text/xml")
TYPES_IMAGE = ("image/png", "image/gif", "image/x-portable-pixmap", "image/x-portable-graymap")
DOSSIER_TELECHARGEMENTS = os.path.join(os.path.expanduser("~"), "Téléchargements")

_feuille_defaut = None


def feuille_par_defaut():
    global _feuille_defaut
    if _feuille_defaut is None:
        _feuille_defaut = FeuilleDeStyle().ajouter_texte(FEUILLE_PAR_DEFAUT)
    return _feuille_defaut


class PageChargee:
    def __init__(self, url, dom, feuilles, images, titre, statut=200):
        self.url = url              # URL finale (après redirections)
        self.dom = dom
        self.feuilles = feuilles
        self.images = images        # url (str) -> bytes
        self.titre = titre
        self.statut = statut
        self.url_images = {}        # nœud <img> -> url (str)


def format_image(octets):
    if octets.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if octets[:2] in (b"P5", b"P6"):
        return "ppm"
    return None


def charger_page(client, url, methode="GET", corps=None, referent=None, stockage=None, annule=lambda: False):
    """Charge ``url`` (objet URL) et renvoie une PageChargee prête à mettre en page."""
    if url.schema == "about":
        html = pages_internes.generer(url.chemin, stockage)
        return construire_page(client, url, html, annule)
    if url.schema == "view-source":
        cible = URL(url.chemin)
        reponse = client.charger(cible)
        return construire_page(client, url, pages_internes.source(str(cible), reponse.texte()), annule, ressources=False)

    reponse = client.charger(url, methode, corps, referent=referent)
    mime = reponse.type_mime
    finale = reponse.url
    if url.fragment and not finale.fragment:
        finale.fragment = url.fragment
    if mime in TYPES_AFFICHABLES or mime.endswith("+xml") and "html" in mime:
        page = construire_page(client, finale, reponse.texte(), annule)
    elif mime.startswith("text/") or mime in TYPES_TEXTE:
        nom = finale.chemin.rsplit("/", 1)[-1] or str(finale)
        page = construire_page(client, finale, pages_internes.texte_brut(nom, reponse.texte()), annule, ressources=False)
    elif mime in TYPES_IMAGE or format_image(reponse.corps):
        page = construire_page(client, finale, pages_internes.image(str(finale)), annule, ressources=False)
        page.images[str(finale.sans_fragment())] = reponse.corps
        for noeud in parcourir(page.dom):
            if isinstance(noeud, Element) and noeud.balise == "img":
                page.url_images[noeud] = str(finale.sans_fragment())
    else:
        chemin = _enregistrer(finale, reponse)
        page = construire_page(client, finale, pages_internes.telechargement(str(finale), chemin, len(reponse.corps)), annule, ressources=False)
    page.statut = reponse.statut
    return page


def _enregistrer(url, reponse):
    nom = pourcent_decoder(url.chemin.split("?")[0].rsplit("/", 1)[-1]) or "telechargement"
    disposition = reponse.entetes.get("content-disposition", "")
    trouve = re.search(r'filename="?([^";]+)"?', disposition)
    if trouve:
        nom = trouve.group(1)
    nom = re.sub(r"[\\/:*?\"<>|]", "_", nom).strip() or "telechargement"
    os.makedirs(DOSSIER_TELECHARGEMENTS, exist_ok=True)
    chemin = os.path.join(DOSSIER_TELECHARGEMENTS, nom)
    base, extension = os.path.splitext(chemin)
    compteur = 1
    while os.path.exists(chemin):
        chemin = "%s (%d)%s" % (base, compteur, extension)
        compteur += 1
    with open(chemin, "wb") as fichier:
        fichier.write(reponse.corps)
    return chemin


def construire_page(client, url, html, annule, ressources=True):
    dom = analyser_html(html)
    base = url
    noeuds = parcourir(dom)
    for noeud in noeuds:
        if isinstance(noeud, Element) and noeud.balise == "base" and noeud.attributs.get("href"):
            try:
                base = url.resoudre(noeud.attributs["href"])
            except ValueError:
                pass
            break

    feuilles = [feuille_par_defaut()]
    auteur = FeuilleDeStyle()
    nb_feuilles = 0
    titre = ""
    for noeud in noeuds:
        if not isinstance(noeud, Element):
            continue
        if noeud.balise == "title" and not titre:
            titre = " ".join(noeud.texte_contenu().split())
        elif noeud.balise == "style":
            media = noeud.attributs.get("media", "")
            if "print" not in media.lower() or "screen" in media.lower():
                texte = "".join(e.texte for e in noeud.enfants if isinstance(e, Texte))
                auteur.ajouter_texte(texte)
                if ressources:
                    nb_feuilles += _imports(client, url, auteur, annule)
        elif (noeud.balise == "link" and ressources and nb_feuilles < MAX_FEUILLES
              and "stylesheet" in noeud.attributs.get("rel", "").lower().split()
              and "alternate" not in noeud.attributs.get("rel", "").lower()
              and noeud.attributs.get("href")):
            media = noeud.attributs.get("media", "").lower()
            if media and "screen" not in media and "all" not in media:
                continue
            if annule():
                break
            try:
                cible = base.resoudre(noeud.attributs["href"])
                reponse = client.charger(cible, referent=url)
                if reponse.statut == 200:
                    auteur.ajouter_texte(reponse.texte())
                    nb_feuilles += 1 + _imports(client, cible, auteur, annule)
            except (ErreurReseau, ValueError):
                pass
    if auteur.regles:
        feuilles.append(auteur)

    calculer_styles(dom, feuilles)

    images = {}
    page = PageChargee(url, dom, feuilles, images, titre)
    if ressources:
        for noeud in noeuds:
            if len(images) >= MAX_IMAGES or annule():
                break
            if not (isinstance(noeud, Element) and noeud.balise in ("img", "input")):
                continue
            if noeud.balise == "input" and noeud.attributs.get("type", "").lower() != "image":
                continue
            if noeud.style.get("display") == "none":
                continue
            source = _source_image(noeud)
            if not source:
                continue
            try:
                cible = base.resoudre(source)
            except ValueError:
                continue
            cle = str(cible.sans_fragment())
            page.url_images[noeud] = cle
            if cle in images:
                continue
            extension = cible.chemin.split("?")[0].lower().rsplit(".", 1)[-1]
            if extension in ("jpg", "jpeg", "webp", "svg", "avif", "ico", "bmp"):
                continue  # formats non décodables sans bibliothèque externe
            try:
                reponse = client.charger(cible, referent=url)
            except (ErreurReseau, ValueError):
                continue
            if reponse.statut == 200 and len(reponse.corps) <= TAILLE_MAX_IMAGE and format_image(reponse.corps):
                images[cle] = reponse.corps
    page.base = base
    return page


def _source_image(noeud):
    """Choisit la source d'une image, en préférant un PNG/GIF dans srcset."""
    candidats = []
    for attribut in ("src", "data-src"):
        if noeud.attributs.get(attribut, "").strip():
            candidats.append(noeud.attributs[attribut].strip())
    for attribut in ("srcset", "data-srcset"):
        for morceau in noeud.attributs.get(attribut, "").split(","):
            morceau = morceau.strip().split(" ")[0]
            if morceau:
                candidats.append(morceau)
    for candidat in candidats:
        if re.search(r"\.(png|gif)(\?|$)", candidat.lower()) or candidat.startswith("data:image/png") or candidat.startswith("data:image/gif"):
            return candidat
    return candidats[0] if candidats else None


def _imports(client, url, feuille, annule):
    """Charge les @import trouvés dans la feuille (un seul niveau)."""
    compte = 0
    imports, feuille.imports = feuille.imports, []
    for adresse in imports[:5]:
        if annule():
            break
        try:
            reponse = client.charger(url.resoudre(adresse), referent=url)
            if reponse.statut == 200:
                feuille.ajouter_texte(reponse.texte())
                compte += 1
        except (ErreurReseau, ValueError):
            pass
    feuille.imports = []
    return compte
