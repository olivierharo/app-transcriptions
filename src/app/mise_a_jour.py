"""
Mises a jour : compare la version installee a la derniere release GitHub,
telecharge l'installateur correspondant et le lance en mode --mise-a-jour.

L'installateur complet est reutilise plutot qu'un simple remplacement des
fichiers : il installe aussi les nouvelles dependances si une version en a
besoin, sans retelecharger les modeles ni toucher au token.

Pour tester sans publier de version : TRANSCRIPTIONS_VERSION_TEST=1.0.0 fait
croire a l'application qu'elle est plus ancienne.
"""
import os
import sys
import json
import hashlib
import subprocess
import tempfile
import urllib.error
import urllib.request

from app import __version__

URL_API = "https://api.github.com/repos/olivierharo/app-transcriptions/releases/latest"
DELAI_RESEAU = 20
WINDOWS = sys.platform == "win32"
NOM_INSTALLATEUR = "Transcriptions-Setup.exe" if WINDOWS else "Transcriptions-Setup-Ubuntu"


class ErreurMiseAJour(Exception):
    pass


def version_installee():
    return os.environ.get("TRANSCRIPTIONS_VERSION_TEST") or __version__


def _numeros(version):
    """'v1.10.2' -> (1, 10, 2) ; les parties non numeriques valent 0."""
    parties = []
    for p in version.lstrip("vV").split("."):
        chiffres = "".join(c for c in p if c.isdigit())
        parties.append(int(chiffres) if chiffres else 0)
    return tuple(parties)


def plus_recente(disponible, installee):
    return _numeros(disponible) > _numeros(installee)


def _ouvrir(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Transcriptions/" + __version__,
                                               "Accept": "application/vnd.github+json"})
    try:
        return urllib.request.urlopen(req, timeout=DELAI_RESEAU)
    except urllib.error.HTTPError as e:
        raise ErreurMiseAJour(f"Erreur de GitHub ({e.code}).")
    except (urllib.error.URLError, OSError) as e:
        raise ErreurMiseAJour(f"GitHub injoignable ({getattr(e, 'reason', e)}).")


def verifier():
    """Retourne la mise a jour disponible (dict) ou None si l'on est a jour.

        {"version", "page", "url", "taille", "sha256"}
    """
    with _ouvrir(URL_API) as r:
        try:
            d = json.load(r)
        except ValueError:
            raise ErreurMiseAJour("Réponse de GitHub illisible.")
    version = (d.get("tag_name") or "").lstrip("vV")
    if not version or d.get("draft") or d.get("prerelease") or not plus_recente(version, version_installee()):
        return None
    for a in d.get("assets", []):
        if a.get("name") == NOM_INSTALLATEUR:
            digest = a.get("digest") or ""
            return {"version": version, "page": d.get("html_url", ""),
                    "url": a["browser_download_url"], "taille": a.get("size", 0),
                    "sha256": digest[7:] if digest.startswith("sha256:") else ""}
    # Release publiee mais installateur pas encore depose : on reessaiera plus tard.
    return None


def telecharger(info, progression=None, annule=None):
    """Telecharge l'installateur dans le dossier temporaire et verifie son
    empreinte. progression(recu, total) ; annule() -> True pour interrompre."""
    cible = os.path.join(tempfile.gettempdir(), NOM_INSTALLATEUR)
    partiel = cible + ".partiel"
    empreinte = hashlib.sha256()
    recu = 0
    with _ouvrir(info["url"]) as r, open(partiel, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("taille") or 0)
        while True:
            if annule and annule():
                break
            bloc = r.read(256 * 1024)
            if not bloc:
                break
            f.write(bloc)
            empreinte.update(bloc)
            recu += len(bloc)
            if progression:
                progression(recu, total)
    if annule and annule():
        os.remove(partiel)
        return None
    if info.get("sha256") and empreinte.hexdigest() != info["sha256"]:
        os.remove(partiel)
        raise ErreurMiseAJour("Le fichier téléchargé est abîmé (empreinte incorrecte). Réessayez plus tard.")
    if total and recu != total:
        os.remove(partiel)
        raise ErreurMiseAJour("Téléchargement incomplet. Réessayez plus tard.")
    os.replace(partiel, cible)
    if not WINDOWS:
        os.chmod(cible, 0o755)
    return cible


def lancer_installateur(chemin, destination):
    """Lance l'installateur detache de l'application, qui doit ensuite se fermer."""
    # L'environnement de l'application (Qt, bibliotheques) ne doit pas se
    # meler a celui de l'installateur, qui embarque les siens. La version de
    # test non plus : l'application relancee apres la mise a jour en heriterait.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("QT_") and k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME",
                                                    "TRANSCRIPTIONS_VERSION_TEST")}
    commande = [chemin, "--mise-a-jour", destination]
    if WINDOWS:
        subprocess.Popen(commande, env=env, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        subprocess.Popen(commande, env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
