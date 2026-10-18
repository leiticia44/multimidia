"""Réseau personnel de navigation et annotations (outils HyWebMap).

Inspiré de HyWebMap (Saleh, Papy, Bouhaï, Paris 8, 2001) :
  * l'historique n'est pas une simple liste mais un GRAPHE de navigation
    (nœuds = pages, liens = passages d'une page à l'autre) ;
  * l'utilisateur peut ajouter ses propres liens nommés entre deux pages
    (« liens personnels »), sans modifier les sites d'origine ;
  * il peut annoter les pages (passage, note, mots-clés, date) ;
  * le réseau personnel peut être exporté en site HTML consultable
    par n'importe quel navigateur.

Tout est enregistré localement dans ~/.navigateur_maison/reseau.json
(aucun service extérieur).
"""

import json
import os
from datetime import datetime

from .analyseur_html import Element, parcourir
from .reseau import ErreurReseau, URL


def maintenant():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class ReseauPersonnel:
    def __init__(self, dossier):
        self.fichier = os.path.join(dossier, "reseau.json")
        self.historique = []     # [{url, titre, date}] : visites datées (navigation par date)
        self.noeuds = {}         # url -> {titre, visites, premiere, niveau, statut}
        self.liens = []          # [{de, vers, nom, perso}]
        self.annotations = []    # [{url, titre, passage, note, mots_cles, date, numero}]
        self.racine = None       # premier nœud du réseau (nœud racine HyWebMap)
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

    def enregistrer(self):
        try:
            os.makedirs(os.path.dirname(self.fichier), exist_ok=True)
            tmp = self.fichier + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"historique": self.historique[-2000:],
                           "noeuds": self.noeuds, "liens": self.liens,
                           "annotations": self.annotations, "racine": self.racine},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.fichier)
        except OSError:
            pass  # stockage indisponible : on continue sans sauvegarder

    # -- navigation ---------------------------------------------------------
    def visite(self, url, titre, depuis=None, texte_lien=None, code_http=200):
        """Enregistre une visite et met à jour le graphe de navigation."""
        if url.startswith(("about:", "view-source:", "data:")):
            return
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
        if depuis and depuis in self.noeuds and depuis != url:
            if not any(l["de"] == depuis and l["vers"] == url for l in self.liens):
                self.liens.append({"de": depuis, "vers": url,
                                   "nom": (texte_lien or "")[:60], "perso": False})
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
        """Typologie HyWebMap : racine, parent, fils, orphelin."""
        if url == self.racine:
            return "racine"
        sortants = any(l["de"] == url for l in self.liens)
        entrants = any(l["vers"] == url for l in self.liens)
        if not sortants and not entrants:
            return "orphelin"
        return "parent" if sortants else "fils"

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

    def chercher_annotations(self, requete):
        q = requete.lower().strip()
        return [a for a in self.annotations
                if q in (a["note"] + " " + a["passage"] + " " + a["titre"] + " " +
                         a["url"] + " " + " ".join(a["mots_cles"])).lower()]

    def supprimer_annotation(self, numero):
        self.annotations = [a for a in self.annotations if a["numero"] != numero]
        self.enregistrer()

    # -- export du réseau personnel en site HTML (HyWebMap § 2.10) ----------
    def exporter_html(self, chemin):
        def esc(t):
            return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        enfants = {}
        for l in self.liens:
            enfants.setdefault(l["de"], []).append(l)

        ids = {u: k for k, u in enumerate(self.noeuds)}
        lignes, vus = [], set()

        def arbre(url, profondeur):
            if url in vus or url not in self.noeuds:
                return
            vus.add(url)
            n = self.noeuds[url]
            lignes.append(f'{"&nbsp;" * 6 * profondeur}{"└─ " if profondeur else ""}'
                          f'<a href="#n{ids[url]}">{esc(n["titre"] or url)}</a><br>')
            for l in enfants.get(url, []):
                arbre(l["vers"], profondeur + 1)

        if self.racine:
            arbre(self.racine, 0)
        for u in self.noeuds:
            arbre(u, 0)

        fiches = []
        for url, n in self.noeuds.items():
            ann = "".join(f"<li><b>{esc(a['date'])}</b> — {esc(a['note'])}"
                          + (f"<br><i>« {esc(a['passage'])} »</i>" if a["passage"] else "")
                          + (f"<br>Mots-clés : {esc(', '.join(a['mots_cles']))}" if a["mots_cles"] else "")
                          + "</li>" for a in self.annotations_de(url))
            sortants = "".join(f'<li>{"<b>[lien perso]</b> " if l["perso"] else ""}'
                               f'{esc(l["nom"] or "→")} : <a href="{esc(l["vers"])}">{esc(l["vers"])}</a></li>'
                               for l in enfants.get(url, []))
            fiches.append(f'<section id="n{ids[url]}"><h2>{esc(n["titre"] or url)}</h2>'
                          f'<p>Adresse : <a href="{esc(url)}">{esc(url)}</a><br>'
                          f'Type de nœud : {self.type_noeud(url)} — visites : {n["visites"]} — '
                          f'première visite : {esc(n["premiere"])}</p>'
                          + (f"<h3>Liens</h3><ul>{sortants}</ul>" if sortants else "")
                          + (f"<h3>Annotations</h3><ol>{ann}</ol>" if ann else "")
                          + "</section><hr>")

        html = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Mon réseau de navigation</title>
<style>body{{font-family:Georgia,serif;max-width:900px;margin:2em auto;padding:0 1em;color:#222}}
nav{{background:#f4f1ea;padding:1em;border-left:4px solid #b03a2e}}a{{color:#1a55c2}}</style></head>
<body><h1>Mon réseau de navigation</h1><p>Généré le {maintenant()} — {len(self.noeuds)} pages,
{len(self.liens)} liens, {len(self.annotations)} annotations.</p>
<nav><h2>Sommaire</h2>{''.join(lignes)}</nav>{''.join(fiches)}</body></html>"""
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(html)
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


def profil_page(page, url, reseau=None):
    """Caractéristiques d'une page (relation « Profils » de HyWebMap)."""
    elements = [n for n in parcourir(page.dom) if isinstance(n, Element)]

    def compte(*balises):
        return sum(1 for n in elements if n.balise in balises)

    def meta(nom):
        for n in elements:
            if n.balise == "meta" and n.attributs.get("name", "").lower() == nom:
                return n.attributs.get("content", "")
        return ""

    liens = liens_page(page, url)
    internes = [l for l in liens if l[2] == "interne"]
    externes = [l for l in liens if l[2] == "externe"]
    corps = next((n for n in elements if n.balise == "body"), page.dom)
    texte = " ".join(_texte_visible(corps).split())
    adresse = str(url.sans_fragment())
    return [
        ("Titre", page.titre or "—"),
        ("Adresse", str(url)),
        ("Auteur (meta)", meta("author") or "—"),
        ("Mots-clés (meta)", meta("keywords") or "—"),
        ("Description (meta)", (meta("description") or "—")[:120]),
        ("Nombre de caractères", "{:,}".format(len(texte)).replace(",", " ")),
        ("Nombre de liens internes", len(internes)),
        ("Nombre de liens externes", len(externes)),
        ("Nombre d'images", compte("img")),
        ("Nombre de scripts", compte("script")),
        ("Nombre de feuilles de style", compte("style") + sum(
            1 for n in elements if n.balise == "link" and "stylesheet" in n.attributs.get("rel", "").lower())),
        ("Nombre de tableaux", compte("table")),
        ("Nombre de formulaires", compte("form")),
        ("Nombre de titres (h1-h3)", compte("h1", "h2", "h3")),
        ("Code HTTP", getattr(page, "statut", "—")),
        ("Type de nœud (réseau)", reseau.type_noeud(adresse) if reseau and adresse in reseau.noeuds else "—"),
    ]


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
    base = getattr(page, "base", None) or url
    resultat, vus = [], set()
    for n in parcourir(page.dom):
        if not (isinstance(n, Element) and n.balise == "a" and n.attributs.get("href")):
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
        resultat.append((" ".join(n.texte_contenu().split()) or adresse, adresse, genre))
    return resultat
