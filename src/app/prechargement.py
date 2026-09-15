"""
Telecharge les modeles d'IA pendant l'installation, pour que la premiere
transcription ne reste pas bloquee de longues minutes sans explication.

Usage (appele par les installateurs) :
    python -m app.prechargement [--modele large-v3] [--langue fr]

Les modeles vont dans le cache standard (~/.cache/huggingface et
~/.cache/torch), la ou le moteur les cherchera ensuite.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def dire(msg):
    print("  " + msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="large-v3")
    ap.add_argument("--langue", default="fr")
    args = ap.parse_args()
    erreurs = 0

    dire(f"[1/3] Modele de transcription Whisper {args.modele} (~3 Go)...")
    from faster_whisper.utils import download_model
    download_model(args.modele)
    dire("      OK")

    dire("[2/3] Modele d'alignement au mot pres (~360 Mo)...")
    import whisperx as wx
    try:
        wx.load_align_model(language_code=args.langue, device="cpu")
        dire("      OK")
    except Exception as e:
        erreurs += 1
        dire(f"      ECHEC : {e}")

    dire("[3/3] Modeles de separation des voix (pyannote)...")
    import config
    token = config.hf_token()
    if not token:
        dire("      IGNORE : pas de token Hugging Face.")
        dire("      Le mode 'Micro + son du PC' fonctionnera ; le mode 'Micro seul'")
        dire("      demandera un token (voir la documentation d'installation).")
    else:
        from app.moteur import _pipeline_diarisation
        try:
            _pipeline_diarisation(wx, token, "cpu")
            dire("      OK")
        except Exception as e:
            erreurs += 1
            dire(f"      ECHEC : {e}")

    sys.exit(1 if erreurs else 0)


if __name__ == "__main__":
    main()
