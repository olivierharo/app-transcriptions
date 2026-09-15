"""
Moteur de transcription (WhisperX) execute en SOUS-PROCESSUS.

L'interface le lance et lit sa sortie standard : une ligne = un evenement JSON.
Ainsi l'UI ne gele jamais, et un plantage GPU ne fait pas tomber l'application.

Evenements emis :
    {"etape": "...", "progression": 0-100, "message": "..."}
    {"fini": true, "sortie": "chemin.dialogue.txt"}
    {"erreur": "message"}
    {"diagnostic": {"gpu": true, "nom": "...", "detail": "..."}}   (--diagnostic)

Le dialogue produit ne nomme pas les locuteurs : chaque changement de
locuteur ouvre une nouvelle replique precedee d'un tiret.

Usage :
    python -m app.moteur "audio.wav" [--correspondant "autre.wav"]
                         [--speakers 2] [--modele large-v3]
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SR = 16000


def charger_audio(chemin):
    """Decode en mono 16 kHz float32, via PyAV.

    On n'utilise PAS whisperx.load_audio() : il lance ffmpeg en
    sous-processus, or ffmpeg n'est pas installe (et PyAV embarque deja
    les bibliotheques necessaires).
    """
    import av
    import numpy as np
    morceaux = []
    with av.open(chemin) as cont:
        flux = cont.streams.audio[0]
        res = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for trame in cont.decode(flux):
            for t in res.resample(trame):
                morceaux.append(t.to_ndarray().reshape(-1))
        for t in res.resample(None):
            morceaux.append(t.to_ndarray().reshape(-1))
    if not morceaux:
        raise RuntimeError("Aucune donnee audio decodee : " + chemin)
    return (np.concatenate(morceaux).astype("float32") / 32768.0)


def emettre(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def etape(nom, pct, msg=""):
    emettre(etape=nom, progression=pct, message=msg)


# --------------------------------------------------------------------------- #
def transcrire_fichier(wx, audio, modele, device, compute_type, langue, aligner=True):
    """Transcrit puis (optionnellement) aligne au mot pres. Retourne les segments."""
    son = charger_audio(audio)
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
    """tours : [texte] deja regroupes, un par changement de locuteur.

    Pas de nom devant les repliques : un tiret signale seulement que
    quelqu'un d'autre prend la parole. On evite ainsi d'afficher un nom
    faux quand la diarisation confond les voix.
    """
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n\n".join("- " + txt for txt in tours) + "\n")


PONCTUATION = (",", ".", "!", "?", ";", ":", "...", "%")


def _recoller(mots):
    """Recolle des mots en texte lisible (espaces avant ponctuation, elisions)."""
    texte = " ".join(m for m in mots if m)
    for signe in PONCTUATION:
        texte = texte.replace(" " + signe, signe)
    texte = texte.replace("' ", "'").replace("’ ", "’")
    return texte.strip()


def _mots_localises(segments):
    """Aplatit les segments en couples (locuteur, mot).

    On utilise l'attribution AU MOT produite par l'alignement WhisperX.
    Attribuer par segment reviendrait a voter a la majorite : une
    replique courte ("oui", "d'accord, je regarde") tombant au milieu
    d'un long segment serait absorbee par le locuteur bavard.
    """
    for s in segments:
        mots = s.get("words") or []
        if mots:
            for m in mots:
                mot = (m.get("word") or "").strip()
                if mot:
                    yield (m.get("speaker") or s.get("speaker")), mot
        else:
            texte = _texte_de(s)
            if texte:
                yield s.get("speaker"), texte


FIN_DE_PHRASE = (".", "!", "?", "…")


def _lisser(blocs):
    """Supprime les faux changements de locuteur de la diarisation.

    blocs : [[locuteur, [mots]]]. Un bloc d'UN seul mot, sans ponctuation
    finale, coince entre deux blocs du meme locuteur, est presque toujours
    un mot mal attribue au milieu d'une phrase : il ferait apparaitre un
    tiret en plein milieu. On le rattache. Une vraie replique breve
    ("Oui.", "D'accord ?") porte une ponctuation et est conservee.
    """
    i = 1
    while i < len(blocs) - 1:
        avant, bloc, apres = blocs[i - 1], blocs[i], blocs[i + 1]
        if (len(bloc[1]) == 1 and avant[0] == apres[0]
                and not bloc[1][0].endswith(FIN_DE_PHRASE)):
            avant[1].extend(bloc[1] + apres[1])
            del blocs[i:i + 2]
        else:
            i += 1
    return blocs


def regrouper(segments, lisser=False):
    """Construit les tours de parole : un nouveau tour a chaque
    changement de locuteur. Retourne la liste des textes."""
    blocs, dernier = [], None
    for loc, mot in _mots_localises(segments):
        if loc:
            dernier = loc
        else:
            loc = dernier                  # mot orphelin : on prolonge le tour
        if blocs and blocs[-1][0] == loc:
            blocs[-1][1].append(mot)
        else:
            blocs.append([loc, [mot]])
    if lisser:
        blocs = _lisser(blocs)
    return [t for t in (_recoller(mots) for _, mots in blocs) if t]


# --------------------------------------------------------------------------- #
def mode_deux_canaux(wx, args, device, compute_type):
    """Un fichier par personne : attribution exacte, aucune diarisation."""
    tous = []
    for idx, audio in enumerate((args.audio, args.correspondant)):
        etape("transcription", 10 + idx * 40, f"piste {idx + 1}/2")
        res, _ = transcrire_fichier(wx, audio, args.modele, device, compute_type, args.langue)
        piste = f"piste{idx + 1}"
        for seg in res["segments"]:
            seg["speaker"] = piste
            for m in (seg.get("words") or []):
                m["speaker"] = piste
            tous.append(seg)

    etape("fusion", 90, "entrelacement chronologique des deux pistes")
    tous.sort(key=lambda s: s.get("start", 0.0))
    return regrouper(tous)


def mode_un_canal(wx, args, device, compute_type):
    """Une seule piste : diarisation pyannote pour separer les voix."""
    etape("transcription", 15, "transcription en cours")
    res, son = transcrire_fichier(wx, args.audio, args.modele, device, compute_type, args.langue)

    if args.speakers == 1:
        return [" ".join(_texte_de(s) for s in res["segments"] if _texte_de(s))]

    etape("diarisation", 75, "identification des locuteurs")
    # On passe le signal deja decode, sinon whisperx rappellerait ffmpeg.
    import config
    token = config.hf_token()
    if not token:
        raise RuntimeError(
            "Token Hugging Face absent. Renseignez HF_TOKEN dans le fichier .env "
            "(voir .env.example) pour activer l'identification des locuteurs."
        )

    pipeline = _pipeline_diarisation(wx, token, device)
    kw = {} if args.speakers in (0, None) else {"num_speakers": args.speakers}
    tours_diar = pipeline(son, **kw)
    res = wx.assign_word_speakers(tours_diar, res)

    etape("fusion", 92, "decoupage des tours de parole")
    return regrouper(res["segments"], lisser=True)


MODELES_DIARISATION = [
    "pyannote/speaker-diarization-community-1",   # defaut de WhisperX 3.8
    "pyannote/speaker-diarization-3.1",           # repli, licence plus repandue
]


def _pipeline_diarisation(wx, token, device):
    """Construit le pipeline de diarisation.

    Les modeles pyannote sont sous licence : il faut accepter leurs
    conditions sur huggingface.co, modele par modele. WhisperX utilise
    par defaut community-1 ; on retombe sur 3.1 s'il n'est pas autorise,
    ce qui evite d'imposer une demarche supplementaire.
    """
    from whisperx.diarize import DiarizationPipeline
    erreurs = []
    for nom in MODELES_DIARISATION:
        for kwargs in ({"model_name": nom, "token": token, "device": device},
                       {"model_name": nom, "use_auth_token": token, "device": device}):
            try:
                pipeline = DiarizationPipeline(**kwargs)
                etape("diarisation", 78, "modele " + nom)
                return pipeline
            except TypeError as e:          # mauvaise convention de nommage
                erreurs.append(nom + " : " + str(e)[:90])
                continue
            except Exception as e:          # licence refusee, reseau...
                erreurs.append(nom + " : " + str(e)[:110])
                break
    raise RuntimeError(
        "Aucun modele de diarisation accessible. Connectez-vous a huggingface.co "
        "et acceptez les conditions d'au moins un de ces modeles : "
        + ", ".join(MODELES_DIARISATION) + ". Details : " + " | ".join(erreurs[-2:]))


# --------------------------------------------------------------------------- #
def cuda_utilisable(torch):
    """Vrai seulement si une carte repond REELLEMENT.

    torch.cuda.is_available() peut repondre oui alors qu'aucune carte n'est
    exploitable (carte masquee, pilote trop ancien) : la transcription
    planterait ensuite. On alloue donc un tenseur minuscule pour verifier.
    """
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() == 0:
            return False
        torch.zeros(1, device="cuda")
        return True
    except Exception:
        return False


def diagnostic():
    """Indique si la transcription tournera sur GPU, sans charger WhisperX.

    Emet {"diagnostic": {"gpu": bool, "nom": str, "detail": str}}.
    On teste torch.cuda comme main() : l'indicateur de l'interface
    reflete donc exactement le choix fait au moment de transcrire.
    """
    try:
        import torch
    except Exception as e:
        emettre(diagnostic={"gpu": False, "nom": "",
                            "detail": f"PyTorch introuvable ({e})"})
        return
    if cuda_utilisable(torch):
        emettre(diagnostic={"gpu": True, "nom": torch.cuda.get_device_name(0),
                            "detail": f"CUDA {torch.version.cuda}"})
    elif torch.version.cuda is None:
        emettre(diagnostic={"gpu": False, "nom": "",
                            "detail": "PyTorch installe sans prise en charge CUDA"})
    else:
        emettre(diagnostic={"gpu": False, "nom": "",
                            "detail": "aucune carte NVIDIA compatible ou pilote absent"})


def main():
    if "--diagnostic" in sys.argv:
        return diagnostic()

    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--correspondant", default=None, help="2e piste (mode 2 canaux)")
    ap.add_argument("--speakers", type=int, default=2, help="0 = automatique")
    ap.add_argument("--modele", default="large-v3")
    ap.add_argument("--langue", default="fr")
    ap.add_argument("--sortie", default=None)
    args = ap.parse_args()

    try:
        etape("demarrage", 2, "chargement de WhisperX")
        import whisperx as wx
        import torch

        device = "cuda" if cuda_utilisable(torch) else "cpu"
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
