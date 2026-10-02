"""Point d'entrée : python3 -m navigateur [adresse]"""

import sys


def main():
    try:
        from .interface import Navigateur, interpreter_saisie
    except ImportError as erreur:
        if "tkinter" in str(erreur).lower():
            sys.exit("Tkinter est introuvable. Installez-le (ex. : sudo apt install python3-tk) puis relancez.")
        raise
    adresse = interpreter_saisie(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else None
    Navigateur(adresse).lancer()


if __name__ == "__main__":
    main()
