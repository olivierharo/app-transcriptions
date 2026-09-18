"""
Administration du relais : comptes des membres de l'equipe.

    python admin.py creer olivier       cree le compte (ou renouvelle ses cles)
    python admin.py lister              comptes et fichiers en attente
    python admin.py supprimer olivier   supprime le compte et sa boite

Avec Docker :  docker compose exec relais python admin.py creer olivier

"creer" affiche le CODE DE CONNEXION a coller dans l'application du PC
(bouton « iPhone »). L'application affiche ensuite elle-meme le QR code a
scanner avec l'iPhone. Les cles ne sont montrees qu'a ce moment-la : le
serveur n'en garde qu'une empreinte.
"""
import os
import sys
import json
import base64
import shutil

import relais


def code_connexion(url, nom, envoi, retrait):
    donnees = json.dumps({"u": url.rstrip("/"), "n": nom, "e": envoi, "r": retrait}, separators=(",", ":"))
    return "TR1-" + base64.urlsafe_b64encode(donnees.encode()).decode().rstrip("=")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("creer", "lister", "supprimer"):
        print(__doc__)
        return 1
    commande = sys.argv[1]

    if commande == "lister":
        comptes = relais.lire_comptes()
        if not comptes:
            print("Aucun compte.")
        for nom, c in sorted(comptes.items()):
            attente = relais.contenu_boite(nom)
            print(f"{nom:20} créé le {c.get('cree', '?')[:10]}   "
                  f"{len(attente)} fichier(s) en attente ({sum(m['taille'] for m in attente) / 1024 ** 2:.0f} Mo)")
        return 0

    if len(sys.argv) < 3:
        print("Précisez le nom du membre, ex. : python admin.py creer olivier")
        return 1
    nom = sys.argv[2].strip().lower()

    if commande == "supprimer":
        comptes = relais.lire_comptes()
        if nom not in comptes:
            print(f"Pas de compte « {nom} ».")
            return 1
        del comptes[nom]
        relais.ecrire_comptes(comptes)
        shutil.rmtree(os.path.join(relais.DONNEES, "boites", nom), ignore_errors=True)
        print(f"Compte « {nom} » et sa boîte supprimés.")
        return 0

    url = os.environ.get("RELAIS_URL")
    if not url:
        print("Variable RELAIS_URL absente (ex. https://transcriptions.mondomaine.fr).")
        return 1
    existait = nom in relais.lire_comptes()
    envoi, retrait = relais.creer_cles(nom)
    code = code_connexion(url, nom, envoi, retrait)
    print()
    print(("Clés RENOUVELÉES" if existait else "Compte créé") + f" pour « {nom} ».")
    if existait:
        print("Les anciennes clés ne fonctionnent plus : reconnectez le PC et refaites les raccourcis iPhone.")
    print()
    print("Code de connexion à coller dans l'application (bouton « 📱 iPhone ») :")
    print()
    print("  " + code)
    print()
    print("Transmettez-le à la personne concernée par un canal sûr : il donne accès à sa boîte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
