"""
Construit l'installateur graphique pour le systeme courant :

    Windows : dist/Transcriptions-Setup.exe
    Ubuntu  : dist/Transcriptions-Setup-Ubuntu

Il embarque le code de l'application (quelques centaines de Ko) ; les
dependances et les modeles sont telecharges sur chaque poste pendant
l'installation. Lance par GitHub Actions a chaque version publiee.

Prerequis : pip install pyinstaller pyside6
Usage     : python installation/construire_installateur.py
"""
import os
import sys
import shutil
import subprocess

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVAIL = os.path.join(RACINE, "build", "installateur")
WINDOWS = sys.platform == "win32"


def preparer():
    """Recopie ce qui sera embarque, sans caches ni fichiers personnels."""
    shutil.rmtree(TRAVAIL, ignore_errors=True)
    charge = os.path.join(TRAVAIL, "charge")
    shutil.copytree(os.path.join(RACINE, "src"), os.path.join(charge, "src"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", ".env"))
    shutil.copy2(os.path.join(RACINE, "requirements-app.txt"), charge)
    ressources = os.path.join(TRAVAIL, "ressources")
    os.makedirs(ressources)
    for nom in ("icone.png", "icone.ico"):
        shutil.copy2(os.path.join(RACINE, "src", "app", nom), ressources)
    return charge, ressources


def main():
    charge, ressources = preparer()
    nom = "Transcriptions-Setup" if WINDOWS else "Transcriptions-Setup-Ubuntu"
    sep = ";" if WINDOWS else ":"
    commande = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", nom,
        "--distpath", os.path.join(RACINE, "dist"),
        "--workpath", os.path.join(TRAVAIL, "pyinstaller"),
        "--specpath", TRAVAIL,
        "--icon", os.path.join(ressources, "icone.ico"),
        "--add-data", f"{charge}{sep}charge",
        "--add-data", f"{ressources}{sep}ressources",
        "--paths", os.path.join(RACINE, "installation", "installateur"),
        # Modules lourds presents dans l'environnement de developpement,
        # inutiles a l'installateur.
        *[a for m in ("torch", "whisperx", "transformers", "numpy", "scipy", "pandas", "matplotlib",
                      "PIL", "av", "sounddevice", "pyannote", "ctranslate2", "onnxruntime")
          for a in ("--exclude-module", m)],
        os.path.join(RACINE, "installation", "installateur", "lanceur.py"),
    ]
    subprocess.run(commande, check=True)
    sortie = os.path.join(RACINE, "dist", nom + (".exe" if WINDOWS else ""))
    print(f"\n{sortie} ({os.path.getsize(sortie) / 1024 ** 2:.0f} Mo)")


if __name__ == "__main__":
    main()
