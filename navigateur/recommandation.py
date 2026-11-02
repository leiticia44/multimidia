"""Recommandation de pages par filtrage basé sur le contenu.

D'après G. Kembellec, M. Chevalier, D. Dudognon, « Systèmes de recommandation »,
Techniques de l'Ingénieur, H7245, 2015 (§ 3, filtrage basé sur le contenu) :

  1. chaque document est représenté par un vecteur de termes pondérés par TF-IDF
     (un mot compte s'il est fréquent dans le document et rare dans l'ensemble) ;
  2. le profil de l'usager est construit à partir de ce qu'il a apprécié — ici, les
     pages qu'il a annotées, ses passages surlignés, ses notes et ses mots-clés ;
  3. on recommande les documents dont le vecteur est le plus proche du profil,
     mesuré par la similarité cosinus.

Comme dans l'article, cette approche ne dépend pas des autres usagers (pas de
démarrage à froid côté communauté) mais risque la surspécialisation : elle propose
des pages proches de ce qu'on connaît déjà.
"""

import math
import re
from collections import Counter

MOTS_VIDES = set("""
a à afin ai aie aient ainsi alors as au aucun aucune aupres auquel aura auront aussi autre autres aux auxquels
avaient avais avait avant avec avez aviez avoir avons ayant bien c ça car ce ceci cela celle celles celui cependant
ces cet cette ceux chaque chez ci comme comment d dans de des depuis donc dont du elle elles en encore entre est et
été étaient était être eu eux fait faire fois font hors il ils j je jusqu l la là le les leur leurs lors lui m ma mais
me même mes moi mon n ne ni non nos notre nous on ont ou où par parce pas peu peut plus pour pourquoi qu quand que quel
quelle quelles quels qui s sa sans se selon ses si sien son sont sous sur t ta tandis te tes toi ton tous tout toute
toutes très tu un une unes uns vers vos votre vous y
the and for are but not you all any can had her was one our out has have this that with from they will would there
their what about which when your into more other some than then them these these also its may such only been were
wikipédia wikipedia modifier code source article page pages lien liens voir aide accueil
""".split())


def mots(texte):
    """Découpe un texte en mots significatifs (minuscules, 3 lettres ou plus, sans mots vides)."""
    return [m for m in re.findall(r"[a-zà-ÿœæç]+", (texte or "").lower())
            if len(m) >= 3 and m not in MOTS_VIDES]


def vecteurs_tfidf(documents):
    """documents : {clé: texte} -> ({clé: {mot: poids}}, idf)"""
    comptes = {cle: Counter(mots(texte)) for cle, texte in documents.items()}
    n = len(comptes) or 1
    frequence_doc = Counter()
    for c in comptes.values():
        frequence_doc.update(c.keys())
    idf = {m: math.log((1 + n) / (1 + df)) + 1 for m, df in frequence_doc.items()}
    vecteurs = {}
    for cle, c in comptes.items():
        total = sum(c.values()) or 1
        vecteurs[cle] = {m: (f / total) * idf[m] for m, f in c.items()}
    return vecteurs, idf


def cosinus(a, b):
    """Similarité cosinus entre deux vecteurs creux {mot: poids} (0 = rien en commun, 1 = identiques)."""
    if len(a) > len(b):
        a, b = b, a
    produit = sum(p * b.get(m, 0.0) for m, p in a.items())
    na = math.sqrt(sum(p * p for p in a.values()))
    nb = math.sqrt(sum(p * p for p in b.values()))
    return produit / (na * nb) if na and nb else 0.0


def recommander(candidats, profil, nombre=10):
    """Classe les pages candidates selon leur proximité avec le profil de l'usager.

    candidats : {url: (titre, texte)}  — pages connues que l'usager n'a pas encore annotées
    profil    : [(texte, poids)]       — ce que l'usager a apprécié (pages annotées, passages,
                                         notes, mots-clés), chacun avec un poids
    Renvoie [(score, url, titre, mots_communs)] du plus proche au moins proche.
    """
    if not candidats or not profil:
        return []
    documents = {url: (titre or "") + " " + (texte or "") for url, (titre, texte) in candidats.items()}
    for k, (texte, _) in enumerate(profil):
        documents[("profil", k)] = texte
    vecteurs, _ = vecteurs_tfidf(documents)
    vecteur_profil = Counter()
    for k, (_, poids) in enumerate(profil):
        for m, p in vecteurs[("profil", k)].items():
            vecteur_profil[m] += poids * p
    resultats = []
    for url, (titre, _) in candidats.items():
        v = vecteurs[url]
        score = cosinus(vecteur_profil, v)
        if score > 0:
            communs = sorted((m for m in v if m in vecteur_profil),
                             key=lambda m: v[m] * vecteur_profil[m], reverse=True)[:6]
            resultats.append((score, url, titre or url, communs))
    resultats.sort(key=lambda r: r[0], reverse=True)
    return resultats[:nombre]


def profil_usager(reseau, contenus):
    """Le profil de l'usager d'après ses annotations (§ 3 de l'article : ce qu'il a apprécié).

    contenus : {url: (titre, texte)} — le texte des pages connues (visites et agent Web).
    """
    profil, annotees = [], set()
    for a in reseau.annotations:
        url = a["url"].split("#")[0]
        annotees.add(url)
        if a["passage"]:
            profil.append((a["passage"], 3.0))           # un passage surligné compte beaucoup
        if a["note"]:
            profil.append((a["note"], 2.0))
        if a["mots_cles"]:
            profil.append((" ".join(a["mots_cles"]), 4.0))  # les mots-clés, choisis par l'usager
    for url in annotees:
        if url in contenus:
            titre, texte = contenus[url]
            profil.append(((titre or "") + " " + (texte or ""), 1.0))
    for n in reseau.noeuds.values():
        if n.get("mots_cles"):
            profil.append((" ".join(n["mots_cles"]), 2.0))
    return profil, annotees
