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
    """Preferences utilisateur, dans %APPDATA% (Windows) ou ~/.config
    (Linux) : elles survivent aux reinstallations et mises a jour."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
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


def _dossier_documents():
    """Dossier Documents REEL de l'utilisateur courant.

    On interroge Windows plutot que de supposer ~/Documents : sur les postes
    ou OneDrive (ou une strategie d'entreprise) redirige Documents, le
    dossier ~/Documents est vide ou absent.
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            from uuid import UUID

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7")   # FOLDERID_Documents
            guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                        (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
            ptr = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32
            if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                            ctypes.byref(ptr)) == 0:
                chemin = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if chemin:
                    return chemin
        except Exception:
            pass
    else:
        # Linux : le nom du dossier depend de la langue ("Documents"...),
        # xdg-user-dir donne le bon.
        try:
            import subprocess
            chemin = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True,
                                    text=True, timeout=5).stdout.strip()
            if chemin and chemin != os.path.expanduser("~") and os.path.isdir(chemin):
                return chemin
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def dossier_par_defaut():
    return os.path.join(_dossier_documents(), "Enregistrements audio")


def _utilisable(chemin):
    """Vrai si le dossier existe ou peut etre cree (lecteur present, droits)."""
    try:
        os.makedirs(chemin, exist_ok=True)
        return os.path.isdir(chemin)
    except OSError:
        return False


def dossier_enregistrements():
    """Dossier des enregistrements.

    Priorite : choix fait dans l'application, puis DOSSIER_ENREGISTREMENTS
    (.env ou environnement), puis la valeur par defaut. Le choix de
    l'utilisateur passe en premier pour que le bouton de l'interface
    fonctionne toujours, meme si une variable d'environnement traine.

    Un choix devenu inaccessible (lecteur reseau deconnecte, cle USB
    retiree, parametres copies d'un autre poste) est ignore : on passe
    au suivant plutot que d'empecher l'application de demarrer.
    """
    candidats = [lire_parametres().get("dossier_enregistrements"),
                 os.environ.get("DOSSIER_ENREGISTREMENTS")]
    for c in candidats:
        if c:
            c = os.path.expandvars(os.path.expanduser(c))
            if _utilisable(c):
                return c
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
