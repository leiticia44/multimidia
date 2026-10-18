"""Fenêtres des outils inspirés de HyWebMap (Saleh, Papy, Bouhaï, Paris 8, ISKO 2001).

* FenetreCarte      : carte du réseau personnel de navigation (nœuds = pages,
                      flèches = liens suivis ou personnels), surveillance des
                      pages, navigation par date, export HTML.
* FenetreAnalyse    : profil de la page (caractéristiques HyWebMap) et
                      détection des liens rompus.
* FenetreAnnotation : annoter un passage sélectionné ou la page entière.

Les données sont gérées par ``reseau_personnel.ReseauPersonnel``.
"""

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

from .reseau import ClientHTTP
from .reseau_personnel import liens_page, profil_page, verifier_lien

ROUGE = "#b03a2e"
VERT = "#2e7d32"
POLICE = "Helvetica"


def exporter_reseau(nav, parent=None):
    chemin = filedialog.asksaveasfilename(parent=parent or nav.racine, defaultextension=".html",
                                          initialfile="mon_reseau.html")
    if chemin:
        nav.stockage.reseau.exporter_html(chemin)
        if messagebox.askyesno("Export", "Réseau exporté. L'ouvrir dans un nouvel onglet ?",
                               parent=parent or nav.racine):
            nav.nouvel_onglet("file://" + chemin.replace("\\", "/"))


# ---------------------------------------------------------------------------
# Annotation (HyWebMap § 2.9)
# ---------------------------------------------------------------------------

class FenetreAnnotation:
    def __init__(self, nav, onglet, passage):
        self.nav, self.onglet = nav, onglet
        self.adresse = str(onglet.url.sans_fragment())
        reseau = nav.stockage.reseau
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Annoter — " + onglet.titre)
        w.geometry("520x470")
        w.transient(nav.racine)
        cadre = ttk.Frame(w, padding=12)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text=onglet.titre, font=(POLICE, 12, "bold")).pack(anchor="w")
        ttk.Label(cadre, text=self.adresse, foreground="#777").pack(anchor="w", pady=(0, 8))

        ttk.Label(cadre, text="Passage annoté (sélection dans la page, facultatif) :").pack(anchor="w")
        self.passage = tk.Text(cadre, height=3, wrap="word", font=(POLICE, 11), bg="#f2fbf2")
        self.passage.insert("1.0", passage)
        self.passage.pack(fill="x", pady=(2, 8))
        ttk.Label(cadre, text="Note :").pack(anchor="w")
        self.note = tk.Text(cadre, height=5, wrap="word", font=(POLICE, 11))
        self.note.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(cadre, text="Mots-clés (séparés par des virgules) :").pack(anchor="w")
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
        self.nav.stockage.reseau.annoter(self.adresse, self.onglet.titre, passage, note, self.mots.get())
        self.fenetre.destroy()
        self.nav.effacer_selection()
        self.onglet.reperer_annotations()
        self.nav.dessiner()
        self.nav._etat("Annotation enregistrée.")


# ---------------------------------------------------------------------------
# Carte de navigation (HyWebMap § 2.3 à 2.8)
# ---------------------------------------------------------------------------

class FenetreCarte:
    def __init__(self, nav):
        self.nav = nav
        self.reseau = nav.stockage.reseau
        w = self.fenetre = tk.Toplevel(nav.racine)
        w.title("Carte de navigation — réseau personnel")
        w.geometry("1000x620")
        barre = ttk.Frame(w, padding=6)
        barre.pack(fill="x")
        ttk.Label(barre, text="Du").pack(side="left")
        self.du = ttk.Entry(barre, width=11)
        self.du.pack(side="left", padx=3)
        ttk.Label(barre, text="au").pack(side="left")
        self.au = ttk.Entry(barre, width=11)
        self.au.pack(side="left", padx=3)
        ttk.Label(barre, text="(AAAA-MM-JJ)", foreground="#777").pack(side="left")
        ttk.Button(barre, text="Filtrer par date", command=self.redessiner).pack(side="left", padx=3)
        ttk.Button(barre, text="Tout", command=self._tout).pack(side="left")
        ttk.Button(barre, text="Exporter en HTML", command=lambda: exporter_reseau(nav, w)).pack(side="right")
        ttk.Button(barre, text="Vérifier les nœuds", command=self.verifier).pack(side="right", padx=4)
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
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        w.bind("<Escape>", lambda e: self._annuler_lien())
        self.positions = {}
        self.lien_depuis = None
        self.police_titre = tkfont.Font(family=POLICE, size=10)
        self.police_gras = tkfont.Font(family=POLICE, size=10, weight="bold")
        self._tout()

    def existe(self):
        try:
            return bool(self.fenetre.winfo_exists())
        except tk.TclError:
            return False

    def _tout(self):
        self.du.delete(0, "end")
        self.au.delete(0, "end")
        self.redessiner()

    def _annuler_lien(self):
        self.lien_depuis = None
        self.redessiner()

    def _noeuds_affiches(self):
        du, au = self.du.get().strip(), self.au.get().strip()
        if not du and not au:
            return list(self.reseau.noeuds)
        retenus = {h["url"] for h in self.reseau.historique_entre(du or "0000", au or "9999")}
        return [u for u in self.reseau.noeuds if u in retenus]

    def _titre(self, u):
        n = self.reseau.noeuds.get(u, {})
        titre = ("✗ " if n.get("statut") == "rompu" else "") + (n.get("titre") or u)
        return titre[:30] + "…" if len(titre) > 31 else titre

    def redessiner(self):
        if not self.existe():
            return
        c = self.canvas
        c.delete("all")
        reseau = self.reseau
        police = (POLICE, 9)
        onglet = self.nav.actif
        courant = str(onglet.url.sans_fragment()) if onglet is not None and onglet.url is not None else None

        # Disposition en colonnes selon la profondeur (niveau d'arborescence)
        colonnes = {}
        for u in self._noeuds_affiches():
            colonnes.setdefault(reseau.noeuds[u].get("niveau", 0), []).append(u)
        self.positions = {}     # url -> (x, y, largeur) ; y = milieu de la boîte
        for niveau in sorted(colonnes):
            for k, u in enumerate(colonnes[niveau]):
                pol = self.police_gras if u == courant else self.police_titre
                largeur = min(250, pol.measure(self._titre(u)) + 34)
                self.positions[u] = (40 + niveau * 320, 120 + k * 74, largeur)

        # ---- liens, dessinés sous les nœuds ----
        etiquettes = []
        for l in reseau.liens:
            if l["de"] not in self.positions or l["vers"] not in self.positions:
                continue
            x1, y1, w1 = self.positions[l["de"]]
            x2, y2, w2 = self.positions[l["vers"]]
            if x2 > x1:                       # vers la colonne suivante
                sx, sy, ex, ey = x1 + w1, y1, x2, y2
                cx, cy = (sx + ex) / 2, (sy + ey) / 2 + (8 if l["perso"] else 0)
            else:                             # retour en arrière : arc au-dessus
                sx, sy, ex, ey = x1 + w1 / 2, y1 - 13, x2 + w2 / 2 + 12, y2 - 13
                cx = (sx + ex) / 2
                cy = min(sy, ey) - 30 - 0.12 * abs(sx - ex) - (14 if l["perso"] else 0)
            couleur = ROUGE if l["perso"] else "#a3a3a3"
            c.create_line(sx, sy, cx, cy, ex, ey, smooth=True, fill=couleur,
                          width=2 if l["perso"] else 1, dash=(6, 3) if l["perso"] else None,
                          arrow="last", arrowshape=(9, 10, 3))
            if l["nom"]:
                mx, my = 0.25 * sx + 0.5 * cx + 0.25 * ex, 0.25 * sy + 0.5 * cy + 0.25 * ey
                nom = l["nom"] if len(l["nom"]) <= 18 else l["nom"][:17] + "…"
                etiquettes.append((mx, my, nom, couleur))

        # ---- nœuds ----
        for u, (x, y, w) in self.positions.items():
            n = reseau.noeuds[u]
            rompu = n.get("statut") == "rompu"
            couleur = "#9e9e9e" if rompu else ROUGE
            fond = "#fdecea" if u == courant else ("#f0f0f0" if rompu else "white")
            c.create_rectangle(x, y - 13, x + w, y + 13, fill=fond, outline=couleur,
                               width=2 if u == courant else 1)
            if u == reseau.racine:            # nœud racine : double cadre
                c.create_rectangle(x - 3, y - 16, x + w + 3, y + 16, outline=couleur)
            c.create_oval(x + 8, y - 5, x + 18, y + 5, outline=couleur, width=2,
                          fill=fond if rompu else couleur)
            c.create_text(x + 24, y, text=self._titre(u), anchor="w",
                          font=self.police_gras if u == courant else self.police_titre,
                          fill="#888" if rompu else "#222")
            nb = len(reseau.annotations_de(u))
            if nb:
                c.create_text(x + w - 2, y - 15, text="%d note(s)" % nb, anchor="se", fill=VERT, font=police)

        for mx, my, texte, couleur in etiquettes:
            t = c.create_text(mx, my, text=texte, fill=couleur, font=police)
            x0, y0, x1, y1 = c.bbox(t)
            r = c.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill="#fbfaf7", outline="")
            c.tag_lower(r, t)

        hauteur = max([y for _, y, _ in self.positions.values()] + [300]) + 80
        c.create_text(16, hauteur - 36, anchor="w", font=police, fill="#555",
                      text="Cadre rouge épais : page courante — double cadre : nœud racine — gris : page "
                           "indisponible — trait gris : lien suivi — pointillés rouges : lien personnel")
        largeur = max([x + w for x, _, w in self.positions.values()] + [600]) + 60
        c.configure(scrollregion=(0, 0, largeur, hauteur))
        if self.lien_depuis:
            message = ("Cliquez sur la page de destination du lien personnel depuis « %s » (Échap pour annuler)."
                       % self._titre(self.lien_depuis))
        else:
            message = ("%d pages, %d liens personnels. Clic : ouvrir la page — clic droit : lien personnel, "
                       "vérifier, supprimer." % (len(self.positions), sum(1 for l in reseau.liens if l["perso"])))
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
        self.nav.actif.naviguer(u)

    def _menu(self, e):
        u = self._noeud_sous(e)
        if u is None:
            return
        n = self.reseau.noeuds[u]
        m = tk.Menu(self.canvas, tearoff=0)
        m.add_command(label=(n.get("titre") or u)[:50], state="disabled")
        m.add_command(label="Type : nœud %s — %d visite(s)" % (self.reseau.type_noeud(u), n["visites"]),
                      state="disabled")
        m.add_separator()
        m.add_command(label="Ouvrir", command=lambda: self.nav.actif.naviguer(u))
        m.add_command(label="Ouvrir dans un nouvel onglet", command=lambda: self.nav.nouvel_onglet(u))
        m.add_command(label="Créer un lien personnel depuis ce nœud…", command=lambda: self._commencer_lien(u))
        m.add_command(label="Définir comme nœud racine", command=lambda: self._racine(u))
        m.add_command(label="Vérifier la disponibilité", command=lambda: self.verifier([u]))
        m.add_separator()
        m.add_command(label="Retirer du réseau", command=lambda: (self.reseau.supprimer_noeud(u), self.redessiner()))
        m.tk_popup(e.x_root, e.y_root)

    def _commencer_lien(self, u):
        self.lien_depuis = u
        self.redessiner()

    def _racine(self, u):
        self.reseau.racine = u
        self.reseau.enregistrer()
        self.redessiner()

    def verifier(self, urls=None):
        """Agent de surveillance : teste que chaque page du réseau existe toujours."""
        urls = urls or list(self.positions)
        self.info.configure(text="Vérification de %d page(s)…" % len(urls))
        resultats = {}

        def travail():
            client = ClientHTTP()
            for u in urls:
                code = verifier_lien(client, u)
                resultats[u] = "ok" if code is not None and code < 400 else "rompu"
            self._fin = True

        self._fin = False
        threading.Thread(target=travail, daemon=True).start()

        def attendre():
            if not self.existe():
                return
            if not self._fin:
                self.fenetre.after(150, attendre)
                return
            for u, statut in resultats.items():
                if u in self.reseau.noeuds:
                    self.reseau.noeuds[u]["statut"] = statut
            self.reseau.enregistrer()
            self.redessiner()
            rompus = [u for u, s in resultats.items() if s == "rompu"]
            if rompus:
                messagebox.showwarning("Agent de surveillance", "%d page(s) ne sont plus disponibles :\n\n%s"
                                       % (len(rompus), "\n".join(u[:80] for u in rompus[:12])), parent=self.fenetre)
            else:
                messagebox.showinfo("Agent de surveillance", "Toutes les pages sont disponibles.",
                                    parent=self.fenetre)

        attendre()


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
