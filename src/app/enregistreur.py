"""
Capture audio au format ideal pour Whisper : WAV 16 kHz, mono, 16 bits.

Deux modes :
  - "micro"          : un seul canal (telephone en haut-parleur, reunion physique)
  - "micro+systeme"  : deux fichiers separes, micro et son du PC (Teams, Zoom...).
                       Chaque fichier ne contient qu'une voix : l'identification
                       des locuteurs devient exacte, sans modele d'IA.

Si le peripherique refuse 16 kHz, on enregistre a sa frequence native puis on
reechantillonne proprement avec PyAV a la fin.
"""
import os
import wave
import time
import threading
import datetime as _dt

import numpy as np
import sounddevice as sd

SR_CIBLE = 16000


# --------------------------------------------------------------------------- #
# Peripheriques
# --------------------------------------------------------------------------- #
def peripheriques_entree():
    """Micros disponibles : [{'id', 'nom', 'canaux', 'sr'}]."""
    res = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            res.append({"id": i, "nom": d["name"],
                        "canaux": d["max_input_channels"],
                        "sr": int(d["default_samplerate"])})
    return res


def peripheriques_sortie():
    """Sorties (haut-parleurs/casque) captables en boucle WASAPI."""
    res = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            res.append({"id": i, "nom": d["name"],
                        "canaux": d["max_output_channels"],
                        "sr": int(d["default_samplerate"])})
    return res


def peripherique_defaut_entree():
    try:
        return sd.default.device[0]
    except Exception:
        return None


def peripherique_defaut_sortie():
    try:
        return sd.default.device[1]
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Une piste = un flux capture vers un fichier WAV
# --------------------------------------------------------------------------- #
class _Piste:
    def __init__(self, chemin, device, loopback=False):
        self.chemin = chemin
        self.device = device
        self.loopback = loopback
        self.stream = None
        self.wav = None
        self.sr = SR_CIBLE
        self.niveau = 0.0          # amplitude recente, pour le vumetre
        self._lock = threading.Lock()

    def _extra(self):
        if not self.loopback:
            return None
        try:
            return sd.WasapiSettings(loopback=True)
        except Exception:
            return None            # non-Windows ou sounddevice trop ancien

    def demarrer(self):
        infos = sd.query_devices(self.device)
        natif = int(infos["default_samplerate"])
        # On tente 16 kHz directement ; sinon frequence native + reechantillonnage
        for sr in (SR_CIBLE, natif):
            try:
                stream = sd.InputStream(
                    device=self.device, channels=1, samplerate=sr,
                    dtype="int16", blocksize=0, callback=self._callback,
                    extra_settings=self._extra(),
                )
                stream.start()
                self.stream, self.sr = stream, sr
                break
            except Exception:
                continue
        if self.stream is None:
            raise RuntimeError(f"Impossible d'ouvrir le peripherique {self.device}")

        self.wav = wave.open(self.chemin, "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.sr)

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            if self.wav is None:
                return
            bloc = indata[:, 0] if indata.ndim > 1 else indata
            self.wav.writeframes(bloc.tobytes())
            self.niveau = float(np.abs(bloc).mean()) / 32768.0

    def arreter(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        with self._lock:
            if self.wav is not None:
                self.wav.close()
                self.wav = None
        if self.sr != SR_CIBLE:
            _reechantillonner(self.chemin, SR_CIBLE)
            self.sr = SR_CIBLE
        return self.chemin


def _reechantillonner(chemin, sr_cible=SR_CIBLE):
    """Convertit un WAV vers sr_cible en mono, via PyAV (filtre correct)."""
    import av
    tmp = chemin + ".tmp.wav"
    os.replace(chemin, tmp)
    try:
        chunks = []
        with av.open(tmp) as cont:
            flux = cont.streams.audio[0]
            res = av.AudioResampler(format="s16", layout="mono", rate=sr_cible)
            for frame in cont.decode(flux):
                for f in res.resample(frame):
                    chunks.append(f.to_ndarray().reshape(-1))
            for f in res.resample(None):
                chunks.append(f.to_ndarray().reshape(-1))
        data = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        with wave.open(chemin, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr_cible)
            w.writeframes(data.astype(np.int16).tobytes())
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Enregistreur
# --------------------------------------------------------------------------- #
class Enregistreur:
    """Pilote une ou deux pistes simultanees."""

    def __init__(self, dossier):
        self.dossier = dossier
        os.makedirs(dossier, exist_ok=True)
        self.pistes = []
        self.debut = None
        self.nom_base = None

    @property
    def en_cours(self):
        return bool(self.pistes)

    @property
    def duree(self):
        return 0.0 if self.debut is None else time.time() - self.debut

    @property
    def niveaux(self):
        return [p.niveau for p in self.pistes]

    def demarrer(self, micro_id, systeme_id=None, titre=None):
        """systeme_id : sortie a capter en boucle (mode Teams), ou None."""
        if self.en_cours:
            raise RuntimeError("Un enregistrement est deja en cours")

        horo = _dt.datetime.now().strftime("%Y-%m-%d_%Hh%M")
        base = f"{horo}_{_nettoyer(titre)}" if titre else horo
        self.nom_base = base

        pistes = [_Piste(os.path.join(self.dossier, f"{base}.wav"), micro_id)]
        if systeme_id is not None:
            pistes[0].chemin = os.path.join(self.dossier, f"{base}.moi.wav")
            pistes.append(_Piste(os.path.join(self.dossier, f"{base}.correspondant.wav"),
                                 systeme_id, loopback=True))

        demarrees = []
        try:
            for p in pistes:
                p.demarrer()
                demarrees.append(p)
        except Exception:
            for p in demarrees:      # rollback : ne pas laisser un flux ouvert
                p.arreter()
            raise

        self.pistes = demarrees
        self.debut = time.time()
        return base

    def arreter(self):
        """Retourne la liste des fichiers WAV produits."""
        chemins = [p.arreter() for p in self.pistes]
        self.pistes = []
        self.debut = None
        return chemins


def _nettoyer(nom):
    interdits = '<>:"/\\|?*'
    nom = "".join("-" if c in interdits else c for c in (nom or "")).strip()
    return nom[:60] or "sans-titre"
