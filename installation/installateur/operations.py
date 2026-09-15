"""
Operations d'installation et de desinstallation, sans interface graphique.

Tout ce qui touche au systeme est ici (GPU, Python, paquets, pip, modeles,
raccourcis, registre) ; l'assistant graphique ne fait qu'afficher la
progression rapportee par Installation.executer().

Windows 10/11 et Ubuntu 22.04/24.04.
"""
import os
import re
import sys
import glob
import json
import time
import shutil
import threading
import subprocess
import urllib.request

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")

NOM = "Transcriptions"
EDITEUR = "Olivier Haro"
PILOTE_MINIMUM = 570                  # requis par PyTorch CUDA 12.8
ESPACE_REQUIS = 14 * 1024 ** 3        # dependances + modeles, avec marge
VERSION_PYTHON_WINDOWS = "3.12.10"
PYTORCH = ["torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0"]
INDEX_PYTORCH = "https://download.pytorch.org/whl/cu128"
LIEN_TOKEN = "https://huggingface.co/settings/tokens"
CLE_DESINSTALLATION = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Transcriptions"

# Paquets Ubuntu : capture audio (parec, pactl), decodage audio de pyannote,
# plugin X11 de Qt 6, dossiers utilisateur localises.
PAQUETS_UBUNTU = ["pulseaudio-utils", "ffmpeg", "libxcb-cursor0", "xdg-user-dirs"]

# Modeles telecharges, avec leur taille pour suivre la progression.
MODELE_WHISPER = ("models--Systran--faster-whisper-large-v3", 3_090_837_011)
MODELE_ALIGNEMENT = ("wav2vec2_voxpopuli_base_10k_asr_fr.pt", 377_708_313)
MODELES_PYANNOTE = ["models--pyannote--segmentation-3.0",
                    "models--pyannote--speaker-diarization-3.1",
                    "models--pyannote--speaker-diarization-community-1"]


class Annule(Exception):
    pass


class ErreurInstallation(Exception):
    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


# --------------------------------------------------------------------------- #
# Emplacements
# --------------------------------------------------------------------------- #
def dossier_charge():
    """Fichiers de l'application embarques dans l'installateur."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "charge")
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def version_application():
    try:
        with open(os.path.join(dossier_charge(), "src", "app", "__init__.py"), encoding="utf-8") as f:
            return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
    except Exception:
        return ""


def destination_par_defaut():
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", NOM)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "transcriptions")


def python_environnement(dest, fenetre=False):
    if WINDOWS:
        return os.path.join(dest, ".venv-whisperx", "Scripts", "pythonw.exe" if fenetre else "python.exe")
    return os.path.join(dest, ".venv-whisperx", "bin", "python")


def deja_installe(dest):
    return os.path.exists(python_environnement(dest)) and os.path.isdir(os.path.join(dest, "src"))


def cache_huggingface():
    base = os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    return os.environ.get("HF_HUB_CACHE") or os.path.join(base, "hub")


def cache_torch():
    base = os.environ.get("TORCH_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "torch")
    return os.path.join(base, "hub", "checkpoints")


def espace_libre(chemin):
    chemin = os.path.abspath(chemin)
    while not os.path.exists(chemin):
        parent = os.path.dirname(chemin)
        if parent == chemin:
            return None
        chemin = parent
    try:
        return shutil.disk_usage(chemin).free
    except OSError:
        return None


def taille(chemin):
    if os.path.isfile(chemin):
        return os.path.getsize(chemin)
    total = 0
    for racine, _, fichiers in os.walk(chemin):
        for f in fichiers:
            try:
                total += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
    return total


def xdg_dossier(nom, defaut):
    try:
        r = subprocess.run(["xdg-user-dir", nom], capture_output=True, text=True, timeout=5,
                           env=environnement_propre()).stdout.strip()
        if r and r != os.path.expanduser("~"):
            return r
    except Exception:
        pass
    return os.path.expanduser(defaut)


# --------------------------------------------------------------------------- #
# Sous-processus
# --------------------------------------------------------------------------- #
def environnement_propre():
    """Environnement pour les programmes lances par l'installateur.

    Un executable PyInstaller modifie son propre environnement (bibliotheques
    et plugins Qt extraits dans un dossier temporaire). Transmis tels quels,
    ces reglages casseraient Python, apt ou l'application elle-meme, qui
    chercheraient leurs bibliotheques dans un dossier bientot supprime.
    """
    env = dict(os.environ)
    if LINUX:
        origine = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if origine is not None:
            env["LD_LIBRARY_PATH"] = origine
        elif getattr(sys, "frozen", False):
            env.pop("LD_LIBRARY_PATH", None)
    for cle in list(env):
        if cle.startswith(("QT_", "QML", "PYTHONHOME", "PYTHONPATH", "_MEI", "_PYI")):
            del env[cle]
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PIP_NO_INPUT="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def _options_processus():
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def trouver_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe and WINDOWS:
        candidat = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        exe = candidat if os.path.exists(candidat) else None
    return exe


def detecter_gpu():
    """(nom, version_pilote) de la premiere carte NVIDIA, ou None."""
    exe = trouver_nvidia_smi()
    if not exe:
        return None
    try:
        sortie = subprocess.run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=20,
                                env=environnement_propre(), **_options_processus()).stdout
    except Exception:
        return None
    for ligne in sortie.splitlines():
        if "," in ligne:
            nom, _, pilote = ligne.rpartition(",")
            return nom.strip(), pilote.strip()
    return None


def pilote_suffisant(pilote):
    try:
        return int(pilote.split(".")[0]) >= PILOTE_MINIMUM
    except (ValueError, AttributeError):
        return True        # format inconnu : on ne bloque pas


def token_existant(dest):
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        with open(os.path.join(dest, ".env"), encoding="utf-8") as f:
            if re.search(r"^HF_TOKEN=\S+", f.read(), re.M):
                return True
    except OSError:
        pass
    if WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return bool(winreg.QueryValueEx(k, "HF_TOKEN")[0])
        except OSError:
            pass
    return False


# --------------------------------------------------------------------------- #
# Installation
# --------------------------------------------------------------------------- #
ETAPES = [
    # (cle, libelle, poids dans la barre globale)
    ("prerequis", "Prérequis système", 4),
    ("fichiers", "Fichiers de l'application", 2),
    ("pytorch", "PyTorch (moteur d'IA)", 48),
    ("dependances", "WhisperX et dépendances", 16),
    ("modeles", "Modèles d'intelligence artificielle", 28),
    ("finalisation", "Finalisation", 2),
]


class Installation:
    """Deroule l'installation. Rapporte l'avancement par callbacks :

        etape(index, libelle)        debut d'une etape
        progression(fraction, texte) avancement GLOBAL (0..1) et detail
        journal(ligne)               sortie brute, pour "Afficher les details"
    """

    def __init__(self, destination, token="", etape=None, progression=None, journal=None):
        self.dest = os.path.abspath(destination)
        self.token = token.strip()
        self._etape = etape or (lambda i, l: None)
        self._progression = progression or (lambda f, t: None)
        self._journal = journal or (lambda l: None)
        self._index = 0
        self._proc = None
        self._annule = False
        self.avertissements = []

    # ------------------------------------------------------------ outils --
    def annuler(self):
        self._annule = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def _verifier(self):
        if self._annule:
            raise Annule()

    def _debut(self, cle):
        self._verifier()
        self._index = [e[0] for e in ETAPES].index(cle)
        self._etape(self._index, ETAPES[self._index][1])
        self._avancer(0.0, "")

    def _avancer(self, fraction, texte):
        """fraction : avancement dans l'etape courante (0..1)."""
        total = sum(e[2] for e in ETAPES)
        fait = sum(e[2] for e in ETAPES[:self._index])
        poids = ETAPES[self._index][2]
        self._progression((fait + poids * max(0.0, min(1.0, fraction))) / total, texte)

    def _executer(self, commande, message_erreur, cwd=None, lecteur=None):
        """Lance une commande, transmet chaque ligne au journal (et au lecteur)."""
        self._verifier()
        self._journal("$ " + " ".join(commande))
        try:
            self._proc = subprocess.Popen(
                commande, cwd=cwd, env=environnement_propre(), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **_options_processus())
        except OSError as e:
            raise ErreurInstallation(message_erreur, str(e))
        dernieres = []
        for brut in self._proc.stdout:
            ligne = brut.decode("utf-8", "replace").rstrip()
            if not ligne:
                continue
            dernieres = (dernieres + [ligne])[-40:]
            if not ligne.startswith("Progress "):
                self._journal(ligne)
            if lecteur:
                lecteur(ligne)
        code = self._proc.wait()
        self._proc = None
        self._verifier()
        if code != 0:
            raise ErreurInstallation(f"{message_erreur} (code {code}).", "\n".join(dernieres))

    def _pip(self, arguments, message_erreur, estimation):
        """pip install avec progression reelle, octet par octet (--progress-bar raw)."""
        etat = {"fini": 0, "courant": 0, "nom": "", "installation": False}

        def lire(ligne):
            m = re.match(r"(?:Downloading|Collecting) (\S+)", ligne)
            if ligne.startswith("Downloading "):
                etat["fini"] += etat["courant"]
                etat["courant"] = 0
                etat["nom"] = m.group(1).split("-")[0] if m else ""
            m = re.match(r"Progress (\d+) of (\d+)", ligne)
            if m:
                etat["courant"] = int(m.group(1))
                recu = etat["fini"] + etat["courant"]
                self._avancer(0.93 * min(1.0, recu / estimation),
                              f"Téléchargement de {etat['nom']} — {_go(recu)} / ~{_go(estimation)}")
            elif ligne.startswith("Installing collected packages"):
                etat["installation"] = True
                self._avancer(0.95, "Installation des paquets (quelques minutes)…")
            elif ligne.startswith(("Using cached", "Requirement already satisfied")) and not etat["installation"]:
                self._avancer(0.93 * min(1.0, etat["fini"] / estimation), "Vérification des paquets déjà présents…")

        self._executer([python_environnement(self.dest), "-m", "pip", "install", "--progress-bar", "raw",
                        "--timeout", "120", "--retries", "10"] + arguments, message_erreur, lecteur=lire)
        self._avancer(1.0, "")

    # ----------------------------------------------------------- etapes --
    def executer(self):
        self._prerequis()
        self._fichiers()
        self._debut("pytorch")
        self._pip(PYTORCH + ["--index-url", INDEX_PYTORCH], "Installation de PyTorch échouée",
                  estimation=3.6 * 1024 ** 3)
        self._debut("dependances")
        self._pip(["-r", os.path.join(self.dest, "requirements-app.txt")],
                  "Installation des dépendances échouée", estimation=0.7 * 1024 ** 3)
        self._modeles()
        self._finalisation()

    def _prerequis(self):
        self._debut("prerequis")
        os.makedirs(self.dest, exist_ok=True)
        if WINDOWS:
            python = self._python_windows()
        else:
            python = self._python_ubuntu()
        self._verifier()
        if not os.path.exists(python_environnement(self.dest)):
            self._avancer(0.8, "Création de l'environnement Python…")
            self._executer([python, "-m", "venv", os.path.join(self.dest, ".venv-whisperx")],
                           "Création de l'environnement Python impossible")
        self._avancer(0.9, "Mise à jour de pip…")
        # pip livre avec Python ne connait pas encore --progress-bar raw
        self._executer([python_environnement(self.dest), "-m", "pip", "install", "--upgrade", "pip"],
                       "Mise à jour de pip impossible")
        self._avancer(1.0, "")

    def _python_windows(self):
        def trouver():
            candidat = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python312", "python.exe")
            if os.path.exists(candidat):
                return candidat
            py = shutil.which("py")
            if py:
                try:
                    r = subprocess.run([py, "-3.12", "-c", "import sys; print(sys.executable)"],
                                       capture_output=True, text=True, timeout=30,
                                       env=environnement_propre(), **_options_processus())
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                except Exception:
                    pass
            return None

        python = trouver()
        if python:
            self._journal("Python 3.12 : " + python)
            return python
        url = (f"https://www.python.org/ftp/python/{VERSION_PYTHON_WINDOWS}/"
               f"python-{VERSION_PYTHON_WINDOWS}-amd64.exe")
        cible = os.path.join(os.environ.get("TEMP", self.dest), f"python-{VERSION_PYTHON_WINDOWS}-amd64.exe")
        self._telecharger(url, cible, "Téléchargement de Python 3.12", 0.0, 0.5)
        self._avancer(0.55, "Installation de Python 3.12…")
        try:
            self._executer([cible, "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0",
                            "Include_test=0", "Shortcuts=0", "AssociateFiles=0"],
                           "Installation de Python 3.12 échouée")
        finally:
            try:
                os.remove(cible)
            except OSError:
                pass
        python = trouver()
        if not python:
            raise ErreurInstallation("Python 3.12 reste introuvable après son installation.")
        return python

    def _python_ubuntu(self):
        installes = [f"python{v}" for v in ("3.12", "3.11", "3.10", "3.13") if shutil.which(f"python{v}")]
        if installes:
            python = installes[0]
        else:
            python = next((f"python{v}" for v in ("3.12", "3.11", "3.10", "3.13")
                           if subprocess.run(["apt-cache", "show", f"python{v}-venv"], capture_output=True,
                                             env=environnement_propre()).returncode == 0), None)
            if not python:
                raise ErreurInstallation("Aucun Python 3.10 à 3.13 disponible pour cette version d'Ubuntu.")
        paquets = [python, python + "-venv"] + PAQUETS_UBUNTU
        manquants = [p for p in paquets if not _paquet_installe(p)]
        if manquants:
            self._avancer(0.2, "Installation des paquets système : " + ", ".join(manquants))
            if not shutil.which("pkexec"):
                raise ErreurInstallation(
                    "Paquets système manquants.",
                    "Installez-les dans un terminal puis relancez l'installateur :\n"
                    "sudo apt install " + " ".join(manquants))
            script = "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y " + " ".join(manquants)
            self._executer(["pkexec", "sh", "-c", script],
                           "Installation des paquets système refusée ou échouée")
        return shutil.which(python) or python

    def _telecharger(self, url, cible, texte, debut, fin):
        self._journal("Téléchargement : " + url)
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(cible, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                recu = 0
                while True:
                    self._verifier()
                    bloc = r.read(256 * 1024)
                    if not bloc:
                        break
                    f.write(bloc)
                    recu += len(bloc)
                    if total:
                        self._avancer(debut + (fin - debut) * recu / total, f"{texte} — {_mo(recu)} / {_mo(total)}")
        except Annule:
            raise
        except Exception as e:
            raise ErreurInstallation(f"{texte} impossible.", str(e))

    def _fichiers(self):
        self._debut("fichiers")
        charge = dossier_charge()
        src = os.path.join(self.dest, "src")
        if os.path.normcase(os.path.abspath(charge)) == os.path.normcase(self.dest):
            raise ErreurInstallation("Le dossier d'installation ne peut pas être celui des sources.")
        if os.path.isdir(src):
            shutil.rmtree(src)
        shutil.copytree(os.path.join(charge, "src"), src,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env"))
        shutil.copy2(os.path.join(charge, "requirements-app.txt"), self.dest)
        if self.token:
            chemin = os.path.join(self.dest, ".env")
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(f"HF_TOKEN={self.token}\n")
            if LINUX:
                os.chmod(chemin, 0o600)
        self._avancer(1.0, "")

    def _modeles(self):
        self._debut("modeles")
        whisper = os.path.join(cache_huggingface(), MODELE_WHISPER[0])
        alignement = os.path.join(cache_torch(), MODELE_ALIGNEMENT[0])
        total = MODELE_WHISPER[1] + MODELE_ALIGNEMENT[1]
        phase = {"n": 1}
        arret = threading.Event()

        def surveiller():
            # Les bibliotheques ne donnent pas de progression exploitable :
            # on mesure ce qui arrive sur le disque.
            while not arret.wait(1.0):
                w = min(taille(whisper), MODELE_WHISPER[1])
                a = min(sum(taille(f) for f in glob.glob(alignement + "*")) +
                        sum(taille(f) for f in glob.glob(os.path.join(cache_torch(), "tmp*"))),
                        MODELE_ALIGNEMENT[1])
                textes = {1: "Modèle de transcription Whisper large-v3",
                          2: "Modèle d'alignement au mot près",
                          3: "Modèles de séparation des voix"}
                self._avancer(0.97 * (w + a) / total,
                              f"{textes[phase['n']]} — {_go(w + a)} / {_go(total)}")

        def lire(ligne):
            m = re.search(r"\[(\d)/3\]", ligne)
            if m:
                phase["n"] = int(m.group(1))
            if "ECHEC" in ligne:
                self.avertissements.append(ligne.strip())

        fil = threading.Thread(target=surveiller, daemon=True)
        fil.start()
        try:
            self._executer([python_environnement(self.dest), "-m", "app.prechargement"],
                           "Téléchargement des modèles échoué", cwd=os.path.join(self.dest, "src"), lecteur=lire)
        except ErreurInstallation as e:
            # Non bloquant : les modeles seront telecharges a la premiere utilisation.
            self.avertissements.append(str(e))
        finally:
            arret.set()
            fil.join(timeout=3)
        self._avancer(1.0, "")

    def _finalisation(self):
        self._debut("finalisation")
        with open(os.path.join(self.dest, "installation.json"), "w", encoding="utf-8") as f:
            json.dump({"version": version_application(), "date": time.strftime("%Y-%m-%d %H:%M")}, f)
        copier_desinstallateur(self.dest)
        if LINUX:
            lanceur = os.path.join(self.dest, "transcriptions.sh")
            with open(lanceur, "w", encoding="utf-8") as f:
                f.write('#!/usr/bin/env bash\nICI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"\n'
                        'cd "$ICI/src" && exec "$ICI/.venv-whisperx/bin/python" -m app "$@"\n')
            os.chmod(lanceur, 0o755)
        if WINDOWS:
            enregistrer_desinstallation(self.dest)
        self._avancer(1.0, "Installation terminée")


def _paquet_installe(paquet):
    r = subprocess.run(["dpkg-query", "-W", "-f=${Status}", paquet], capture_output=True, text=True,
                       env=environnement_propre())
    return "ok installed" in r.stdout


def _go(octets):
    return f"{octets / 1024 ** 3:.2f} Go".replace(".", ",")


def _mo(octets):
    return f"{octets / 1024 ** 2:.0f} Mo"


# --------------------------------------------------------------------------- #
# Raccourcis, desinstallateur, registre
# --------------------------------------------------------------------------- #
def chemin_desinstallateur(dest):
    if WINDOWS:
        return os.path.join(dest, "Désinstaller Transcriptions.exe")
    return os.path.join(dest, "desinstaller")


def commande_desinstallation(dest):
    """Commande qui ouvre l'assistant de desinstallation."""
    if getattr(sys, "frozen", False):
        return [chemin_desinstallateur(dest)]
    lanceur = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanceur.py")
    return [sys.executable, lanceur, "--desinstaller", dest]


def copier_desinstallateur(dest):
    """L'installateur se copie lui-meme : lance depuis l'installation, il
    ouvre l'assistant de desinstallation."""
    if getattr(sys, "frozen", False):
        cible = chemin_desinstallateur(dest)
        if os.path.abspath(sys.executable) != os.path.abspath(cible):
            shutil.copy2(sys.executable, cible)
        if LINUX:
            os.chmod(cible, 0o755)


def _powershell(script, **variables):
    """Execute un court script PowerShell ; les valeurs passent par
    l'environnement, ce qui evite tout probleme de guillemets."""
    env = environnement_propre()
    env.update({"TR_" + k: v for k, v in variables.items()})
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, env=env, timeout=60, **_options_processus())


def creer_raccourcis(dest, menu=True, bureau=True):
    if WINDOWS:
        dossiers = []
        if menu:
            dossiers.append("Programs")
        if bureau:
            dossiers.append("Desktop")
        for d in dossiers:
            _powershell(
                "$l = (New-Object -ComObject WScript.Shell).CreateShortcut("
                "(Join-Path ([Environment]::GetFolderPath($env:TR_DOSSIER)) 'Transcriptions.lnk'));"
                "$l.TargetPath = $env:TR_CIBLE; $l.Arguments = '-m app'; $l.WorkingDirectory = $env:TR_SRC;"
                "$l.IconLocation = $env:TR_ICONE + ',0'; $l.Description = 'Enregistrer et transcrire des conversations';"
                "$l.Save()",
                DOSSIER=d, CIBLE=python_environnement(dest, fenetre=True), SRC=os.path.join(dest, "src"),
                ICONE=os.path.join(dest, "src", "app", "icone.ico"))
        return
    donnees = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    icones = os.path.join(donnees, "icons", "hicolor", "256x256", "apps")
    os.makedirs(icones, exist_ok=True)
    shutil.copy2(os.path.join(dest, "src", "app", "icone.png"), os.path.join(icones, "transcriptions.png"))
    entree = ("[Desktop Entry]\nType=Application\nName=Transcriptions\n"
              "Comment=Enregistrer et transcrire des conversations\n"
              f"Exec=\"{os.path.join(dest, 'transcriptions.sh')}\"\nIcon=transcriptions\nTerminal=false\n"
              "Categories=AudioVideo;Audio;Office;\nStartupWMClass=Transcriptions\n")
    desinstallation = ("[Desktop Entry]\nType=Application\nName=Désinstaller Transcriptions\n"
                       f"Exec=\"{chemin_desinstallateur(dest)}\"\nIcon=transcriptions\nTerminal=false\n"
                       "Categories=Settings;\n")
    applications = os.path.join(donnees, "applications")
    os.makedirs(applications, exist_ok=True)
    if menu:
        _ecrire_desktop(os.path.join(applications, "transcriptions.desktop"), entree)
        if getattr(sys, "frozen", False):
            _ecrire_desktop(os.path.join(applications, "transcriptions-desinstaller.desktop"), desinstallation)
    if bureau:
        bureau_dossier = xdg_dossier("DESKTOP", "~/Desktop")
        if os.path.isdir(bureau_dossier):
            chemin = os.path.join(bureau_dossier, "transcriptions.desktop")
            _ecrire_desktop(chemin, entree)
            # GNOME n'autorise le lancement depuis le bureau que si le fichier est "de confiance"
            subprocess.run(["gio", "set", chemin, "metadata::trusted", "true"],
                           capture_output=True, env=environnement_propre())
    for commande in (["update-desktop-database", applications],
                     ["gtk-update-icon-cache", "-q", os.path.join(donnees, "icons", "hicolor")]):
        try:
            subprocess.run(commande, capture_output=True, env=environnement_propre(), timeout=30)
        except Exception:
            pass


def _ecrire_desktop(chemin, contenu):
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(contenu)
    os.chmod(chemin, 0o755)


def enregistrer_desinstallation(dest):
    """Entree dans "Applications installees" (par utilisateur, sans droits admin)."""
    import winreg
    commande = subprocess.list2cmdline(commande_desinstallation(dest))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLE_DESINSTALLATION) as k:
        for nom, valeur in (("DisplayName", NOM), ("DisplayVersion", version_application()),
                            ("Publisher", EDITEUR), ("InstallLocation", dest),
                            ("DisplayIcon", os.path.join(dest, "src", "app", "icone.ico")),
                            ("UninstallString", commande)):
            winreg.SetValueEx(k, nom, 0, winreg.REG_SZ, valeur)
        for nom, valeur in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", 9 * 1024 * 1024)):
            winreg.SetValueEx(k, nom, 0, winreg.REG_DWORD, valeur)


def lancer_application(dest):
    if WINDOWS:
        subprocess.Popen([python_environnement(dest, fenetre=True), "-m", "app"], cwd=os.path.join(dest, "src"),
                         env=environnement_propre(), close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        subprocess.Popen([os.path.join(dest, "transcriptions.sh")], env=environnement_propre(),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- #
# Desinstallation
# --------------------------------------------------------------------------- #
def fermer_application(dest):
    """Arrete l'application et le moteur s'ils tournent depuis dest."""
    if WINDOWS:
        # Le python.exe d'un venv n'est qu'un relais qui relance le Python
        # principal : on repere les relais par leur ligne de commande, puis
        # leurs descendants.
        _powershell(
            "$d = $env:TR_DEST; $p = @(Get-CimInstance Win32_Process);"
            "$a = @($p | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($d) -and $_.ProcessId -ne $PID"
            " -and $_.Name -notmatch 'Transcriptions|powershell' });"
            "for ($i = 0; $i -lt 3; $i++) { $ids = @($a | ForEach-Object { $_.ProcessId });"
            " $a += @($p | Where-Object { ($ids -contains $_.ParentProcessId) -and ($ids -notcontains $_.ProcessId) }) };"
            "$a | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
            DEST=dest)
    else:
        subprocess.run(["pkill", "-f", os.path.join(dest, ".venv-whisperx")], capture_output=True)


def desinstaller(dest, supprimer_modeles=False):
    """Retourne la liste des elements qui n'ont pas pu etre supprimes."""
    dest = os.path.abspath(dest)
    if not os.path.exists(os.path.join(dest, "src", "app", "fenetre.py")):
        raise ErreurInstallation("Ce dossier ne contient pas d'installation de Transcriptions.", dest)
    fermer_application(dest)
    time.sleep(1)
    restes = []
    if WINDOWS:
        _powershell("foreach ($d in 'Programs','Desktop') { Remove-Item (Join-Path "
                    "([Environment]::GetFolderPath($d)) 'Transcriptions.lnk') -ErrorAction SilentlyContinue }")
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CLE_DESINSTALLATION)
        except OSError:
            pass
    else:
        donnees = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        for f in (os.path.join(donnees, "applications", "transcriptions.desktop"),
                  os.path.join(donnees, "applications", "transcriptions-desinstaller.desktop"),
                  os.path.join(donnees, "icons", "hicolor", "256x256", "apps", "transcriptions.png"),
                  os.path.join(xdg_dossier("DESKTOP", "~/Desktop"), "transcriptions.desktop")):
            try:
                os.remove(f)
            except OSError:
                pass
    if supprimer_modeles:
        for m in [MODELE_WHISPER[0]] + MODELES_PYANNOTE:
            shutil.rmtree(os.path.join(cache_huggingface(), m), ignore_errors=True)
        try:
            os.remove(os.path.join(cache_torch(), MODELE_ALIGNEMENT[0]))
        except OSError:
            pass
    for _ in range(5):
        shutil.rmtree(dest, ignore_errors=True)
        if not os.path.exists(dest):
            break
        time.sleep(1)
    if os.path.exists(dest):
        restes.append(dest)
    return restes
