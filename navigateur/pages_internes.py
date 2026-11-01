"""Pages internes du navigateur (about:accueil, about:historique, ...) et
pages générées (erreurs, texte brut, source, images, téléchargements)."""

import time

from .reseau import pourcent_decoder, pourcent_encoder
from .reseau_personnel import lier_urls

MOTEUR_RECHERCHE = "https://lite.duckduckgo.com/lite/"   # moteur sans Google
PAGE_ACCUEIL = "about:accueil"

STYLE = """
body { font-family: sans-serif; background-color: #f6f7fb; color: #222; margin: 0; }
.page { max-width: 760px; margin: 0 auto; padding: 24px 16px; }
h1 { color: #2b3a67; font-size: 28px; }
h2 { color: #2b3a67; font-size: 20px; border-bottom: 1px solid #d0d4e4; padding-bottom: 4px; }
a { color: #1f5fbf; text-decoration: none; }
.carte { background-color: #ffffff; border: 1px solid #dde1ee; padding: 12px 16px; margin-bottom: 12px; }
.discret { color: #777; font-size: 13px; }
.centre { text-align: center; }
kbd { font-family: monospace; background-color: #eceef4; border: 1px solid #c7cbd8; padding: 0 4px; }
td { padding: 4px 10px; }
"""


def echapper(texte):
    return (texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _page(titre, contenu):
    return ("<!doctype html><html><head><meta charset=utf-8><title>%s</title><style>%s</style></head>"
            "<body><div class=page>%s</div></body></html>" % (echapper(titre), STYLE, contenu))


def url_recherche(requete):
    return MOTEUR_RECHERCHE + "?q=" + pourcent_encoder(requete).replace("%20", "+")


def accueil(stockage):
    favoris = "".join('<li><a href="%s">%s</a></li>' % (echapper(f["url"]), echapper(f["titre"]))
                      for f in stockage.favoris[-12:]) or "<li class=discret>Aucun favori pour l'instant (Ctrl+D pour en ajouter).</li>"
    contenu = """
<h1 class=centre>Navigateur Maison</h1>
<p class="centre discret">Un navigateur écrit entièrement à la main en Python &mdash; sans aucune API Google.</p>
<div class="carte centre">
<form action="%s" method=get>
<input name=q size=40 placeholder="Rechercher sur le Web (DuckDuckGo)"> <input type=submit value="Rechercher">
</form>
</div>
<h2>Favoris</h2>
<ul>%s</ul>
<h2>Raccourcis</h2>
<p><a href="about:historique">Historique</a> &middot; <a href="about:favoris">Gérer les favoris</a>
&middot; <a href="about:annotations">Mes annotations</a>
&middot; <a href="about:aide">Aide et raccourcis clavier</a></p>
<p class=discret>Outils inspirés de HyWebMap : agent Web (Ctrl+E), carte du réseau virtuel (Ctrl+M),
annotations (Ctrl+N), analyse de la page et liens rompus (Ctrl+I).</p>
""" % (MOTEUR_RECHERCHE, favoris)
    return _page("Accueil", contenu)


def historique(stockage):
    lignes = []
    for entree in reversed(stockage.historique[-300:]):
        date = time.strftime("%d/%m/%Y %H:%M", time.localtime(entree.get("date", 0)))
        lignes.append('<tr><td class=discret>%s</td><td><a href="%s">%s</a><br><span class=discret>%s</span></td></tr>' % (
            date, echapper(entree["url"]), echapper(entree["titre"][:90]), echapper(entree["url"][:90])))
    contenu = "<h1>Historique</h1><p><a href=\"about:historique?effacer\">Effacer tout l'historique</a></p>"
    contenu += "<table>%s</table>" % "".join(lignes) if lignes else "<p class=discret>L'historique est vide.</p>"
    return _page("Historique", contenu)


def favoris(stockage):
    lignes = "".join('<li><a href="%s">%s</a> <span class=discret>&mdash; %s</span> '
                     '[<a href="about:favoris?supprimer=%s">supprimer</a>]</li>' % (
                         echapper(f["url"]), echapper(f["titre"]), echapper(f["url"]),
                         pourcent_encoder(f["url"])) for f in stockage.favoris)
    contenu = "<h1>Favoris</h1>" + ("<ul>%s</ul>" % lignes if lignes else "<p class=discret>Aucun favori.</p>")
    return _page("Favoris", contenu)


def _parametres(chemin):
    resultat = {}
    if "?" in chemin:
        for morceau in chemin.split("?", 1)[1].split("&"):
            cle, _, valeur = morceau.partition("=")
            resultat[cle] = pourcent_decoder(valeur, plus_en_espace=True)
    return resultat


def annotations(stockage, chemin):
    """Recherche dans les annotations (§ 2.9) : plein texte ou par attribut, résultats
    regroupés par document, chaque document résumé par la fusion de ses passages surlignés."""
    reseau = stockage.reseau
    parametres = _parametres(chemin)
    requete, champ = parametres.get("q", ""), parametres.get("champ", "tout")
    liste = reseau.chercher_annotations(requete, champ) if requete else reseau.annotations
    options = "".join('<option value="%s"%s>%s</option>' % (c, " selected" if c == champ else "", c)
                      for c in reseau.CHAMPS)
    synonymes = sorted(reseau.etendre(requete) - {requete.lower()}) if requete else []
    blocs = []
    for url, titre, notes, resume in reseau.regrouper_par_document(liste):
        bloc = '<div class=carte><h2><a href="%s">%s</a></h2><p class=discret>%s</p>' % (
            echapper(url), echapper(titre), echapper(url))
        if resume:
            bloc += "<p><b>Résumé (passages surlignés) :</b> <i>%s</i></p>" % echapper(resume)
        for a in notes:
            couleur = ' style="color:#999"' if a.get("introuvable") else ""
            bloc += '<p%s><b>n° %d</b> <span class=discret>%s</span> &mdash; %s' % (
                couleur, a["numero"], echapper(a["date"]), lier_urls(echapper(a["note"])) or "<i>(sans note)</i>")
            if a["passage"]:
                bloc += "<br>&laquo; %s &raquo;" % echapper(a["passage"])
            if a["mots_cles"]:
                bloc += "<br><span class=discret>Mots-clés : %s</span>" % echapper(", ".join(a["mots_cles"]))
            if a.get("introuvable"):
                bloc += "<br><span class=discret>Passage introuvable : le document a changé.</span>"
            bloc += ' <span class=discret>[<a href="about:annotations?supprimer=%d">supprimer</a>]</span></p>' % a["numero"]
        blocs.append(bloc + "</div>")
    contenu = """<h1>Mes annotations</h1>
<form action="about:annotations" method=get><input name=q size=34 value="%s" placeholder="Chercher (synonymes inclus)">
<select name=champ>%s</select> <input type=submit value="Chercher"></form>
<p class=discret>%s%d annotation(s) dans %d document(s). Sélectionnez un passage puis Ctrl+N pour annoter.</p>%s""" % (
        echapper(requete), options,
        ("Synonymes pris en compte : %s. " % echapper(", ".join(synonymes))) if synonymes else "",
        len(liste), len({a["url"] for a in liste}), "".join(blocs) or "<p class=discret>Aucune annotation.</p>")
    return _page("Annotations", contenu)


def aide():
    raccourcis = [
        ("Ctrl+L / F6", "Aller à la barre d'adresse"), ("Ctrl+T", "Nouvel onglet"),
        ("Ctrl+W", "Fermer l'onglet"), ("Ctrl+Tab", "Onglet suivant"),
        ("Alt+← / Alt+→", "Précédent / Suivant"), ("F5 / Ctrl+R", "Recharger"),
        ("Ctrl+D", "Ajouter / retirer des favoris"), ("Ctrl+H", "Historique"),
        ("Ctrl+F", "Rechercher dans la page"), ("Ctrl+U", "Afficher le code source"),
        ("Ctrl+ + / Ctrl+ - / Ctrl+0", "Zoom avant / arrière / réinitialiser"),
        ("Espace / Page suivante", "Défiler d'un écran"), ("Début / Fin", "Haut / bas de la page"),
        ("Clic milieu ou Ctrl+clic", "Ouvrir le lien dans un nouvel onglet"),
        ("Glisser la souris / Ctrl+C", "Sélectionner du texte / le copier"),
        ("Ctrl+M", "Carte de navigation (réseau personnel)"),
        ("Ctrl+N", "Annoter la sélection ou la page"),
        ("Ctrl+I", "Analyse de la page et liens rompus"),
        ("Ctrl+E", "Agent Web : explorer un site (profondeur, largeur)"),
    ]
    lignes = "".join("<tr><td><kbd>%s</kbd></td><td>%s</td></tr>" % (echapper(t), echapper(d)) for t, d in raccourcis)
    contenu = """<h1>Aide</h1>
<h2>Raccourcis clavier</h2><table>%s</table>
<h2>Ce que sait faire ce navigateur</h2>
<ul>
<li>HTTP/1.1 et HTTPS (TLS), redirections, cookies, compression gzip, cache, proxys.</li>
<li>Analyse HTML tolérante (balises implicites, entités, commentaires).</li>
<li>CSS : sélecteurs (balise, classe, id, attributs, descendants, enfants), cascade, héritage,
@media, couleurs, polices, marges, bordures, largeurs, centrage.</li>
<li>Mise en page : blocs, texte avec retour à la ligne, listes, tableaux, images PNG/GIF.</li>
<li>Formulaires GET/POST : champs texte, cases à cocher, boutons radio, listes, zones de texte.</li>
<li>Onglets, historique, favoris, zoom, recherche dans la page, code source.</li>
<li>Les étapes de l'article HyWebMap (Saleh, Papy, Bouhaï, Paris 8) :
<ol>
<li><b>Agent Web</b> (Ctrl+E) : explore un site en profondeur et en largeur, détecte les liens rompus ;</li>
<li><b>Base de données</b> : nœuds, liens, ancres, profils et propriétés de chaque page (fichier hywebmap.db) ;</li>
<li><b>Réseau virtuel</b> (Ctrl+M) : la carte du site et de vos visites, vos liens personnels ;</li>
<li><b>Nœuds libres</b> : un nom, une ressource Web, des mots-clés, une annotation ;</li>
<li><b>Typologie</b> : 5 types de nœuds et 7 types de liens ;</li>
<li><b>Agents de surveillance</b> : pages disparues, avec une règle selon le type de nœud ;</li>
<li><b>Navigation</b> par historique, par niveau, par date, et vue locale d'un nœud ;</li>
<li><b>Annotations</b> (Ctrl+N), panneau en bas de la page, recherche par attribut, dictionnaire de synonymes ;</li>
<li><b>Export</b> du réseau en site HTML à deux cadres.</li>
</ol></li>
</ul>
<p class=discret>JavaScript n'est pas exécuté : les pages s'affichent comme avec JavaScript désactivé.</p>
""" % lignes
    return _page("Aide", contenu)


def erreur(url, message):
    contenu = """<h1>Impossible d'afficher la page</h1>
<div class=carte><p><b>%s</b></p><p class=discret>%s</p></div>
<p><a href="%s">Réessayer</a> &middot; <a href="%s">Accueil</a></p>""" % (
        echapper(message), echapper(url), echapper(url), PAGE_ACCUEIL)
    return _page("Erreur", contenu)


def texte_brut(titre, texte):
    return ("<html><head><title>%s</title></head><body><pre>%s</pre></body></html>"
            % (echapper(titre), echapper(texte)))


def source(url, texte):
    return ("<html><head><title>Source de %s</title></head><body style=\"background-color:#fbfbfb\">"
            "<pre style=\"font-size:13px\">%s</pre></body></html>" % (echapper(url), echapper(texte)))


def image(url):
    return ("<html><head><title>%s</title></head><body style=\"background-color:#333;text-align:center\">"
            "<img src=\"%s\" alt=\"image\"></body></html>" % (echapper(url.rsplit("/", 1)[-1] or url), echapper(url)))


def telechargement(url, chemin, taille):
    contenu = """<h1>Fichier téléchargé</h1>
<div class=carte><p>Ce type de contenu ne peut pas être affiché ; il a été enregistré :</p>
<p><b>%s</b> (%d octets)</p><p class=discret>Source : %s</p></div>""" % (echapper(chemin), taille, echapper(url))
    return _page("Téléchargement", contenu)


def generer(chemin, stockage):
    """Renvoie le HTML d'une page about: (``chemin`` sans le préfixe « about: »)."""
    nom = chemin.split("?")[0].lower()
    if nom in ("accueil", "home", "newtab"):
        return accueil(stockage)
    if nom in ("historique", "history"):
        return historique(stockage)
    if nom in ("favoris", "bookmarks"):
        return favoris(stockage)
    if nom in ("aide", "help"):
        return aide()
    if nom == "annotations":
        return annotations(stockage, chemin)
    if nom == "blank":
        return "<html><head><title>Nouvel onglet</title></head><body></body></html>"
    return erreur("about:" + chemin, "Page interne inconnue")
