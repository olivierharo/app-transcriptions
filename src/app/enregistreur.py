"""
Capture audio au format ideal pour Whisper : WAV 16 kHz, mono, 16 bits.

Deux modes :
  - "micro"          : un seul canal (telephone en haut-parleur, reunion physique)
  - "micro+systeme"  : deux fichiers separes, micro et son du PC (Teams, Zoom...).
                       Chaque fichier ne contient qu'une voix : l'identification
                       des locuteurs devient exacte, sans modele d'IA.

Si le peripherique refuse 16 kHz, on enregistre a sa frequence native puis on
reechantillonne proprement avec PyAV a la fin.

Windows : sounddevice (micro) et PyAudioWPatch (loopback WASAPI).
Linux   : PulseAudio / PipeWire via les outils pactl et parec. Le son du PC
          se capte sur la source "monitor" de la sortie, qui existe nativement.
"""
import os
import sys
import wave
import time
import shutil
import threading
import subprocess
import datetime as _dt

import numpy as np

LINUX = sys.platform.startswith("linux")
if not LINUX:
    import sounddevice as sd

SR_CIBLE = 16000


# --------------------------------------------------------------------------- #
# Peripheriques - Linux (PulseAudio / PipeWire)
# --------------------------------------------------------------------------- #
def _pactl(*args):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True,
                              timeout=5, env={**os.environ, "LC_ALL": "C"}).stdout
    except Exception:
        return ""


def _sources_pulse():
    """[(nom_technique, description)] de toutes les sources, monitors compris."""
    res, nom = [], None
    for ligne in _pactl("list", "sources").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("Name:"):
            nom = ligne.split(":", 1)[1].strip()
        elif ligne.startswith("Description:") and nom:
            res.append((nom, ligne.split(":", 1)[1].strip()))
            nom = None
    return res


def _pulse_entree():
    return [{"id": n, "nom": d} for n, d in _sources_pulse() if not n.endswith(".monitor")]


def _pulse_sortie():
    return [{"id": n, "nom": d.replace("Monitor of ", "Son de : ")}
            for n, d in _sources_pulse() if n.endswith(".monitor")]


def _pulse_defaut(liste, commande, suffixe=""):
    defaut = _pactl(commande).strip() + suffixe
    if any(x["id"] == defaut for x in liste):
        return defaut
    return liste[0]["id"] if liste else None


# --------------------------------------------------------------------------- #
# Peripheriques
# --------------------------------------------------------------------------- #
def _lister(sortie=False):
    """Peripheriques d'entree ou de sortie, avec leur API hote."""
    apis = sd.query_hostapis()
    cle = "max_output_channels" if sortie else "max_input_channels"
    res = []
    for i, d in enumerate(sd.query_devices()):
        if d[cle] > 0:
            res.append({"id": i, "nom": d["name"], "api": apis[d["hostapi"]]["name"],
                        "canaux": d[cle], "sr": int(d["default_samplerate"])})
    return res


def peripheriques_entree():
    """Micros. On privilegie WASAPI (liste propre, faible latence) ; sinon tout."""
    if LINUX:
        return _pulse_entree()
    tous = _lister(sortie=False)
    return [d for d in tous if d["api"] == "Windows WASAPI"] or tous


def peripheriques_sortie():
    """Sorties captables en boucle (loopback WASAPI), via PyAudioWPatch.

    sounddevice ne sait pas faire de loopback : sa classe WasapiSettings
    n'expose que exclusive / auto_convert / explicit_sample_format.
    """
    if LINUX:
        return _pulse_sortie()
    res = []
    try:
        import pyaudiowpatch as pa
    except ImportError:
        return res
    p = pa.PyAudio()
    try:
        for d in p.get_loopback_device_info_generator():
            res.append({"id": int(d["index"]), "nom": d["name"], "api": "WASAPI loopback",
                        "canaux": int(d["maxInputChannels"]),
                        "sr": int(d["defaultSampleRate"])})
    finally:
        p.terminate()
    return res


def peripherique_defaut_entree():
    liste = peripheriques_entree()
    if not liste:
        return None
    if LINUX:
        return _pulse_defaut(liste, "get-default-source")
    try:
        d = sd.default.device[0]
        if any(x["id"] == d for x in liste):
            return d
    except Exception:
        pass
    return liste[0]["id"]


def peripherique_defaut_sortie():
    liste = peripheriques_sortie()
    if not liste:
        return None
    if LINUX:
        return _pulse_defaut(liste, "get-default-sink", ".monitor")
    try:
        import pyaudiowpatch as pa
        p = pa.PyAudio()
        try:
            nom = p.get_device_info_by_index(
                p.get_host_api_info_by_type(pa.paWASAPI)["defaultOutputDevice"])["name"]
        finally:
            p.terminate()
        for d in liste:
            if nom in d["nom"]:
                return d["id"]
    except Exception:
        pass
    return liste[0]["id"]


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

    def demarrer(self):
        infos = sd.query_devices(self.device)
        natif = int(infos["default_samplerate"])
        # On tente 16 kHz directement ; sinon frequence native + reechantillonnage
        for sr in (SR_CIBLE, natif):
            try:
                stream = sd.InputStream(
                    device=self.device, channels=1, samplerate=sr,
                    dtype="int16", blocksize=0, callback=self._callback,
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



class _PisteLoopback:
    """Capture du son sortant du PC (WASAPI loopback), via PyAudioWPatch.

    Le loopback impose le format natif du peripherique de sortie (souvent
    48 kHz stereo) : on enregistre tel quel, puis _reechantillonner ramene
    le tout en mono 16 kHz.
    """

    def __init__(self, chemin, index):
        self.chemin = chemin
        self.index = index
        self.pa = None
        self.stream = None
        self.wav = None
        self.sr = SR_CIBLE
        self.canaux = 1
        self.niveau = 0.0
        self.t0 = None          # horloge de reference
        self.ecrits = 0         # echantillons ecrits (par canal)
        self._lock = threading.Lock()

    def demarrer(self):
        import pyaudiowpatch as pa
        self.pa = pa.PyAudio()
        infos = self.pa.get_device_info_by_index(self.index)
        self.canaux = int(infos["maxInputChannels"])
        self.sr = int(infos["defaultSampleRate"])

        self.wav = wave.open(self.chemin, "wb")
        self.wav.setnchannels(self.canaux)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.sr)

        self.t0 = time.time()
        self.stream = self.pa.open(
            format=pa.paInt16, channels=self.canaux, rate=self.sr,
            input=True, input_device_index=self.index,
            frames_per_buffer=1024, stream_callback=self._callback,
        )
        self.stream.start_stream()

    def _combler(self, jusqu_a):
        """Ecrit du silence pour rattraper l'horloge.

        Le loopback ne delivre AUCUNE donnee tant que rien ne joue sur le PC.
        Sans ce rattrapage, les silences du correspondant disparaissent et la
        piste se desynchronise du micro, faussant l'attribution des tours.
        """
        manque = jusqu_a - self.ecrits
        if manque > 0:
            self.wav.writeframes(b"\x00" * (manque * self.canaux * 2))
            self.ecrits += manque

    def _callback(self, donnees, nb, infos, statut):
        import pyaudiowpatch as pa
        with self._lock:
            if self.wav is not None:
                attendu = int((time.time() - self.t0) * self.sr) - nb
                self._combler(attendu)
                self.wav.writeframes(donnees)
                self.ecrits += nb
                ech = np.frombuffer(donnees, dtype=np.int16)
                if ech.size:
                    self.niveau = float(np.abs(ech).mean()) / 32768.0
        return (None, pa.paContinue)

    def arreter(self):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.pa is not None:
            try:
                self.pa.terminate()
            except Exception:
                pass
            self.pa = None
        with self._lock:
            if self.wav is not None:
                if self.t0 is not None:
                    self._combler(int((time.time() - self.t0) * self.sr))
                self.wav.close()
                self.wav = None
        # Stereo 48 kHz -> mono 16 kHz
        if self.sr != SR_CIBLE or self.canaux != 1:
            _reechantillonner(self.chemin, SR_CIBLE)
            self.sr, self.canaux = SR_CIBLE, 1
        return self.chemin


class _PistePulse:
    """Capture Linux d'une source PulseAudio / PipeWire (micro ou monitor).

    parec convertit lui-meme en 16 kHz mono : pas de reechantillonnage.
    Comme pour le loopback Windows, on comble d'apres l'horloge au cas ou
    le serveur de son suspend le flux pendant un silence.
    """

    def __init__(self, chemin, source):
        self.chemin = chemin
        self.source = source
        self.proc = None
        self.wav = None
        self.niveau = 0.0
        self.t0 = None
        self.ecrits = 0
        self.fil = None
        self._lock = threading.Lock()

    def demarrer(self):
        if not shutil.which("parec"):
            raise RuntimeError("Outil 'parec' introuvable : installez le paquet pulseaudio-utils.")
        self.proc = subprocess.Popen(
            ["parec", "--device=" + self.source, "--rate=%d" % SR_CIBLE,
             "--channels=1", "--format=s16le", "--latency-msec=100"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # L'audio arrive des le lancement (et attend dans le tube) : c'est
        # l'origine de l'horloge. Courte attente pour detecter un echec
        # immediat (source inconnue), sans trop decaler la 2e piste.
        t0 = time.time()
        time.sleep(0.15)
        if self.proc.poll() is not None:
            erreur = self.proc.stderr.read().decode("utf-8", "replace").strip()
            self.proc = None
            raise RuntimeError(f"Impossible d'ouvrir {self.source} : {erreur}")
        self.wav = wave.open(self.chemin, "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(SR_CIBLE)
        self.t0 = t0
        self.fil = threading.Thread(target=self._lire, daemon=True)
        self.fil.start()

    def _combler(self, jusqu_a):
        manque = jusqu_a - self.ecrits
        if manque > SR_CIBLE // 5:          # tolerance 200 ms : latence normale
            self.wav.writeframes(b"\x00" * (manque * 2))
            self.ecrits += manque

    def _lire(self):
        flux = self.proc.stdout
        while True:
            bloc = flux.read(1600 * 2)      # 100 ms
            if not bloc:
                break
            bloc = bloc[: len(bloc) // 2 * 2]
            with self._lock:
                if self.wav is None:
                    break
                n = len(bloc) // 2
                self._combler(int((time.time() - self.t0) * SR_CIBLE) - n)
                self.wav.writeframes(bloc)
                self.ecrits += n
                ech = np.frombuffer(bloc, dtype=np.int16)
                if ech.size:
                    self.niveau = float(np.abs(ech).mean()) / 32768.0

    def arreter(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.fil is not None:
            self.fil.join(timeout=3)
        with self._lock:
            if self.wav is not None:
                self._combler(int((time.time() - self.t0) * SR_CIBLE))
                self.wav.close()
                self.wav = None
        self.proc = None
        return self.chemin


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

        Micro = _PistePulse if LINUX else _Piste
        Systeme = _PistePulse if LINUX else _PisteLoopback
        pistes = [Micro(os.path.join(self.dossier, f"{base}.wav"), micro_id)]
        if systeme_id is not None:
            pistes[0].chemin = os.path.join(self.dossier, f"{base}.moi.wav")
            pistes.append(Systeme(
                os.path.join(self.dossier, f"{base}.correspondant.wav"), systeme_id))

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
