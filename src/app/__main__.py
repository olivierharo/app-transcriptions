"""Point d'entree : python -m app"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.fenetre import lancer

if __name__ == "__main__":
    lancer()
