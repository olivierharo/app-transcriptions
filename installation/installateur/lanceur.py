"""
Point d'entree de l'installateur (et du desinstallateur).

    Transcriptions-Setup.exe                      assistant d'installation
    Transcriptions-Setup.exe --desinstaller [DOSSIER]
    Transcriptions-Setup.exe --mise-a-jour DOSSIER     (lance par l'application)
    "Désinstaller Transcriptions.exe"             (copie placee dans l'installation)

Options de test : --auto (aucun clic, raccourcis non lances), --destination DOSSIER.
"""
import os
import sys
import shutil
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import operations as op


def relancer_hors_installation(dest):
    """Windows ne permet pas de supprimer un .exe en cours d'execution : le
    desinstallateur se copie dans le dossier temporaire et se relance de la."""
    exe = os.path.abspath(sys.executable)
    if not (op.WINDOWS and getattr(sys, "frozen", False)):
        return False
    if not os.path.normcase(exe).startswith(os.path.normcase(os.path.abspath(dest)) + os.sep):
        return False
    copie = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "Transcriptions-desinstallation.exe")
    shutil.copy2(exe, copie)
    subprocess.Popen([copie, "--desinstaller", dest] + [a for a in sys.argv[1:] if a == "--auto"],
                     env=op.environnement_propre(), close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desinstaller", nargs="?", const="", default=None)
    ap.add_argument("--destination", default=None)
    ap.add_argument("--mise-a-jour", dest="mise_a_jour", default=None)
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    # Copie "Désinstaller Transcriptions.exe" / "desinstaller" placee dans
    # l'installation : sans argument, elle desinstalle son propre dossier.
    nom = os.path.basename(sys.executable).lower()
    if args.desinstaller is None and getattr(sys, "frozen", False) and nom.startswith(("désinstaller", "desinstaller")):
        args.desinstaller = os.path.dirname(os.path.abspath(sys.executable))

    if args.desinstaller is not None:
        dest = args.desinstaller or args.destination or op.destination_par_defaut()
        if relancer_hors_installation(dest):
            return 0

    if op.WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OlivierHaro.Transcriptions.Installation")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication
    import assistant

    app = QApplication(sys.argv)
    app.setApplicationName("Transcriptions")
    assistant.appliquer_theme(app)
    if args.desinstaller is not None:
        fenetre = assistant.AssistantDesinstallation(dest, auto=args.auto)
    elif args.mise_a_jour:
        fenetre = assistant.AssistantInstallation(auto=args.auto, destination=args.mise_a_jour, mise_a_jour=True)
    else:
        fenetre = assistant.AssistantInstallation(auto=args.auto, destination=args.destination)
    fenetre.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
