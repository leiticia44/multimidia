"""Interface graphique du navigateur (Tkinter) : fenêtre, onglets, barre
d'adresse, rendu de la liste d'affichage sur un canevas et interactions."""

import base64
import os
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont

from . import pages_internes
from .analyseur_html import Element, ancetre, parcourir
from .chargeur import charger_page, construire_page, format_image
from .mise_en_page import (CmdImage, CmdLigne, CmdOvale, CmdRect, CmdTexte, Contexte, LayoutDocument,
                           option_choisie, options_de, valeur_champ)
from .reseau import ClientHTTP, ErreurReseau, URL, encoder_formulaire, pourcent_decoder
from .stockage import Stockage

NOM = "Navigateur Maison"
PAS_DEFILEMENT = 60
NIVEAUX_ZOOM = [0.5, 0.67, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

COULEURS = {
    "barre": "#e8eaf0", "onglet": "#d3d7e2", "onglet_actif": "#ffffff", "texte": "#20232a",
    "bouton_survol": "#cfd4e0", "etat": "#f3f4f7",
}


# ---------------------------------------------------------------------------
# Polices et images Tk
# ---------------------------------------------------------------------------

class PolicesTk:
    """Fournit la mesure du texte à la mise en page, avec cache."""

    def __init__(self):
        self.polices = {}
        self.mesures = {}
        self.metriques_cache = {}

    def police(self, spec):
        police = self.polices.get(spec)
        if police is None:
            famille, taille, gras, italique, souligne, barre = spec
            police = tkfont.Font(family=famille, size=-taille, weight="bold" if gras else "normal",
                                 slant="italic" if italique else "roman",
                                 underline=souligne, overstrike=barre)
            self.polices[spec] = police
        return police

    def mesurer(self, spec, texte):
        cle = (spec, texte)
        largeur = self.mesures.get(cle)
        if largeur is None:
            largeur = self.police(spec).measure(texte)
            if len(self.mesures) > 200000:
                self.mesures.clear()
            self.mesures[cle] = largeur
        return largeur

    def metriques(self, spec):
        resultat = self.metriques_cache.get(spec)
        if resultat is None:
            metriques = self.police(spec).metrics()
            resultat = (metriques["ascent"], metriques["descent"])
            self.metriques_cache[spec] = resultat
        return resultat


class ImageTk:
    def __init__(self, photo):
        self.photo = photo
        self.largeur = photo.width()
        self.hauteur = photo.height()
        self.variantes = {}

    def pour_taille(self, largeur, hauteur):
        largeur, hauteur = max(1, int(round(largeur))), max(1, int(round(hauteur)))
        if abs(largeur - self.largeur) <= 2 and abs(hauteur - self.hauteur) <= 2:
            return self.photo
        cle = (largeur, hauteur)
        if cle not in self.variantes:
            fx, fy = self.largeur / largeur, self.hauteur / hauteur
            if fx >= 1 and fy >= 1:
                variante = self.photo.subsample(max(1, int(round(fx))), max(1, int(round(fy))))
            elif fx <= 1 and fy <= 1:
                variante = self.photo.zoom(max(1, int(round(1 / fx))), max(1, int(round(1 / fy))))
            else:
                variante = self.photo
            self.variantes[cle] = variante
        return self.variantes[cle]


def creer_image(octets):
    genre = format_image(octets)
    if genre is None:
        return None
    try:
        photo = tk.PhotoImage(data=base64.b64encode(octets).decode("ascii"))
    except tk.TclError:
        return None
    if photo.width() * photo.height() > 25_000_000 or photo.width() == 0:
        return None
    return ImageTk(photo)


# ---------------------------------------------------------------------------
# Saisie dans la barre d'adresse
# ---------------------------------------------------------------------------

_SCHEMAS = ("http://", "https://", "file://", "about:", "data:", "view-source:")


def interpreter_saisie(texte):
    texte = texte.strip()
    if not texte:
        return None
    if texte.lower().startswith(_SCHEMAS):
        return texte
    if texte.startswith(("/", "~")):
        return "file://" + os.path.abspath(os.path.expanduser(texte))
    if " " not in texte:
        hote = re.split(r"[/:?#]", texte, maxsplit=1)[0]
        est_ip = re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", hote) is not None
        if hote == "localhost" or est_ip:
            return "http://" + texte
        if "." in hote and re.fullmatch(r"[A-Za-z0-9.-]+", hote) and not hote.endswith("."):
            return "https://" + texte
    return pages_internes.url_recherche(texte)


# ---------------------------------------------------------------------------
# Onglet
# ---------------------------------------------------------------------------

class Onglet:
    def __init__(self, navigateur):
        self.nav = navigateur
        self.historique = []        # [(url str, corps)]
        self.index = -1
        self.page = None
        self.document = None
        self.contexte = None
        self.commandes = []
        self.zones = []
        self.defilement = 0
        self.titre = "Nouvel onglet"
        self.url = None
        self.chargement = False
        self.generation = 0
        self.champ_actif = None
        self.images = {}
        self.zoom = 1.0
        self.fond = "#ffffff"
        self.erreur = None

    # -- navigation ---------------------------------------------------------

    def naviguer(self, adresse, corps=None, ajouter=True, referent=None):
        try:
            url = URL(adresse) if not isinstance(adresse, URL) else adresse
        except ValueError as erreur:
            self._afficher_html(pages_internes.erreur(str(adresse), str(erreur)), "about:erreur")
            return
        if url.schema == "about" and self._action_interne(url):
            return
        # Ancre dans la page actuelle : on fait défiler sans recharger.
        if (corps is None and self.url is not None and url.fragment and self.page is not None
                and str(url.sans_fragment()) == str(self.url.sans_fragment())):
            if ajouter:
                self._ajouter_historique(str(url), None)
            self.url = url
            self.aller_ancre(url.fragment)
            self.nav.mettre_a_jour()
            return
        if ajouter:
            self._ajouter_historique(str(url), corps)
        self._charger(url, corps, referent)

    def _ajouter_historique(self, adresse, corps):
        del self.historique[self.index + 1:]
        self.historique.append((adresse, corps))
        self.index = len(self.historique) - 1

    def _action_interne(self, url):
        chemin = url.chemin
        if chemin.startswith("historique?effacer"):
            self.nav.stockage.effacer_historique()
            self.naviguer("about:historique", ajouter=False)
            return True
        if chemin.startswith("favoris?supprimer="):
            self.nav.stockage.supprimer_favori(pourcent_decoder(chemin.split("=", 1)[1]))
            self.naviguer("about:favoris", ajouter=False)
            return True
        return False

    def _charger(self, url, corps=None, referent=None):
        self.generation += 1
        generation = self.generation
        self.chargement = True
        self.url = url
        self.erreur = None
        self.nav.mettre_a_jour()
        methode = "POST" if corps is not None else "GET"

        def travail():
            try:
                resultat = charger_page(self.nav.client, url, methode, corps, referent, self.nav.stockage,
                                        annule=lambda: generation != self.generation)
            except ErreurReseau as erreur:
                resultat = erreur
            except Exception as erreur:  # on ne veut jamais faire planter la fenêtre
                resultat = ErreurReseau("Erreur interne : %s: %s" % (type(erreur).__name__, erreur))
            self.nav.file.put((self, generation, resultat))

        threading.Thread(target=travail, daemon=True).start()

    def arreter(self):
        self.generation += 1
        self.chargement = False
        self.nav.mettre_a_jour()

    def recevoir(self, generation, resultat):
        if generation != self.generation:
            return
        self.chargement = False
        if isinstance(resultat, Exception):
            self.erreur = str(resultat)
            url = self.url
            self._afficher_html(pages_internes.erreur(str(url), str(resultat)), str(url), garder_url=True)
            return
        self.page = resultat
        self.url = resultat.url
        if self.index >= 0:
            self.historique[self.index] = (str(resultat.url), self.historique[self.index][1])
        self.titre = resultat.titre or str(resultat.url)
        self.champ_actif = None
        self.images = {}
        for adresse, octets in resultat.images.items():
            image = creer_image(octets)
            if image is not None:
                self.images[adresse] = image
        self.defilement = 0
        self.mettre_en_page()
        if self.url.fragment:
            self.aller_ancre(self.url.fragment)
        self.nav.stockage.ajouter_historique(str(self.url), self.titre)
        self.nav.mettre_a_jour()

    def _afficher_html(self, html, adresse, garder_url=False):
        page = construire_page(None, URL("about:blank"), html, lambda: False, ressources=False)
        page.url = self.url if garder_url and self.url is not None else URL("about:blank")
        self.page = page
        self.titre = page.titre or adresse
        self.images = {}
        self.defilement = 0
        self.chargement = False
        self.mettre_en_page()
        self.nav.mettre_a_jour()

    def precedent(self):
        if self.index > 0:
            self.index -= 1
            adresse, corps = self.historique[self.index]
            self.naviguer(adresse, corps, ajouter=False)

    def suivant(self):
        if self.index < len(self.historique) - 1:
            self.index += 1
            adresse, corps = self.historique[self.index]
            self.naviguer(adresse, corps, ajouter=False)

    def recharger(self):
        if self.index >= 0:
            adresse, corps = self.historique[self.index]
            self.nav.client.cache.entrees.clear()
            position = self.defilement
            self._charger(URL(adresse), corps)
            self._defilement_apres = position

    # -- mise en page et dessin ------------------------------------------

    def mettre_en_page(self):
        if self.page is None:
            return
        largeur = max(200, self.nav.canevas.winfo_width())
        self.contexte = Contexte(self.nav.polices, self.images, self.zoom, self.champ_actif)
        self.contexte.url_images = self.page.url_images
        self.document = LayoutDocument(self.page.dom, self.contexte)
        self.document.mise_en_page(largeur)
        self.fond = self.document.couleur_fond()
        self.peindre()
        position = getattr(self, "_defilement_apres", None)
        if position is not None:
            self.defilement = position
            self._defilement_apres = None
        self.borner_defilement()

    def peindre(self):
        if self.document is None:
            return
        self.contexte.champ_actif = self.champ_actif
        self.commandes, self.zones = self.document.peindre()

    def hauteur_max(self):
        if self.document is None:
            return 0
        return max(0, self.document.hauteur - self.nav.canevas.winfo_height() + 20)

    def borner_defilement(self):
        self.defilement = max(0, min(self.defilement, self.hauteur_max()))

    def aller_ancre(self, nom):
        if self.contexte is None:
            return
        nom = pourcent_decoder(nom)
        if nom in self.contexte.ancres:
            self.defilement = self.contexte.ancres[nom]
        elif nom.lower() == "top" or nom == "":
            self.defilement = 0
        self.borner_defilement()
        self.nav.dessiner()

    # -- formulaires --------------------------------------------------------

    def soumettre(self, formulaire, bouton=None):
        paires = []
        for noeud in parcourir(formulaire):
            if not isinstance(noeud, Element) or noeud.balise not in ("input", "select", "textarea", "button"):
                continue
            nom = noeud.attributs.get("name")
            if not nom or "disabled" in noeud.attributs:
                continue
            genre = noeud.attributs.get("type", "text" if noeud.balise == "input" else "submit").lower()
            if noeud.balise == "select":
                option = option_choisie(noeud)
                if option is not None:
                    paires.append((nom, option.attributs.get("value", option.texte_contenu().strip())))
            elif noeud.balise == "textarea":
                paires.append((nom, valeur_champ(noeud)))
            elif genre in ("submit", "button", "image", "reset") or noeud.balise == "button":
                if noeud is bouton and genre != "reset":
                    paires.append((nom, noeud.attributs.get("value", "")))
            elif genre in ("checkbox", "radio"):
                if "checked" in noeud.attributs:
                    paires.append((nom, noeud.attributs.get("value", "on")))
            elif genre != "file":
                paires.append((nom, noeud.attributs.get("value", "")))
        donnees = encoder_formulaire(paires)
        action = formulaire.attributs.get("action", "").strip()
        if bouton is not None and bouton.attributs.get("formaction"):
            action = bouton.attributs["formaction"]
        base = getattr(self.page, "base", self.url)
        try:
            cible = base.resoudre(action) if action else self.url.sans_fragment()
        except ValueError:
            return
        methode = formulaire.attributs.get("method", "get").lower()
        if bouton is not None and bouton.attributs.get("formmethod"):
            methode = bouton.attributs["formmethod"].lower()
        if methode == "post":
            self.naviguer(cible, corps=donnees, referent=self.url)
        else:
            adresse = str(cible.sans_fragment()).split("?")[0] + "?" + donnees
            self.naviguer(adresse, referent=self.url)

    def activer_champ(self, noeud, x_ecran, y_ecran):
        balise = noeud.balise
        genre = noeud.attributs.get("type", "text").lower() if balise == "input" else None
        formulaire = ancetre(noeud, "form")
        if "disabled" in noeud.attributs:
            return
        if genre == "checkbox":
            if "checked" in noeud.attributs:
                del noeud.attributs["checked"]
            else:
                noeud.attributs["checked"] = ""
        elif genre == "radio":
            nom = noeud.attributs.get("name")
            racine = formulaire or self.page.dom
            for autre in parcourir(racine):
                if (isinstance(autre, Element) and autre.balise == "input" and autre.attributs.get("type", "").lower() == "radio"
                        and autre.attributs.get("name") == nom):
                    autre.attributs.pop("checked", None)
            noeud.attributs["checked"] = ""
        elif balise == "select":
            self._menu_select(noeud, x_ecran, y_ecran)
            return
        elif balise == "button" or genre in ("submit", "image", "button", "reset"):
            genre_bouton = noeud.attributs.get("type", "submit").lower()
            if genre_bouton == "reset" and formulaire is not None:
                return
            if genre_bouton in ("submit", "image") and formulaire is not None:
                self.soumettre(formulaire, noeud)
            return
        else:
            self.champ_actif = noeud
        self.peindre()
        self.nav.dessiner()

    def _menu_select(self, noeud, x_ecran, y_ecran):
        menu = tk.Menu(self.nav.racine, tearoff=0)
        for option in options_de(noeud):
            def choisir(option=option):
                for autre in options_de(noeud):
                    autre.attributs.pop("selected", None)
                option.attributs["selected"] = ""
                self.peindre()
                self.nav.dessiner()
            menu.add_command(label=option.texte_contenu().strip() or " ", command=choisir)
        menu.tk_popup(x_ecran, y_ecran)

    def saisir(self, evenement):
        """Gère la frappe au clavier dans le champ actif. Renvoie True si consommée."""
        noeud = self.champ_actif
        if noeud is None:
            return False
        touche = evenement.keysym
        est_zone = noeud.balise == "textarea"
        valeur = valeur_champ(noeud)
        if touche == "BackSpace":
            valeur = valeur[:-1]
        elif touche in ("Return", "KP_Enter"):
            if est_zone:
                valeur += "\n"
            else:
                formulaire = ancetre(noeud, "form")
                if formulaire is not None:
                    self.soumettre(formulaire)
                return True
        elif touche == "Escape":
            self.champ_actif = None
            self.peindre()
            self.nav.dessiner()
            return True
        elif touche == "Tab":
            self._champ_suivant()
            return True
        elif evenement.char and evenement.char.isprintable() and not (evenement.state & 0x4):
            if "maxlength" in noeud.attributs and noeud.attributs["maxlength"].isdigit() \
                    and len(valeur) >= int(noeud.attributs["maxlength"]):
                return True
            valeur += evenement.char
        else:
            return False
        if est_zone:
            noeud.attributs["_valeur"] = valeur
        else:
            noeud.attributs["value"] = valeur
        self.peindre()
        self.nav.dessiner()
        return True

    def _champ_suivant(self):
        champs = [z.noeud for z in self.zones if z.genre == "champ"
                  and (z.noeud.balise == "textarea" or (z.noeud.balise == "input" and
                       z.noeud.attributs.get("type", "text").lower() in ("text", "search", "email", "url", "password", "tel", "number")))]
        if not champs:
            return
        if self.champ_actif in champs:
            suivant = champs[(champs.index(self.champ_actif) + 1) % len(champs)]
        else:
            suivant = champs[0]
        self.champ_actif = suivant
        self.peindre()
        self.nav.dessiner()


# ---------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------

class Navigateur:
    def __init__(self, url_initiale=None):
        self.racine = tk.Tk()
        self.racine.title(NOM)
        self.racine.geometry("1100x760")
        self.racine.minsize(420, 300)
        self.client = ClientHTTP()
        self.stockage = Stockage()
        self.polices = PolicesTk()
        self.file = queue.Queue()
        self.onglets = []
        self.actif = None
        self.correspondances = []
        self.index_correspondance = -1
        self._largeur_precedente = None
        self._relayout_prevu = None

        self._construire_interface()
        self._raccourcis()
        self.racine.after(30, self._traiter_file)
        self.nouvel_onglet(url_initiale or pages_internes.PAGE_ACCUEIL)

    # -- construction -----------------------------------------------------------

    def _bouton(self, parent, texte, commande, info=None):
        bouton = tk.Button(parent, text=texte, command=commande, relief="flat", bd=0, padx=8, pady=3,
                           bg=COULEURS["barre"], activebackground=COULEURS["bouton_survol"],
                           font=("Helvetica", 13), cursor="hand2")
        bouton.bind("<Enter>", lambda e: (bouton.configure(bg=COULEURS["bouton_survol"]), self._etat(info or "")))
        bouton.bind("<Leave>", lambda e: (bouton.configure(bg=COULEURS["barre"]), self._etat("")))
        return bouton

    def _construire_interface(self):
        racine = self.racine
        racine.configure(bg=COULEURS["barre"])

        self.barre_onglets = tk.Frame(racine, bg=COULEURS["barre"])
        self.barre_onglets.pack(fill="x", padx=4, pady=(4, 0))

        outils = tk.Frame(racine, bg=COULEURS["barre"])
        outils.pack(fill="x", padx=4, pady=4)
        self.bouton_precedent = self._bouton(outils, "◀", lambda: self.actif.precedent(), "Page précédente (Alt+←)")
        self.bouton_suivant = self._bouton(outils, "▶", lambda: self.actif.suivant(), "Page suivante (Alt+→)")
        self.bouton_recharger = self._bouton(outils, "⟳", self._recharger_ou_arreter, "Recharger (F5)")
        self.bouton_accueil = self._bouton(outils, "⌂", lambda: self.actif.naviguer(pages_internes.PAGE_ACCUEIL), "Accueil")
        for bouton in (self.bouton_precedent, self.bouton_suivant, self.bouton_recharger, self.bouton_accueil):
            bouton.pack(side="left")

        self.adresse = tk.Entry(outils, font=("Helvetica", 13), relief="flat", bd=6,
                                highlightthickness=1, highlightcolor="#4a7bd8", highlightbackground="#c4c9d6")
        self.adresse.pack(side="left", fill="x", expand=True, padx=6)
        self.adresse.bind("<Return>", self._valider_adresse)
        self.adresse.bind("<FocusIn>", lambda e: self.adresse.after(1, lambda: self.adresse.select_range(0, "end")))

        self.bouton_favori = self._bouton(outils, "☆", self.basculer_favori, "Ajouter aux favoris (Ctrl+D)")
        self.bouton_favori.pack(side="left")
        self.bouton_menu = self._bouton(outils, "☰", self._ouvrir_menu, "Menu")
        self.bouton_menu.pack(side="left")

        self.barre_recherche = tk.Frame(racine, bg=COULEURS["etat"])
        tk.Label(self.barre_recherche, text="Rechercher :", bg=COULEURS["etat"]).pack(side="left", padx=4)
        self.champ_recherche = tk.Entry(self.barre_recherche, width=30)
        self.champ_recherche.pack(side="left", pady=3)
        self.champ_recherche.bind("<KeyRelease>", self._chercher)
        self.champ_recherche.bind("<Return>", lambda e: self._correspondance_suivante())
        self.champ_recherche.bind("<Escape>", lambda e: self.fermer_recherche())
        tk.Button(self.barre_recherche, text="Suivant", command=self._correspondance_suivante, relief="flat").pack(side="left", padx=4)
        self.compteur_recherche = tk.Label(self.barre_recherche, text="", bg=COULEURS["etat"])
        self.compteur_recherche.pack(side="left")
        tk.Button(self.barre_recherche, text="✕", command=self.fermer_recherche, relief="flat").pack(side="right", padx=4)

        self.barre_etat = tk.Label(racine, text="", anchor="w", bg=COULEURS["etat"], fg="#444", font=("Helvetica", 11))
        self.barre_etat.pack(side="bottom", fill="x")

        zone = tk.Frame(racine)
        zone.pack(fill="both", expand=True)
        self.ascenseur = tk.Scrollbar(zone, orient="vertical", command=self._defiler_barre)
        self.ascenseur.pack(side="right", fill="y")
        self.canevas = tk.Canvas(zone, bg="white", highlightthickness=0, takefocus=1)
        self.canevas.pack(side="left", fill="both", expand=True)

        self.canevas.bind("<Configure>", self._redimensionnement)
        self.canevas.bind("<Button-1>", self._clic)
        self.canevas.bind("<Button-2>", lambda e: self._clic(e, nouvel_onglet=True))
        self.canevas.bind("<Button-3>", self._menu_contextuel)
        self.canevas.bind("<Motion>", self._survol)
        self.canevas.bind("<MouseWheel>", lambda e: self.defiler(-PAS_DEFILEMENT * (1 if e.delta > 0 else -1)))
        self.canevas.bind("<Button-4>", lambda e: self.defiler(-PAS_DEFILEMENT))
        self.canevas.bind("<Button-5>", lambda e: self.defiler(PAS_DEFILEMENT))
        self.canevas.bind("<Key>", self._touche_canevas)

    def _raccourcis(self):
        r = self.racine
        r.bind_all("<Control-l>", lambda e: self._focus_adresse())
        r.bind_all("<F6>", lambda e: self._focus_adresse())
        r.bind_all("<Control-t>", lambda e: self.nouvel_onglet(pages_internes.PAGE_ACCUEIL))
        r.bind_all("<Control-w>", lambda e: self.fermer_onglet(self.actif))
        r.bind_all("<Control-Tab>", lambda e: self._onglet_relatif(1))
        r.bind_all("<Control-ISO_Left_Tab>", lambda e: self._onglet_relatif(-1))
        r.bind_all("<Alt-Left>", lambda e: self.actif.precedent())
        r.bind_all("<Alt-Right>", lambda e: self.actif.suivant())
        r.bind_all("<F5>", lambda e: self.actif.recharger())
        r.bind_all("<Control-r>", lambda e: self.actif.recharger())
        r.bind_all("<Control-d>", lambda e: self.basculer_favori())
        r.bind_all("<Control-h>", lambda e: self.nouvel_onglet("about:historique"))
        r.bind_all("<Control-f>", lambda e: self.ouvrir_recherche())
        r.bind_all("<Control-u>", lambda e: self.voir_source())
        r.bind_all("<Control-plus>", lambda e: self.zoomer(1))
        r.bind_all("<Control-equal>", lambda e: self.zoomer(1))
        r.bind_all("<Control-KP_Add>", lambda e: self.zoomer(1))
        r.bind_all("<Control-minus>", lambda e: self.zoomer(-1))
        r.bind_all("<Control-KP_Subtract>", lambda e: self.zoomer(-1))
        r.bind_all("<Control-0>", lambda e: self.zoomer(0))

    # -- onglets ---------------------------------------------------------------

    def nouvel_onglet(self, adresse=None, activer=True, referent=None):
        onglet = Onglet(self)
        position = self.onglets.index(self.actif) + 1 if self.actif in self.onglets else len(self.onglets)
        self.onglets.insert(position, onglet)
        if activer or self.actif is None:
            self.actif = onglet
        self.mettre_a_jour()
        self.racine.update_idletasks()
        onglet.naviguer(adresse or pages_internes.PAGE_ACCUEIL, referent=referent)
        if activer:
            self.canevas.focus_set()
        return onglet

    def fermer_onglet(self, onglet):
        if onglet not in self.onglets:
            return
        index = self.onglets.index(onglet)
        onglet.generation += 1
        self.onglets.remove(onglet)
        if not self.onglets:
            self.racine.destroy()
            return
        if onglet is self.actif:
            self.actif = self.onglets[min(index, len(self.onglets) - 1)]
            self._relayout_si_necessaire()
        self.mettre_a_jour()

    def activer(self, onglet):
        self.actif = onglet
        self._relayout_si_necessaire()
        self.mettre_a_jour()

    def _onglet_relatif(self, decalage):
        index = (self.onglets.index(self.actif) + decalage) % len(self.onglets)
        self.activer(self.onglets[index])
        return "break"

    def _relayout_si_necessaire(self):
        onglet = self.actif
        if onglet.document is not None and onglet.document.largeur != max(200, self.canevas.winfo_width()):
            onglet.mettre_en_page()

    # -- mise à jour de l'interface -----------------------------------------

    def mettre_a_jour(self):
        onglet = self.actif
        if onglet is None:
            return
        self._dessiner_onglets()
        adresse = str(onglet.url) if onglet.url is not None else ""
        if self.racine.focus_get() is not self.adresse:
            self.adresse.delete(0, "end")
            self.adresse.insert(0, "" if adresse == pages_internes.PAGE_ACCUEIL else adresse)
        self.bouton_precedent.configure(state="normal" if onglet.index > 0 else "disabled")
        self.bouton_suivant.configure(state="normal" if onglet.index < len(onglet.historique) - 1 else "disabled")
        self.bouton_recharger.configure(text="✕" if onglet.chargement else "⟳")
        self.bouton_favori.configure(text="★" if self.stockage.est_favori(adresse) else "☆")
        self.racine.title("%s — %s" % (onglet.titre, NOM) if onglet.titre else NOM)
        if onglet.chargement:
            self._etat("Chargement de %s…" % adresse)
        elif onglet.erreur:
            self._etat(onglet.erreur)
        else:
            self._etat("")
        self.dessiner()

    def _dessiner_onglets(self):
        for enfant in self.barre_onglets.winfo_children():
            enfant.destroy()
        largeur = max(8, min(28, 160 // max(1, len(self.onglets))))
        for onglet in self.onglets:
            actif = onglet is self.actif
            fond = COULEURS["onglet_actif"] if actif else COULEURS["onglet"]
            cadre = tk.Frame(self.barre_onglets, bg=fond, padx=6, pady=3)
            cadre.pack(side="left", padx=(0, 2))
            titre = ("⏳ " if onglet.chargement else "") + (onglet.titre or "Nouvel onglet")
            if len(titre) > largeur:
                titre = titre[:largeur - 1] + "…"
            etiquette = tk.Label(cadre, text=titre, bg=fond, fg=COULEURS["texte"], font=("Helvetica", 11),
                                 cursor="hand2")
            etiquette.pack(side="left")
            fermer = tk.Label(cadre, text=" ✕", bg=fond, fg="#666", font=("Helvetica", 10), cursor="hand2")
            fermer.pack(side="left")
            for widget in (cadre, etiquette):
                widget.bind("<Button-1>", lambda e, o=onglet: self.activer(o))
                widget.bind("<Button-2>", lambda e, o=onglet: self.fermer_onglet(o))
            fermer.bind("<Button-1>", lambda e, o=onglet: self.fermer_onglet(o))
        plus = tk.Label(self.barre_onglets, text=" + ", bg=COULEURS["barre"], font=("Helvetica", 13, "bold"), cursor="hand2")
        plus.pack(side="left")
        plus.bind("<Button-1>", lambda e: self.nouvel_onglet(pages_internes.PAGE_ACCUEIL))

    def _etat(self, texte):
        self.barre_etat.configure(text=" " + texte)

    def dessiner(self):
        canevas = self.canevas
        canevas.delete("all")
        onglet = self.actif
        if onglet is None:
            return
        canevas.configure(bg=onglet.fond)
        hauteur = canevas.winfo_height()
        haut = onglet.defilement
        bas = haut + hauteur
        polices = self.polices
        surlignes = set(id(c) for c in self.correspondances)
        courante = self.correspondances[self.index_correspondance] if 0 <= self.index_correspondance < len(self.correspondances) else None
        for commande in onglet.commandes:
            if commande.bas < haut or commande.haut > bas:
                continue
            if isinstance(commande, CmdTexte):
                if id(commande) in surlignes:
                    canevas.create_rectangle(commande.x - 1, commande.y - haut, commande.x + commande.largeur + 1,
                                             commande.bas - haut, fill="#ff9632" if commande is courante else "#ffff00",
                                             outline="")
                canevas.create_text(commande.x, commande.y - haut, text=commande.texte, anchor="nw",
                                    font=polices.police(commande.police), fill=commande.couleur)
            elif isinstance(commande, CmdOvale):
                canevas.create_oval(commande.x1, commande.y1 - haut, commande.x2, commande.y2 - haut,
                                    fill=commande.couleur, outline=commande.contour or "", width=commande.epaisseur)
            elif isinstance(commande, CmdRect):
                canevas.create_rectangle(commande.x1, commande.y1 - haut, commande.x2, commande.y2 - haut,
                                         fill=commande.couleur, outline=commande.contour or "",
                                         width=commande.epaisseur if commande.contour else 0)
            elif isinstance(commande, CmdLigne):
                canevas.create_line(commande.x1, commande.y1 - haut, commande.x2, commande.y2 - haut,
                                    fill=commande.couleur, width=commande.epaisseur)
            elif isinstance(commande, CmdImage):
                photo = commande.image.pour_taille(commande.largeur, commande.hauteur)
                canevas.create_image(commande.x, commande.y - haut, image=photo, anchor="nw")
        total = onglet.document.hauteur if onglet.document is not None else 0
        if total > hauteur > 0:
            self.ascenseur.set(haut / total, min(1.0, bas / total))
        else:
            self.ascenseur.set(0, 1)

    # -- évènements -----------------------------------------------------------

    def _traiter_file(self):
        try:
            while True:
                onglet, generation, resultat = self.file.get_nowait()
                if onglet in self.onglets:
                    onglet.recevoir(generation, resultat)
                    if onglet is not self.actif:
                        self._dessiner_onglets()
        except queue.Empty:
            pass
        self.racine.after(30, self._traiter_file)

    def _valider_adresse(self, evenement=None):
        adresse = interpreter_saisie(self.adresse.get())
        if adresse:
            self.canevas.focus_set()
            self.actif.naviguer(adresse)
        return "break"

    def _focus_adresse(self):
        self.adresse.focus_set()
        self.adresse.select_range(0, "end")
        return "break"

    def _recharger_ou_arreter(self):
        if self.actif.chargement:
            self.actif.arreter()
        else:
            self.actif.recharger()

    def _redimensionnement(self, evenement):
        if evenement.width == self._largeur_precedente:
            self.dessiner()
            return
        self._largeur_precedente = evenement.width
        if self._relayout_prevu is not None:
            self.racine.after_cancel(self._relayout_prevu)

        def relayout():
            self._relayout_prevu = None
            if self.actif is not None and self.actif.page is not None:
                self.actif.mettre_en_page()
            self.dessiner()

        self._relayout_prevu = self.racine.after(120, relayout)

    def defiler(self, delta):
        onglet = self.actif
        onglet.defilement += delta
        onglet.borner_defilement()
        self.dessiner()

    def _defiler_barre(self, action, *arguments):
        onglet = self.actif
        if onglet.document is None:
            return
        hauteur = self.canevas.winfo_height()
        if action == "moveto":
            onglet.defilement = float(arguments[0]) * onglet.document.hauteur
        elif action == "scroll":
            quantite = int(arguments[0])
            onglet.defilement += quantite * (hauteur * 0.9 if arguments[1] == "pages" else PAS_DEFILEMENT)
        onglet.borner_defilement()
        self.dessiner()

    def _zone_a(self, x, y):
        onglet = self.actif
        y_document = y + onglet.defilement
        for zone in reversed(onglet.zones):
            if zone.contient(x, y_document):
                return zone
        return None

    def _clic(self, evenement, nouvel_onglet=False):
        self.canevas.focus_set()
        onglet = self.actif
        zone = self._zone_a(evenement.x, evenement.y)
        if onglet.champ_actif is not None and (zone is None or zone.noeud is not onglet.champ_actif):
            onglet.champ_actif = None
            onglet.peindre()
            self.dessiner()
        if zone is None:
            return
        if zone.genre == "lien":
            self.suivre_lien(zone.noeud, nouvel_onglet or bool(evenement.state & 0x4))
        elif zone.genre == "champ":
            onglet.activer_champ(zone.noeud, evenement.x_root, evenement.y_root)

    def suivre_lien(self, lien, nouvel_onglet=False):
        onglet = self.actif
        href = lien.attributs.get("href", "")
        try:
            base = getattr(onglet.page, "base", onglet.url) or onglet.url
            cible = base.resoudre(href)
        except ValueError:
            self._etat("Lien non pris en charge : %s" % href)
            return
        if nouvel_onglet or lien.attributs.get("target", "").lower() == "_blank":
            self.nouvel_onglet(str(cible), activer=not nouvel_onglet, referent=onglet.url)
        else:
            onglet.naviguer(cible, referent=onglet.url)

    def _survol(self, evenement):
        zone = self._zone_a(evenement.x, evenement.y)
        if zone is not None and zone.genre == "lien":
            self.canevas.configure(cursor="hand2")
            try:
                base = getattr(self.actif.page, "base", self.actif.url)
                self._etat(str(base.resoudre(zone.noeud.attributs.get("href", ""))))
            except (ValueError, AttributeError):
                self._etat(zone.noeud.attributs.get("href", ""))
        elif zone is not None:
            genre = zone.noeud.attributs.get("type", "text").lower() if zone.noeud.balise == "input" else zone.noeud.balise
            self.canevas.configure(cursor="xterm" if genre in ("text", "search", "email", "url", "password", "textarea", "tel", "number") else "hand2")
        else:
            self.canevas.configure(cursor="")
            if not self.actif.chargement:
                self._etat("")

    def _touche_canevas(self, evenement):
        onglet = self.actif
        if onglet.saisir(evenement):
            return "break"
        hauteur = self.canevas.winfo_height()
        deplacements = {
            "Down": PAS_DEFILEMENT, "Up": -PAS_DEFILEMENT, "Next": hauteur * 0.9, "Prior": -hauteur * 0.9,
            "space": hauteur * 0.9, "Home": -10 ** 9, "End": 10 ** 9,
        }
        if evenement.keysym in deplacements:
            delta = deplacements[evenement.keysym]
            if evenement.keysym == "space" and evenement.state & 0x1:
                delta = -delta
            self.defiler(delta)
            return "break"
        if evenement.keysym == "BackSpace":
            onglet.precedent()
            return "break"
        return None

    def _menu_contextuel(self, evenement):
        zone = self._zone_a(evenement.x, evenement.y)
        menu = tk.Menu(self.racine, tearoff=0)
        if zone is not None and zone.genre == "lien":
            menu.add_command(label="Ouvrir le lien dans un nouvel onglet", command=lambda: self.suivre_lien(zone.noeud, True))
            menu.add_command(label="Copier l'adresse du lien", command=lambda: self._copier_lien(zone.noeud))
            menu.add_separator()
        menu.add_command(label="Précédent", command=self.actif.precedent)
        menu.add_command(label="Suivant", command=self.actif.suivant)
        menu.add_command(label="Recharger", command=self.actif.recharger)
        menu.add_separator()
        menu.add_command(label="Code source de la page", command=self.voir_source)
        menu.tk_popup(evenement.x_root, evenement.y_root)

    def _copier_lien(self, lien):
        try:
            base = getattr(self.actif.page, "base", self.actif.url)
            texte = str(base.resoudre(lien.attributs.get("href", "")))
        except ValueError:
            texte = lien.attributs.get("href", "")
        self.racine.clipboard_clear()
        self.racine.clipboard_append(texte)

    def _ouvrir_menu(self):
        menu = tk.Menu(self.racine, tearoff=0)
        menu.add_command(label="Nouvel onglet\tCtrl+T", command=lambda: self.nouvel_onglet(pages_internes.PAGE_ACCUEIL))
        menu.add_command(label="Historique\tCtrl+H", command=lambda: self.nouvel_onglet("about:historique"))
        menu.add_command(label="Favoris", command=lambda: self.nouvel_onglet("about:favoris"))
        menu.add_separator()
        menu.add_command(label="Rechercher dans la page\tCtrl+F", command=self.ouvrir_recherche)
        menu.add_command(label="Code source\tCtrl+U", command=self.voir_source)
        menu.add_command(label="Zoom avant\tCtrl++", command=lambda: self.zoomer(1))
        menu.add_command(label="Zoom arrière\tCtrl+-", command=lambda: self.zoomer(-1))
        menu.add_command(label="Taille réelle\tCtrl+0", command=lambda: self.zoomer(0))
        menu.add_separator()
        menu.add_command(label="Aide", command=lambda: self.nouvel_onglet("about:aide"))
        menu.add_command(label="Quitter", command=self.racine.destroy)
        x = self.bouton_menu.winfo_rootx()
        y = self.bouton_menu.winfo_rooty() + self.bouton_menu.winfo_height()
        menu.tk_popup(x, y)

    # -- fonctions ------------------------------------------------------------

    def basculer_favori(self):
        onglet = self.actif
        if onglet.url is None or onglet.url.schema in ("about", "view-source"):
            return
        ajoute = self.stockage.basculer_favori(str(onglet.url), onglet.titre)
        self._etat("Ajouté aux favoris" if ajoute else "Retiré des favoris")
        self.bouton_favori.configure(text="★" if ajoute else "☆")

    def voir_source(self):
        onglet = self.actif
        if onglet.url is not None and onglet.url.schema in ("http", "https", "file"):
            self.nouvel_onglet("view-source:" + str(onglet.url.sans_fragment()))

    def zoomer(self, sens):
        onglet = self.actif
        if sens == 0:
            onglet.zoom = 1.0
        else:
            proche = min(range(len(NIVEAUX_ZOOM)), key=lambda i: abs(NIVEAUX_ZOOM[i] - onglet.zoom))
            onglet.zoom = NIVEAUX_ZOOM[max(0, min(len(NIVEAUX_ZOOM) - 1, proche + sens))]
        onglet.mettre_en_page()
        self._etat("Zoom : %d %%" % round(onglet.zoom * 100))
        self.dessiner()
        return "break"

    def ouvrir_recherche(self):
        self.barre_recherche.pack(side="bottom", fill="x", before=self.barre_etat)
        self.champ_recherche.focus_set()
        self.champ_recherche.select_range(0, "end")
        return "break"

    def fermer_recherche(self):
        self.barre_recherche.pack_forget()
        self.correspondances = []
        self.index_correspondance = -1
        self.canevas.focus_set()
        self.dessiner()

    def _chercher(self, evenement=None):
        if evenement is not None and evenement.keysym in ("Return", "Escape"):
            return
        requete = self.champ_recherche.get().strip().lower()
        if not requete:
            self.correspondances = []
        else:
            self.correspondances = [c for c in self.actif.commandes if isinstance(c, CmdTexte) and requete in c.texte.lower()]
        self.index_correspondance = -1
        self._correspondance_suivante()

    def _correspondance_suivante(self):
        if not self.correspondances:
            self.compteur_recherche.configure(text="Aucun résultat" if self.champ_recherche.get() else "")
            self.dessiner()
            return
        self.index_correspondance = (self.index_correspondance + 1) % len(self.correspondances)
        commande = self.correspondances[self.index_correspondance]
        onglet = self.actif
        hauteur = self.canevas.winfo_height()
        if not onglet.defilement <= commande.y <= onglet.defilement + hauteur - 30:
            onglet.defilement = commande.y - hauteur / 3
            onglet.borner_defilement()
        self.compteur_recherche.configure(text="%d / %d" % (self.index_correspondance + 1, len(self.correspondances)))
        self.dessiner()

    def lancer(self):
        self.racine.mainloop()
