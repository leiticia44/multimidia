"""Analyseur HTML écrit à la main : découpe en jetons puis construit l'arbre DOM.

L'analyseur est tolérant comme celui d'un vrai navigateur : il ajoute les
balises <html>, <head> et <body> manquantes, ferme automatiquement les
paragraphes et éléments de liste, et ignore les balises fermantes orphelines.
"""

# ---------------------------------------------------------------------------
# Nœuds de l'arbre
# ---------------------------------------------------------------------------


class Texte:
    def __init__(self, texte, parent):
        self.texte = texte
        self.parent = parent
        self.enfants = []
        self.style = {}

    def __repr__(self):
        return "Texte(%r)" % self.texte[:40]


class Element:
    def __init__(self, balise, attributs, parent):
        self.balise = balise
        self.attributs = attributs
        self.parent = parent
        self.enfants = []
        self.style = {}

    def __repr__(self):
        return "<%s%s>" % (self.balise, "".join(' %s="%s"' % p for p in self.attributs.items()))

    @property
    def classes(self):
        return self.attributs.get("class", "").split()

    def texte_contenu(self):
        return "".join(n.texte if isinstance(n, Texte) else n.texte_contenu() for n in self.enfants)


def parcourir(noeud, liste=None):
    """Renvoie la liste de tous les nœuds de l'arbre (parcours préfixe)."""
    if liste is None:
        liste = []
    pile = [noeud]
    while pile:
        courant = pile.pop()
        liste.append(courant)
        pile.extend(reversed(courant.enfants))
    return liste


def ancetre(noeud, balise):
    while noeud is not None:
        if isinstance(noeud, Element) and noeud.balise == balise:
            return noeud
        noeud = noeud.parent
    return None


# ---------------------------------------------------------------------------
# Entités HTML (&eacute; &#233; &#xE9; ...)
# ---------------------------------------------------------------------------

ENTITES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
    "copy": "©", "reg": "®", "trade": "™", "euro": "€", "pound": "£", "yen": "¥",
    "cent": "¢", "sect": "§", "para": "¶", "deg": "°", "plusmn": "±", "times": "×",
    "divide": "÷", "micro": "µ", "middot": "·", "bull": "•", "hellip": "…",
    "laquo": "«", "raquo": "»", "lsquo": "‘", "rsquo": "’", "ldquo": "“", "rdquo": "”",
    "sbquo": "‚", "bdquo": "„", "ndash": "–", "mdash": "—", "shy": "­",
    "iexcl": "¡", "iquest": "¿", "ordf": "ª", "ordm": "º", "sup1": "¹", "sup2": "²",
    "sup3": "³", "frac12": "½", "frac14": "¼", "frac34": "¾", "larr": "←", "rarr": "→",
    "uarr": "↑", "darr": "↓", "harr": "↔", "hearts": "♥", "ensp": " ",
    "emsp": " ", "thinsp": " ", "zwnj": "‌", "zwj": "‍",
    "Agrave": "À", "Aacute": "Á", "Acirc": "Â", "Atilde": "Ã", "Auml": "Ä", "Aring": "Å",
    "AElig": "Æ", "Ccedil": "Ç", "Egrave": "È", "Eacute": "É", "Ecirc": "Ê", "Euml": "Ë",
    "Igrave": "Ì", "Iacute": "Í", "Icirc": "Î", "Iuml": "Ï", "Ntilde": "Ñ",
    "Ograve": "Ò", "Oacute": "Ó", "Ocirc": "Ô", "Otilde": "Õ", "Ouml": "Ö", "Oslash": "Ø",
    "Ugrave": "Ù", "Uacute": "Ú", "Ucirc": "Û", "Uuml": "Ü", "Yacute": "Ý", "OElig": "Œ",
    "agrave": "à", "aacute": "á", "acirc": "â", "atilde": "ã", "auml": "ä", "aring": "å",
    "aelig": "æ", "ccedil": "ç", "egrave": "è", "eacute": "é", "ecirc": "ê", "euml": "ë",
    "igrave": "ì", "iacute": "í", "icirc": "î", "iuml": "ï", "ntilde": "ñ",
    "ograve": "ò", "oacute": "ó", "ocirc": "ô", "otilde": "õ", "ouml": "ö", "oslash": "ø",
    "ugrave": "ù", "uacute": "ú", "ucirc": "û", "uuml": "ü", "yacute": "ý", "yuml": "ÿ",
    "oelig": "œ", "szlig": "ß",
}

# Correspondance Windows-1252 utilisée par les navigateurs pour &#128; à &#159;
_CP1252 = {128: "€", 130: "‚", 131: "ƒ", 132: "„", 133: "…", 134: "†", 135: "‡", 136: "ˆ",
           137: "‰", 138: "Š", 139: "‹", 140: "Œ", 142: "Ž", 145: "‘", 146: "’", 147: "“",
           148: "”", 149: "•", 150: "–", 151: "—", 152: "˜", 153: "™", 154: "š", 155: "›",
           156: "œ", 158: "ž", 159: "Ÿ"}


def decoder_entites(texte):
    if "&" not in texte:
        return texte
    resultat = []
    i = 0
    n = len(texte)
    while i < n:
        caractere = texte[i]
        if caractere != "&":
            suivant = texte.find("&", i)
            if suivant == -1:
                suivant = n
            resultat.append(texte[i:suivant])
            i = suivant
            continue
        fin = texte.find(";", i + 1, i + 34)
        if i + 1 < n and texte[i + 1] == "#":
            j = i + 2
            hexa = j < n and texte[j] in "xX"
            if hexa:
                j += 1
            debut = j
            chiffres = "0123456789abcdefABCDEF" if hexa else "0123456789"
            while j < n and texte[j] in chiffres:
                j += 1
            if j > debut:
                code = int(texte[debut:j], 16 if hexa else 10)
                if code in _CP1252:
                    resultat.append(_CP1252[code])
                elif 0 < code < 0x110000 and not 0xD800 <= code <= 0xDFFF:
                    resultat.append(chr(code))
                else:
                    resultat.append("�")
                i = j + 1 if j < n and texte[j] == ";" else j
                continue
        elif fin != -1 and texte[i + 1:fin] in ENTITES:
            resultat.append(ENTITES[texte[i + 1:fin]])
            i = fin + 1
            continue
        else:
            # Entités sans point-virgule tolérées par les navigateurs (&amp, &nbsp...)
            for nom in ("amp", "lt", "gt", "quot", "nbsp", "copy"):
                if texte.startswith(nom, i + 1):
                    resultat.append(ENTITES[nom])
                    i += 1 + len(nom)
                    break
            else:
                resultat.append("&")
                i += 1
            continue
        resultat.append("&")
        i += 1
    return "".join(resultat)


# ---------------------------------------------------------------------------
# Construction de l'arbre
# ---------------------------------------------------------------------------

ELEMENTS_VIDES = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                  "meta", "param", "source", "track", "wbr", "keygen"}
BALISES_ENTETE = {"base", "basefont", "bgsound", "link", "meta", "title", "style", "script"}
TEXTE_BRUT = {"script", "style", "textarea", "title", "xmp", "noembed", "noframes"}
FERMENT_P = {"address", "article", "aside", "blockquote", "center", "details", "dialog", "dir",
             "div", "dl", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
             "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
             "p", "pre", "section", "summary", "table", "ul", "li", "dd", "dt"}
# Pour chaque balise, les balises ouvertes qu'elle ferme implicitement, et les
# « barrières » au-delà desquelles on ne remonte pas.
FERMETURES_IMPLICITES = {
    "li": ({"li"}, {"ul", "ol", "menu"}),
    "dt": ({"dt", "dd"}, {"dl"}),
    "dd": ({"dt", "dd"}, {"dl"}),
    "option": ({"option"}, {"select", "datalist"}),
    "optgroup": ({"option", "optgroup"}, {"select"}),
    "tr": ({"tr", "td", "th"}, {"table", "thead", "tbody", "tfoot"}),
    "td": ({"td", "th"}, {"tr", "table"}),
    "th": ({"td", "th"}, {"tr", "table"}),
    "thead": ({"thead", "tbody", "tfoot", "tr", "td", "th"}, {"table"}),
    "tbody": ({"thead", "tbody", "tfoot", "tr", "td", "th"}, {"table"}),
    "tfoot": ({"thead", "tbody", "tfoot", "tr", "td", "th"}, {"table"}),
}
BARRIERES_P = {"button", "td", "th", "table", "li", "div", "body", "html", "blockquote", "section",
               "article", "form", "dd", "dt"}


class AnalyseurHTML:
    def __init__(self, source):
        self.source = source
        self.non_termines = []
        self.racine = None

    # -- jetons ------------------------------------------------------------

    def analyser(self):
        source = self.source
        n = len(source)
        i = 0
        debut_texte = 0
        while i < n:
            i = source.find("<", i)
            if i == -1:
                break
            suivant = source[i + 1:i + 2]
            if source.startswith("<!--", i):
                self._texte(source[debut_texte:i])
                fin = source.find("-->", i + 4)
                i = n if fin == -1 else fin + 3
                debut_texte = i
            elif suivant in ("!", "?"):
                self._texte(source[debut_texte:i])
                fin = source.find(">", i)
                i = n if fin == -1 else fin + 1
                debut_texte = i
            elif suivant.isalpha() or (suivant == "/" and source[i + 2:i + 3].isalpha()):
                self._texte(source[debut_texte:i])
                i = self._lire_balise(i)
                debut_texte = i
            else:
                i += 1
        self._texte(source[debut_texte:])
        return self.terminer()

    def _lire_balise(self, i):
        source = self.source
        n = len(source)
        i += 1
        fermante = source[i] == "/"
        if fermante:
            i += 1
        debut = i
        while i < n and source[i] not in " \t\n\r\f/>":
            i += 1
        balise = source[debut:i].lower()
        attributs = {}
        auto_fermante = False
        while i < n:
            while i < n and source[i] in " \t\n\r\f":
                i += 1
            if i >= n:
                break
            if source[i] == ">":
                i += 1
                break
            if source[i] == "/":
                auto_fermante = source[i + 1:i + 2] == ">"
                i += 1
                continue
            debut = i
            while i < n and source[i] not in " \t\n\r\f/>=":
                i += 1
            nom = source[debut:i].lower()
            while i < n and source[i] in " \t\n\r\f":
                i += 1
            valeur = ""
            if i < n and source[i] == "=":
                i += 1
                while i < n and source[i] in " \t\n\r\f":
                    i += 1
                if i < n and source[i] in "\"'":
                    guillemet = source[i]
                    fin = source.find(guillemet, i + 1)
                    if fin == -1:
                        fin = n
                    valeur = source[i + 1:fin]
                    i = fin + 1
                else:
                    debut = i
                    while i < n and source[i] not in " \t\n\r\f>":
                        i += 1
                    valeur = source[debut:i]
            if nom and nom not in attributs:
                attributs[nom] = decoder_entites(valeur)

        if fermante:
            self._fermer(balise)
            return i
        self._ouvrir(balise, attributs)
        if balise in TEXTE_BRUT and not auto_fermante:
            fin = self._chercher_fermeture(balise, i)
            contenu = source[i:fin]
            if contenu:
                parent = self.non_termines[-1]
                texte = decoder_entites(contenu) if balise in ("textarea", "title") else contenu
                if balise == "textarea" and texte.startswith("\n"):
                    texte = texte[1:]
                parent.enfants.append(Texte(texte, parent))
            self._fermer(balise)
            fin_balise = source.find(">", fin)
            return n if fin_balise == -1 else fin_balise + 1
        if auto_fermante and balise not in ELEMENTS_VIDES:
            self._fermer(balise)
        return i

    def _chercher_fermeture(self, balise, depuis):
        minuscule = self.source.lower()
        motif = "</" + balise
        position = depuis
        while True:
            position = minuscule.find(motif, position)
            if position == -1:
                return len(self.source)
            apres = minuscule[position + len(motif):position + len(motif) + 1]
            if apres in ("", ">", " ", "\t", "\n", "\r", "/"):
                return position
            position += len(motif)

    # -- construction --------------------------------------------------------

    def _balises_implicites(self, balise):
        while True:
            ouvertes = [n.balise for n in self.non_termines]
            if not ouvertes and balise != "html":
                self._ouvrir_brut("html", {})
            elif ouvertes == ["html"] and balise not in ("head", "body", "/html"):
                if balise in BALISES_ENTETE or balise == "noscript":
                    self._ouvrir_brut("head", {})
                else:
                    self._ouvrir_brut("body", {})
            elif ouvertes == ["html", "head"] and balise not in ("/head",) and balise not in BALISES_ENTETE and balise != "noscript":
                self.non_termines.pop()
            else:
                break

    def _ouvrir_brut(self, balise, attributs):
        parent = self.non_termines[-1] if self.non_termines else None
        noeud = Element(balise, attributs, parent)
        if parent is not None:
            parent.enfants.append(noeud)
        else:
            self.racine = noeud
        self.non_termines.append(noeud)
        return noeud

    def _ouvrir(self, balise, attributs):
        if balise == "html" and self.non_termines:
            self.non_termines[0].attributs.update({k: v for k, v in attributs.items() if k not in self.non_termines[0].attributs})
            return
        if balise == "body":
            corps = next((n for n in self.non_termines if n.balise == "body"), None)
            if corps is not None:
                corps.attributs.update({k: v for k, v in attributs.items() if k not in corps.attributs})
                return
            if self.non_termines and self.non_termines[-1].balise == "head":
                self.non_termines.pop()
        if balise == "head" and len(self.non_termines) > 1:
            return  # <head> en double : ignoré
        self._balises_implicites(balise)

        if balise in FERMETURES_IMPLICITES:
            a_fermer, barrieres = FERMETURES_IMPLICITES[balise]
            for index in range(len(self.non_termines) - 1, -1, -1):
                ouverte = self.non_termines[index].balise
                if ouverte in a_fermer:
                    del self.non_termines[index:]
                    break
                if ouverte in barrieres:
                    break
        if balise in FERMENT_P:
            for index in range(len(self.non_termines) - 1, -1, -1):
                ouverte = self.non_termines[index].balise
                if ouverte == "p":
                    del self.non_termines[index:]
                    break
                if ouverte in BARRIERES_P:
                    break
        if balise in ("td", "th") and self.non_termines and self.non_termines[-1].balise in ("table", "tbody", "thead", "tfoot"):
            self._ouvrir_brut("tr", {})
        if balise == "a":
            # Les liens ne s'imbriquent pas.
            for index in range(len(self.non_termines) - 1, -1, -1):
                if self.non_termines[index].balise == "a":
                    del self.non_termines[index:]
                    break

        noeud = self._ouvrir_brut(balise, attributs)
        if balise in ELEMENTS_VIDES:
            self.non_termines.pop()
        return noeud

    def _fermer(self, balise):
        if balise in ("html", "body"):
            return  # on garde body ouvert pour le contenu situé après </body>
        if balise == "br":
            self._balises_implicites("br")
            self._ouvrir_brut("br", {})
            self.non_termines.pop()
            return
        if balise == "p" and not any(n.balise == "p" for n in self.non_termines):
            self._balises_implicites("p")
            self._ouvrir_brut("p", {})
        for index in range(len(self.non_termines) - 1, 0, -1):
            if self.non_termines[index].balise == balise:
                del self.non_termines[index:]
                return

    def _texte(self, texte):
        if not texte:
            return
        if texte.isspace() and (not self.non_termines or self.non_termines[-1].balise in ("html", "head")):
            return
        self._balises_implicites("#texte")
        parent = self.non_termines[-1]
        texte = decoder_entites(texte)
        if parent.enfants and isinstance(parent.enfants[-1], Texte):
            parent.enfants[-1].texte += texte
        else:
            parent.enfants.append(Texte(texte, parent))

    def terminer(self):
        if not self.non_termines:
            self._balises_implicites("#fin")
        if len(self.non_termines) == 1:
            self._ouvrir_brut("body", {})
        return self.racine


def analyser_html(source):
    return AnalyseurHTML(source).analyser()


def afficher_arbre(noeud, indentation=0):
    """Affiche l'arbre DOM (utile pour déboguer)."""
    lignes = []
    for courant, profondeur in _avec_profondeur(noeud, indentation):
        lignes.append(" " * profondeur + (repr(courant)))
    return "\n".join(lignes)


def _avec_profondeur(noeud, profondeur):
    yield noeud, profondeur
    for enfant in noeud.enfants:
        yield from _avec_profondeur(enfant, profondeur + 2)
