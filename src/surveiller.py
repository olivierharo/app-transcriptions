"""
Surveillance automatique du dossier d'enregistrements.

Transcrit automatiquement tout fichier audio depose dans le dossier surveille
(par defaut %USERPROFILE%\\Documents\\Enregistrements audio, configurable via
la variable DOSSIER_ENREGISTREMENTS dans le fichier .env).

- Au lancement : transcrit tout le RETARD (chaque audio qui n'a pas encore de .txt).
- Ensuite : surveille et transcrit les nouveaux fichiers deposes.
- Un fichier deja accompagne de son .txt n'est pas re-transcrit.
- Le fichier texte est ecrit a cote de l'audio, avec le meme nom (.txt).
- GPU (large-v3) utilise automatiquement si disponible, sinon CPU (medium).

Pour arreter : fermez la fenetre ou faites Ctrl+C.
"""
import os
import sys
import glob
import time

# Reutilise le correctif DLL CUDA + la detection GPU depuis transcrire.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from transcrire import gpu_disponible  # (importer transcrire applique le correctif PATH/CUDA)
from faster_whisper import WhisperModel

DOSSIER = config.dossier_enregistrements()
EXTS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".wma", ".aac", ".mp4", ".opus", ".webm"}
INTERVALLE = 3  # secondes entre deux scans

_model = None

def get_model():
    global _model
    if _model is None:
        device = "cuda" if gpu_disponible() else "cpu"
        name = "large-v3" if device == "cuda" else "medium"
        ct = "float16" if device == "cuda" else "int8"
        print(f"[modele] Chargement de '{name}' sur {device} (une seule fois)...", flush=True)
        _model = WhisperModel(name, device=device, compute_type=ct)
        print("[modele] Pret.", flush=True)
    return _model

def txt_de(audio):
    return os.path.splitext(audio)[0] + ".txt"

def fichier_stable(path, attente=2):
    """Vrai si la taille du fichier ne bouge plus (fin d'ecriture/copie)."""
    try:
        s1 = os.path.getsize(path)
        time.sleep(attente)
        s2 = os.path.getsize(path)
    except OSError:
        return False
    return s1 == s2 and s1 > 0

def transcrire(audio):
    out = txt_de(audio)
    nom = os.path.basename(audio)
    print(f"[transcription] {nom} ...", flush=True)
    t0 = time.time()
    model = get_model()
    segments, info = model.transcribe(audio, language="fr", vad_filter=True, beam_size=5)
    with open(out, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(seg.text.strip() + "\n")
    print(f"[ok] {os.path.basename(out)} ecrit en {time.time()-t0:.0f}s "
          f"(audio {info.duration:.0f}s)\n", flush=True)

def main():
    if not os.path.isdir(DOSSIER):
        print(f"[erreur] Dossier introuvable : {DOSSIER}", flush=True)
        return
    print("=" * 60, flush=True)
    print(f"Surveillance de : {DOSSIER}", flush=True)
    print("Au lancement : transcription de tout ce qui n'a pas encore de .txt.", flush=True)
    print("Puis surveillance des nouveaux fichiers deposes.", flush=True)
    print("Laissez cette fenetre ouverte. Fermez-la (ou Ctrl+C) pour arreter.", flush=True)
    print("=" * 60, flush=True)

    # Rien n'est ignore : on transcrit tout audio sans .txt (retard + nouveaux).
    connus = set()

    def audios_en_attente():
        res = []
        for p in glob.glob(os.path.join(DOSSIER, "*")):
            if os.path.splitext(p)[1].lower() in EXTS and not os.path.exists(txt_de(p)):
                res.append(p)
        return res

    retard = audios_en_attente()
    if retard:
        print(f"[retard] {len(retard)} fichier(s) a transcrire.\n", flush=True)

    try:
        while True:
            # Les plus anciens d'abord (retard traite dans l'ordre chronologique)
            fichiers = sorted(glob.glob(os.path.join(DOSSIER, "*")), key=lambda p: os.path.getmtime(p))
            for path in fichiers:
                ext = os.path.splitext(path)[1].lower()
                if ext not in EXTS or path in connus:
                    continue
                if os.path.exists(txt_de(path)):   # deja transcrit
                    connus.add(path)
                    continue
                if not fichier_stable(path):        # encore en cours d'ecriture -> on reessaiera
                    continue
                try:
                    transcrire(path)
                except Exception as e:
                    print(f"[erreur] {os.path.basename(path)} : {e}", flush=True)
                connus.add(path)
            time.sleep(INTERVALLE)
    except KeyboardInterrupt:
        print("\nArret de la surveillance.", flush=True)

if __name__ == "__main__":
    main()
