"""Tests unitaires du navigateur (aucun écran ni réseau externe nécessaire).

Lancer : python3 -m unittest discover -s tests -v
"""

import http.server
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from navigateur.analyseur_css import (FEUILLE_PAR_DEFAUT, analyser_couleur, analyser_css,
                                      analyser_declarations, calculer_styles, longueur)
from navigateur.analyseur_html import Element, analyser_html, decoder_entites, parcourir
from navigateur.chargeur import charger_page
from navigateur.mise_en_page import CmdTexte, Contexte, LayoutDocument
from navigateur.reseau import URL, ClientHTTP, encoder_formulaire, pourcent_decoder
from navigateur.stockage import Stockage


class PolicesFactices:
    """Police à chasse fixe : chaque caractère fait la moitié de la taille."""

    def mesurer(self, police, texte):
        return len(texte) * police[1] * 0.5

    def metriques(self, police):
        return police[1] * 0.8, police[1] * 0.2


def mettre_en_page(html, largeur=800, css=""):
    dom = analyser_html(html)
    feuilles = [analyser_css(FEUILLE_PAR_DEFAUT)]
    if css:
        feuilles.append(analyser_css(css))
    calculer_styles(dom, feuilles)
    document = LayoutDocument(dom, Contexte(PolicesFactices()))
    document.mise_en_page(largeur)
    commandes, zones = document.peindre()
    return dom, document, commandes, zones


def element(dom, balise):
    return next(n for n in parcourir(dom) if isinstance(n, Element) and n.balise == balise)


# ---------------------------------------------------------------------------

class TestURL(unittest.TestCase):
    def test_analyse(self):
        url = URL("https://Exemple.fr:8443/a/b?x=1#haut")
        self.assertEqual((url.schema, url.hote, url.port, url.chemin, url.fragment),
                         ("https", "exemple.fr", 8443, "/a/b?x=1", "haut"))
        self.assertEqual(str(URL("http://exemple.fr")), "http://exemple.fr/")
        self.assertEqual(URL("http://exemple.fr?q=1").chemin, "/?q=1")

    def test_resolution(self):
        base = URL("https://exemple.fr/dossier/page.html?x=1")
        cas = {
            "autre.html": "https://exemple.fr/dossier/autre.html",
            "../haut.html": "https://exemple.fr/haut.html",
            "/racine": "https://exemple.fr/racine",
            "//cdn.fr/a.css": "https://cdn.fr/a.css",
            "?y=2": "https://exemple.fr/dossier/page.html?y=2",
            "#ancre": "https://exemple.fr/dossier/page.html?x=1#ancre",
            "./a/./b/../c": "https://exemple.fr/dossier/a/c",
            "http://ailleurs.org/": "http://ailleurs.org/",
        }
        for relatif, attendu in cas.items():
            self.assertEqual(str(base.resoudre(relatif)), attendu, relatif)
        with self.assertRaises(ValueError):
            base.resoudre("javascript:alert(1)")

    def test_encodage(self):
        self.assertEqual(encoder_formulaire([("q", "été 2026"), ("a&b", "=")]), "q=%C3%A9t%C3%A9+2026&a%26b=%3D")
        self.assertEqual(pourcent_decoder("%C3%A9t%C3%A9+x", plus_en_espace=True), "été x")

    def test_data_et_fichier(self):
        client = ClientHTTP()
        self.assertEqual(client.charger(URL("data:text/plain,Bonjour%20!")).corps, b"Bonjour !")
        self.assertEqual(client.charger(URL("data:text/plain;base64,U2FsdXQ=")).corps, b"Salut")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fichier:
            fichier.write("<p>local</p>")
        try:
            reponse = client.charger(URL("file://" + fichier.name))
            self.assertEqual(reponse.type_mime, "text/html")
            self.assertEqual(reponse.texte(), "<p>local</p>")
        finally:
            os.unlink(fichier.name)


class ServeurTest(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *arguments):
        pass

    def _repondre(self, corps, entetes=(), statut=200, morceaux=False):
        self.send_response(statut)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for nom, valeur in entetes:
            self.send_header(nom, valeur)
        if morceaux:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, len(corps), 7):
                bout = corps[i:i + 7]
                self.wfile.write(b"%x\r\n%s\r\n" % (len(bout), bout))
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

    def do_GET(self):
        if self.path == "/redirection":
            self._repondre(b"", [("Location", "/cible")], statut=302)
        elif self.path == "/cible":
            self._repondre("<title>Cible</title><p>arrivé</p>".encode("utf-8"), morceaux=True)
        elif self.path == "/gzip":
            import gzip
            self._repondre(gzip.compress(b"<p>compresse</p>"), [("Content-Encoding", "gzip")])
        elif self.path == "/cookie":
            self._repondre(b"ok", [("Set-Cookie", "jeton=42; Path=/")])
        elif self.path == "/montre-cookie":
            self._repondre((self.headers.get("Cookie") or "").encode())
        elif self.path == "/style.css":
            self.send_response(200)
            self.send_header("Content-Type", "text/css")
            corps = b"p { color: #123456 }"
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
        elif self.path == "/avec-style":
            self._repondre(b'<link rel=stylesheet href="style.css"><p>bleu</p>')
        else:
            self._repondre(b"introuvable", statut=404)

    def do_POST(self):
        taille = int(self.headers["Content-Length"])
        self._repondre(b"recu:" + self.rfile.read(taille))


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ServeurTest)
        cls.base = "http://127.0.0.1:%d" % cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.anciens = {cle: os.environ.pop(cle) for cle in list(os.environ) if cle.lower() == "http_proxy"}

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()
        os.environ.update(cls.anciens)

    def test_redirection_et_morceaux(self):
        reponse = ClientHTTP().charger(URL(self.base + "/redirection"))
        self.assertEqual(reponse.statut, 200)
        self.assertEqual(reponse.url.chemin, "/cible")
        self.assertIn("arrivé", reponse.texte())

    def test_gzip(self):
        self.assertEqual(ClientHTTP().charger(URL(self.base + "/gzip")).corps, b"<p>compresse</p>")

    def test_cookies(self):
        client = ClientHTTP()
        client.charger(URL(self.base + "/cookie"))
        self.assertEqual(client.charger(URL(self.base + "/montre-cookie")).corps, b"jeton=42")

    def test_post(self):
        reponse = ClientHTTP().charger(URL(self.base + "/"), "POST", "a=1&b=2")
        self.assertEqual(reponse.corps, b"recu:a=1&b=2")

    def test_page_avec_feuille_externe(self):
        page = charger_page(ClientHTTP(), URL(self.base + "/avec-style"))
        self.assertEqual(element(page.dom, "p").style["color"], "#123456")


class TestHTML(unittest.TestCase):
    def test_balises_implicites(self):
        dom = analyser_html("<title>T</title><p>Bonjour")
        self.assertEqual(dom.balise, "html")
        self.assertEqual([e.balise for e in dom.enfants], ["head", "body"])
        self.assertEqual(element(dom, "p").enfants[0].texte, "Bonjour")

    def test_fermetures_implicites(self):
        dom = analyser_html("<ul><li>un<li>deux</ul><p>a<p>b<table><td>x<td>y</table>")
        self.assertEqual(len(element(dom, "ul").enfants), 2)
        corps = element(dom, "body")
        self.assertEqual([e.balise for e in corps.enfants], ["ul", "p", "p", "table"])
        rangee = element(dom, "tr")
        self.assertEqual([e.balise for e in rangee.enfants], ["td", "td"])

    def test_attributs_et_entites(self):
        dom = analyser_html('<a href="/x?a=1&amp;b=2" class=lien data-v=\'z\'>&eacute;t&eacute; &#233; &#xE9; &copy</a>')
        lien = element(dom, "a")
        self.assertEqual(lien.attributs, {"href": "/x?a=1&b=2", "class": "lien", "data-v": "z"})
        self.assertEqual(lien.enfants[0].texte, "été é é ©")

    def test_script_et_commentaires(self):
        dom = analyser_html("<p>a<!-- <b>non</b> -->b</p><script>if (a<b) {}</script>")
        self.assertEqual(element(dom, "p").texte_contenu(), "ab")
        self.assertEqual(element(dom, "script").enfants[0].texte, "if (a<b) {}")

    def test_elements_vides(self):
        dom = analyser_html("<p>a<br>b<img src=x>c</p>")
        self.assertEqual([type(e).__name__ for e in element(dom, "p").enfants], ["Texte", "Element", "Texte", "Element", "Texte"])

    def test_entites_numeriques_windows(self):
        self.assertEqual(decoder_entites("&#146;&#8217;&nbsp;"), "’’ ")


class TestCSS(unittest.TestCase):
    def test_couleurs(self):
        self.assertEqual(analyser_couleur("#abc"), "#aabbcc")
        self.assertEqual(analyser_couleur("rgb(255, 0, 10)"), "#ff000a")
        self.assertEqual(analyser_couleur("hsl(120, 100%, 25%)"), "#008000")
        self.assertEqual(analyser_couleur("rgba(0,0,0,0)"), "transparent")
        self.assertEqual(analyser_couleur("Navy"), "#000080")
        self.assertIsNone(analyser_couleur("pas-une-couleur"))

    def test_longueurs(self):
        self.assertEqual(longueur("12px"), 12)
        self.assertEqual(longueur("2em", 10), 20)
        self.assertEqual(longueur("50%", 16, 300), 150)
        self.assertEqual(longueur("12pt"), 16)
        self.assertEqual(longueur("calc(100% - 20px)", 16, 200), 180)

    def test_raccourcis(self):
        declarations = dict((p, v) for p, v, _ in analyser_declarations("margin: 1px 2px; border: 2px solid red"))
        self.assertEqual(declarations["margin-left"], "2px")
        self.assertEqual(declarations["margin-bottom"], "1px")
        self.assertEqual(declarations["border-top-width"], "2px")
        self.assertEqual(declarations["border-left-color"], "red")

    def test_cascade(self):
        dom = analyser_html('<div id=a class="x y"><p class=z style="font-style:italic">t</p></div>')
        css = """
            p { color: red }
            .x p { color: green }
            #a .z { color: blue }
            div > p.z { font-weight: bold !important }
            p { font-weight: normal }
            @media print { p { color: black } }
        """
        calculer_styles(dom, [analyser_css(FEUILLE_PAR_DEFAUT), analyser_css(css)])
        p = element(dom, "p")
        self.assertEqual(p.style["color"], "#0000ff")
        self.assertEqual(p.style["font-weight"], "bold")
        self.assertEqual(p.style["font-style"], "italic")
        self.assertEqual(p.enfants[0].style["color"], "#0000ff")  # héritage

    def test_heritage_taille(self):
        dom = analyser_html('<div style="font-size:20px"><p style="font-size:1.5em"><span style="font-size:50%">x</span></p></div>')
        calculer_styles(dom, [analyser_css(FEUILLE_PAR_DEFAUT)])
        self.assertEqual(element(dom, "span").style["font-size"], "15.00px")

    def test_selecteurs_avances(self):
        dom = analyser_html('<ul><li>a</li><li class=b>b</li><li>c</li></ul><input type=text>')
        css = "li:first-child{color:red} li.b + li{color:green} input[type=text]{color:blue} li:not(.b){font-weight:bold}"
        calculer_styles(dom, [analyser_css(FEUILLE_PAR_DEFAUT), analyser_css(css)])
        items = [n for n in parcourir(dom) if isinstance(n, Element) and n.balise == "li"]
        self.assertEqual([i.style["color"] for i in items], ["#ff0000", "#000000", "#008000"])
        self.assertEqual([i.style["font-weight"] for i in items], ["bold", "normal", "bold"])
        self.assertEqual(element(dom, "input").style["color"], "#0000ff")


class TestMiseEnPage(unittest.TestCase):
    def textes(self, commandes):
        return [c.texte for c in commandes if isinstance(c, CmdTexte)]

    def test_retour_a_la_ligne(self):
        # 16px -> 8px par caractère ; largeur utile 100 - 2*8 (marges de body) = 84px
        _, _, commandes, _ = mettre_en_page("<p>aaaa bbbb cccc</p>", largeur=100)
        mots = [c for c in commandes if isinstance(c, CmdTexte)]
        self.assertEqual(len({c.y for c in mots}), 2)

    def test_blocs_empiles(self):
        _, document, commandes, _ = mettre_en_page("<h1>Titre</h1><p>Texte</p>")
        titre, texte = [c for c in commandes if isinstance(c, CmdTexte)]
        self.assertLess(titre.y, texte.y)
        self.assertGreater(document.hauteur, texte.y)

    def test_centrage(self):
        _, _, commandes, _ = mettre_en_page('<div style="width:200px;margin:0 auto">x</div>', largeur=616)
        texte = next(c for c in commandes if isinstance(c, CmdTexte))
        self.assertEqual(texte.x, 8 + (600 - 200) / 2)

    def test_alignement_centre(self):
        _, _, commandes, _ = mettre_en_page('<p style="text-align:center">abcd</p>', largeur=216)
        texte = next(c for c in commandes if isinstance(c, CmdTexte))
        self.assertEqual(texte.x, 8 + (200 - 32) / 2)

    def test_liens_cliquables(self):
        _, _, _, zones = mettre_en_page('<p>Voir <a href="/page">ce lien</a></p>')
        self.assertTrue(zones)
        self.assertTrue(all(z.genre == "lien" and z.noeud.attributs["href"] == "/page" for z in zones))

    def test_display_none(self):
        _, _, commandes, _ = mettre_en_page('<p>visible</p><p style="display:none">cache</p><script>code</script>')
        self.assertEqual(self.textes(commandes), ["visible"])

    def test_liste_numerotee(self):
        _, _, commandes, _ = mettre_en_page('<ol><li>a<li>b</ol><ul><li>c</ul>')
        textes = self.textes(commandes)
        self.assertIn("1.", textes)
        self.assertIn("2.", textes)
        self.assertIn("•", textes)

    def test_tableau(self):
        _, _, commandes, _ = mettre_en_page("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>")
        positions = {c.texte: (c.x, c.y) for c in commandes if isinstance(c, CmdTexte)}
        self.assertEqual(positions["a"][1], positions["b"][1])   # même rangée
        self.assertLess(positions["a"][0], positions["b"][0])    # colonnes côte à côte
        self.assertEqual(positions["a"][0], positions["c"][0])   # colonnes alignées
        self.assertLess(positions["a"][1], positions["c"][1])

    def test_pre(self):
        _, _, commandes, _ = mettre_en_page("<pre>  a\n    b</pre>")
        self.assertEqual(self.textes(commandes), ["  a", "    b"])

    def test_formulaire(self):
        _, _, commandes, zones = mettre_en_page('<form><input name=q value="salut"><input type=submit value=Go></form>')
        self.assertEqual([z.genre for z in zones], ["champ", "champ"])
        self.assertIn("salut", self.textes(commandes))
        self.assertIn("Go", self.textes(commandes))

    def test_ancres(self):
        _, document, _, _ = mettre_en_page('<p>a</p><h2 id="section">S</h2>')
        self.assertIn("section", document.contexte.ancres)


class TestStockage(unittest.TestCase):
    def test_favoris_et_historique(self):
        with tempfile.TemporaryDirectory() as dossier:
            stockage = Stockage(dossier)
            self.assertTrue(stockage.basculer_favori("https://a.fr/", "A"))
            stockage.ajouter_historique("https://a.fr/", "A")
            relu = Stockage(dossier)
            self.assertTrue(relu.est_favori("https://a.fr/"))
            self.assertEqual(relu.historique[0]["url"], "https://a.fr/")
            self.assertFalse(relu.basculer_favori("https://a.fr/", "A"))


class TestPagesInternes(unittest.TestCase):
    def test_accueil(self):
        with tempfile.TemporaryDirectory() as dossier:
            page = charger_page(ClientHTTP(), URL("about:accueil"), stockage=Stockage(dossier))
        self.assertEqual(page.titre, "Accueil")
        formulaire = element(page.dom, "form")
        self.assertIn("duckduckgo", formulaire.attributs["action"])
        self.assertNotIn("google", formulaire.attributs["action"])


if __name__ == "__main__":
    unittest.main()
