"""Mise en page : transforme l'arbre DOM stylé en boîtes positionnées, puis en
une liste de commandes de dessin indépendante de l'interface graphique.

Modèle utilisé (simplifié par rapport à CSS 2.1) :
  * boîtes de bloc empilées verticalement (marges, bordures, remplissage,
    width / max-width / min-width, centrage par margin: auto) ;
  * contexte en ligne : découpage en mots, retour à la ligne automatique,
    alignement du texte, interligne, white-space: pre ;
  * tableaux avec calcul automatique de la largeur des colonnes et colspan ;
  * images, champs de formulaire, puces et numéros de liste.

La mesure du texte est déléguée à un objet « polices » (voir PolicesTk dans
interface.py ou PolicesFactices dans les tests) pour pouvoir tester sans écran.
"""

import re

from .analyseur_css import analyser_couleur, longueur
from .analyseur_html import Element, Texte

AFFICHAGES_BLOC = {"block", "list-item", "table", "table-row", "flex", "grid", "flow-root",
                   "table-row-group", "table-header-group", "table-footer-group",
                   "table-caption", "table-cell", "-webkit-box"}
_ESPACES = re.compile(r"[ \t\n\r\f]+")
CHAMPS_TEXTE = {"text", "search", "email", "url", "password", "tel", "number", "", None}


# ---------------------------------------------------------------------------
# Commandes de dessin
# ---------------------------------------------------------------------------

class CmdTexte:
    def __init__(self, x, y, texte, police, couleur, largeur=0, hauteur=0):
        self.x, self.y, self.texte, self.police, self.couleur = x, y, texte, police, couleur
        self.haut, self.bas = y, y + hauteur
        self.largeur = largeur

    def __repr__(self):
        return "CmdTexte(%d, %d, %r)" % (self.x, self.y, self.texte)


class CmdRect:
    def __init__(self, x1, y1, x2, y2, couleur, contour=None, epaisseur=1):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.couleur, self.contour, self.epaisseur = couleur, contour, epaisseur
        self.haut, self.bas = y1, y2


class CmdOvale(CmdRect):
    pass


class CmdLigne:
    def __init__(self, x1, y1, x2, y2, couleur, epaisseur=1):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.couleur, self.epaisseur = couleur, epaisseur
        self.haut, self.bas = min(y1, y2) - epaisseur, max(y1, y2) + epaisseur


class CmdImage:
    def __init__(self, x, y, image, largeur, hauteur):
        self.x, self.y, self.image = x, y, image
        self.largeur, self.hauteur = largeur, hauteur
        self.haut, self.bas = y, y + hauteur


class Zone:
    """Rectangle interactif : lien ou champ de formulaire."""

    def __init__(self, x1, y1, x2, y2, genre, noeud):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.genre = genre      # "lien" ou "champ"
        self.noeud = noeud

    def contient(self, x, y):
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2


# ---------------------------------------------------------------------------
# Contexte partagé pendant la mise en page
# ---------------------------------------------------------------------------

class Contexte:
    def __init__(self, polices, images=None, zoom=1.0, champ_actif=None):
        self.polices = polices
        self.images = images or {}     # url absolue -> objet avec .largeur/.hauteur
        self.zoom = zoom
        self.champ_actif = champ_actif
        self.ancres = {}               # id -> y
        self.url_images = {}           # noeud <img> -> url absolue (rempli par l'appelant)


def police_de(style, zoom=1.0):
    familles = [f.strip().strip("\"'").lower() for f in style["font-family"].split(",")]
    famille = "Times"
    for nom in familles:
        if "mono" in nom or nom in ("courier", "courier new", "consolas", "menlo", "monaco", "lucida console"):
            famille = "Courier"
            break
        if nom in ("serif", "times", "times new roman", "georgia", "garamond", "palatino", "cambria",
                   "linux libertine", "book antiqua") or nom.endswith(" serif") and "sans" not in nom:
            famille = "Times"
            break
        if nom in ("sans-serif", "arial", "helvetica", "verdana", "tahoma", "system-ui", "-apple-system",
                   "blinkmacsystemfont", "segoe ui", "roboto", "helvetica neue", "open sans", "ubuntu",
                   "lato", "noto sans", "trebuchet ms", "inter", "dejavu sans", "liberation sans") or "sans" in nom:
            famille = "Helvetica"
            break
    taille = max(1, int(round(float(style["font-size"][:-2]) * zoom)))
    decoration = style["text-decoration"].lower()
    return (famille, taille, style["font-weight"] == "bold", style["font-style"] == "italic",
            "underline" in decoration, "line-through" in decoration)


def _hauteur_ligne(style, ascent, descent, zoom):
    valeur = style["line-height"].strip().lower()
    naturelle = ascent + descent
    if valeur == "normal":
        return naturelle
    taille = float(style["font-size"][:-2])
    try:
        return max(naturelle * 0.6, float(valeur) * taille * zoom)
    except ValueError:
        pixels = longueur(valeur, taille, taille, None)
        return naturelle if pixels is None else max(naturelle * 0.6, pixels * zoom)


def est_cache(noeud):
    """Vrai pour les éléments invisibles (display: none, texte « lecteur d'écran »...)."""
    style = noeud.style
    if style.get("display") == "none" or style.get("visibility") in ("hidden", "collapse"):
        return True
    position = style.get("position", "static")
    if position in ("absolute", "fixed"):
        for cote in ("left", "top"):
            if longueur(style.get(cote), 16, 0, 0) < -500:
                return True
    if style.get("overflow", "").startswith("hidden") or "clip" in style:
        largeur = longueur(style.get("width"), 16, 0, 100)
        hauteur = longueur(style.get("height"), 16, 0, 100)
        if largeur <= 1 or hauteur <= 1:
            return True
    if "rect(0" in style.get("clip", "").replace(" ", "") or "inset(50%" in style.get("clip-path", ""):
        return True
    if isinstance(noeud, Element) and noeud.balise == "input" and noeud.attributs.get("type", "").lower() == "hidden":
        return True
    return False


def est_bloc(noeud):
    return isinstance(noeud, Element) and noeud.style.get("display") in AFFICHAGES_BLOC and not est_cache(noeud)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class LayoutDocument:
    def __init__(self, racine, contexte):
        self.noeud = racine
        self.contexte = contexte
        self.enfants = []
        self.x = self.y = 0
        self.largeur = self.hauteur = 0

    @property
    def x_contenu(self):
        return 0

    @property
    def y_contenu(self):
        return 0

    @property
    def largeur_contenu(self):
        return self.largeur

    def mise_en_page(self, largeur):
        self.largeur = largeur
        self.contexte.ancres = {}
        enfant = LayoutBloc([self.noeud], self, None, self.contexte)
        self.enfants = [enfant]
        enfant.mise_en_page()
        self.hauteur = enfant.y + enfant.hauteur + enfant.marge_bas

    def couleur_fond(self):
        for noeud in [self.noeud] + [e for e in self.noeud.enfants if isinstance(e, Element) and e.balise == "body"]:
            if "background-color" in noeud.style:
                return noeud.style["background-color"]
        return "#ffffff"

    def peindre(self):
        commandes, zones = [], []
        for enfant in self.enfants:
            enfant.peindre(commandes, zones)
        return commandes, zones


# ---------------------------------------------------------------------------
# Blocs
# ---------------------------------------------------------------------------

class Ligne:
    def __init__(self, y):
        self.y = y
        self.hauteur = 0
        self.ligne_de_base = 0
        self.elements = []


class Element_en_ligne:
    """Un mot, une image ou un champ placé sur une ligne."""
    __slots__ = ("x", "largeur", "ascent", "descent", "interligne", "genre", "contenu",
                 "police", "couleur", "lien", "fond", "noeud")

    def __init__(self, x, largeur, ascent, descent, interligne, genre, contenu=None, police=None,
                 couleur=None, lien=None, fond=None, noeud=None):
        self.x, self.largeur, self.ascent, self.descent = x, largeur, ascent, descent
        self.interligne, self.genre, self.contenu = interligne, genre, contenu
        self.police, self.couleur, self.lien, self.fond, self.noeud = police, couleur, lien, fond, noeud


class LayoutBloc:
    def __init__(self, noeuds, parent, precedent, contexte, anonyme=False):
        self.noeuds = noeuds
        self.noeud = None if anonyme else noeuds[0]
        self.parent = parent
        self.precedent = precedent
        self.contexte = contexte
        self.anonyme = anonyme
        self.style = parent.style if anonyme else noeuds[0].style
        self.enfants = []
        self.lignes = []
        self.x = self.y = self.largeur = self.hauteur = 0
        self.marge_haut = self.marge_bas = self.marge_gauche = self.marge_droite = 0
        self.remplissage = [0, 0, 0, 0]   # haut, droite, bas, gauche
        self.bordures = [0, 0, 0, 0]
        self.x_impose = None              # utilisé par les cellules de tableau
        self.largeur_imposee = None

    # -- géométrie -------------------------------------------------------------

    @property
    def x_contenu(self):
        return self.x + self.bordures[3] + self.remplissage[3]

    @property
    def y_contenu(self):
        return self.y + self.bordures[0] + self.remplissage[0]

    @property
    def largeur_contenu(self):
        return max(0, self.largeur - self.bordures[1] - self.bordures[3] - self.remplissage[1] - self.remplissage[3])

    def px(self, valeur, reference=0.0, defaut=0.0):
        zoom = self.contexte.zoom
        taille = float(self.style["font-size"][:-2])
        resultat = longueur(valeur, taille, reference / zoom, None)
        return defaut if resultat is None else resultat * zoom

    # -- calcul ------------------------------------------------------------

    def _boite(self):
        if self.anonyme:
            return
        style = self.style
        disponible = self.parent.largeur_contenu if self.largeur_imposee is None else self.largeur_imposee
        self.marge_haut = self.px(style.get("margin-top"), disponible)
        self.marge_bas = self.px(style.get("margin-bottom"), disponible)
        self.marge_gauche = self.px(style.get("margin-left"), disponible)
        self.marge_droite = self.px(style.get("margin-right"), disponible)
        self.remplissage = [max(0, self.px(style.get("padding-" + c), disponible)) for c in ("top", "right", "bottom", "left")]
        self.bordures = []
        for cote in ("top", "right", "bottom", "left"):
            if style.get("border-%s-style" % cote, "none") in ("none", "hidden"):
                self.bordures.append(0)
            else:
                epaisseur = style.get("border-%s-width" % cote, "medium")
                epaisseur = {"thin": "1px", "medium": "3px", "thick": "5px"}.get(epaisseur, epaisseur)
                self.bordures.append(max(0, self.px(epaisseur, disponible)))

    def mise_en_page(self):
        self._boite()
        style = self.style
        disponible = self.parent.largeur_contenu
        if self.largeur_imposee is not None:
            self.x = self.x_impose
            self.largeur = self.largeur_imposee
        else:
            horizontal = self.remplissage[1] + self.remplissage[3] + self.bordures[1] + self.bordures[3]
            boite_bordure = style.get("box-sizing") == "border-box"

            def vers_bordure(valeur):
                if valeur is None:
                    return None
                return valeur if boite_bordure else valeur + horizontal

            largeur_css = vers_bordure(self._longueur_definie("width", disponible))
            maximum = vers_bordure(self._longueur_definie("max-width", disponible))
            minimum = vers_bordure(self._longueur_definie("min-width", disponible))
            auto = disponible - self.marge_gauche - self.marge_droite
            largeur = largeur_css if largeur_css is not None and not self.anonyme else auto
            if maximum is not None:
                largeur = min(largeur, maximum)
            if minimum is not None:
                largeur = max(largeur, minimum)
            largeur = max(0, largeur)
            self.largeur = largeur
            gauche_auto = style.get("margin-left", "").strip() == "auto"
            droite_auto = style.get("margin-right", "").strip() == "auto"
            libre = disponible - largeur - self.marge_gauche - self.marge_droite
            if libre > 0 and not self.anonyme:
                if gauche_auto and droite_auto:
                    self.marge_gauche += libre / 2
                elif gauche_auto:
                    self.marge_gauche += libre
            self.x = self.parent.x_contenu + self.marge_gauche

        if self.precedent is not None:
            self.y = self.precedent.y + self.precedent.hauteur + max(self.precedent.marge_bas, self.marge_haut)
        else:
            self.y = self.parent.y_contenu + self.marge_haut

        if self.noeud is not None:
            ident = self.noeud.attributs.get("id")
            if ident and ident not in self.contexte.ancres:
                self.contexte.ancres[ident] = self.y

        hauteur_contenu = self._disposer_enfants()
        hauteur_css = self._longueur_definie("height", 0)
        if hauteur_css is not None and hauteur_css > hauteur_contenu and not self.anonyme and "%" not in self.style.get("height", ""):
            if self.style.get("box-sizing") == "border-box":
                hauteur_css -= self.remplissage[0] + self.remplissage[2] + self.bordures[0] + self.bordures[2]
            hauteur_contenu = max(hauteur_contenu, min(hauteur_css, 4000))
        self.hauteur = hauteur_contenu + self.remplissage[0] + self.remplissage[2] + self.bordures[0] + self.bordures[2]

    def _longueur_definie(self, propriete, reference):
        valeur = self.style.get(propriete)
        if valeur is None or valeur.strip().lower() in ("auto", "none", "fit-content", "max-content", "min-content", "inherit", "initial"):
            return None
        if "%" in valeur and reference <= 0:
            return None
        return self.px(valeur, reference, None)

    def _mode(self):
        if self.anonyme:
            return "en_ligne"
        for enfant in self.noeud.enfants:
            if est_bloc(enfant):
                return "bloc"
        return "en_ligne"

    def _disposer_enfants(self):
        if self._mode() == "bloc":
            return self._disposer_blocs(self.noeud.enfants)
        self._disposer_en_ligne()
        if not self.lignes:
            return 0
        derniere = self.lignes[-1]
        return derniere.y + derniere.hauteur - self.y_contenu

    def _disposer_blocs(self, noeuds):
        groupe = []
        precedent = None

        def vider_groupe():
            nonlocal precedent, groupe
            if any(not (isinstance(n, Texte) and n.texte.isspace()) for n in groupe):
                bloc = LayoutBloc(groupe, self, precedent, self.contexte, anonyme=True)
                self.enfants.append(bloc)
                bloc.mise_en_page()
                precedent = bloc
            groupe = []

        for enfant in noeuds:
            if isinstance(enfant, Element) and est_cache(enfant):
                continue
            if est_bloc(enfant):
                vider_groupe()
                affichage = enfant.style["display"]
                classe = LayoutTableau if affichage == "table" else LayoutBloc
                bloc = classe([enfant], self, precedent, self.contexte)
                self.enfants.append(bloc)
                bloc.mise_en_page()
                precedent = bloc
            else:
                groupe.append(enfant)
        vider_groupe()
        if precedent is None:
            return 0
        return precedent.y + precedent.hauteur + precedent.marge_bas - self.y_contenu

    # -- contexte en ligne -------------------------------------------------------

    def _disposer_en_ligne(self):
        self.lignes = []
        self.ligne = Ligne(self.y_contenu)
        self.curseur_x = 0
        self.espace_en_attente = False
        self.hauteur_vide = 0
        for noeud in self.noeuds if self.anonyme else self.noeud.enfants:
            self._recurser(noeud, None, None)
        self._nouvelle_ligne()
        del self.ligne

    def _recurser(self, noeud, lien, fond):
        if isinstance(noeud, Texte):
            self._texte(noeud, lien, fond)
            return
        if est_cache(noeud):
            return
        balise = noeud.balise
        ident = noeud.attributs.get("id") or (noeud.attributs.get("name") if balise == "a" else None)
        if ident and ident not in self.contexte.ancres:
            self.contexte.ancres[ident] = self.ligne.y
        if balise == "br":
            self._nouvelle_ligne(forcee=True)
            return
        if balise == "img":
            self._image(noeud, lien)
            return
        if balise in ("input", "button", "select", "textarea"):
            self._champ(noeud)
            return
        if balise == "a" and "href" in noeud.attributs:
            lien = noeud
        if "background-color" in noeud.style:
            fond = noeud.style["background-color"]
        bloc = est_bloc(noeud)
        if bloc:
            self._nouvelle_ligne()
        for enfant in noeud.enfants:
            self._recurser(enfant, lien, fond)
        if bloc:
            self._nouvelle_ligne()

    def _texte(self, noeud, lien, fond):
        style = noeud.style
        police = police_de(style, self.contexte.zoom)
        couleur = style["color"]
        texte = noeud.texte
        transformation = style.get("text-transform", "none")
        if transformation == "uppercase":
            texte = texte.upper()
        elif transformation == "lowercase":
            texte = texte.lower()
        elif transformation == "capitalize":
            texte = re.sub(r"\b(\w)", lambda m: m.group(1).upper(), texte)
        texte = texte.replace("­", "")
        blancs = style["white-space"]
        if blancs in ("pre", "pre-wrap", "pre-line", "break-spaces"):
            for index, ligne in enumerate(texte.split("\n")):
                if index > 0:
                    self._nouvelle_ligne(forcee=True, police=police, style=style)
                if blancs == "pre-line":
                    ligne = " ".join(_ESPACES.split(ligne.strip()))
                ligne = ligne.expandtabs(8)
                if blancs == "pre":
                    if ligne:
                        self._mot(ligne, police, couleur, lien, fond, style, coupure=False)
                else:
                    for mot in ligne.split(" "):
                        if mot:
                            self._mot(mot, police, couleur, lien, fond, style)
                        self.espace_en_attente = True
            return
        if texte[:1] in " \t\n\r\f":
            self.espace_en_attente = True
        coupure = blancs != "nowrap"
        for mot in _ESPACES.split(texte):
            if mot:
                self._mot(mot, police, couleur, lien, fond, style, coupure)
                self.espace_en_attente = True
        if texte[-1:] not in (" ", "\t", "\n", "\r", "\f"):
            self.espace_en_attente = False

    def _mot(self, mot, police, couleur, lien, fond, style, coupure=True):
        polices = self.contexte.polices
        largeur_dispo = self.largeur_contenu
        largeur = polices.mesurer(police, mot)
        espace = polices.mesurer(police, " ") if self.espace_en_attente and self.ligne.elements else 0
        if coupure and self.ligne.elements and self.curseur_x + espace + largeur > largeur_dispo:
            self._nouvelle_ligne()
            espace = 0
        if coupure and largeur > largeur_dispo > 20 and len(mot) > 1:
            # Mot plus long que la ligne (URL...) : on le coupe.
            debut = 0
            while debut < len(mot):
                fin = len(mot)
                while fin > debut + 1 and self.curseur_x + polices.mesurer(police, mot[debut:fin]) > largeur_dispo:
                    fin = debut + max(1, (fin - debut) * 3 // 4)
                morceau = mot[debut:fin]
                self._placer_mot(morceau, polices.mesurer(police, morceau), police, couleur, lien, fond, style)
                debut = fin
                if debut < len(mot):
                    self._nouvelle_ligne()
            return
        self.curseur_x += espace
        if espace and self.ligne.elements:
            precedent = self.ligne.elements[-1]
            if precedent.genre == "texte" and precedent.police == police and precedent.couleur == couleur \
                    and precedent.fond == fond and precedent.lien is lien:
                # Même style : on rattache l'espace au mot précédent (soulignement continu).
                precedent.contenu += " "
                precedent.largeur += espace
            elif fond is not None and precedent.fond == fond:
                precedent.largeur += espace
        self._placer_mot(mot, largeur, police, couleur, lien, fond, style)

    def _placer_mot(self, mot, largeur, police, couleur, lien, fond, style):
        ascent, descent = self.contexte.polices.metriques(police)
        element = Element_en_ligne(self.curseur_x, largeur, ascent, descent,
                                   _hauteur_ligne(style, ascent, descent, self.contexte.zoom),
                                   "texte", mot.replace(" ", " "), police, couleur, lien, fond)
        self.ligne.elements.append(element)
        self.curseur_x += largeur
        self.espace_en_attente = False

    def _placer_boite(self, largeur, hauteur, genre, contenu, noeud, lien=None, espace_police=None, descent=0):
        polices = self.contexte.polices
        espace = 0
        if self.espace_en_attente and self.ligne.elements and espace_police is not None:
            espace = polices.mesurer(espace_police, " ")
        if self.ligne.elements and self.curseur_x + espace + largeur > self.largeur_contenu:
            self._nouvelle_ligne()
            espace = 0
        self.curseur_x += espace
        element = Element_en_ligne(self.curseur_x, largeur, hauteur - descent, descent, hauteur, genre, contenu,
                                   lien=lien, noeud=noeud)
        self.ligne.elements.append(element)
        self.curseur_x += largeur
        self.espace_en_attente = False

    def _image(self, noeud, lien):
        url = self.contexte.url_images.get(noeud)
        image = self.contexte.images.get(url) if url else None
        zoom = self.contexte.zoom

        def dimension(nom):
            valeur = noeud.style.get(nom) or noeud.attributs.get(nom)
            if valeur is None:
                return None
            valeur = valeur.strip()
            if valeur.isdigit():
                valeur += "px"
            if "%" in valeur:
                return None
            resultat = longueur(valeur, 16, 0, None)
            return None if resultat is None or resultat <= 0 else resultat * zoom

        largeur, hauteur = dimension("width"), dimension("height")
        if image is not None:
            naturelle_l, naturelle_h = image.largeur * zoom, image.hauteur * zoom
            if largeur is None and hauteur is None:
                largeur, hauteur = naturelle_l, naturelle_h
            elif largeur is None:
                largeur = naturelle_l * hauteur / max(1, naturelle_h)
            elif hauteur is None:
                hauteur = naturelle_h * largeur / max(1, naturelle_l)
            if largeur > self.largeur_contenu > 0:
                hauteur = hauteur * self.largeur_contenu / largeur
                largeur = self.largeur_contenu
            self._placer_boite(largeur, hauteur, "image", image, noeud, lien, police_de(noeud.style, zoom))
            return
        alt = noeud.attributs.get("alt", "").strip()
        if alt:
            style = dict(noeud.style)
            style["font-style"] = "italic"
            police = police_de(style, zoom)
            self._mot("[" + alt + "]" if len(alt) < 60 else "[image]", police, "#707070", lien, None, style)
        elif largeur and hauteur and largeur > 4 and hauteur > 4:
            self._placer_boite(min(largeur, self.largeur_contenu), hauteur, "image_absente", None, noeud, lien)

    def _champ(self, noeud):
        balise = noeud.balise
        style = noeud.style
        police = police_de(style, self.contexte.zoom)
        polices = self.contexte.polices
        ascent, descent = polices.metriques(police)
        hauteur_texte = ascent + descent
        genre_input = noeud.attributs.get("type", "text").lower() if balise == "input" else None
        largeur_css = longueur(style.get("width"), float(style["font-size"][:-2]), self.largeur_contenu / self.contexte.zoom, None)
        if balise == "input" and genre_input in ("checkbox", "radio"):
            cote = 13 * self.contexte.zoom
            self._placer_boite(cote + 4, cote, "champ", None, noeud, espace_police=police, descent=2 * self.contexte.zoom)
            return
        if balise == "button" or (balise == "input" and genre_input in ("submit", "button", "reset", "image")):
            libelle = texte_bouton(noeud)
            largeur = polices.mesurer(police, libelle) + 18 * self.contexte.zoom
            hauteur = hauteur_texte + 8 * self.contexte.zoom
        elif balise == "select":
            options = [o.texte_contenu().strip() for o in options_de(noeud)] or [""]
            largeur = max(polices.mesurer(police, o) for o in options) + 28 * self.contexte.zoom
            hauteur = hauteur_texte + 8 * self.contexte.zoom
        elif balise == "textarea":
            colonnes = int(noeud.attributs.get("cols", "40")) if noeud.attributs.get("cols", "").isdigit() else 40
            rangees = int(noeud.attributs.get("rows", "3")) if noeud.attributs.get("rows", "").isdigit() else 3
            largeur = colonnes * polices.mesurer(police, "m") * 0.62
            hauteur = rangees * hauteur_texte + 8 * self.contexte.zoom
        else:
            taille = noeud.attributs.get("size", "")
            caracteres = int(taille) if taille.isdigit() else 22
            largeur = caracteres * polices.mesurer(police, "n") + 10 * self.contexte.zoom
            hauteur = hauteur_texte + 8 * self.contexte.zoom
        if largeur_css is not None and largeur_css > 0:
            largeur = largeur_css * self.contexte.zoom
        largeur = min(largeur, max(40, self.largeur_contenu))
        # La ligne de base du champ est celle de son texte (comme dans les vrais navigateurs).
        if balise == "textarea":
            descent = hauteur - (4 * self.contexte.zoom + ascent)
        else:
            descent = (hauteur - hauteur_texte) / 2 + descent
        self._placer_boite(largeur, hauteur, "champ", None, noeud, espace_police=police, descent=descent)

    def _nouvelle_ligne(self, forcee=False, police=None, style=None):
        ligne = self.ligne
        if not ligne.elements:
            if forcee:
                style = style or self.style
                police = police or police_de(style, self.contexte.zoom)
                ascent, descent = self.contexte.polices.metriques(police)
                ligne.hauteur = _hauteur_ligne(style, ascent, descent, self.contexte.zoom)
                self.lignes.append(ligne)
                self.ligne = Ligne(ligne.y + ligne.hauteur)
            return
        ascent = max(e.ascent for e in ligne.elements)
        descent = max(e.descent for e in ligne.elements)
        interligne = max(max(e.interligne for e in ligne.elements), ascent + descent)
        extra = interligne - ascent - descent
        ligne.ligne_de_base = ligne.y + extra / 2 + ascent
        ligne.hauteur = interligne

        alignement = self.style.get("text-align", "left").strip().lower()
        largeur_utilisee = ligne.elements[-1].x + ligne.elements[-1].largeur
        decalage = 0
        if alignement in ("center", "-webkit-center"):
            decalage = (self.largeur_contenu - largeur_utilisee) / 2
        elif alignement in ("right", "end", "-webkit-right"):
            decalage = self.largeur_contenu - largeur_utilisee
        if decalage > 0:
            for element in ligne.elements:
                element.x += decalage

        self.lignes.append(ligne)
        self.ligne = Ligne(ligne.y + ligne.hauteur)
        self.curseur_x = 0
        self.espace_en_attente = False

    # -- dessin ------------------------------------------------------------

    def peindre(self, commandes, zones):
        if not self.anonyme:
            self._peindre_boite(commandes)
            if self.style.get("display") == "list-item":
                self._peindre_puce(commandes)
        for ligne in self.lignes:
            self._peindre_ligne(ligne, commandes, zones)
        for enfant in self.enfants:
            enfant.peindre(commandes, zones)

    def _peindre_boite(self, commandes):
        x1, y1 = self.x, self.y
        x2, y2 = self.x + self.largeur, self.y + self.hauteur
        if "background-color" in self.style and self.noeud.balise not in ("html", "body"):
            commandes.append(CmdRect(x1, y1, x2, y2, self.style["background-color"]))
        haut, droite, bas, gauche = self.bordures
        if any(self.bordures):
            couleur_texte = self.style["color"]

            for epaisseur, cote, rectangle in (
                    (haut, "top", (x1, y1, x2, y1 + haut)),
                    (bas, "bottom", (x1, y2 - bas, x2, y2)),
                    (gauche, "left", (x1, y1, x1 + gauche, y2)),
                    (droite, "right", (x2 - droite, y1, x2, y2))):
                if not epaisseur:
                    continue
                valeur = self.style.get("border-%s-color" % cote)
                couleur = (analyser_couleur(valeur, couleur_texte) if valeur else None) or couleur_texte
                if couleur != "transparent":
                    commandes.append(CmdRect(*rectangle, couleur))

    def _peindre_puce(self, commandes):
        genre = self.style.get("list-style-type", "disc").strip().lower()
        if genre == "none":
            return
        police = police_de(self.style, self.contexte.zoom)
        if genre in ("disc", "circle", "square"):
            marqueur = {"disc": "•", "circle": "◦", "square": "▪"}[genre]
        else:
            numero = self._numero_dans_liste()
            if genre in ("lower-alpha", "lower-latin"):
                marqueur = _alphabetique(numero).lower() + "."
            elif genre in ("upper-alpha", "upper-latin"):
                marqueur = _alphabetique(numero) + "."
            elif genre == "lower-roman":
                marqueur = _romain(numero).lower() + "."
            elif genre == "upper-roman":
                marqueur = _romain(numero) + "."
            else:
                marqueur = "%d." % numero
        largeur = self.contexte.polices.mesurer(police, marqueur)
        ascent, descent = self.contexte.polices.metriques(police)
        base = self.premiere_ligne_de_base()
        y = (base - ascent) if base is not None else self.y_contenu
        commandes.append(CmdTexte(self.x_contenu - largeur - 6 * self.contexte.zoom, y, marqueur, police,
                                  self.style["color"], largeur, ascent + descent))

    def _numero_dans_liste(self):
        parent = self.noeud.parent
        debut = 1
        if parent is not None and parent.attributs.get("start", "").lstrip("-").isdigit():
            debut = int(parent.attributs["start"])
        numero = debut - 1
        for frere in parent.enfants if parent is not None else []:
            if isinstance(frere, Element) and frere.style.get("display") == "list-item":
                if frere.attributs.get("value", "").isdigit():
                    numero = int(frere.attributs["value"]) - 1
                numero += 1
            if frere is self.noeud:
                break
        return numero

    def premiere_ligne_de_base(self):
        if self.lignes:
            for ligne in self.lignes:
                if ligne.elements:
                    return ligne.ligne_de_base
        for enfant in self.enfants:
            base = enfant.premiere_ligne_de_base()
            if base is not None:
                return base
        return None

    def _peindre_ligne(self, ligne, commandes, zones):
        x_base = self.x_contenu
        for element in ligne.elements:
            x = x_base + element.x
            haut = ligne.ligne_de_base - element.ascent
            if element.genre == "texte":
                if element.fond:
                    commandes.append(CmdRect(x, haut, x + element.largeur, haut + element.ascent + element.descent, element.fond))
                commandes.append(CmdTexte(x, haut, element.contenu, element.police, element.couleur,
                                          element.largeur, element.ascent + element.descent))
            elif element.genre == "image":
                commandes.append(CmdImage(x, haut, element.contenu, element.largeur, element.ascent))
            elif element.genre == "image_absente":
                commandes.append(CmdRect(x, haut, x + element.largeur, haut + element.ascent, "#f0f0f0", "#c0c0c0"))
            elif element.genre == "champ":
                self._peindre_champ(element, x, haut, commandes)
                zones.append(Zone(x, haut, x + element.largeur, haut + element.ascent + element.descent, "champ", element.noeud))
                continue
            if element.lien is not None:
                zones.append(Zone(x, haut, x + element.largeur, haut + element.ascent + element.descent, "lien", element.lien))

    def _peindre_champ(self, element, x, y, commandes):
        noeud = element.noeud
        polices = self.contexte.polices
        police = police_de(noeud.style, self.contexte.zoom)
        ascent, descent = polices.metriques(police)
        largeur, hauteur = element.largeur, element.ascent + element.descent
        x2, y2 = x + largeur, y + hauteur
        actif = noeud is self.contexte.champ_actif
        balise = noeud.balise
        genre = noeud.attributs.get("type", "text").lower() if balise == "input" else None
        couleur_texte = noeud.style.get("color", "#000000")
        y_texte = y + (hauteur - ascent - descent) / 2

        if genre in ("checkbox", "radio"):
            cote = hauteur
            classe = CmdOvale if genre == "radio" else CmdRect
            commandes.append(classe(x + 2, y, x + 2 + cote, y + cote, "#ffffff", "#767676"))
            if "checked" in noeud.attributs:
                if genre == "radio":
                    marge = cote * 0.28
                    commandes.append(CmdOvale(x + 2 + marge, y + marge, x + 2 + cote - marge, y + cote - marge, "#0060df"))
                else:
                    commandes.append(CmdLigne(x + 4, y + cote * 0.5, x + 2 + cote * 0.4, y + cote - 3, "#0060df", 2))
                    commandes.append(CmdLigne(x + 2 + cote * 0.4, y + cote - 3, x + cote, y + 3, "#0060df", 2))
            return
        if balise == "button" or genre in ("submit", "button", "reset", "image"):
            fond = noeud.style.get("background-color", "#e9e9ed")
            commandes.append(CmdRect(x, y, x2, y2, fond, "#8f8f9d"))
            libelle = texte_bouton(noeud)
            largeur_texte = polices.mesurer(police, libelle)
            commandes.append(CmdTexte(x + (largeur - largeur_texte) / 2, y_texte, libelle, police, couleur_texte,
                                      largeur_texte, ascent + descent))
            return
        commandes.append(CmdRect(x, y, x2, y2, noeud.style.get("background-color", "#ffffff"),
                                 "#0060df" if actif else "#8f8f9d", 2 if actif else 1))
        marge = 5 * self.contexte.zoom
        if balise == "select":
            choisie = option_choisie(noeud)
            texte = choisie.texte_contenu().strip() if choisie is not None else ""
            commandes.append(CmdTexte(x + marge, y_texte, texte, police, couleur_texte, 0, ascent + descent))
            commandes.append(CmdTexte(x2 - 16 * self.contexte.zoom, y_texte, "▾", police, couleur_texte, 0, ascent + descent))
            return
        valeur = valeur_champ(noeud)
        if balise == "textarea":
            lignes = valeur.split("\n")
            ligne_y = y + 4
            for ligne in lignes:
                if ligne_y + ascent + descent > y2:
                    break
                commandes.append(CmdTexte(x + marge, ligne_y, _tronquer(polices, police, ligne, largeur - 2 * marge),
                                          police, couleur_texte, 0, ascent + descent))
                ligne_y += ascent + descent
            if actif:
                derniere = lignes[-1]
                curseur_x = x + marge + polices.mesurer(police, derniere)
                curseur_y = y + 4 + (len(lignes) - 1) * (ascent + descent)
                commandes.append(CmdLigne(curseur_x, curseur_y, curseur_x, curseur_y + ascent + descent, "#000000"))
            return
        if genre == "password":
            valeur = "•" * len(valeur)
        affiche = valeur
        couleur = couleur_texte
        if not valeur and noeud.attributs.get("placeholder"):
            affiche, couleur = noeud.attributs["placeholder"], "#8a8a8a"
        disponible = largeur - 2 * marge
        if actif and valeur:
            # On montre la fin du texte quand il dépasse (comme un vrai champ).
            while affiche and polices.mesurer(police, affiche) > disponible:
                affiche = affiche[1:]
        else:
            affiche = _tronquer(polices, police, affiche, disponible)
        commandes.append(CmdTexte(x + marge, y_texte, affiche, police, couleur, 0, ascent + descent))
        if actif:
            curseur_x = x + marge + (polices.mesurer(police, affiche) if valeur else 0)
            commandes.append(CmdLigne(curseur_x, y_texte, curseur_x, y_texte + ascent + descent, "#000000"))


# ---------------------------------------------------------------------------
# Tableaux
# ---------------------------------------------------------------------------

class LayoutTableau(LayoutBloc):
    """Tableau : colonnes calculées à partir de la largeur min / préférée des cellules."""

    def _rangees(self):
        rangees, avant = [], []
        for enfant in self.noeud.enfants:
            if not isinstance(enfant, Element) or est_cache(enfant):
                continue
            affichage = enfant.style["display"]
            if affichage == "table-row":
                rangees.append(enfant)
            elif affichage in ("table-row-group", "table-header-group", "table-footer-group") or enfant.balise in ("tbody", "thead", "tfoot"):
                rangees.extend(r for r in enfant.enfants if isinstance(r, Element) and not est_cache(r)
                               and r.style["display"] == "table-row")
            elif enfant.balise == "caption" or affichage == "table-caption":
                avant.append(enfant)
        return avant, rangees

    def mise_en_page(self):
        # On calcule d'abord la largeur « naturelle » pour pouvoir rétrécir le tableau.
        self.avant, self.rangees = self._rangees()
        self.cellules = [[c for c in r.enfants if isinstance(c, Element) and not est_cache(c)] for r in self.rangees]
        super().mise_en_page()

    def _disposer_enfants(self):
        zoom = self.contexte.zoom
        espacement = 2 * zoom
        espacement_attr = self.noeud.attributs.get("cellspacing", "").strip()
        if espacement_attr.isdigit():
            espacement = int(espacement_attr) * zoom
        if self.style.get("border-collapse") == "collapse":
            espacement = 0
        nb_colonnes = max([sum(_colspan(c) for c in rangee) for rangee in self.cellules] + [0])
        disponible = self.largeur_contenu - espacement * (nb_colonnes + 1)
        minimums = [0.0] * nb_colonnes
        preferees = [0.0] * nb_colonnes
        fixees = [None] * nb_colonnes
        for rangee in self.cellules:
            colonne = 0
            for cellule in rangee:
                etendue = _colspan(cellule)
                if etendue == 1 and colonne < nb_colonnes:
                    mini, pref = mesures_intrinseques(cellule, self.contexte)
                    minimums[colonne] = max(minimums[colonne], mini)
                    preferees[colonne] = max(preferees[colonne], pref)
                    largeur_css = cellule.style.get("width")
                    if largeur_css and largeur_css.strip() not in ("auto",):
                        valeur = longueur(largeur_css, 16, disponible / zoom, None)
                        if valeur is not None and valeur > 0:
                            fixees[colonne] = max(fixees[colonne] or 0, valeur * zoom)
                colonne += etendue
        for index in range(nb_colonnes):
            if fixees[index] is not None:
                preferees[index] = max(fixees[index], minimums[index])
            preferees[index] = max(preferees[index], minimums[index])

        a_largeur_explicite = self._longueur_definie("width", self.parent.largeur_contenu) is not None
        largeurs = _repartir(minimums, preferees, disponible, etirer=a_largeur_explicite)
        if not a_largeur_explicite and nb_colonnes:
            utilisee = sum(largeurs) + espacement * (nb_colonnes + 1) + self.remplissage[1] + self.remplissage[3] + self.bordures[1] + self.bordures[3]
            if utilisee < self.largeur:
                libre = self.largeur - utilisee
                self.largeur = utilisee
                if self.style.get("margin-left", "").strip() == "auto" and self.style.get("margin-right", "").strip() == "auto":
                    self.x += libre / 2
                    self.marge_gauche += libre / 2

        precedent = None
        y = self.y_contenu
        for legende in self.avant:
            bloc = LayoutBloc([legende], self, precedent, self.contexte)
            self.enfants.append(bloc)
            bloc.mise_en_page()
            precedent = bloc
            y = bloc.y + bloc.hauteur + bloc.marge_bas
        y += espacement
        for rangee, cellules in zip(self.rangees, self.cellules):
            x = self.x_contenu + espacement
            colonne = 0
            blocs = []
            for cellule in cellules:
                etendue = _colspan(cellule)
                largeur = sum(largeurs[colonne:colonne + etendue]) + espacement * (etendue - 1)
                colonne += etendue
                bloc = CelluleTableau([cellule], self, None, self.contexte)
                bloc.x_impose, bloc.largeur_imposee = x, max(0, largeur)
                bloc.y_impose = y
                bloc.mise_en_page()
                blocs.append(bloc)
                x += largeur + espacement
            hauteur = max([b.hauteur for b in blocs] + [0])
            hauteur_css = longueur(rangee.style.get("height"), 16, 0, 0) * zoom
            hauteur = max(hauteur, hauteur_css)
            if "background-color" in rangee.style:
                self.enfants.append(FondRangee(self.x_contenu, y, self.x_contenu + self.largeur_contenu, y + hauteur,
                                               rangee.style["background-color"]))
            for bloc in blocs:
                bloc.etirer(hauteur)
                self.enfants.append(bloc)
            if rangee.attributs.get("id"):
                self.contexte.ancres.setdefault(rangee.attributs["id"], y)
            y += hauteur + espacement
        return y - self.y_contenu


class FondRangee:
    def __init__(self, x1, y1, x2, y2, couleur):
        self.commande = CmdRect(x1, y1, x2, y2, couleur)

    def peindre(self, commandes, zones):
        commandes.append(self.commande)

    def premiere_ligne_de_base(self):
        return None


class CelluleTableau(LayoutBloc):
    y_impose = 0

    def mise_en_page(self):
        super().mise_en_page()

    def _boite(self):
        super()._boite()
        self.marge_haut = self.marge_bas = self.marge_gauche = self.marge_droite = 0

    def _disposer_enfants(self):
        self.y = self.y_impose
        return super()._disposer_enfants()

    def etirer(self, hauteur):
        """Agrandit la cellule à la hauteur de la rangée (et gère vertical-align)."""
        surplus = hauteur - self.hauteur
        if surplus <= 0:
            return
        alignement = self.style.get("vertical-align", "middle").strip().lower()
        if self.noeud is not None and "valign" in self.noeud.attributs:
            alignement = self.noeud.attributs["valign"].lower()
        if alignement in ("middle", "center"):
            self._decaler(surplus / 2)
        elif alignement == "bottom":
            self._decaler(surplus)
        self.hauteur = hauteur

    def _decaler(self, dy):
        def decaler(bloc):
            for ligne in bloc.lignes:
                ligne.y += dy
                ligne.ligne_de_base += dy
            for enfant in bloc.enfants:
                if isinstance(enfant, FondRangee):
                    enfant.commande.y1 += dy
                    enfant.commande.y2 += dy
                    enfant.commande.haut += dy
                    enfant.commande.bas += dy
                    continue
                if enfant is not bloc:
                    enfant.y += dy
                    decaler(enfant)
        decaler(self)


def _colspan(cellule):
    valeur = cellule.attributs.get("colspan", "1").strip()
    return max(1, min(100, int(valeur))) if valeur.isdigit() else 1


def _repartir(minimums, preferees, disponible, etirer=False):
    total_min, total_pref = sum(minimums), sum(preferees)
    if not minimums:
        return []
    if total_pref <= disponible:
        if etirer and total_pref > 0:
            facteur = disponible / total_pref
            return [p * facteur for p in preferees]
        return list(preferees)
    if total_min >= disponible:
        if total_min == 0:
            return [disponible / len(minimums)] * len(minimums)
        return [m * disponible / total_min for m in minimums]
    surplus = disponible - total_min
    ecarts = [p - m for p, m in zip(preferees, minimums)]
    total_ecart = sum(ecarts) or 1
    return [m + surplus * e / total_ecart for m, e in zip(minimums, ecarts)]


def mesures_intrinseques(noeud, contexte, _cache=None):
    """Renvoie (largeur minimale, largeur préférée) approximatives d'un nœud."""
    polices = contexte.polices
    zoom = contexte.zoom
    if isinstance(noeud, Texte):
        police = police_de(noeud.style, zoom)
        texte = noeud.texte
        if noeud.style["white-space"] in ("pre", "nowrap"):
            lignes = texte.split("\n")
            largeur = max(polices.mesurer(police, ligne) for ligne in lignes)
            return largeur, largeur
        mots = [m for m in _ESPACES.split(texte) if m]
        if not mots:
            return 0, 0
        minimum = max(polices.mesurer(police, m) for m in mots)
        return minimum, polices.mesurer(police, " ".join(mots))
    if est_cache(noeud):
        return 0, 0
    style = noeud.style
    taille = float(style["font-size"][:-2])
    horizontal = 0
    for propriete in ("padding-left", "padding-right", "margin-left", "margin-right"):
        horizontal += max(0, longueur(style.get(propriete), taille, 0, 0)) * zoom
    for cote in ("left", "right"):
        if style.get("border-%s-style" % cote, "none") not in ("none", "hidden"):
            horizontal += longueur(style.get("border-%s-width" % cote, "1px"), taille, 0, 1) * zoom
    largeur_css = style.get("width")
    if largeur_css and "%" not in largeur_css and noeud.balise not in ("td", "th"):
        valeur = longueur(largeur_css, taille, 0, None)
        if valeur is not None and valeur > 0:
            return valeur * zoom + horizontal, valeur * zoom + horizontal
    if noeud.balise == "img":
        url = contexte.url_images.get(noeud)
        image = contexte.images.get(url) if url else None
        largeur = None
        if noeud.attributs.get("width", "").isdigit():
            largeur = int(noeud.attributs["width"]) * zoom
        elif image is not None:
            largeur = image.largeur * zoom
        if largeur is None:
            alt = noeud.attributs.get("alt", "")
            largeur = polices.mesurer(police_de(style, zoom), "[" + alt + "]") if alt else 0
        return largeur, largeur
    if noeud.balise in ("input", "button", "select", "textarea"):
        police = police_de(style, zoom)
        if noeud.balise == "button" or noeud.attributs.get("type", "").lower() in ("submit", "button", "reset"):
            largeur = polices.mesurer(police, texte_bouton(noeud)) + 18 * zoom
        elif noeud.attributs.get("type", "").lower() in ("checkbox", "radio"):
            largeur = 17 * zoom
        else:
            largeur = 22 * polices.mesurer(police, "n") + 10 * zoom
        return largeur, largeur
    minimum = 0
    preferee = 0
    ligne = 0
    for enfant in noeud.enfants:
        mini, pref = mesures_intrinseques(enfant, contexte)
        minimum = max(minimum, mini)
        if est_bloc(enfant) or (isinstance(enfant, Element) and enfant.balise == "br"):
            preferee = max(preferee, ligne, pref)
            ligne = 0
        else:
            ligne += pref
    preferee = max(preferee, ligne)
    if style.get("white-space") == "nowrap":
        minimum = max(minimum, preferee)
    return minimum + horizontal, preferee + horizontal


# ---------------------------------------------------------------------------
# Utilitaires formulaires
# ---------------------------------------------------------------------------

def texte_bouton(noeud):
    if noeud.balise == "button":
        texte = " ".join(noeud.texte_contenu().split())
        return texte or "Bouton"
    genre = noeud.attributs.get("type", "").lower()
    if "value" in noeud.attributs:
        return noeud.attributs["value"]
    return {"submit": "Envoyer", "reset": "Réinitialiser", "image": noeud.attributs.get("alt", "Envoyer")}.get(genre, "")


def options_de(select):
    resultat = []
    pile = list(reversed(select.enfants))
    while pile:
        noeud = pile.pop()
        if isinstance(noeud, Element):
            if noeud.balise == "option":
                resultat.append(noeud)
            else:
                pile.extend(reversed(noeud.enfants))
    return resultat


def option_choisie(select):
    options = options_de(select)
    for option in options:
        if "selected" in option.attributs:
            return option
    return options[0] if options else None


def valeur_champ(noeud):
    if noeud.balise == "textarea":
        if "_valeur" not in noeud.attributs:
            noeud.attributs["_valeur"] = noeud.texte_contenu()
        return noeud.attributs["_valeur"]
    return noeud.attributs.get("value", "")


def _tronquer(polices, police, texte, largeur):
    if polices.mesurer(police, texte) <= largeur:
        return texte
    while texte and polices.mesurer(police, texte + "…") > largeur:
        texte = texte[:-1]
    return texte + "…" if texte else ""


def _alphabetique(nombre):
    lettres = ""
    while nombre > 0:
        nombre, reste = divmod(nombre - 1, 26)
        lettres = chr(65 + reste) + lettres
    return lettres or "A"


def _romain(nombre):
    valeurs = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
               (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    resultat = ""
    for valeur, symbole in valeurs:
        while nombre >= valeur:
            resultat += symbole
            nombre -= valeur
    return resultat or "0"
