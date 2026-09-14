"""
Configuration partagee.

Lit le fichier .env a la racine du projet (jamais versionne) puis les variables
d'environnement. Aucun secret n'est ecrit en dur dans les sources.
"""
import os

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


def dossier_enregistrements():
    """Dossier surveille. Configurable via DOSSIER_ENREGISTREMENTS."""
    d = os.environ.get("DOSSIER_ENREGISTREMENTS")
    if d:
        return os.path.expandvars(os.path.expanduser(d))
    return os.path.join(os.path.expanduser("~"), "Documents", "Enregistrements audio")


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
