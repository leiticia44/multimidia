"""Couche réseau du navigateur, écrite à la main au-dessus des sockets.

Gère :
  * l'analyse et la résolution des URL (http, https, file, data, about) ;
  * le protocole HTTP/1.1 (requêtes GET/POST, réponses « chunked »,
    compression gzip/deflate, redirections) ;
  * HTTPS (TLS via le module ssl standard) ;
  * les cookies, un petit cache mémoire et les proxys HTTP (CONNECT).
"""

import base64
import os
import socket
import ssl
import time
import zlib

AGENT_UTILISATEUR = "NavigateurMaison/1.0 (projet etudiant; Python)"
PORTS_PAR_DEFAUT = {"http": 80, "https": 443}
MAX_REDIRECTIONS = 10
DELAI_RESEAU = 20  # secondes


class ErreurReseau(Exception):
    """Toute erreur survenue pendant le chargement d'une ressource."""


# ---------------------------------------------------------------------------
# Encodage « pourcent » (RFC 3986) et formulaires
# ---------------------------------------------------------------------------

_NON_RESERVES = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def pourcent_encoder(texte, sur=""):
    """Encode ``texte`` en UTF-8 puis remplace les octets spéciaux par %XX."""
    morceaux = []
    for octet in texte.encode("utf-8"):
        caractere = chr(octet)
        if caractere in _NON_RESERVES or (octet < 128 and caractere in sur):
            morceaux.append(caractere)
        else:
            morceaux.append("%%%02X" % octet)
    return "".join(morceaux)


def pourcent_decoder(texte, plus_en_espace=False):
    if plus_en_espace:
        texte = texte.replace("+", " ")
    octets = bytearray()
    i = 0
    brut = texte.encode("utf-8")
    while i < len(brut):
        if brut[i] == 0x25 and _est_hexa(brut[i + 1:i + 3]):
            octets.append(int(brut[i + 1:i + 3], 16))
            i += 3
        else:
            octets.append(brut[i])
            i += 1
    return octets.decode("utf-8", errors="replace")


def _est_hexa(deux_octets):
    return len(deux_octets) == 2 and all(c in b"0123456789abcdefABCDEF" for c in deux_octets)


def encoder_formulaire(paires):
    """Encode une liste (nom, valeur) au format application/x-www-form-urlencoded."""
    return "&".join(
        pourcent_encoder(nom).replace("%20", "+") + "=" + pourcent_encoder(valeur).replace("%20", "+")
        for nom, valeur in paires
    )


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

def _normaliser_chemin(chemin):
    """Supprime les segments « . » et « .. » d'un chemin absolu."""
    requete = ""
    if "?" in chemin:
        chemin, requete = chemin.split("?", 1)
        requete = "?" + requete
    segments = chemin.split("/")
    resultat = []
    for segment in segments[1:]:
        if segment == "..":
            if resultat:
                resultat.pop()
        elif segment != ".":
            resultat.append(segment)
    if segments[-1] in (".", "..") and (not resultat or resultat[-1] != ""):
        resultat.append("")
    return "/" + "/".join(resultat) + requete


class URL:
    def __init__(self, url):
        url = url.strip()
        self.fragment = ""
        self.hote = ""
        self.port = None
        self.chemin = ""

        minuscule = url.lower()
        if minuscule.startswith(("about:", "data:", "view-source:")):
            self.schema, self.chemin = url.split(":", 1)
            self.schema = self.schema.lower()
            if self.schema == "about" and "#" in self.chemin:
                self.chemin, self.fragment = self.chemin.split("#", 1)
            return

        if "://" not in url:
            raise ValueError("URL sans schéma : %r" % url)
        self.schema, reste = url.split("://", 1)
        self.schema = self.schema.lower()
        if self.schema not in ("http", "https", "file"):
            raise ValueError("Schéma non pris en charge : %s" % self.schema)

        if "#" in reste:
            reste, self.fragment = reste.split("#", 1)

        if self.schema == "file":
            self.chemin = pourcent_decoder(reste) or "/"
            return

        fin_hote = len(reste)
        for separateur in "/?":
            position = reste.find(separateur)
            if position != -1:
                fin_hote = min(fin_hote, position)
        hote, chemin = reste[:fin_hote], reste[fin_hote:]
        if not chemin.startswith("/"):
            chemin = "/" + chemin
        if "@" in hote:  # on ignore les identifiants intégrés à l'URL
            hote = hote.rsplit("@", 1)[1]
        if hote.startswith("["):  # IPv6 : [::1]:8080
            fin = hote.find("]")
            adresse, suite = hote[1:fin], hote[fin + 1:]
            hote = adresse
            if suite.startswith(":") and suite[1:].isdigit():
                self.port = int(suite[1:])
        elif ":" in hote:
            hote, port = hote.rsplit(":", 1)
            if port:
                if not port.isdigit():
                    raise ValueError("Port invalide : %r" % port)
                self.port = int(port)
        if not hote:
            raise ValueError("URL sans hôte : %r" % url)
        self.hote = hote.lower()
        self.chemin = _normaliser_chemin(chemin)
        if self.port is None:
            self.port = PORTS_PAR_DEFAUT[self.schema]

    # -- représentation ----------------------------------------------------

    def origine(self):
        return "%s://%s" % (self.schema, self._hote_port())

    def _hote_port(self):
        hote = "[%s]" % self.hote if ":" in self.hote else self.hote
        if self.port and self.port != PORTS_PAR_DEFAUT.get(self.schema):
            return "%s:%d" % (hote, self.port)
        return hote

    def sans_fragment(self):
        copie = URL.__new__(URL)
        copie.__dict__.update(self.__dict__)
        copie.fragment = ""
        return copie

    def __str__(self):
        if self.schema in ("about", "data", "view-source"):
            texte = "%s:%s" % (self.schema, self.chemin)
        elif self.schema == "file":
            texte = "file://" + self.chemin
        else:
            texte = self.origine() + self.chemin
        if self.fragment:
            texte += "#" + self.fragment
        return texte

    def __repr__(self):
        return "URL(%r)" % str(self)

    def __eq__(self, autre):
        return isinstance(autre, URL) and str(self) == str(autre)

    def __hash__(self):
        return hash(str(self))

    # -- résolution des liens relatifs -----------------------------------

    def resoudre(self, relatif):
        relatif = relatif.strip()
        minuscule = relatif.lower()
        if "://" in relatif.split("?")[0] or minuscule.startswith(("about:", "data:", "view-source:")):
            return URL(relatif)
        if minuscule.startswith(("javascript:", "mailto:", "tel:")):
            raise ValueError("Lien non navigable : %s" % relatif)
        if self.schema in ("about", "data", "view-source"):
            raise ValueError("Impossible de résoudre %r depuis %s" % (relatif, self))
        if relatif.startswith("//"):
            return URL(self.schema + ":" + relatif)
        base = self.origine() if self.schema != "file" else "file://"
        chemin_actuel = self.chemin
        if relatif == "":
            return URL(base + chemin_actuel)
        if relatif.startswith("#"):
            return URL(base + chemin_actuel + relatif)
        if relatif.startswith("?"):
            return URL(base + chemin_actuel.split("?")[0] + relatif)
        fragment = ""
        if "#" in relatif:
            relatif, fragment = relatif.split("#", 1)
            fragment = "#" + fragment
        if not relatif.startswith("/"):
            dossier = chemin_actuel.split("?")[0].rsplit("/", 1)[0]
            relatif = dossier + "/" + relatif
        return URL(base + _normaliser_chemin(relatif) + fragment)


# ---------------------------------------------------------------------------
# Réponse
# ---------------------------------------------------------------------------

class Reponse:
    def __init__(self, url, statut, raison, entetes, corps):
        self.url = url              # URL finale (après redirections)
        self.statut = statut
        self.raison = raison
        self.entetes = entetes      # dict, clés en minuscules
        self.corps = corps          # bytes

    @property
    def type_mime(self):
        return self.entetes.get("content-type", "").split(";")[0].strip().lower()

    def texte(self):
        """Décode le corps en texte en détectant le jeu de caractères."""
        encodage = _charset_depuis_entete(self.entetes.get("content-type", ""))
        if not encodage:
            encodage = _charset_depuis_meta(self.corps[:2048]) or "utf-8"
        try:
            return self.corps.decode(encodage, errors="replace")
        except LookupError:
            return self.corps.decode("utf-8", errors="replace")


def _charset_depuis_entete(valeur):
    for parametre in valeur.split(";")[1:]:
        if "=" in parametre:
            nom, val = parametre.split("=", 1)
            if nom.strip().lower() == "charset":
                return val.strip().strip("\"'")
    return None


def _charset_depuis_meta(debut):
    texte = debut.decode("ascii", errors="ignore").lower()
    position = texte.find("charset=")
    if position == -1:
        return None
    position += len("charset=")
    while position < len(texte) and texte[position] in "\"' ":
        position += 1
    fin = position
    while fin < len(texte) and (texte[fin].isalnum() or texte[fin] in "-_"):
        fin += 1
    return texte[position:fin] or None


# ---------------------------------------------------------------------------
# Cookies et cache
# ---------------------------------------------------------------------------

class BocalACookies:
    """Stocke les cookies par domaine (version simplifiée de la RFC 6265)."""

    def __init__(self):
        self.cookies = {}  # domaine -> {nom: valeur}

    def enregistrer(self, url, entete):
        morceaux = [m.strip() for m in entete.split(";")]
        if "=" not in morceaux[0]:
            return
        nom, valeur = morceaux[0].split("=", 1)
        domaine = url.hote
        expire = False
        for attribut in morceaux[1:]:
            cle, _, val = attribut.partition("=")
            cle = cle.strip().lower()
            if cle == "domain" and val:
                candidat = val.strip().lstrip(".").lower()
                if url.hote == candidat or url.hote.endswith("." + candidat):
                    domaine = candidat
            elif cle == "max-age" and val.strip().lstrip("-").isdigit() and int(val) <= 0:
                expire = True
        boite = self.cookies.setdefault(domaine, {})
        if expire:
            boite.pop(nom.strip(), None)
        else:
            boite[nom.strip()] = valeur.strip()

    def entete_pour(self, url):
        paires = {}
        for domaine, boite in self.cookies.items():
            if url.hote == domaine or url.hote.endswith("." + domaine):
                paires.update(boite)
        return "; ".join("%s=%s" % p for p in paires.items())


class Cache:
    def __init__(self):
        self.entrees = {}

    def lire(self, cle):
        entree = self.entrees.get(cle)
        if entree and time.time() < entree[0]:
            return entree[1]
        self.entrees.pop(cle, None)
        return None

    def ecrire(self, cle, reponse):
        controle = reponse.entetes.get("cache-control", "").lower()
        if "no-store" in controle or "no-cache" in controle or "private" in controle:
            return
        for directive in controle.split(","):
            directive = directive.strip()
            if directive.startswith("max-age="):
                valeur = directive[len("max-age="):]
                if valeur.isdigit() and int(valeur) > 0:
                    self.entrees[cle] = (time.time() + int(valeur), reponse)


# ---------------------------------------------------------------------------
# Client HTTP
# ---------------------------------------------------------------------------

def _proxy_pour(url):
    """Renvoie (hote, port) du proxy à utiliser pour ``url`` ou None."""
    noms = ("https_proxy", "HTTPS_PROXY") if url.schema == "https" else ("http_proxy", "HTTP_PROXY")
    adresse = next((os.environ[n] for n in noms if os.environ.get(n)), None)
    if not adresse:
        return None
    exclusions = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    for exclu in exclusions.split(","):
        exclu = exclu.strip().lstrip("*").lower()
        if exclu and "/" not in exclu and (url.hote == exclu.lstrip(".") or url.hote.endswith(exclu if exclu.startswith(".") else "." + exclu)):
            return None
    if "://" not in adresse:
        adresse = "http://" + adresse
    try:
        proxy = URL(adresse)
    except ValueError:
        return None
    return proxy.hote, proxy.port


class ClientHTTP:
    def __init__(self):
        self.cookies = BocalACookies()
        self.cache = Cache()
        self.contexte_tls = ssl.create_default_context()

    # -- point d'entrée ---------------------------------------------------

    def charger(self, url, methode="GET", corps=None, entetes=None, referent=None):
        """Charge ``url`` (objet URL) et renvoie une Reponse."""
        if url.schema == "file":
            return self._charger_fichier(url)
        if url.schema == "data":
            return self._charger_data(url)
        if url.schema == "about":
            return Reponse(url, 200, "OK", {"content-type": "text/html; charset=utf-8"}, b"")
        if url.schema not in ("http", "https"):
            raise ErreurReseau("Schéma non pris en charge : %s" % url.schema)

        for _ in range(MAX_REDIRECTIONS + 1):
            cle = str(url.sans_fragment())
            if methode == "GET" and corps is None:
                en_cache = self.cache.lire(cle)
                if en_cache is not None:
                    return en_cache
            reponse = self._requete(url, methode, corps, entetes or {}, referent)
            if reponse.statut in (301, 302, 303, 307, 308) and "location" in reponse.entetes:
                nouvelle = url.resoudre(reponse.entetes["location"])
                if not nouvelle.fragment and url.fragment:
                    nouvelle.fragment = url.fragment
                if reponse.statut in (301, 302, 303):
                    methode, corps = "GET", None
                referent, url = url, nouvelle
                continue
            if methode == "GET" and reponse.statut == 200:
                self.cache.ecrire(cle, reponse)
            return reponse
        raise ErreurReseau("Trop de redirections")

    # -- schémas locaux -----------------------------------------------------

    def _charger_fichier(self, url):
        chemin = url.chemin
        if os.name == "nt" and len(chemin) > 2 and chemin[0] == "/" and chemin[2] == ":":
            chemin = chemin[1:]
        if os.path.isdir(chemin):
            elements = sorted(os.listdir(chemin))
            lignes = ['<li><a href="%s">%s</a></li>' % (
                pourcent_encoder(nom, "/") + ("/" if os.path.isdir(os.path.join(chemin, nom)) else ""), nom)
                for nom in elements]
            base = chemin if chemin.endswith("/") else chemin + "/"
            html = "<html><head><title>%s</title><base href=\"file://%s\"></head><body><h1>Index de %s</h1><ul>%s</ul></body></html>" % (
                chemin, pourcent_encoder(base, "/:"), chemin, "".join(lignes))
            return Reponse(url, 200, "OK", {"content-type": "text/html; charset=utf-8"}, html.encode("utf-8"))
        try:
            with open(chemin, "rb") as fichier:
                donnees = fichier.read()
        except OSError as erreur:
            raise ErreurReseau("Impossible de lire %s : %s" % (chemin, erreur.strerror))
        return Reponse(url, 200, "OK", {"content-type": _type_depuis_extension(chemin)}, donnees)

    def _charger_data(self, url):
        if "," not in url.chemin:
            raise ErreurReseau("URL data: invalide")
        entete, contenu = url.chemin.split(",", 1)
        est_base64 = entete.endswith(";base64")
        if est_base64:
            entete = entete[:-len(";base64")]
            try:
                donnees = base64.b64decode(pourcent_decoder(contenu))
            except ValueError:
                raise ErreurReseau("Données base64 invalides")
        else:
            donnees = pourcent_decoder(contenu).encode("utf-8")
        return Reponse(url, 200, "OK", {"content-type": entete or "text/plain"}, donnees)

    # -- HTTP ---------------------------------------------------------------

    def _ouvrir_socket(self, url):
        proxy = _proxy_pour(url)
        try:
            if proxy:
                connexion = socket.create_connection(proxy, timeout=DELAI_RESEAU)
                if url.schema == "https":
                    cible = "%s:%d" % (url.hote, url.port)
                    connexion.sendall(("CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (cible, cible)).encode("ascii"))
                    reponse = b""
                    while b"\r\n\r\n" not in reponse:
                        morceau = connexion.recv(4096)
                        if not morceau:
                            break
                        reponse += morceau
                    ligne = reponse.split(b"\r\n", 1)[0].decode("latin-1")
                    if " 200" not in ligne:
                        connexion.close()
                        raise ErreurReseau("Le proxy a refusé la connexion : %s" % ligne)
            else:
                connexion = socket.create_connection((url.hote, url.port), timeout=DELAI_RESEAU)
            if url.schema == "https":
                connexion = self.contexte_tls.wrap_socket(connexion, server_hostname=url.hote)
        except socket.gaierror:
            raise ErreurReseau("Serveur introuvable : %s" % url.hote)
        except ssl.SSLError as erreur:
            raise ErreurReseau("Erreur de sécurité TLS : %s" % erreur)
        except OSError as erreur:
            raise ErreurReseau("Connexion impossible à %s : %s" % (url.hote, erreur))
        return connexion, bool(proxy) and url.schema == "http"

    def _requete(self, url, methode, corps, entetes_sup, referent):
        connexion, via_proxy = self._ouvrir_socket(url)
        cible = str(url.sans_fragment()) if via_proxy else url.chemin
        entetes = {
            "Host": url._hote_port(),
            "User-Agent": AGENT_UTILISATEUR,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        cookies = self.cookies.entete_pour(url)
        if cookies:
            entetes["Cookie"] = cookies
        if referent is not None and referent.schema == url.schema:
            entetes["Referer"] = str(referent.sans_fragment())
        if corps is not None:
            if isinstance(corps, str):
                corps = corps.encode("utf-8")
            entetes["Content-Length"] = str(len(corps))
            entetes.setdefault("Content-Type", "application/x-www-form-urlencoded")
        entetes.update(entetes_sup)

        requete = "%s %s HTTP/1.1\r\n" % (methode, cible)
        requete += "".join("%s: %s\r\n" % paire for paire in entetes.items()) + "\r\n"
        try:
            connexion.sendall(requete.encode("utf-8") + (corps or b""))
            flux = connexion.makefile("rb")
            ligne_statut = flux.readline().decode("latin-1").strip()
            morceaux = ligne_statut.split(" ", 2)
            if len(morceaux) < 2 or not morceaux[0].startswith("HTTP/") or not morceaux[1].isdigit():
                raise ErreurReseau("Réponse HTTP invalide : %r" % ligne_statut)
            statut = int(morceaux[1])
            raison = morceaux[2] if len(morceaux) > 2 else ""

            reponse_entetes = {}
            while True:
                ligne = flux.readline().decode("latin-1")
                if ligne in ("\r\n", "\n", ""):
                    break
                nom, _, valeur = ligne.partition(":")
                nom, valeur = nom.strip().lower(), valeur.strip()
                if nom == "set-cookie":
                    self.cookies.enregistrer(url, valeur)
                if nom in reponse_entetes:
                    reponse_entetes[nom] += ", " + valeur
                else:
                    reponse_entetes[nom] = valeur

            if methode == "HEAD" or statut in (204, 304) or 100 <= statut < 200:
                donnees = b""
            elif "chunked" in reponse_entetes.get("transfer-encoding", "").lower():
                donnees = self._lire_par_morceaux(flux)
            elif reponse_entetes.get("content-length", "").isdigit():
                donnees = flux.read(int(reponse_entetes["content-length"]))
            else:
                donnees = flux.read()
        except socket.timeout:
            raise ErreurReseau("Le serveur %s ne répond pas (délai dépassé)" % url.hote)
        except OSError as erreur:
            raise ErreurReseau("Erreur pendant l'échange avec %s : %s" % (url.hote, erreur))
        finally:
            connexion.close()

        donnees = _decompresser(donnees, reponse_entetes.get("content-encoding", "").lower())
        return Reponse(url, statut, raison, reponse_entetes, donnees)

    @staticmethod
    def _lire_par_morceaux(flux):
        donnees = bytearray()
        while True:
            ligne = flux.readline()
            if not ligne:
                break
            taille_hexa = ligne.split(b";")[0].strip()
            if not taille_hexa:
                continue
            taille = int(taille_hexa, 16)
            if taille == 0:
                while flux.readline() not in (b"\r\n", b"\n", b""):
                    pass
                break
            donnees += flux.read(taille)
            flux.readline()  # CRLF après chaque morceau
        return bytes(donnees)


def _decompresser(donnees, encodage):
    if not donnees:
        return donnees
    try:
        if encodage in ("gzip", "x-gzip"):
            return zlib.decompress(donnees, 16 + zlib.MAX_WBITS)
        if encodage == "deflate":
            try:
                return zlib.decompress(donnees)
            except zlib.error:
                return zlib.decompress(donnees, -zlib.MAX_WBITS)
    except zlib.error:
        raise ErreurReseau("Contenu compressé invalide")
    return donnees


_TYPES = {
    ".html": "text/html", ".htm": "text/html", ".css": "text/css", ".txt": "text/plain",
    ".png": "image/png", ".gif": "image/gif", ".ppm": "image/x-portable-pixmap",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
    ".js": "application/javascript", ".json": "application/json", ".pdf": "application/pdf",
    ".py": "text/plain", ".md": "text/plain",
}


def _type_depuis_extension(chemin):
    extension = os.path.splitext(chemin)[1].lower()
    return _TYPES.get(extension, "application/octet-stream")
