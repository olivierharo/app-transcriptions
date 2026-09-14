"""
Transcription audio -> texte avec faster-whisper.

Usage :
    python transcrire.py "mon_audio.m4a"                  # auto : GPU si dispo, modele large-v3
    python transcrire.py "mon_audio.m4a" --model medium   # choisir le modele
    python transcrire.py "mon_audio.m4a" --device cpu      # forcer le CPU

Formats audio acceptes : m4a, mp3, wav, ogg, flac... (decodage via 'av', pas besoin de ffmpeg)
"""
import os
import sys
import glob
import json
import time
import argparse

# --- Rendre les DLL CUDA (cuBLAS/cuDNN installees via pip) visibles sous Windows ---
# CTranslate2 charge cublas/cudnn via LoadLibrary a l'execution : cela ignore
# os.add_dll_directory, il faut donc aussi prefixer le PATH.
def _ajouter_dll_cuda():
    base = os.path.join(os.path.dirname(sys.executable), "..", "Lib", "site-packages", "nvidia")
    for d in glob.glob(os.path.join(base, "*", "bin")):
        if os.path.isdir(d):
            d = os.path.abspath(d)
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

_ajouter_dll_cuda()

from faster_whisper import WhisperModel

def gpu_disponible():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--model", default=None, help="tiny/base/small/medium/large-v3")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--lang", default="fr")
    args = p.parse_args()

    # Choix device
    if args.device == "auto":
        device = "cuda" if gpu_disponible() else "cpu"
    else:
        device = args.device

    # Modele par defaut selon le device (GPU = on peut se permettre large-v3)
    if args.model is None:
        model_name = "large-v3" if device == "cuda" else "medium"
    else:
        model_name = args.model

    compute_type = "float16" if device == "cuda" else "int8"
    base = os.path.splitext(os.path.abspath(args.audio))[0]   # a cote de l'audio
    out_txt = base + ".txt"
    out_json = base + ".segments.json"                        # horodatages (pour la diarisation)

    print(f"Device : {device} | Modele : {model_name} | compute_type : {compute_type}", flush=True)
    t0 = time.time()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    print(f"Modele charge en {time.time()-t0:.0f}s. Transcription...", flush=True)

    segments, info = model.transcribe(args.audio, language=args.lang, vad_filter=True, beam_size=5)
    print(f"Langue : {info.language} (proba {info.language_probability:.2f}) | duree {info.duration:.0f}s", flush=True)

    n = 0
    t1 = time.time()
    collectes = []
    with open(out_txt, "w", encoding="utf-8") as f:
        for seg in segments:
            txt = seg.text.strip()
            f.write(txt + "\n")
            f.flush()
            collectes.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": txt})
            pct = 100 * seg.end / info.duration
            print(f"[{pct:5.1f}%] {int(seg.start//60):02d}:{int(seg.start%60):02d} -> {txt}", flush=True)
            n += 1

    # Sidecar JSON : permet de rejouer la diarisation sans re-transcrire l'audio
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"audio": os.path.abspath(args.audio), "duree": info.duration,
                   "segments": collectes}, f, ensure_ascii=False, indent=1)

    dur = time.time() - t1
    print(f"\nTermine en {dur:.0f}s ({info.duration/max(dur,1):.1f}x temps reel). "
          f"{n} segments -> {out_txt}", flush=True)

if __name__ == "__main__":
    main()
