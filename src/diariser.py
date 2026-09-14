"""
Diarisation : "qui a parle quand", puis fusion avec la transcription.

A lancer avec le venv dedie :
    .venv-diar\\Scripts\\python.exe diariser.py "audio.m4a" --noms "Olivier,Christian"

Produit, a cote de l'audio :
    X.speakers.json   les tours de parole (debut, fin, locuteur)
    X.dialogue.txt    la transcription enrichie "Olivier : ..." / "Christian : ..."
                      (necessite X.segments.json, produit par transcrire.py)

Le token Hugging Face est lu dans la variable d'environnement HF_TOKEN (jamais affiche).
"""
import os
import sys
import json
import time
import argparse

import numpy as np
import torch
import av

# Pipelines candidats (le nom a change entre pyannote 3.x et 4.x)
CANDIDATS = [
    "pyannote/speaker-diarization-3.1",
    "pyannote/speaker-diarization-community-1",
]


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def lire_token():
    """Token HF via .env ou environnement utilisateur. Jamais affiche."""
    return config.hf_token()


def charger_audio(path, sr=16000):
    """Decode n'importe quel format en mono float32 a 16 kHz via PyAV."""
    chunks = []
    with av.open(path) as cont:
        stream = cont.streams.audio[0]
        res = av.AudioResampler(format="s16", layout="mono", rate=sr)
        for frame in cont.decode(stream):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):          # flush
            chunks.append(f.to_ndarray().reshape(-1))
    data = np.concatenate(chunks).astype(np.float32) / 32768.0
    return data, sr


def charger_pipeline(token):
    from pyannote.audio import Pipeline
    derniere_erreur = None
    for nom in CANDIDATS:
        for kwargs in ({"token": token}, {"use_auth_token": token}):
            try:
                p = Pipeline.from_pretrained(nom, **kwargs)
                if p is not None:
                    print(f"[pipeline] {nom}", flush=True)
                    return p
            except Exception as e:
                derniere_erreur = f"{nom} -> {e}"
    raise RuntimeError(
        "Aucun pipeline de diarisation n'a pu etre charge.\n"
        "Verifiez que vous avez accepte les conditions sur huggingface.co pour :\n"
        "  - pyannote/segmentation-3.0\n"
        "  - pyannote/speaker-diarization-3.1\n"
        f"Derniere erreur : {derniere_erreur}"
    )


def fusionner(segments, tours, noms):
    """Attribue a chaque segment de texte le locuteur qui le recouvre le plus."""
    def locuteur_de(seg):
        meilleur, best = None, 0.0
        for t in tours:
            chevauche = min(seg["end"], t["end"]) - max(seg["start"], t["start"])
            if chevauche > best:
                best, meilleur = chevauche, t["speaker"]
        return meilleur

    # Ordre d'apparition -> noms fournis
    ordre, mapping = [], {}
    for t in sorted(tours, key=lambda x: x["start"]):
        if t["speaker"] not in ordre:
            ordre.append(t["speaker"])
    for i, sp in enumerate(ordre):
        mapping[sp] = noms[i] if i < len(noms) else sp

    lignes, courant, tampon = [], None, []
    for seg in segments:
        sp = locuteur_de(seg)
        nom = mapping.get(sp, "?") if sp else "?"
        if nom != courant:
            if tampon:
                lignes.append(f"{courant} : " + " ".join(tampon))
            courant, tampon = nom, [seg["text"]]
        else:
            tampon.append(seg["text"])
    if tampon:
        lignes.append(f"{courant} : " + " ".join(tampon))
    return lignes, mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--speakers", type=int, default=2, help="nombre de locuteurs (0 = auto)")
    ap.add_argument("--noms", default="", help="ex: \"Olivier,Christian\" (ordre d'apparition)")
    args = ap.parse_args()

    token = lire_token()
    if not token:
        print("[erreur] HF_TOKEN introuvable. Faites :  setx HF_TOKEN \"hf_xxx\"  puis relancez.", flush=True)
        sys.exit(1)

    base = os.path.splitext(os.path.abspath(args.audio))[0]
    out_speakers = base + ".speakers.json"
    out_dialogue = base + ".dialogue.txt"
    in_segments = base + ".segments.json"

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[device] {device}", flush=True)

    pipeline = charger_pipeline(token)
    pipeline.to(torch.device(device))

    print("[audio] decodage...", flush=True)
    data, sr = charger_audio(args.audio)
    duree = len(data) / sr
    waveform = torch.from_numpy(data).unsqueeze(0)
    print(f"[audio] {duree:.0f}s a {sr} Hz", flush=True)

    print("[diarisation] en cours...", flush=True)
    t0 = time.time()
    kw = {} if args.speakers in (0, None) else {"num_speakers": args.speakers}
    diar = pipeline({"waveform": waveform, "sample_rate": sr}, **kw)
    print(f"[diarisation] terminee en {time.time()-t0:.0f}s", flush=True)

    tours = [{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": sp}
             for t, _, sp in diar.itertracks(yield_label=True)]
    with open(out_speakers, "w", encoding="utf-8") as f:
        json.dump(tours, f, ensure_ascii=False, indent=1)
    locuteurs = sorted({t["speaker"] for t in tours})
    print(f"[ok] {len(tours)} tours de parole, {len(locuteurs)} locuteur(s) -> "
          f"{os.path.basename(out_speakers)}", flush=True)

    # Fusion avec la transcription si disponible
    if not os.path.exists(in_segments):
        print(f"[info] {os.path.basename(in_segments)} absent : lancez d'abord transcrire.py "
              f"pour obtenir le dialogue attribue.", flush=True)
        return
    with open(in_segments, encoding="utf-8") as f:
        segments = json.load(f)["segments"]
    noms = [n.strip() for n in args.noms.split(",") if n.strip()]
    lignes, mapping = fusionner(segments, tours, noms)
    with open(out_dialogue, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lignes) + "\n")
    print(f"[ok] {len(lignes)} tours rediges -> {os.path.basename(out_dialogue)}", flush=True)
    print(f"[correspondance] {mapping}", flush=True)


if __name__ == "__main__":
    main()
