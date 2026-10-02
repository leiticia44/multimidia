"""Moteur CSS écrit à la main : analyse des feuilles de style, sélecteurs,
cascade (spécificité + ordre), héritage et calcul des valeurs.
"""

import re

from .analyseur_html import Element, ancetre

LARGEUR_ECRAN_SUPPOSEE = 1000  # pour évaluer les @media (min-width / max-width)

# ---------------------------------------------------------------------------
# Feuille de style par défaut du navigateur
# ---------------------------------------------------------------------------

FEUILLE_PAR_DEFAUT = """
html, body, div, p, ul, ol, li, dl, dt, dd, h1, h2, h3, h4, h5, h6, pre, blockquote,
form, header, footer, nav, section, article, aside, main, figure, figcaption, hr,
address, center, fieldset, legend, details, summary, menu, dir, hgroup, noscript,
search, dialog[open] { display: block; }
table { display: table; }
caption { display: table-caption; }
thead { display: table-header-group; }
tbody { display: table-row-group; }
tfoot { display: table-footer-group; }
head, script, style, title, meta, link, template, base, datalist, param, dialog,
input[type=hidden], [hidden], area, map, noembed, noframes, iframe, object, embed,
video, audio, canvas, svg, picture source { display: none; }
li { display: list-item; }
tr { display: table-row; }
td, th { display: table-cell; padding: 2px 4px; }
th { font-weight: bold; text-align: center; }
body { margin: 8px; }
p, dl, blockquote, figure, pre, ul, ol, menu, fieldset { margin-top: 1em; margin-bottom: 1em; }
h1 { font-size: 2em; margin-top: .67em; margin-bottom: .67em; font-weight: bold; }
h2 { font-size: 1.5em; margin-top: .83em; margin-bottom: .83em; font-weight: bold; }
h3 { font-size: 1.17em; margin-top: 1em; margin-bottom: 1em; font-weight: bold; }
h4 { margin-top: 1.33em; margin-bottom: 1.33em; font-weight: bold; }
h5 { font-size: .83em; margin-top: 1.67em; margin-bottom: 1.67em; font-weight: bold; }
h6 { font-size: .67em; margin-top: 2.33em; margin-bottom: 2.33em; font-weight: bold; }
ul, ol, menu, dir { padding-left: 40px; }
ul ul, ol ul, ul ol, ol ol { margin-top: 0; margin-bottom: 0; }
ol { list-style-type: decimal; }
ul ul { list-style-type: circle; }
dd { margin-left: 40px; }
blockquote, figure { margin-left: 40px; margin-right: 40px; }
fieldset { border: 1px solid #c0c0c0; padding: 6px 10px; margin-left: 2px; margin-right: 2px; }
legend { font-weight: bold; }
a { color: #0645ad; text-decoration: underline; }
b, strong, dt { font-weight: bold; }
i, em, cite, var, dfn, address { font-style: italic; }
u, ins { text-decoration: underline; }
s, strike, del { text-decoration: line-through; }
small { font-size: smaller; }
big { font-size: larger; }
sub, sup { font-size: smaller; }
mark { background-color: yellow; color: black; }
pre, code, kbd, samp, tt, textarea { font-family: monospace; }
pre, textarea { white-space: pre; }
center { text-align: center; }
hr { border-top: 1px solid #a0a0a0; margin-top: .5em; margin-bottom: .5em; }
input, button, select, textarea { font-size: 13px; font-family: sans-serif; }
caption { text-align: center; }
"""

PROPRIETES_HERITEES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "font-family": "serif",
    "color": "black",
    "text-align": "left",
    "white-space": "normal",
    "text-decoration": "none",
    "list-style-type": "disc",
    "line-height": "normal",
    "visibility": "visible",
    "text-transform": "none",
}

TAILLES_MOTS_CLES = {
    "xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18,
    "x-large": 24, "xx-large": 32, "xxx-large": 48,
}

COULEURS_NOMMEES = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000",
    "olive": "#808000", "lime": "#00ff00", "aqua": "#00ffff", "cyan": "#00ffff",
    "teal": "#008080", "navy": "#000080", "fuchsia": "#ff00ff", "magenta": "#ff00ff",
    "pink": "#ffc0cb", "brown": "#a52a2a", "gold": "#ffd700", "beige": "#f5f5dc",
    "ivory": "#fffff0", "khaki": "#f0e68c", "lavender": "#e6e6fa", "salmon": "#fa8072",
    "coral": "#ff7f50", "tomato": "#ff6347", "crimson": "#dc143c", "indigo": "#4b0082",
    "violet": "#ee82ee", "orchid": "#da70d6", "plum": "#dda0dd", "tan": "#d2b48c",
    "chocolate": "#d2691e", "sienna": "#a0522d", "darkred": "#8b0000",
    "darkgreen": "#006400", "darkblue": "#00008b", "darkgray": "#a9a9a9",
    "darkgrey": "#a9a9a9", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
    "lightblue": "#add8e6", "lightgreen": "#90ee90", "lightyellow": "#ffffe0",
    "dimgray": "#696969", "dimgrey": "#696969", "gainsboro": "#dcdcdc",
    "whitesmoke": "#f5f5f5", "skyblue": "#87ceeb", "steelblue": "#4682b4",
    "royalblue": "#4169e1", "dodgerblue": "#1e90ff", "slategray": "#708090",
    "forestgreen": "#228b22", "seagreen": "#2e8b57", "darkorange": "#ff8c00",
    "firebrick": "#b22222", "midnightblue": "#191970", "aliceblue": "#f0f8ff",
    "ghostwhite": "#f8f8ff", "honeydew": "#f0fff0", "linen": "#faf0e6",
    "mintcream": "#f5fffa", "snow": "#fffafa", "wheat": "#f5deb3", "turquoise": "#40e0d0",
    "darkslategray": "#2f4f4f", "lightcoral": "#f08080", "cornflowerblue": "#6495ed",
    "rebeccapurple": "#663399", "transparent": "transparent",
}


# ---------------------------------------------------------------------------
# Valeurs
# ---------------------------------------------------------------------------

def analyser_couleur(valeur, actuelle="#000000"):
    """Convertit une couleur CSS en "#rrggbb" (ou "transparent"), sinon None."""
    valeur = valeur.strip().lower()
    if valeur in COULEURS_NOMMEES:
        return COULEURS_NOMMEES[valeur]
    if valeur == "currentcolor":
        return actuelle
    if valeur.startswith("#"):
        hexa = valeur[1:]
        if not all(c in "0123456789abcdef" for c in hexa):
            return None
        if len(hexa) in (3, 4):
            if len(hexa) == 4 and hexa[3] == "0":
                return "transparent"
            return "#" + "".join(c * 2 for c in hexa[:3])
        if len(hexa) in (6, 8):
            if len(hexa) == 8 and hexa[6:] == "00":
                return "transparent"
            return "#" + hexa[:6]
        return None
    correspondance = re.match(r"(rgba?|hsla?)\(([^)]*)\)", valeur)
    if correspondance:
        fonction = correspondance.group(1)
        morceaux = [m for m in re.split(r"[\s,/]+", correspondance.group(2).strip()) if m]
        if len(morceaux) < 3:
            return None
        try:
            if len(morceaux) > 3:
                alpha = morceaux[3]
                alpha = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
                if alpha == 0:
                    return "transparent"
            if fonction.startswith("rgb"):
                canaux = []
                for morceau in morceaux[:3]:
                    nombre = float(morceau[:-1]) * 2.55 if morceau.endswith("%") else float(morceau)
                    canaux.append(max(0, min(255, int(round(nombre)))))
            else:
                teinte = float(morceaux[0].replace("deg", "")) % 360 / 360
                saturation = float(morceaux[1].rstrip("%")) / 100
                luminosite = float(morceaux[2].rstrip("%")) / 100
                canaux = _hsl_vers_rgb(teinte, saturation, luminosite)
        except ValueError:
            return None
        return "#%02x%02x%02x" % tuple(canaux)
    return None


def _hsl_vers_rgb(h, s, l):
    def composante(p, q, t):
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p
    if s == 0:
        return [int(l * 255)] * 3
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return [max(0, min(255, int(round(composante(p, q, h + d) * 255)))) for d in (1 / 3, 0, -1 / 3)]


_LONGUEUR = re.compile(r"^(-?[0-9]*\.?[0-9]+)(px|em|rem|%|pt|pc|in|cm|mm|ex|ch|vw|vh|vmin|vmax)?$")


def longueur(valeur, taille_police=16.0, reference=0.0, defaut=0.0):
    """Convertit une longueur CSS en pixels (float). ``reference`` sert aux %."""
    if valeur is None:
        return defaut
    valeur = valeur.strip().lower()
    if valeur in ("auto", "none", "normal", "", "inherit", "initial", "unset"):
        return defaut
    if valeur.startswith(("calc(", "min(", "max(", "clamp(", "var(")):
        return _evaluer_fonction(valeur, taille_police, reference, defaut)
    correspondance = _LONGUEUR.match(valeur)
    if not correspondance:
        return defaut
    nombre = float(correspondance.group(1))
    unite = correspondance.group(2) or "px"
    if unite == "px":
        return nombre
    if unite == "em":
        return nombre * taille_police
    if unite == "rem":
        return nombre * 16
    if unite in ("ex", "ch"):
        return nombre * taille_police / 2
    if unite == "%":
        return nombre * reference / 100
    if unite == "pt":
        return nombre * 4 / 3
    if unite == "pc":
        return nombre * 16
    if unite == "in":
        return nombre * 96
    if unite == "cm":
        return nombre * 96 / 2.54
    if unite == "mm":
        return nombre * 96 / 25.4
    if unite in ("vw", "vmin"):
        return nombre * LARGEUR_ECRAN_SUPPOSEE / 100
    if unite in ("vh", "vmax"):
        return nombre * 800 / 100
    return defaut


def _evaluer_fonction(valeur, taille_police, reference, defaut):
    """Approximation de calc()/min()/max()/clamp() : on prend la première longueur lisible."""
    if valeur.startswith("calc("):
        interieur = valeur[5:-1]
        termes = re.findall(r"([+-]?)\s*(-?[0-9]*\.?[0-9]+(?:px|em|rem|%|pt|vw|vh)?)", interieur)
        if " * " in interieur or " / " in interieur or not termes:
            return defaut
        total = 0.0
        for signe, terme in termes:
            total += (-1 if signe == "-" else 1) * longueur(terme, taille_police, reference)
        return total
    for terme in re.findall(r"-?[0-9]*\.?[0-9]+(?:px|em|rem|%|pt|vw|vh)?", valeur):
        return longueur(terme, taille_police, reference, defaut)
    return defaut


# ---------------------------------------------------------------------------
# Sélecteurs
# ---------------------------------------------------------------------------

class SelecteurSimple:
    """Sélecteur composé : balise#id.classe[attr=val]:pseudo"""

    def __init__(self, balise, ident, classes, attributs, pseudos):
        self.balise = balise
        self.ident = ident
        self.classes = classes
        self.attributs = attributs
        self.pseudos = pseudos
        self.priorite = (1 if ident else 0,
                         len(classes) + len(attributs) + len(pseudos),
                         1 if balise else 0)

    def correspond(self, noeud):
        if not isinstance(noeud, Element):
            return False
        if self.balise and self.balise != noeud.balise:
            return False
        if self.ident and noeud.attributs.get("id") != self.ident:
            return False
        if self.classes:
            classes_noeud = noeud.classes
            if any(c not in classes_noeud for c in self.classes):
                return False
        for nom, operateur, attendu in self.attributs:
            if nom not in noeud.attributs:
                return False
            reel = noeud.attributs[nom]
            if operateur == "=":
                egal = reel.lower() == attendu.lower() if nom == "type" else reel == attendu
                if not egal:
                    return False
            if operateur == "~=" and attendu not in reel.split():
                return False
            if operateur == "^=" and not reel.startswith(attendu):
                return False
            if operateur == "$=" and not reel.endswith(attendu):
                return False
            if operateur == "*=" and attendu not in reel:
                return False
            if operateur == "|=" and not (reel == attendu or reel.startswith(attendu + "-")):
                return False
        for pseudo in self.pseudos:
            if not _pseudo_correspond(pseudo, noeud):
                return False
        return True


def _pseudo_correspond(pseudo, noeud):
    if pseudo in ("link", "any-link"):
        return noeud.balise == "a" and "href" in noeud.attributs
    if pseudo == "root":
        return noeud.balise == "html"
    if pseudo in ("first-child", "last-child", "only-child"):
        freres = [e for e in noeud.parent.enfants if isinstance(e, Element)] if noeud.parent else [noeud]
        if pseudo == "first-child":
            return freres[0] is noeud
        if pseudo == "last-child":
            return freres[-1] is noeud
        return len(freres) == 1
    if pseudo == "checked":
        return "checked" in noeud.attributs or "selected" in noeud.attributs
    if pseudo == "disabled":
        return "disabled" in noeud.attributs
    if pseudo == "empty":
        return not noeud.enfants
    if pseudo.startswith("not(") and pseudo.endswith(")"):
        interieur = analyser_selecteur_compose(pseudo[4:-1].strip())
        return interieur is not None and not interieur.correspond(noeud)
    # :hover, :focus, :visited, ::before ... ne correspondent jamais (pas d'état / pas de pseudo-éléments)
    return False


_COMPOSE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9-]*|\*)?"
    r"((?:#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?)*)$"
)
_MORCEAU = re.compile(r"#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?")


def analyser_selecteur_compose(texte):
    correspondance = _COMPOSE.match(texte)
    if not correspondance or not texte:
        return None
    balise = correspondance.group(1)
    balise = None if balise in (None, "*") else balise.lower()
    ident, classes, attributs, pseudos = None, [], [], []
    for morceau in _MORCEAU.findall(correspondance.group(2) or ""):
        if morceau.startswith("#"):
            ident = morceau[1:]
        elif morceau.startswith("."):
            classes.append(morceau[1:])
        elif morceau.startswith("["):
            interieur = morceau[1:-1].strip()
            attr = re.match(r"([\w-]+)\s*([~^$*|]?=)?\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\]]*))?\s*(i|s)?$", interieur)
            if not attr:
                return None
            valeur = next((g for g in attr.group(3, 4, 5) if g is not None), "")
            attributs.append((attr.group(1).lower(), attr.group(2), valeur))
        elif morceau.startswith("::") or morceau[1:] in ("before", "after", "first-line", "first-letter"):
            pseudos.append("::pseudo-element")
        else:
            pseudos.append(morceau[1:].lower())
    return SelecteurSimple(balise, ident, classes, attributs, pseudos)


class Selecteur:
    """Sélecteur complexe : suite de sélecteurs composés reliés par des combinateurs."""

    def __init__(self, parties):
        self.parties = parties  # [(combinateur, SelecteurSimple)] ; combinateur du 1er = None
        a = b = c = 0
        for _, simple in parties:
            a += simple.priorite[0]
            b += simple.priorite[1]
            c += simple.priorite[2]
        self.priorite = (a, b, c)
        self.cible = parties[-1][1]

    def correspond(self, noeud):
        return self._correspond_depuis(len(self.parties) - 1, noeud)

    def _correspond_depuis(self, index, noeud):
        combinateur, simple = self.parties[index]
        if not simple.correspond(noeud):
            return False
        if index == 0:
            return True
        lien = self.parties[index][0]
        if lien == ">":
            return noeud.parent is not None and self._correspond_depuis(index - 1, noeud.parent)
        if lien in ("+", "~"):
            precedents = _freres_precedents(noeud)
            if lien == "+":
                return bool(precedents) and self._correspond_depuis(index - 1, precedents[-1])
            return any(self._correspond_depuis(index - 1, frere) for frere in precedents)
        parent = noeud.parent
        while parent is not None:
            if self._correspond_depuis(index - 1, parent):
                return True
            parent = parent.parent
        return False


def _freres_precedents(noeud):
    if noeud.parent is None:
        return []
    freres = []
    for frere in noeud.parent.enfants:
        if frere is noeud:
            break
        if isinstance(frere, Element):
            freres.append(frere)
    return freres


def analyser_selecteur(texte):
    texte = re.sub(r"\s*([>+~])\s*", r" \1 ", texte.strip())
    morceaux = _decouper_hors_parentheses(texte)
    parties = []
    combinateur = " "
    for morceau in morceaux:
        if morceau in (">", "+", "~"):
            combinateur = morceau
            continue
        simple = analyser_selecteur_compose(morceau)
        if simple is None:
            return None
        parties.append((combinateur if parties else None, simple))
        combinateur = " "
    return Selecteur(parties) if parties else None


def _decouper_hors_parentheses(texte, separateurs=" \t\n"):
    morceaux, courant, profondeur, crochets = [], [], 0, 0
    for caractere in texte:
        if caractere == "(":
            profondeur += 1
        elif caractere == ")":
            profondeur -= 1
        elif caractere == "[":
            crochets += 1
        elif caractere == "]":
            crochets -= 1
        if caractere in separateurs and profondeur == 0 and crochets == 0:
            if courant:
                morceaux.append("".join(courant))
            courant = []
        else:
            courant.append(caractere)
    if courant:
        morceaux.append("".join(courant))
    return morceaux


# ---------------------------------------------------------------------------
# Déclarations et raccourcis
# ---------------------------------------------------------------------------

def _quatre_valeurs(valeurs):
    if len(valeurs) == 1:
        return valeurs * 4
    if len(valeurs) == 2:
        return [valeurs[0], valeurs[1], valeurs[0], valeurs[1]]
    if len(valeurs) == 3:
        return [valeurs[0], valeurs[1], valeurs[2], valeurs[1]]
    return valeurs[:4]


COTES = ("top", "right", "bottom", "left")
STYLES_BORDURE = {"none", "hidden", "solid", "dotted", "dashed", "double", "groove", "ridge", "inset", "outset"}


def developper(propriete, valeur):
    """Développe les propriétés raccourcies (margin, padding, border, background, font...)."""
    morceaux = _decouper_hors_parentheses(valeur)
    if propriete in ("margin", "padding"):
        if not morceaux:
            return []
        return [("%s-%s" % (propriete, cote), v) for cote, v in zip(COTES, _quatre_valeurs(morceaux))]
    if propriete in ("border", "border-top", "border-right", "border-bottom", "border-left"):
        cotes = COTES if propriete == "border" else (propriete.split("-")[1],)
        epaisseur, couleur, style = "medium", None, "none"
        for morceau in morceaux:
            if morceau.lower() in STYLES_BORDURE:
                style = morceau.lower()
            elif analyser_couleur(morceau) is not None:
                couleur = morceau
            else:
                epaisseur = morceau
        if style in ("none", "hidden"):
            epaisseur = "0"
        resultat = []
        for cote in cotes:
            resultat.append(("border-%s-width" % cote, epaisseur))
            resultat.append(("border-%s-style" % cote, style))
            if couleur:
                resultat.append(("border-%s-color" % cote, couleur))
        return resultat
    if propriete in ("border-width", "border-color", "border-style"):
        attribut = propriete.split("-")[1]
        return [("border-%s-%s" % (cote, attribut), v) for cote, v in zip(COTES, _quatre_valeurs(morceaux or [valeur]))]
    if propriete == "background":
        for morceau in morceaux:
            if analyser_couleur(morceau) is not None:
                return [("background-color", morceau)]
        if valeur.strip().lower() in ("none", "transparent"):
            return [("background-color", "transparent")]
        return []
    if propriete == "font":
        resultat = []
        for index, morceau in enumerate(morceaux):
            minuscule = morceau.lower()
            if minuscule in ("bold", "bolder") or (minuscule.isdigit() and len(minuscule) == 3):
                resultat.append(("font-weight", minuscule))
            elif minuscule in ("italic", "oblique"):
                resultat.append(("font-style", "italic"))
            elif _LONGUEUR.match(minuscule.split("/")[0]) or minuscule.split("/")[0] in TAILLES_MOTS_CLES:
                taille, _, interligne = minuscule.partition("/")
                resultat.append(("font-size", taille))
                if interligne:
                    resultat.append(("line-height", interligne))
                famille = " ".join(morceaux[index + 1:])
                if famille:
                    resultat.append(("font-family", famille))
                break
        return resultat
    if propriete == "text-decoration-line":
        return [("text-decoration", valeur)]
    if propriete in ("inset-inline-start", "margin-inline-start"):
        return [("margin-left", valeur)]
    if propriete == "margin-inline-end":
        return [("margin-right", valeur)]
    if propriete == "padding-inline-start":
        return [("padding-left", valeur)]
    if propriete == "padding-inline-end":
        return [("padding-right", valeur)]
    if propriete in ("margin-block-start", "padding-block-start"):
        return [(propriete.split("-")[0] + "-top", valeur)]
    if propriete in ("margin-block-end", "padding-block-end"):
        return [(propriete.split("-")[0] + "-bottom", valeur)]
    if propriete == "list-style":
        for morceau in morceaux:
            if morceau.lower() in ("none", "disc", "circle", "square", "decimal", "lower-alpha",
                                   "upper-alpha", "lower-roman", "upper-roman", "lower-latin", "upper-latin"):
                return [("list-style-type", morceau.lower())]
        return []
    return [(propriete, valeur)]


def analyser_declarations(texte):
    """Analyse « prop: valeur; prop2: valeur2 » en liste (propriété, valeur, important)."""
    declarations = []
    for morceau in _decouper_declarations(texte):
        if ":" not in morceau:
            continue
        propriete, valeur = morceau.split(":", 1)
        propriete = propriete.strip().lower()
        valeur = valeur.strip()
        important = False
        if valeur.lower().endswith("!important"):
            important = True
            valeur = valeur[:-len("!important")].strip()
        if not propriete or not valeur or propriete.startswith("--"):
            continue
        for nom, val in developper(propriete, valeur):
            declarations.append((nom, val, important))
    return declarations


def _decouper_declarations(texte):
    morceaux, courant, profondeur, guillemet = [], [], 0, None
    for caractere in texte:
        if guillemet:
            if caractere == guillemet:
                guillemet = None
        elif caractere in "\"'":
            guillemet = caractere
        elif caractere == "(":
            profondeur += 1
        elif caractere == ")":
            profondeur = max(0, profondeur - 1)
        elif caractere == ";" and profondeur == 0:
            morceaux.append("".join(courant))
            courant = []
            continue
        courant.append(caractere)
    morceaux.append("".join(courant))
    return morceaux


# ---------------------------------------------------------------------------
# Analyse d'une feuille de style
# ---------------------------------------------------------------------------

class Regle:
    __slots__ = ("selecteur", "declarations", "ordre")

    def __init__(self, selecteur, declarations, ordre):
        self.selecteur = selecteur
        self.declarations = declarations
        self.ordre = ordre


def _retirer_commentaires(texte):
    morceaux = []
    i = 0
    while True:
        debut = texte.find("/*", i)
        if debut == -1:
            morceaux.append(texte[i:])
            break
        morceaux.append(texte[i:debut])
        fin = texte.find("*/", debut + 2)
        if fin == -1:
            break
        i = fin + 2
    return "".join(morceaux)


def _media_applicable(requete):
    requete = requete.strip().lower()
    if not requete:
        return True
    for alternative in requete.split(","):
        alternative = alternative.strip()
        if alternative.startswith("not ") or "print" in alternative or "speech" in alternative:
            continue
        ok = True
        for condition in re.findall(r"\(([^)]*)\)", alternative):
            nom, _, valeur = condition.partition(":")
            nom, valeur = nom.strip(), valeur.strip()
            if nom in ("min-width", "max-width"):
                pixels = longueur(valeur, 16, 0, None)
                if pixels is None:
                    continue
                if nom == "min-width" and LARGEUR_ECRAN_SUPPOSEE < pixels:
                    ok = False
                if nom == "max-width" and LARGEUR_ECRAN_SUPPOSEE > pixels:
                    ok = False
            elif nom == "prefers-color-scheme" and valeur == "dark":
                ok = False
            elif nom == "prefers-reduced-motion" and valeur == "reduce":
                ok = False
            elif nom in ("orientation",) and valeur == "portrait":
                ok = False
            elif nom in ("hover",) and valeur == "none":
                ok = False
        if ok:
            return True
    return False


def _trouver_fin_bloc(texte, debut):
    """``debut`` pointe juste après '{' ; renvoie l'index du '}' correspondant."""
    profondeur = 1
    i = debut
    guillemet = None
    while i < len(texte):
        caractere = texte[i]
        if guillemet:
            if caractere == "\\":
                i += 1
            elif caractere == guillemet:
                guillemet = None
        elif caractere in "\"'":
            guillemet = caractere
        elif caractere == "{":
            profondeur += 1
        elif caractere == "}":
            profondeur -= 1
            if profondeur == 0:
                return i
        i += 1
    return len(texte)


class FeuilleDeStyle:
    def __init__(self):
        self.regles = []
        self.index = {}          # clé -> [Regle]
        self.compteur = 0
        self.imports = []        # URL des @import (à charger par l'appelant)

    def ajouter_texte(self, texte):
        self._analyser(_retirer_commentaires(texte))
        return self

    def _analyser(self, texte):
        i = 0
        n = len(texte)
        while i < n:
            while i < n and texte[i] in " \t\r\n;":
                i += 1
            if i >= n:
                break
            if texte[i] == "@":
                accolade = texte.find("{", i)
                point_virgule = texte.find(";", i)
                if point_virgule != -1 and (accolade == -1 or point_virgule < accolade):
                    instruction = texte[i:point_virgule]
                    if instruction.lower().startswith("@import"):
                        cible = re.search(r"url\(\s*['\"]?([^'\")]+)|['\"]([^'\"]+)['\"]", instruction)
                        media = re.sub(r".*?(\)|['\"])\s*", "", instruction[7:], count=1) if cible else ""
                        if cible and _media_applicable(media):
                            self.imports.append(cible.group(1) or cible.group(2))
                    i = point_virgule + 1
                    continue
                if accolade == -1:
                    break
                prelude = texte[i:accolade].strip()
                fin = _trouver_fin_bloc(texte, accolade + 1)
                mot = prelude.split()[0].lower() if prelude.split() else ""
                if mot == "@media" and _media_applicable(prelude[6:]):
                    self._analyser(texte[accolade + 1:fin])
                elif mot in ("@supports", "@layer", "@document", "@container") and "not " not in prelude.lower():
                    self._analyser(texte[accolade + 1:fin])
                i = fin + 1
                continue
            accolade = texte.find("{", i)
            if accolade == -1:
                break
            fin = _trouver_fin_bloc(texte, accolade + 1)
            selecteurs = texte[i:accolade]
            declarations = analyser_declarations(texte[accolade + 1:fin])
            if declarations:
                for selecteur_texte in _decouper_hors_parentheses(selecteurs, ","):
                    selecteur = analyser_selecteur(selecteur_texte)
                    if selecteur is not None:
                        self._ajouter(Regle(selecteur, declarations, self.compteur))
                        self.compteur += 1
            i = fin + 1

    def _ajouter(self, regle):
        self.regles.append(regle)
        cible = regle.selecteur.cible
        if cible.ident:
            cle = "#" + cible.ident
        elif cible.classes:
            cle = "." + cible.classes[0]
        elif cible.balise:
            cle = cible.balise
        else:
            cle = "*"
        self.index.setdefault(cle, []).append(regle)

    def regles_candidates(self, noeud):
        candidates = list(self.index.get("*", ()))
        candidates.extend(self.index.get(noeud.balise, ()))
        ident = noeud.attributs.get("id")
        if ident:
            candidates.extend(self.index.get("#" + ident, ()))
        for classe in noeud.classes:
            candidates.extend(self.index.get("." + classe, ()))
        return candidates


def analyser_css(texte):
    return FeuilleDeStyle().ajouter_texte(texte)


# ---------------------------------------------------------------------------
# Calcul des styles
# ---------------------------------------------------------------------------

_POIDS = {"bold": "bold", "bolder": "bold", "normal": "normal", "lighter": "normal"}

ATTRIBUTS_PRESENTATION = {
    "bgcolor": "background-color", "color": "color", "align": "text-align",
    "width": "width", "height": "height",
}


def _styles_attributs(noeud):
    """Convertit les vieux attributs HTML de présentation (bgcolor, align...) en CSS."""
    declarations = []
    for attribut, propriete in ATTRIBUTS_PRESENTATION.items():
        valeur = noeud.attributs.get(attribut)
        if valeur is None:
            continue
        if attribut == "color" and noeud.balise != "font":
            continue
        if attribut == "align" and noeud.balise in ("img", "table"):
            continue
        if attribut in ("width", "height"):
            if noeud.balise not in ("img", "table", "td", "th", "input", "hr", "col"):
                continue
            valeur = valeur.strip()
            if valeur.isdigit():
                valeur += "px"
        if attribut == "align" and valeur.lower() == "middle":
            valeur = "center"
        declarations.append((propriete, valeur, False))
    if noeud.balise == "font" and "size" in noeud.attributs:
        tailles = {"1": "10px", "2": "13px", "3": "16px", "4": "18px", "5": "24px", "6": "32px", "7": "48px"}
        taille = noeud.attributs["size"].strip()
        if taille.startswith(("+", "-")) and taille[1:].isdigit():
            taille = str(max(1, min(7, 3 + int(taille))))
        if taille in tailles:
            declarations.append(("font-size", tailles[taille], False))
    if noeud.balise == "font" and "face" in noeud.attributs:
        declarations.append(("font-family", noeud.attributs["face"], False))
    if noeud.balise == "table" and noeud.attributs.get("align", "").lower() == "center":
        declarations.append(("margin-left", "auto", False))
        declarations.append(("margin-right", "auto", False))
    if noeud.balise == "body" and "text" in noeud.attributs:
        declarations.append(("color", noeud.attributs["text"], False))
    if noeud.balise in ("td", "th"):
        tableau = ancetre(noeud, "table")
        if tableau is not None:
            if tableau.attributs.get("border", "0").strip() not in ("0", ""):
                declarations += [(p, v, False) for p, v in developper("border", "1px solid #808080")]
            remplissage = tableau.attributs.get("cellpadding", "").strip()
            if remplissage.isdigit():
                declarations += [(p, v, False) for p, v in developper("padding", remplissage + "px")]
    if noeud.balise == "table" and noeud.attributs.get("border", "0").strip() not in ("0", ""):
        declarations += [(p, v, False) for p, v in developper("border", "1px solid #808080")]
    if noeud.balise in ("td", "th") and "nowrap" in noeud.attributs:
        declarations.append(("white-space", "nowrap", False))
    return declarations


def calculer_styles(noeud, feuilles, style_parent=None):
    """Calcule le style de ``noeud`` et de ses descendants (cascade + héritage)."""
    pile = [(noeud, style_parent)]
    while pile:
        courant, parent_style = pile.pop()
        _calculer_style_noeud(courant, feuilles, parent_style)
        for enfant in reversed(courant.enfants):
            pile.append((enfant, courant.style))


def _calculer_style_noeud(noeud, feuilles, style_parent):
    style = {}
    for propriete, defaut in PROPRIETES_HERITEES.items():
        style[propriete] = style_parent[propriete] if style_parent else defaut

    if isinstance(noeud, Element):
        normales = []
        importantes = []
        for rang, feuille in enumerate(feuilles):
            for regle in feuille.regles_candidates(noeud):
                if regle.selecteur.correspond(noeud):
                    cle = (rang > 0, regle.selecteur.priorite, rang, regle.ordre)
                    normales.append((cle, regle.declarations))
        normales.sort(key=lambda e: e[0])
        appliquees = [(p, v) for p, v, _ in _styles_attributs(noeud)]
        for _, declarations in normales:
            for propriete, valeur, important in declarations:
                if important:
                    importantes.append((propriete, valeur))
                else:
                    appliquees.append((propriete, valeur))
        if "style" in noeud.attributs:
            for propriete, valeur, important in analyser_declarations(noeud.attributs["style"]):
                (importantes if important else appliquees).append((propriete, valeur))
        appliquees.extend(importantes)
        for propriete, valeur in appliquees:
            valeur_min = valeur.strip().lower()
            if valeur_min == "inherit":
                if style_parent and propriete in style_parent:
                    style[propriete] = style_parent[propriete]
                continue
            if valeur_min in ("initial", "unset", "revert"):
                if propriete in PROPRIETES_HERITEES and valeur_min != "initial" and style_parent:
                    style[propriete] = style_parent[propriete]
                elif propriete in PROPRIETES_HERITEES:
                    style[propriete] = PROPRIETES_HERITEES[propriete]
                else:
                    style.pop(propriete, None)
                continue
            if "var(" in valeur_min:
                continue  # variables CSS non prises en charge : on garde la valeur précédente
            style[propriete] = valeur

    # -- valeurs calculées --------------------------------------------------
    taille_parent = float(style_parent["font-size"][:-2]) if style_parent else 16.0
    taille = style["font-size"].strip().lower()
    if style_parent is not None and taille == style_parent["font-size"]:
        pixels = taille_parent
    elif taille in TAILLES_MOTS_CLES:
        pixels = TAILLES_MOTS_CLES[taille]
    elif taille == "smaller":
        pixels = taille_parent / 1.2
    elif taille == "larger":
        pixels = taille_parent * 1.2
    else:
        pixels = longueur(taille, taille_parent, taille_parent, taille_parent)
    style["font-size"] = "%.2fpx" % max(1.0, pixels)

    poids = style["font-weight"].strip().lower()
    if poids.isdigit():
        poids = "bold" if int(poids) >= 600 else "normal"
    style["font-weight"] = _POIDS.get(poids, "normal")
    style["font-style"] = "italic" if style["font-style"].strip().lower() in ("italic", "oblique") else "normal"

    couleur_parent = style_parent["color"] if style_parent else "#000000"
    couleur = analyser_couleur(style["color"], couleur_parent)
    style["color"] = couleur if couleur and couleur != "transparent" else couleur_parent

    if "background-color" in style:
        fond = analyser_couleur(style["background-color"], style["color"])
        if fond is None or fond == "transparent":
            del style["background-color"]
        else:
            style["background-color"] = fond

    if isinstance(noeud, Element):
        style.setdefault("display", "inline")
        style["display"] = style["display"].strip().lower()
    else:
        style["display"] = "inline"
    noeud.style = style
