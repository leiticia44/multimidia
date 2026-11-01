"""Fenêtres des outils HyWebMap (Saleh, Papy, Bouhaï, Paris 8, ISKO 2001).

Chaque fenêtre suit une étape de l'article :

* FenetreAgent        § 2.1-2.2  agent Web paramétrable (profondeur, largeur) et base de données
* FenetreCarte        § 2.3-2.8  réseau virtuel : liens personnels, nœuds libres, typologie,
                                 agents de surveillance, navigation par niveau, par date, locale
* FenetreRecherche    § 2.6      méta-recherche (Copernic dans l'article ; ici Mojeek, Wikipédia, DuckDuckGo) :
                                 remplacer un nœud disparu, propositions « NP » de l'agent de profil
* FenetreAnnotation   § 2.9      annoter un passage, une page ou un nœud
* FenetreDictionnaire § 2.9      dictionnaire personnel de mots-clés et de synonymes
* exporter_reseau     § 2.10     génération d'un site HTML en deux cadres
* FenetreAnalyse                 profil de la page affichée et liens rompus

Les données sont gérées par ``reseau_personnel.ReseauPersonnel`` (réseau du lecteur)
et ``agent_web.BaseHyWebMap`` (sites analysés par l'agent).
"""

import os
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

from .agent_web import AgentWeb, BaseHyWebMap
from .reseau import ClientHTTP, ErreurReseau
from .reseau_personnel import liens_page, meta_recherche, profil_page, verifier_lien

ROUGE = "#b03a2e"
VERT = "#2e7d32"
GRIS = "#9e9e9e"
ORANGE = "#e65100"
POLICE = "Helvetica"


def base_de(nav):
    """La base de données de l'agent, ouverte une seule fois."""
    if getattr(nav, "_base_hywebmap", None) is None:
        nav._base_hywebmap = BaseHyWebMap(os.path.join(nav.stockage.dossier, "hywebmap.db"))
    return nav._base_hywebmap


def _existe(fenetre):
    try:
        return bool(fenetre.winfo_exists())
    except tk.TclError:
        return False


def exporter_reseau(nav, parent=None):
    """§ 2.10 : génération d'un site HTML à partir du réseau virtuel."""
    parent = parent or nav.racine
    nom = simpledialog.askstring("Export du réseau", "Nom du réseau :", initialvalue="Mon réseau personnel",
                                 parent=parent)
    if nom is None:
        return
    chemin = filedialog.asksaveasfilename(parent=parent, defaultextension=".html", initialfile="mon_reseau.html")
    if chemin:
        nav.stockage.reseau.exporter_html(chemin, nom)
        if messagebox.askyesno("Export", "Site généré : %s\n(et le dossier « %s_fichiers »).\n\n"
                               "L'ouvrir dans un nouvel onglet ?" % (chemin, os.path.splitext(os.path.basename(chemin))[0]),
                               parent=parent):
            nav.nouvel_onglet("file://" + chemin.replace("\\", "/"))


def surveiller_en_fond(nav, fin=None):
    """Agent de surveillance périodique (§ 2.6) : vérifie les nœuds sans ouvrir de fenêtre."""
    reseau = nav.stockage.reseau
    urls = [u for u in reseau.noeuds if u.startswith(("http://", "https://"))]
    resultats = {}

    def travail():
        client = ClientHTTP()
        for u in urls:
            code = verifier_lien(client, u)
            resultats[u] = "ok" if code is not None and code < 400 else "rompu"
        nav.file_outils.put(appliquer)

    def appliquer():
        for u, statut in resultats.items():
            if u in reseau.noeuds:
                reseau.noeuds[u]["statut"] = statut
        reseau.enregistrer()
        rompus = [u for u, s in resultats.items() if s == "rompu"]
        if rompus:
            nav._etat("Agent de surveillance : %d page(s) du réseau ne sont plus disponibles — "
                      "ouvrez la carte (Ctrl+M) puis « Vérifier les nœuds »." % len(rompus))
        nav.rafraichir_carte()
        if fin:
            fin(rompus)

    threading.Thread(target=travail, daemon=True).start()


# ---------------------------------------------------------------------------
# Agent Web et base de données (§ 2.1 et 2.2)
# ---------------------------------------------------------------------------

class FenetreAgent:
    def __init__(self, nav):
        self.nav = nav
        self.base = base_de(nav)
        self.messages = queue.Queue()
        self.exploration = None
        self.en_cours = False
        self._arret = False
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Agent Web — exploration et analyse d'un site")
        w.geometry("1060x600")

        haut = ttk.Frame(w, padding=8)
        haut.pack(fill="x")
        ttk.Label(haut, text="Page de départ :").grid(row=0, column=0, sticky="w")
        self.depart = ttk.Entry(haut, width=70)
        self.depart.grid(row=0, column=1, columnspan=6, sticky="we", padx=4)
        actuelle = nav.actif.url if nav.actif is not None else None
        if actuelle is not None and actuelle.schema in ("http", "https"):
            self.depart.insert(0, str(actuelle.sans_fragment()))

        self.profondeur = tk.IntVar(value=1)
        self.largeur = tk.IntVar(value=10)
        self.max_pages = tk.IntVar(value=60)
        for colonne, (texte, variable, mini, maxi) in enumerate((
                ("Profondeur (niveaux) :", self.profondeur, 0, 5),
                ("Largeur (liens suivis par page) :", self.largeur, 1, 100),
                ("Pages au maximum :", self.max_pages, 1, 500))):
            ttk.Label(haut, text=texte).grid(row=1, column=2 * colonne, sticky="w", pady=4)
            ttk.Spinbox(haut, from_=mini, to=maxi, width=5, textvariable=variable,
                        command=self._estimer).grid(row=1, column=2 * colonne + 1, sticky="w", padx=(2, 14))
        self.meme_site = tk.BooleanVar(value=True)
        self.verifier = tk.BooleanVar(value=True)
        self.rapatrier = tk.BooleanVar(value=False)
        ttk.Checkbutton(haut, text="Rester sur le même site", variable=self.meme_site).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(haut, text="Vérifier les liens non explorés (liens rompus)",
                        variable=self.verifier).grid(row=2, column=2, columnspan=2, sticky="w")
        ttk.Checkbutton(haut, text="Rapatrier une copie des pages",
                        variable=self.rapatrier).grid(row=2, column=4, columnspan=2, sticky="w")
        boutons = ttk.Frame(haut)
        boutons.grid(row=0, column=7, rowspan=3, sticky="ne", padx=(10, 0))
        self.bouton_lancer = ttk.Button(boutons, text="Lancer l'agent", command=self.lancer)
        self.bouton_lancer.pack(fill="x")
        ttk.Button(boutons, text="Arrêter", command=self.arreter).pack(fill="x", pady=4)
        ttk.Button(boutons, text="Voir sur la carte", command=self.ajouter_au_reseau).pack(fill="x")
        haut.columnconfigure(1, weight=1)

        self.estimation = ttk.Label(w, padding=(10, 0), foreground="#555")
        self.estimation.pack(fill="x")
        self.info = ttk.Label(w, padding=(10, 2), foreground=ROUGE)
        self.info.pack(fill="x")
        for variable in (self.profondeur, self.largeur, self.max_pages):
            variable.trace_add("write", lambda *a: self._estimer())
        self._estimer()

        choix = ttk.Frame(w, padding=(8, 2))
        choix.pack(fill="x")
        ttk.Label(choix, text="Explorations enregistrées dans la base :").pack(side="left")
        self.liste = ttk.Combobox(choix, state="readonly", width=80)
        self.liste.pack(side="left", padx=4)
        self.liste.bind("<<ComboboxSelected>>", lambda e: self._choisir())
        ttk.Button(choix, text="Supprimer", command=self._supprimer).pack(side="left")

        # Barre du bas placée AVANT le tableau : elle reste visible même si la fenêtre est petite.
        bas = ttk.Frame(w, padding=8)
        bas.pack(side="bottom", fill="x")
        ttk.Button(bas, text="Ajouter au réseau virtuel et ouvrir la carte",
                   command=self.ajouter_au_reseau).pack(side="left")
        ttk.Label(bas, text="Double-clic sur une ligne : ouvrir la page.", foreground="#777").pack(side="left", padx=10)

        carnet = ttk.Notebook(w)
        carnet.pack(fill="both", expand=True, padx=8, pady=6)
        self.table_noeuds = self._table(carnet, "Nœuds", (
            ("niveau", "Niv.", 40), ("type", "Type", 70), ("statut", "HTTP", 50), ("titre", "Titre", 230),
            ("car", "Caract.", 60), ("img", "Images", 55), ("int", "Liens int.", 65), ("ext", "Liens ext.", 65),
            ("scr", "Scripts", 55), ("url", "Adresse", 330)))
        self.table_liens = self._table(carnet, "Liens (liaisons)", (
            ("type", "Type de lien", 100), ("texte", "Texte de l'ancre", 220), ("de", "De", 330), ("vers", "Vers", 330)))
        cadre = ttk.Frame(carnet, padding=10)
        carnet.add(cadre, text="Synthèse")
        self.synthese = tk.Text(cadre, wrap="word", font=(POLICE, 11), height=10, relief="flat", bg="#fbfaf7")
        self.synthese.pack(fill="both", expand=True)
        for table in (self.table_noeuds, self.table_liens):
            table.tag_configure("rompu", foreground="#c62828")
            table.tag_configure("non", foreground="#888")
            table.bind("<Double-1>", lambda e, t=table: self._ouvrir(t))

        self._remplir_liste()
        w.protocol("WM_DELETE_WINDOW", self._fermer)

    def _table(self, carnet, titre, colonnes):
        cadre = ttk.Frame(carnet)
        carnet.add(cadre, text=titre)
        table = ttk.Treeview(cadre, columns=[c for c, _, _ in colonnes], show="headings", height=10)
        for c, texte, largeur in colonnes:
            table.heading(c, text=texte)
            table.column(c, width=largeur, stretch=c in ("titre", "url", "de", "vers", "texte"))
        defil = ttk.Scrollbar(cadre, command=table.yview)
        table.configure(yscrollcommand=defil.set)
        defil.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        return table

    def _estimer(self):
        try:
            k, n, maxi = self.largeur.get(), self.profondeur.get(), self.max_pages.get()
        except (tk.TclError, ValueError):
            return
        total = sum(k ** i for i in range(n + 1))
        self.estimation.configure(text="Avec %d lien(s) par page sur %d niveau(x), l'agent peut rencontrer jusqu'à "
                                       "%s pages (croissance en k^n, § 2.1) ; il s'arrêtera à %d." % (
                                           k, n, "{:,}".format(total).replace(",", " "), maxi))

    def _remplir_liste(self):
        self.explorations = self.base.explorations()
        self.liste["values"] = ["n° %d — %s — %s (prof. %d, larg. %d, %d pages)" % (
            e["id"], e["date"], e["url_depart"], e["profondeur"], e["largeur"], e["nb_pages"]) for e in self.explorations]

    def _choisir(self):
        index = self.liste.current()
        if 0 <= index < len(self.explorations):
            self.afficher(self.explorations[index]["id"])

    def _supprimer(self):
        if self.exploration is None:
            return
        if messagebox.askyesno("Agent Web", "Supprimer cette exploration de la base ?", parent=self.fenetre):
            self.base.supprimer_exploration(self.exploration)
            self.exploration = None
            for table in (self.table_noeuds, self.table_liens):
                table.delete(*table.get_children())
            self.synthese.delete("1.0", "end")
            self.liste.set("")
            self._remplir_liste()

    # -- exploration ---------------------------------------------------------
    def lancer(self):
        if self.en_cours:
            return
        depart = self.depart.get().strip()
        if not depart:
            messagebox.showinfo("Agent Web", "Indiquez la page de départ.", parent=self.fenetre)
            return
        if "://" not in depart:
            depart = "https://" + depart
        self.en_cours, self._arret = True, False
        self.bouton_lancer.state(["disabled"])
        dossier = os.path.join(self.nav.stockage.dossier, "copies") if self.rapatrier.get() else None
        options = dict(profondeur=self.profondeur.get(), largeur=self.largeur.get(), meme_site=self.meme_site.get(),
                       max_pages=self.max_pages.get(), verifier_liens=self.verifier.get())

        def travail():
            try:
                agent = AgentWeb(ClientHTTP(), self.base, dossier)
                ident = agent.explorer(depart, rappel=lambda m: self.messages.put(("info", m)),
                                       annule=lambda: self._arret, **options)
                self.messages.put(("fin", ident))
            except (ErreurReseau, ValueError, OSError) as erreur:
                self.messages.put(("erreur", str(erreur)))

        threading.Thread(target=travail, daemon=True).start()
        self._lire()

    def arreter(self):
        self._arret = True

    def _lire(self):
        if not _existe(self.fenetre):
            self._arret = True
            return
        try:
            while True:
                genre, valeur = self.messages.get_nowait()
                if genre == "info":
                    self.info.configure(text=valeur)
                elif genre == "erreur":
                    self.info.configure(text="Erreur : %s" % valeur)
                    self._fini()
                    return
                else:
                    self._fini()
                    self._remplir_liste()
                    self.afficher(valeur)
                    return
        except queue.Empty:
            pass
        self.fenetre.after(120, self._lire)

    def _fini(self):
        self.en_cours = False
        self.bouton_lancer.state(["!disabled"])

    def _fermer(self):
        self._arret = True
        self.fenetre.destroy()

    # -- affichage des résultats de la base -------------------------------
    def afficher(self, exploration):
        self.exploration = exploration
        for i, e in enumerate(self.explorations):
            if e["id"] == exploration:
                self.liste.current(i)
        noeuds = self.base.noeuds(exploration)
        liaisons = self.base.liaisons(exploration)
        self.lignes = {}
        t = self.table_noeuds
        t.delete(*t.get_children())
        for n in noeuds:
            statut = n["statut"]
            tag = "rompu" if statut is not None and (statut == 0 or statut >= 400) else ("" if n["explore"] else "non")
            iid = t.insert("", "end", tags=(tag,), values=(
                n["niveau"], n["type"], "—" if statut is None else ("injoignable" if statut == 0 else statut),
                (n["titre"] or "") if n["explore"] else "(non exploré)", _v(n["nb_caracteres"]), _v(n["nb_images"]),
                _v(n["nb_liens_internes"]), _v(n["nb_liens_externes"]), _v(n["nb_scripts"]), n["url"]))
            self.lignes[(t, iid)] = n["url"]
        t = self.table_liens
        t.delete(*t.get_children())
        for l in liaisons:
            iid = t.insert("", "end", tags=("rompu",) if "rompu" in (l["type"] or "") else (),
                           values=(l["type"], l["texte"] or "", l["de"], l["vers"]))
            self.lignes[(t, iid)] = l["vers"]
        types_noeuds, types_liens = self.base.compter(exploration)
        exp = next((e for e in self.explorations if e["id"] == exploration), None)
        self.synthese.delete("1.0", "end")
        lignes = []
        if exp:
            lignes.append("Exploration n° %d du %s\nDépart : %s\nProfondeur %d, largeur %d — %d page(s) analysée(s)\n"
                          % (exp["id"], exp["date"], exp["url_depart"], exp["profondeur"], exp["largeur"], exp["nb_pages"]))
        lignes.append("Types de nœuds (§ 2.5) : " + ", ".join("%s %d" % (k, v) for k, v in sorted(types_noeuds.items())))
        lignes.append("Types de liens (§ 2.5) : " + ", ".join("%s %d" % (k, v) for k, v in sorted(types_liens.items())))
        rompus = types_liens.get("interne rompu", 0) + types_liens.get("externe rompu", 0)
        lignes.append("\nLiens obsolètes ou rompus : %d" % rompus)
        lignes.append("\nTables de la base : noeud, ancre, liaison (Document-A, Document-B, Lien-L), "
                      "profil, propriete — fichier %s" % self.base.chemin)
        self.synthese.insert("1.0", "\n".join(lignes))
        self.info.configure(text="Exploration n° %d : %d nœuds, %d liaisons." % (exploration, len(noeuds), len(liaisons)))

    def _ouvrir(self, table):
        selection = table.selection()
        if selection and (table, selection[0]) in self.lignes:
            self.nav.nouvel_onglet(self.lignes[(table, selection[0])])

    def ajouter_au_reseau(self):
        if self.exploration is None:
            messagebox.showinfo("Agent Web", "Lancez ou choisissez d'abord une exploration.", parent=self.fenetre)
            return
        reseau = self.nav.stockage.reseau
        ajoutes = reseau.importer_exploration(self.base.noeuds(self.exploration), self.base.liaisons(self.exploration))
        self.info.configure(text="%d nœud(s) ajouté(s) au réseau virtuel." % ajoutes)
        self.nav.ouvrir_carte()


def _v(valeur):
    return "" if valeur is None else valeur


# ---------------------------------------------------------------------------
# Annotation (§ 2.9)
# ---------------------------------------------------------------------------

class FenetreAnnotation:
    def __init__(self, nav, onglet=None, passage="", adresse=None, titre=None):
        self.nav, self.onglet = nav, onglet
        self.adresse = adresse or str(onglet.url.sans_fragment())
        self.titre = titre or (onglet.titre if onglet else self.adresse)
        reseau = nav.stockage.reseau
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Annoter — " + self.titre)
        w.geometry("540x490")
        w.transient(nav.racine)
        cadre = ttk.Frame(w, padding=12)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text=self.titre, font=(POLICE, 12, "bold")).pack(anchor="w")
        ttk.Label(cadre, text=self.adresse, foreground="#777").pack(anchor="w", pady=(0, 8))

        ttk.Label(cadre, text="Passage annoté (sélection dans la page, facultatif) :").pack(anchor="w")
        self.passage = tk.Text(cadre, height=3, wrap="word", font=(POLICE, 11), bg="#f2fbf2")
        self.passage.insert("1.0", passage)
        self.passage.pack(fill="x", pady=(2, 8))
        ttk.Label(cadre, text="Note (texte, et adresses http://… qui deviendront des liens) :").pack(anchor="w")
        self.note = tk.Text(cadre, height=5, wrap="word", font=(POLICE, 11))
        self.note.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(cadre, text="Mots-clés / métadonnées (séparés par des virgules) :").pack(anchor="w")
        self.mots = ttk.Entry(cadre)
        self.mots.pack(fill="x", pady=(2, 8))

        existantes = reseau.annotations_de(self.adresse)
        if existantes:
            ttk.Label(cadre, text="%d annotation(s) déjà sur cette page (about:annotations)." % len(existantes),
                      foreground=VERT).pack(anchor="w")
            perdues = [a for a in existantes if a.get("introuvable")]
            if perdues:
                ttk.Label(cadre, text="%d passage(s) annoté(s) introuvable(s) : la page a changé depuis."
                          % len(perdues), foreground="#888").pack(anchor="w")
        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x", pady=(8, 0))
        ttk.Button(boutons, text="Enregistrer", command=self.enregistrer).pack(side="right")
        ttk.Button(boutons, text="Annuler", command=w.destroy).pack(side="right", padx=6)
        self.note.focus_set()

    def enregistrer(self):
        note = self.note.get("1.0", "end").strip()
        passage = " ".join(self.passage.get("1.0", "end").split())
        if not note and not passage:
            messagebox.showwarning("Annotation", "Écrivez une note ou indiquez un passage.", parent=self.fenetre)
            return
        self.nav.stockage.reseau.annoter(self.adresse, self.titre, passage, note, self.mots.get())
        self.fenetre.destroy()
        if self.onglet is not None:
            self.nav.effacer_selection()
            self.onglet.reperer_annotations()
        self.nav.dessiner()
        self.nav.maj_panneau_annotations()
        self.nav.rafraichir_carte()
        self.nav._etat("Annotation enregistrée.")


class FenetreDictionnaire:
    """Dictionnaire personnel (§ 2.9) : chaque mot-clé et ses synonymes, utilisés pour chercher."""

    def __init__(self, nav):
        self.nav = nav
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Dictionnaire personnel")
        w.geometry("520x420")
        cadre = ttk.Frame(w, padding=12)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text="Une ligne par mot-clé :   mot-clé : synonyme, synonyme, …",
                  font=(POLICE, 11, "bold")).pack(anchor="w")
        ttk.Label(cadre, text="Exemple :   cartographie : carte, plan, réseau virtuel\n"
                              "La recherche d'annotations trouve aussi les synonymes.",
                  foreground="#666").pack(anchor="w", pady=(2, 8))
        self.texte = tk.Text(cadre, wrap="word", font=(POLICE, 11))
        self.texte.pack(fill="both", expand=True)
        self.texte.insert("1.0", nav.stockage.reseau.dictionnaire_texte())
        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x", pady=(8, 0))
        ttk.Button(boutons, text="Enregistrer", command=self.enregistrer).pack(side="right")
        ttk.Button(boutons, text="Annuler", command=w.destroy).pack(side="right", padx=6)

    def enregistrer(self):
        self.nav.stockage.reseau.charger_dictionnaire_texte(self.texte.get("1.0", "end"))
        self.fenetre.destroy()
        self.nav._etat("Dictionnaire personnel enregistré (%d mot(s)-clé(s))." % len(self.nav.stockage.reseau.dictionnaire))


# ---------------------------------------------------------------------------
# Méta-recherche (§ 2.6) : remplacer un nœud, affecter un nœud libre, propositions « NP »
# ---------------------------------------------------------------------------

class FenetreRecherche:
    """Lance la méta-recherche avec des mots-clés et propose les trois premières pages de chacun.

    mode « proposer »  : agent de gestion de profils — pages ajoutées au réseau avec la marque NP ;
    mode « remplacer » : agent de surveillance — la page choisie remplace un nœud parent disparu ;
    mode « affecter »  : agent d'aide à la création — la page choisie devient la ressource d'un nœud libre.
    """

    TITRES = {"proposer": "Propositions de l'agent de profil (NP)",
              "remplacer": "Remplacer un nœud indisponible",
              "affecter": "Chercher une ressource pour un nœud libre"}

    def __init__(self, nav, mots_cles, mode="proposer", cible=None):
        self.nav, self.mode, self.cible = nav, mode, cible
        self.reseau = nav.stockage.reseau
        self.resultats = queue.Queue()
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title(self.TITRES[mode])
        w.geometry("900x460")
        cadre = ttk.Frame(w, padding=10)
        cadre.pack(fill="both", expand=True)
        if cible:
            titre_cible = self.reseau.noeuds.get(cible, {}).get("titre") or cible
            ttk.Label(cadre, text="Nœud : %s" % titre_cible, font=(POLICE, 11, "bold")).pack(anchor="w")
        ttk.Label(cadre, text="Mots-clés : %s — méta-recherche (Mojeek, Wikipédia ou DuckDuckGo), 3 premières pages par mot-clé."
                  % ", ".join(mots_cles), foreground="#555").pack(anchor="w", pady=(0, 6))
        self.etat = ttk.Label(cadre, text="Recherche en cours…", foreground=ROUGE)
        self.etat.pack(anchor="w")
        zone = ttk.Frame(cadre)
        zone.pack(fill="both", expand=True, pady=6)
        self.table = ttk.Treeview(zone, columns=("mot", "titre", "url"), show="headings",
                                  selectmode="extended" if mode == "proposer" else "browse")
        for c, texte, largeur in (("mot", "Mot-clé", 120), ("titre", "Titre", 320), ("url", "Adresse", 400)):
            self.table.heading(c, text=texte)
            self.table.column(c, width=largeur)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<Double-1>", self._ouvrir)
        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x")
        texte_bouton = {"proposer": "Ajouter la sélection au réseau (marquée NP)",
                        "remplacer": "Remplacer le nœud par la page choisie",
                        "affecter": "Affecter la page choisie au nœud libre"}[mode]
        ttk.Button(boutons, text=texte_bouton, command=self.valider).pack(side="right")
        ttk.Button(boutons, text="Fermer", command=w.destroy).pack(side="right", padx=6)
        ttk.Label(boutons, text="Double-clic : ouvrir la page.", foreground="#777").pack(side="left")
        self.lignes = {}

        def travail():
            client = ClientHTTP()
            for mot in mots_cles:
                try:
                    for titre, url in meta_recherche(client, mot, 3):
                        self.resultats.put((mot, titre, url))
                except (ErreurReseau, ValueError, OSError) as erreur:
                    self.resultats.put(("erreur", str(erreur), ""))
            self.resultats.put(None)

        threading.Thread(target=travail, daemon=True).start()
        self._lire()

    def _lire(self):
        if not _existe(self.fenetre):
            return
        try:
            while True:
                element = self.resultats.get_nowait()
                if element is None:
                    n = len(self.lignes)
                    self.etat.configure(text="%d page(s) proposée(s)." % n if n else
                                        "Aucun résultat (pas de connexion, ou moteur indisponible).")
                    return
                mot, titre, url = element
                if mot == "erreur":
                    self.etat.configure(text="Erreur : %s" % titre)
                    continue
                self.lignes[self.table.insert("", "end", values=(mot, titre, url))] = (mot, titre, url)
        except queue.Empty:
            pass
        self.fenetre.after(150, self._lire)

    def _ouvrir(self, e):
        selection = self.table.selection()
        if selection:
            self.nav.nouvel_onglet(self.lignes[selection[0]][2])

    def valider(self):
        choisis = [self.lignes[i] for i in self.table.selection() if i in self.lignes]
        if not choisis:
            messagebox.showinfo("Méta-recherche", "Sélectionnez au moins une page.", parent=self.fenetre)
            return
        if self.mode == "proposer":
            ajoutes = sum(self.reseau.ajouter_proposition(url, titre, mot, self.cible) for mot, titre, url in choisis)
            self.nav._etat("%d proposition(s) ajoutée(s) au réseau (marquées NP)." % ajoutes)
        elif self.mode == "remplacer":
            mot, titre, url = choisis[0]
            self.reseau.remplacer_noeud(self.cible, url, titre)
            self.nav._etat("Nœud remplacé par : %s" % titre)
        else:
            mot, titre, url = choisis[0]
            self.reseau.affecter_ressource(self.cible, url)
            self.nav._etat("Ressource affectée au nœud libre : %s" % url)
        self.fenetre.destroy()
        self.nav.rafraichir_carte()


# ---------------------------------------------------------------------------
# Nœud libre (§ 2.5, « Déclaration de nœuds et de liens »)
# ---------------------------------------------------------------------------

class FenetreNoeudLibre:
    def __init__(self, nav, relier_a=None, apres=None):
        self.nav, self.apres = nav, apres
        self.reseau = nav.stockage.reseau
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Insérer un nœud libre")
        w.geometry("540x500")
        cadre = ttk.Frame(w, padding=12)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text="Un nœud libre sert de support à une information que vous lui affectez.",
                  foreground="#555").pack(anchor="w", pady=(0, 8))
        self.champs = {}
        for cle, texte in (("nom", "Nom du nœud :"), ("ressource", "Ressource Web (adresse, facultatif) :"),
                           ("mots", "Descripteurs / mots-clés (séparés par des virgules) :")):
            ttk.Label(cadre, text=texte).pack(anchor="w")
            champ = ttk.Entry(cadre)
            champ.pack(fill="x", pady=(2, 8))
            self.champs[cle] = champ
        ttk.Label(cadre, text="Annotation :").pack(anchor="w")
        self.annotation = tk.Text(cadre, height=4, wrap="word", font=(POLICE, 11))
        self.annotation.pack(fill="x", pady=(2, 8))
        ttk.Label(cadre, text="Relier depuis le nœud (facultatif) :").pack(anchor="w")
        self.cles = [""] + list(self.reseau.noeuds)
        self.relier = ttk.Combobox(cadre, state="readonly", values=["(aucun)"] + [
            (self.reseau.noeuds[u].get("titre") or u)[:70] for u in self.cles[1:]])
        self.relier.pack(fill="x", pady=(2, 4))
        self.relier.current(self.cles.index(relier_a) if relier_a in self.cles else 0)
        ttk.Label(cadre, text="Nom du lien (ex. « remarques personnelles ») :").pack(anchor="w")
        self.nom_lien = ttk.Entry(cadre)
        self.nom_lien.pack(fill="x", pady=(2, 8))
        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x")
        ttk.Button(boutons, text="Insérer", command=self.inserer).pack(side="right")
        ttk.Button(boutons, text="Annuler", command=w.destroy).pack(side="right", padx=6)
        self.champs["nom"].focus_set()

    def inserer(self):
        nom = self.champs["nom"].get().strip()
        if not nom:
            messagebox.showwarning("Nœud libre", "Donnez un nom au nœud.", parent=self.fenetre)
            return
        relier = self.cles[self.relier.current()] if self.relier.current() > 0 else None
        self.reseau.ajouter_noeud_libre(nom, self.champs["ressource"].get(), self.champs["mots"].get(),
                                        self.annotation.get("1.0", "end"), relier, self.nom_lien.get().strip())
        self.fenetre.destroy()
        if self.apres:
            self.apres()


# ---------------------------------------------------------------------------
# Carte du réseau virtuel (§ 2.3 à 2.8)
# ---------------------------------------------------------------------------

class FenetreCarte:
    MAX_AFFICHES = 250

    def __init__(self, nav):
        self.nav = nav
        self.reseau = nav.stockage.reseau
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Carte de navigation — réseau virtuel")
        w.geometry("1100x680")

        barre = ttk.Frame(w, padding=(6, 6, 6, 0))
        barre.pack(fill="x")
        ttk.Label(barre, text="Niveau :").pack(side="left")
        self.niveau = ttk.Combobox(barre, state="readonly", width=12)
        self.niveau.pack(side="left", padx=(2, 10))
        self.niveau.bind("<<ComboboxSelected>>", lambda e: self.redessiner())
        ttk.Label(barre, text="Du").pack(side="left")
        self.du = ttk.Entry(barre, width=11)
        self.du.pack(side="left", padx=3)
        ttk.Label(barre, text="au").pack(side="left")
        self.au = ttk.Entry(barre, width=11)
        self.au.pack(side="left", padx=3)
        ttk.Label(barre, text="(AAAA-MM-JJ)", foreground="#777").pack(side="left")
        ttk.Button(barre, text="Filtrer", command=self.redessiner).pack(side="left", padx=3)
        ttk.Button(barre, text="Tout afficher", command=self._tout).pack(side="left")
        ttk.Button(barre, text="Exporter en HTML", command=lambda: exporter_reseau(nav, w)).pack(side="right")
        ttk.Button(barre, text="Vider le réseau", command=self._vider).pack(side="right", padx=4)

        barre2 = ttk.Frame(w, padding=6)
        barre2.pack(fill="x")
        ttk.Button(barre2, text="Agent Web…", command=nav.ouvrir_agent).pack(side="left")
        ttk.Button(barre2, text="Nœud libre…", command=lambda: FenetreNoeudLibre(nav, apres=self.redessiner)).pack(side="left", padx=4)
        ttk.Button(barre2, text="Propositions (NP)…", command=self.propositions).pack(side="left")
        ttk.Button(barre2, text="Dictionnaire…", command=lambda: FenetreDictionnaire(nav)).pack(side="left", padx=4)
        self.auto = tk.BooleanVar(value=self.reseau.parametres.get("surveillance_auto", False))
        ttk.Checkbutton(barre2, text="Surveillance automatique (toutes les %d min)"
                        % self.reseau.parametres.get("minutes_surveillance", 30),
                        variable=self.auto, command=self._auto).pack(side="right")
        ttk.Button(barre2, text="Vérifier les nœuds", command=self.verifier).pack(side="right", padx=6)

        self.info = ttk.Label(w, padding=(8, 0), foreground="#555")
        self.info.pack(fill="x")
        cadre = ttk.Frame(w)
        cadre.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(cadre, bg="#fbfaf7", highlightthickness=0)
        dy = ttk.Scrollbar(cadre, orient="vertical", command=self.canvas.yview)
        dx = ttk.Scrollbar(cadre, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=dy.set, xscrollcommand=dx.set)
        dy.pack(side="right", fill="y")
        dx.pack(side="bottom", fill="x")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._clic)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Button-2>", self._menu)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        w.bind("<Escape>", lambda e: self._annuler())
        self.positions = {}
        self.lien_depuis = None
        self.centre = None            # navigation locale : un nœud et ses voisins
        self.police_titre = tkfont.Font(family=POLICE, size=10)
        self.police_gras = tkfont.Font(family=POLICE, size=10, weight="bold")
        self._tout()

    def existe(self):
        return _existe(self.fenetre)

    def _tout(self):
        self.du.delete(0, "end")
        self.au.delete(0, "end")
        self.centre = None
        self.niveau.set("")
        self.redessiner()

    def _vider(self):
        if messagebox.askyesno("Vider le réseau", "Retirer toutes les pages et tous les liens de la carte ?\n\n"
                               "Vos annotations, votre dictionnaire et la base de l'agent sont conservés.",
                               parent=self.fenetre):
            self.reseau.vider()
            self._tout()

    def _annuler(self):
        self.lien_depuis = None
        self.redessiner()

    def _auto(self):
        self.reseau.parametres["surveillance_auto"] = self.auto.get()
        self.reseau.enregistrer()
        self.nav.programmer_surveillance()

    # -- choix des nœuds affichés : par date, par niveau, vue locale (§ 2.8) ----
    def _noeuds_affiches(self):
        urls = list(self.reseau.noeuds)
        du, au = self.du.get().strip(), self.au.get().strip()
        if du or au:
            retenus = {h["url"] for h in self.reseau.historique_entre(du or "0000", au or "9999")}
            urls = [u for u in urls if u in retenus]
        choix = self.niveau.get()
        if choix.startswith("jusqu"):
            maxi = int(choix.split()[-1])
            urls = [u for u in urls if self.reseau.noeuds[u].get("niveau", 0) <= maxi]
        elif choix.endswith("seulement"):
            seul = int(choix.split()[1])
            urls = [u for u in urls if self.reseau.noeuds[u].get("niveau", 0) == seul]
        if self.centre in self.reseau.noeuds:
            voisins = self.reseau.voisins(self.centre)
            urls = [u for u in urls if u in voisins]
        self.masques = 0
        if len(urls) > self.MAX_AFFICHES:
            # carte trop grande pour rester lisible : d'abord la racine et les pages visitées
            noeuds = self.reseau.noeuds
            urls.sort(key=lambda u: (u != self.reseau.racine, noeuds[u].get("visites", 0) == 0,
                                     noeuds[u].get("niveau", 0)))
            self.masques = len(urls) - self.MAX_AFFICHES
            urls = urls[:self.MAX_AFFICHES]
        return urls

    def _titre(self, u):
        n = self.reseau.noeuds.get(u, {})
        titre = ("✗ " if n.get("statut") == "rompu" else "") + (n.get("titre") or u)
        return titre[:30] + "…" if len(titre) > 31 else titre

    def redessiner(self):
        if not self.existe():
            return
        reseau = self.reseau
        niveaux = reseau.niveaux()
        self.niveau["values"] = (["Tous les niveaux"] + ["jusqu'au niveau %d" % n for n in niveaux]
                                 + ["niveau %d seulement" % n for n in niveaux])
        c = self.canvas
        c.delete("all")
        police = (POLICE, 9)
        onglet = self.nav.actif
        courant = str(onglet.url.sans_fragment()) if onglet is not None and onglet.url is not None else None

        colonnes = {}
        for u in self._noeuds_affiches():
            colonnes.setdefault(reseau.noeuds[u].get("niveau", 0), []).append(u)
        self.positions = {}
        for k_col, niveau in enumerate(sorted(colonnes)):
            c.create_text(40 + k_col * 320, 22, text="Niveau %d" % niveau, anchor="w", fill="#999", font=police)
            for k, u in enumerate(colonnes[niveau]):
                pol = self.police_gras if u == courant else self.police_titre
                largeur = min(250, pol.measure(self._titre(u)) + 34)
                self.positions[u] = (40 + k_col * 320, 70 + k * 62, largeur)

        # ---- liens : parcourus en rouge, non parcourus en gris, personnels en pointillés (§ 2.3, 2.8) ----
        etiquettes = []
        entrants = set()
        for l in reseau.liens:
            if l["de"] not in self.positions or l["vers"] not in self.positions:
                continue
            if l.get("agent") and not l.get("parcouru") and self.centre is None and len(self.positions) > 12:
                # Grand site exploré par l'agent : en vue complète, on ne dessine que l'arbre du site
                # (un seul lien d'arrivée par page). Tous les liens restent visibles en vue locale.
                if l.get("type") == "référence" or l["vers"] in entrants:
                    continue
                entrants.add(l["vers"])
            x1, y1, w1 = self.positions[l["de"]]
            x2, y2, w2 = self.positions[l["vers"]]
            if x2 > x1:
                sx, sy, ex, ey = x1 + w1, y1, x2, y2
                cx, cy = (sx + ex) / 2, (sy + ey) / 2 + (8 if l["perso"] else 0)
            else:
                sx, sy, ex, ey = x1 + w1 / 2, y1 - 13, x2 + w2 / 2 + 12, y2 - 13
                cx = (sx + ex) / 2
                cy = min(sy, ey) - 30 - 0.12 * abs(sx - ex) - (14 if l["perso"] else 0)
            parcouru = l.get("parcouru", not l.get("agent"))
            if l["perso"]:
                couleur, largeur, tirets = ROUGE, 2, (6, 3)
            elif parcouru:
                couleur, largeur, tirets = ROUGE, 1.5, None
            else:
                couleur, largeur, tirets = "#c4c4c4", 1, None
            c.create_line(sx, sy, cx, cy, ex, ey, smooth=True, fill=couleur, width=largeur, dash=tirets,
                          arrow="last", arrowshape=(9, 10, 3))
            if l.get("nom") and (l["perso"] or parcouru or len(self.positions) <= 25):
                mx, my = 0.25 * sx + 0.5 * cx + 0.25 * ex, 0.25 * sy + 0.5 * cy + 0.25 * ey
                nom = l["nom"] if len(l["nom"]) <= 18 else l["nom"][:17] + "…"
                etiquettes.append((mx, my, nom, couleur if couleur != "#c4c4c4" else "#999"))

        # ---- nœuds : visités = point rouge plein ; non visités = point creux (§ 2.8) ----
        for u, (x, y, w) in self.positions.items():
            n = reseau.noeuds[u]
            rompu = n.get("statut") == "rompu"
            libre = n.get("libre") and not n.get("ressource")
            couleur = GRIS if rompu else ROUGE
            fond = "#fdecea" if u == courant else ("#f0f0f0" if rompu else "white")
            c.create_rectangle(x, y - 13, x + w, y + 13, fill=fond, outline=couleur,
                               width=2 if u == courant else 1, dash=(4, 2) if libre else None)
            if u == reseau.racine:
                c.create_rectangle(x - 3, y - 16, x + w + 3, y + 16, outline=couleur)
            visite = n.get("visites", 0) > 0
            c.create_oval(x + 8, y - 5, x + 18, y + 5, outline=couleur, width=2,
                          fill=couleur if visite and not rompu else fond)
            c.create_text(x + 24, y, text=self._titre(u), anchor="w",
                          font=self.police_gras if u == courant else self.police_titre,
                          fill="#888" if rompu else "#222")
            badges = []
            nb = len(reseau.annotations_de(u))
            if nb:
                badges.append(("%d note(s)" % nb, VERT))
            if n.get("np"):
                badges.append(("NP", ORANGE))
            if n.get("vide"):
                badges.append(("vide", GRIS))
            if n.get("copie"):
                badges.append(("copie", "#1565c0"))
            bx = x + w - 2
            for texte, couleur_badge in badges:
                t = c.create_text(bx, y - 15, text=texte, anchor="se", fill=couleur_badge, font=(POLICE, 8, "bold"))
                bx = c.bbox(t)[0] - 6

        for mx, my, texte, couleur in etiquettes:
            t = c.create_text(mx, my, text=texte, fill=couleur, font=police)
            x0, y0, x1, y1 = c.bbox(t)
            r = c.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill="#fbfaf7", outline="")
            c.tag_lower(r, t)

        hauteur = max([y for _, y, _ in self.positions.values()] + [300]) + 90
        c.create_text(16, hauteur - 50, anchor="w", font=police, fill="#555",
                      text="● point plein : nœud visité   ○ point creux : nœud non visité (exploré par l'agent)   "
                           "cadre pointillé : nœud libre   double cadre : nœud racine   gris : indisponible")
        c.create_text(16, hauteur - 32, anchor="w", font=police, fill="#555",
                      text="flèche rouge : lien parcouru   flèche grise : lien non parcouru   "
                           "pointillés rouges : lien personnel   NP : nouvelle proposition")
        largeur = max([x + w for x, _, w in self.positions.values()] + [600]) + 60
        c.configure(scrollregion=(0, 0, largeur, hauteur))
        if self.lien_depuis:
            message = ("Cliquez sur la page de destination du lien personnel depuis « %s » (Échap pour annuler)."
                       % self._titre(self.lien_depuis))
        else:
            message = "%d nœud(s) affiché(s) sur %d, %d lien(s) personnel(s).%s%s Clic : ouvrir — clic droit : outils." % (
                len(self.positions), len(reseau.noeuds), sum(1 for l in reseau.liens if l["perso"]),
                "  Vue locale autour de « %s »." % self._titre(self.centre) if self.centre else "",
                "  %d nœud(s) non affiché(s) : utilisez le filtre Niveau ou la vue locale." % self.masques
                if self.masques else "")
        self.info.configure(text=message)

    def _noeud_sous(self, e):
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        for u, (nx, ny, w) in self.positions.items():
            if nx <= x <= nx + w and ny - 14 <= y <= ny + 14:
                return u
        return None

    def _clic(self, e):
        u = self._noeud_sous(e)
        if u is None:
            return
        if self.lien_depuis:
            depuis, self.lien_depuis = self.lien_depuis, None
            if depuis != u:
                nom = simpledialog.askstring("Lien personnel", "Nom du lien (ex. « explique », « contredit ») :",
                                             parent=self.fenetre)
                if nom is not None:
                    self.reseau.ajouter_lien_perso(depuis, u, nom)
            self.redessiner()
            return
        n = self.reseau.noeuds[u]
        if u.startswith("libre:"):
            notes = "\n".join("• " + a["note"] for a in self.reseau.annotations_de(u))
            messagebox.showinfo("Nœud libre", "%s\n\nMots-clés : %s\n%s\n\nClic droit › « Affecter une ressource » "
                                "pour lui associer une page Web." % (n.get("titre"), ", ".join(self.reseau.mots_cles(u))
                                                                    or "—", notes), parent=self.fenetre)
            return
        self.nav.actif.naviguer(u)

    def _menu(self, e):
        u = self._noeud_sous(e)
        m = tk.Menu(self.canvas, tearoff=0)
        if u is None:
            m.add_command(label="Insérer un nœud libre…", command=lambda: FenetreNoeudLibre(self.nav, apres=self.redessiner))
            m.add_command(label="Lancer l'agent Web…", command=self.nav.ouvrir_agent)
            m.add_command(label="Propositions de l'agent de profil (NP)…", command=self.propositions)
            m.add_command(label="Dictionnaire personnel…", command=lambda: FenetreDictionnaire(self.nav))
            if self.centre:
                m.add_command(label="Revenir à la vue complète", command=self._tout)
            m.tk_popup(e.x_root, e.y_root)
            return
        n = self.reseau.noeuds[u]
        mots = self.reseau.mots_cles(u)
        m.add_command(label=(n.get("titre") or u)[:50], state="disabled")
        m.add_command(label="Nœud %s — niveau %d — %d visite(s)" % (self.reseau.type_noeud(u), n.get("niveau", 0),
                                                                    n.get("visites", 0)), state="disabled")
        sortants = [l for l in self.reseau.liens if l["de"] == u][:6]
        for l in sortants:
            m.add_command(label="   → lien %s : %s" % (self.reseau.type_lien(l), (l.get("nom") or "")[:30]), state="disabled")
        m.add_separator()
        if not u.startswith("libre:"):
            m.add_command(label="Ouvrir", command=lambda: self.nav.actif.naviguer(u))
            m.add_command(label="Ouvrir dans un nouvel onglet", command=lambda: self.nav.nouvel_onglet(u))
        if n.get("copie") and os.path.exists(n["copie"]):
            m.add_command(label="Ouvrir la copie locale (hors connexion)",
                          command=lambda: self.nav.nouvel_onglet("file://" + n["copie"].replace("\\", "/")))
        m.add_command(label="Afficher ce nœud et ses voisins (vue locale)", command=lambda: self._centrer(u))
        m.add_separator()
        m.add_command(label="Créer un lien personnel depuis ce nœud…", command=lambda: self._commencer_lien(u))
        m.add_command(label="Insérer un nœud libre relié à ce nœud…",
                      command=lambda: FenetreNoeudLibre(self.nav, relier_a=u, apres=self.redessiner))
        m.add_command(label="Annoter ce nœud…", command=lambda: FenetreAnnotation(
            self.nav, adresse=u, titre=n.get("titre") or u))
        if u.startswith("libre:"):
            m.add_command(label="Affecter une ressource (adresse)…", command=lambda: self._affecter(u))
        m.add_command(label="Chercher des pages avec ses mots-clés (%s)…" % (", ".join(mots[:3]) or "aucun"),
                      state="normal" if mots else "disabled",
                      command=lambda: FenetreRecherche(self.nav, mots[:3], "affecter" if u.startswith("libre:")
                                                       else "proposer", u))
        m.add_command(label="Définir comme nœud racine", command=lambda: self._racine(u))
        if not u.startswith("libre:"):
            m.add_command(label="Vérifier la disponibilité", command=lambda: self.verifier([u]))
        m.add_separator()
        m.add_command(label="Retirer du réseau", command=lambda: (self.reseau.supprimer_noeud(u), self.redessiner()))
        m.tk_popup(e.x_root, e.y_root)

    def _centrer(self, u):
        self.centre = u
        self.redessiner()

    def _commencer_lien(self, u):
        self.lien_depuis = u
        self.redessiner()

    def _racine(self, u):
        self.reseau.racine = u
        self.reseau.enregistrer()
        self.redessiner()

    def _affecter(self, u):
        adresse = simpledialog.askstring("Affecter une ressource", "Adresse de la page Web :", parent=self.fenetre)
        if adresse:
            self.reseau.affecter_ressource(u, adresse)
            self.redessiner()

    def propositions(self):
        mots = self.reseau.mots_cles_frequents(3)
        if not mots:
            messagebox.showinfo("Agent de profil", "Ajoutez d'abord des mots-clés à vos annotations ou à vos nœuds : "
                                "l'agent s'en sert pour vous proposer de nouvelles pages.", parent=self.fenetre)
            return
        FenetreRecherche(self.nav, mots, "proposer", self.reseau.racine)

    # -- agents de surveillance (§ 2.6) --------------------------------------
    def verifier(self, urls=None):
        """Teste chaque nœud du réseau puis applique les règles de l'article selon son type."""
        urls = [u for u in (urls or list(self.positions)) if u.startswith(("http://", "https://"))]
        self.info.configure(text="Vérification de %d page(s)…" % len(urls))
        resultats = {}
        fini = []

        def travail():
            client = ClientHTTP()
            for u in urls:
                code = verifier_lien(client, u)
                resultats[u] = "ok" if code is not None and code < 400 else "rompu"
            fini.append(True)

        threading.Thread(target=travail, daemon=True).start()

        def attendre():
            if not self.existe():
                return
            if not fini:
                self.fenetre.after(150, attendre)
                return
            for u, statut in resultats.items():
                if u in self.reseau.noeuds:
                    self.reseau.noeuds[u]["statut"] = statut
            self.reseau.enregistrer()
            self.redessiner()
            self._regles([u for u, s in resultats.items() if s == "rompu"])

        attendre()

    def _regles(self, rompus):
        if not rompus:
            messagebox.showinfo("Agent de surveillance", "Toutes les pages vérifiées sont disponibles.", parent=self.fenetre)
            return
        decisions = {}
        for u in rompus:
            decisions.setdefault(self.reseau.decision_surveillance(u), []).append(u)
        titre = lambda u: self.reseau.noeuds.get(u, {}).get("titre") or u
        if decisions.get("changer_racine"):
            messagebox.showwarning("Agent de surveillance", "Le nœud racine n'est plus disponible :\n%s\n\nChoisissez un "
                                   "autre nœud racine (clic droit › Définir comme nœud racine)."
                                   % titre(decisions["changer_racine"][0]), parent=self.fenetre)
        fils = decisions.get("supprimer", [])
        if fils and messagebox.askyesno("Agent de surveillance", "%d nœud(s) fils ne sont plus disponibles :\n\n%s\n\n"
                                        "Les supprimer du réseau (suppression locale, le réseau n'est pas réorganisé) ?"
                                        % (len(fils), "\n".join("• " + titre(u)[:70] for u in fils[:10])), parent=self.fenetre):
            for u in fils:
                self.reseau.supprimer_noeud(u)
        for u in decisions.get("garder_vide", []):
            self.reseau.marquer_vide(u)
        if decisions.get("garder_vide"):
            messagebox.showinfo("Agent de surveillance", "Nœud(s) parent(s) indisponible(s), gardé(s) dans le réseau avec "
                                "leurs annotations et marqué(s) « vide » :\n\n%s\n\nVous pouvez choisir un autre nœud parent."
                                % "\n".join("• " + titre(u)[:70] for u in decisions["garder_vide"]), parent=self.fenetre)
        for u in decisions.get("rechercher_remplacant", []):
            if messagebox.askyesno("Agent de surveillance", "Le nœud parent « %s » n'est plus disponible.\n\nIl a des "
                                   "mots-clés (%s) : lancer la méta-recherche pour proposer trois pages de remplacement ?"
                                   % (titre(u), ", ".join(self.reseau.mots_cles(u)[:3])), parent=self.fenetre):
                FenetreRecherche(self.nav, self.reseau.mots_cles(u)[:3], "remplacer", u)
            else:
                self.reseau.marquer_vide(u)
        autres = decisions.get("signaler", [])
        if autres:
            messagebox.showinfo("Agent de surveillance", "%d autre(s) page(s) indisponible(s) (grisées sur la carte)."
                                % len(autres), parent=self.fenetre)
        self.redessiner()


# ---------------------------------------------------------------------------
# Analyse de la page : profil HyWebMap et liens rompus
# ---------------------------------------------------------------------------

class FenetreAnalyse:
    def __init__(self, nav, onglet):
        self.nav, self.onglet = nav, onglet
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Analyse — " + onglet.titre)
        w.geometry("880x540")
        carnet = ttk.Notebook(w)
        carnet.pack(fill="both", expand=True, padx=6, pady=6)
        self.carnet = carnet

        p = ttk.Frame(carnet, padding=10)
        carnet.add(p, text="Profil de la page")
        arbre = ttk.Treeview(p, columns=("valeur",), show="tree headings")
        arbre.heading("#0", text="Caractéristique")
        arbre.heading("valeur", text="Valeur")
        arbre.column("#0", width=240)
        arbre.column("valeur", width=560)
        for cle, valeur in profil_page(onglet.page, onglet.url, nav.stockage.reseau):
            arbre.insert("", "end", text=cle, values=(str(valeur),))
        arbre.pack(fill="both", expand=True)

        liens = liens_page(onglet.page, onglet.url)
        l = ttk.Frame(carnet, padding=10)
        carnet.add(l, text="Liens (%d)" % len(liens))
        haut = ttk.Frame(l)
        haut.pack(fill="x", pady=(0, 6))
        self.bouton = ttk.Button(haut, text="Détecter les liens rompus", command=self.verifier)
        self.bouton.pack(side="left")
        self.resume = ttk.Label(haut, text="Double-clic : ouvrir le lien dans un nouvel onglet.", foreground="#555")
        self.resume.pack(side="left", padx=10)
        cadre = ttk.Frame(l)
        cadre.pack(fill="both", expand=True)
        self.table = ttk.Treeview(cadre, columns=("texte", "type", "statut", "url"), show="headings")
        for col, titre, larg in (("texte", "Texte du lien", 210), ("type", "Type", 70),
                                 ("statut", "État", 110), ("url", "Adresse", 430)):
            self.table.heading(col, text=titre)
            self.table.column(col, width=larg)
        defil = ttk.Scrollbar(cadre, command=self.table.yview)
        self.table.configure(yscrollcommand=defil.set)
        defil.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.table.tag_configure("rompu", foreground="#c62828")
        self.table.tag_configure("ok", foreground=VERT)
        self.table.bind("<Double-1>", self._ouvrir)
        self.lignes = {}
        for texte, adresse, genre in liens:
            iid = self.table.insert("", "end", values=(texte[:50], genre, "", adresse))
            self.lignes[iid] = (adresse, genre)

    def _ouvrir(self, e):
        selection = self.table.selection()
        if selection:
            self.nav.nouvel_onglet(self.lignes[selection[0]][0])

    def verifier(self):
        self.bouton.state(["disabled"])
        a_tester = [(iid, u) for iid, (u, genre) in self.lignes.items() if genre != "ancre"]
        resultats = queue.Queue()
        total = len(a_tester)

        def travail(lot):
            client = ClientHTTP()
            for iid, u in lot:
                resultats.put((iid, verifier_lien(client, u)))

        for k in range(6):            # 6 vérificateurs en parallèle
            threading.Thread(target=travail, args=(a_tester[k::6],), daemon=True).start()
        self._recus, self._rompus = 0, 0

        def lire():
            try:
                if not self.fenetre.winfo_exists():
                    return
            except tk.TclError:
                return
            try:
                while True:
                    iid, code = resultats.get_nowait()
                    self._recus += 1
                    if code is None:
                        etat, tag = "injoignable", "rompu"
                    elif code >= 400:
                        etat, tag = "rompu (%d)" % code, "rompu"
                    else:
                        etat, tag = "ok (%d)" % code, "ok"
                    self._rompus += tag == "rompu"
                    self.table.set(iid, "statut", etat)
                    self.table.item(iid, tags=(tag,))
            except queue.Empty:
                pass
            self.resume.configure(text="%d/%d vérifiés — %d lien(s) rompu(s)" % (self._recus, total, self._rompus))
            if self._recus < total:
                self.fenetre.after(100, lire)
            else:
                self.bouton.state(["!disabled"])

        lire()
