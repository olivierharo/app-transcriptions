"""
Moteur de transcription (WhisperX) execute en SOUS-PROCESSUS.

L'interface le lance et lit sa sortie standard : une ligne = un evenement JSON.
Ainsi l'UI ne gele jamais, et un plantage GPU ne fait pas tomber l'application.

Evenements emis :
    {"etape": "...", "progression": 0-100, "message": "..."}
    {"fini": true, "sortie": "chemin.dialogue.txt"}
    {"erreur": "message"}

Usage :
    python -m app.moteur "audio.wav" [--correspondant "autre.wav"]
                         [--noms "Olivier,Christian"] [--speakers 2]
                         [--modele large-v3]
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def emettre(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def etape(nom, pct, msg=""):
    emettre(etape=nom, progression=pct, message=msg)


# --------------------------------------------------------------------------- #
def transcrire_fichier(wx, audio, modele, device, compute_type, langue, aligner=True):
    """Transcrit puis (optionnellement) aligne au mot pres. Retourne les segments."""
    son = wx.load_audio(audio)
    modele_asr = wx.load_model(modele, device, compute_type=compute_type, language=langue)
    res = modele_asr.transcribe(son, batch_size=8)
    del modele_asr
    _vider_gpu(device)

    if aligner:
        try:
            modele_al, meta = wx.load_align_model(language_code=langue, device=device)
            res = wx.align(res["segments"], modele_al, meta, son, device,
                           return_char_alignments=False)
            del modele_al
            _vider_gpu(device)
        except Exception as e:
            emettre(etape="alignement", progression=70,
                    message=f"alignement indisponible ({e}) - horodatage par segment")
    return res, son


def _vider_gpu(device):
    if device == "cuda":
        try:
            import torch, gc
            gc.collect()
            torch.cuda.empty_cache()
        except Exception:
            pass


def _texte_de(seg):
    return (seg.get("text") or "").strip()


def ecrire_dialogue(chemin, tours):
    """tours : [(locuteur, texte)] deja regroupes."""
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n\n".join(f"{loc} : {txt}" for loc, txt in tours) + "\n")


def regrouper(segments, cle_locuteur, noms):
    """Fusionne les segments consecutifs d'un meme locuteur en tours de parole."""
    mapping, ordre = {}, []
    tours, courant, tampon = [], None, []
    for s in segments:
        loc = cle_locuteur(s)
        if loc not in mapping:
            ordre.append(loc)
            i = len(ordre) - 1
            mapping[loc] = noms[i] if i < len(noms) else (loc or "?")
        nom = mapping[loc]
        txt = _texte_de(s)
        if not txt:
            continue
        if nom != courant:
            if tampon:
                tours.append((courant, " ".join(tampon)))
            courant, tampon = nom, [txt]
        else:
            tampon.append(txt)
    if tampon:
        tours.append((courant, " ".join(tampon)))
    return tours


# --------------------------------------------------------------------------- #
def mode_deux_canaux(wx, args, device, compute_type):
    """Un fichier par personne : attribution exacte, aucune diarisation."""
    noms = [n.strip() for n in args.noms.split(",") if n.strip()] or ["Moi", "Correspondant"]
    tous = []
    for idx, (audio, nom) in enumerate(((args.audio, noms[0]),
                                        (args.correspondant, noms[1] if len(noms) > 1 else "Correspondant"))):
        etape("transcription", 10 + idx * 40, f"piste {idx + 1}/2 : {nom}")
        res, _ = transcrire_fichier(wx, audio, args.modele, device, compute_type, args.langue)
        for s in res["segments"]:
            s["_loc"] = nom
            tous.append(s)

    etape("fusion", 90, "entrelacement chronologique des deux pistes")
    tous.sort(key=lambda s: s.get("start", 0.0))
    tours = regrouper(tous, lambda s: s["_loc"], [])
    return tours


def mode_un_canal(wx, args, device, compute_type):
    """Une seule piste : diarisation pyannote pour separer les voix."""
    etape("transcription", 15, "transcription en cours")
    res, son = transcrire_fichier(wx, args.audio, args.modele, device, compute_type, args.langue)

    if args.speakers == 1:
        noms = [n.strip() for n in args.noms.split(",") if n.strip()]
        seul = noms[0] if noms else "Locuteur"
        return [(seul, " ".join(_texte_de(s) for s in res["segments"] if _texte_de(s)))]

    etape("diarisation", 75, "identification des locuteurs")
    import config
    token = config.hf_token()
    if not token:
        raise RuntimeError(
            "Token Hugging Face absent. Renseignez HF_TOKEN dans le fichier .env "
            "(voir .env.example) pour activer l'identification des locuteurs."
        )

    pipeline = _pipeline_diarisation(wx, token, device)
    kw = {} if args.speakers in (0, None) else {"num_speakers": args.speakers}
    tours_diar = pipeline(args.audio, **kw)
    res = wx.assign_word_speakers(tours_diar, res)

    etape("fusion", 92, "attribution des tours de parole")
    noms = [n.strip() for n in args.noms.split(",") if n.strip()]
    return regrouper(res["segments"], lambda s: s.get("speaker"), noms)


def _pipeline_diarisation(wx, token, device):
    """L'emplacement de la classe a change selon les versions de WhisperX."""
    erreurs = []
    for fabrique in (
        lambda: __import__("whisperx.diarize", fromlist=["DiarizationPipeline"]).DiarizationPipeline,
        lambda: getattr(wx, "DiarizationPipeline"),
    ):
        try:
            cls = fabrique()
        except Exception as e:
            erreurs.append(str(e))
            continue
        for kwargs in ({"use_auth_token": token, "device": device},
                       {"token": token, "device": device}):
            try:
                return cls(**kwargs)
            except Exception as e:
                erreurs.append(str(e))
    raise RuntimeError("Pipeline de diarisation introuvable : " + " | ".join(erreurs[-2:]))


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--correspondant", default=None, help="2e piste (mode 2 canaux)")
    ap.add_argument("--noms", default="", help='ex: "Olivier,Christian"')
    ap.add_argument("--speakers", type=int, default=2, help="0 = automatique")
    ap.add_argument("--modele", default="large-v3")
    ap.add_argument("--langue", default="fr")
    ap.add_argument("--sortie", default=None)
    args = ap.parse_args()

    try:
        etape("demarrage", 2, "chargement de WhisperX")
        import whisperx as wx
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        etape("demarrage", 5, f"{device} / {args.modele} / {compute_type}")

        if args.correspondant and os.path.exists(args.correspondant):
            tours = mode_deux_canaux(wx, args, device, compute_type)
        else:
            tours = mode_un_canal(wx, args, device, compute_type)

        sortie = args.sortie or (os.path.splitext(args.audio)[0] + ".dialogue.txt")
        # "base.moi.wav" -> "base.dialogue.txt"
        if sortie.endswith(".moi.dialogue.txt"):
            sortie = sortie[: -len(".moi.dialogue.txt")] + ".dialogue.txt"
        ecrire_dialogue(sortie, tours)

        emettre(fini=True, sortie=sortie, tours=len(tours))
    except Exception as e:
        import traceback
        emettre(erreur=str(e), detail=traceback.format_exc()[-1500:])
        sys.exit(1)


if __name__ == "__main__":
    main()
