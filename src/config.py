"""
Configuration partagee.

Lit le fichier .env a la racine du projet (jamais versionne) puis les variables
d'environnement. Aucun secret n'est ecrit en dur dans les sources.
"""
import os
import json

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def charger_env(chemin=None):
    """Charge un .env simple (CLE=valeur) sans ecraser l'environnement existant."""
    chemin = chemin or os.path.join(RACINE, ".env")
    if not os.path.exists(chemin):
        return
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, val = ligne.partition("=")
            cle, val = cle.strip(), val.strip().strip('"').strip("'")
            if cle and val and cle not in os.environ:
                os.environ[cle] = val


charger_env()


def _fichier_parametres():
    """Preferences utilisateur, dans %APPDATA% : elles survivent aux
    reconstructions de l'executable et aux mises a jour du projet."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    dossier = os.path.join(base, "Transcriptions")
    os.makedirs(dossier, exist_ok=True)
    return os.path.join(dossier, "parametres.json")


def lire_parametres():
    try:
        with open(_fichier_parametres(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ecrire_parametre(cle, valeur):
    p = lire_parametres()
    p[cle] = valeur
    chemin = _fichier_parametres()
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def dossier_par_defaut():
    return os.path.join(os.path.expanduser("~"), "Documents", "Enregistrements audio")


def dossier_enregistrements():
    """Dossier des enregistrements.

    Priorite : choix fait dans l'application, puis DOSSIER_ENREGISTREMENTS
    (.env ou environnement), puis la valeur par defaut. Le choix de
    l'utilisateur passe en premier pour que le bouton de l'interface
    fonctionne toujours, meme si une variable d'environnement traine.
    """
    choisi = lire_parametres().get("dossier_enregistrements")
    if choisi:
        return os.path.expandvars(os.path.expanduser(choisi))
    d = os.environ.get("DOSSIER_ENREGISTREMENTS")
    if d:
        return os.path.expandvars(os.path.expanduser(d))
    return dossier_par_defaut()


def definir_dossier_enregistrements(chemin):
    """Memorise le dossier choisi dans l'application."""
    ecrire_parametre("dossier_enregistrements", os.path.abspath(chemin))


def hf_token():
    """Token Hugging Face, ou None. Jamais affiche ni journalise."""
    tok = os.environ.get("HF_TOKEN")
    if tok:
        return tok
    # 'setx' n'atteint pas les processus deja lances : relire l'environnement utilisateur.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val = winreg.QueryValueEx(k, "HF_TOKEN")[0]
            return val or None
    except Exception:
        return None
