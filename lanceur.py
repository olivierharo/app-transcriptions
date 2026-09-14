"""Point d'entree de l'application empaquetee (PyInstaller).

Le moteur de transcription n'est PAS embarque ici : il est execute en
sous-processus par l'environnement Python, ce qui garde l'.exe leger.
"""
from app.fenetre import lancer

if __name__ == "__main__":
    lancer()
