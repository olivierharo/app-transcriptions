"""
Index des enregistrements et de leur etat de transcription.

Un "enregistrement" est une entree logique qui peut reposer sur un seul fichier
(mode micro) ou sur deux (mode micro + correspondant). L'index est un simple
JSON a cote des fichiers ; il est reconstruit a partir du disque si besoin, ce
qui rend l'application tolerante a une suppression manuelle de fichiers.
"""
import os
import json
import wave
import datetime as _dt

ETATS = ("nouveau", "en_attente", "en_cours", "termine", "erreur")
EXTS_AUDIO = {".wav", ".m4a", ".mp3", ".ogg", ".flac", ".aac", ".opus", ".mp4", ".webm"}


def _duree_wav(chemin):
    try:
        with wave.open(chemin, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


def _duree(chemin):
    if chemin.lower().endswith(".wav"):
        d = _duree_wav(chemin)
        if d is not None:
            return d
    try:
        import av
        with av.open(chemin) as c:
            if c.duration:
                return c.duration / 1_000_000
    except Exception:
        pass
    return None


class Bibliotheque:
    def __init__(self, dossier):
        self.dossier = dossier
        os.makedirs(dossier, exist_ok=True)
        self.chemin_index = os.path.join(dossier, "index.json")
        self.entrees = {}
        self.charger()

    # ---------------------------------------------------------------- I/O --
    def charger(self):
        if os.path.exists(self.chemin_index):
            try:
                with open(self.chemin_index, encoding="utf-8") as f:
                    self.entrees = {e["id"]: e for e in json.load(f)}
            except Exception:
                self.entrees = {}
        self.synchroniser()

    def enregistrer(self):
        tmp = self.chemin_index + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.liste(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.chemin_index)

    # ------------------------------------------------------------ lecture --
    def liste(self):
        """Entrees triees, plus recentes d'abord."""
        return sorted(self.entrees.values(), key=lambda e: e.get("date", ""), reverse=True)

    def get(self, ident):
        return self.entrees.get(ident)

    # --------------------------------------------------------- ecriture ----
    def definir_etat(self, ident, etat, progression=None, erreur=None, transcription=None):
        e = self.entrees.get(ident)
        if not e:
            return
        e["etat"] = etat
        if progression is not None:
            e["progression"] = max(0, min(100, int(progression)))
        if erreur is not None:
            e["erreur"] = erreur
        if transcription is not None:
            e["transcription"] = transcription
        if etat == "termine":
            e["progression"] = 100
            e["erreur"] = None
        self.enregistrer()

    def renommer(self, ident, titre):
        e = self.entrees.get(ident)
        if e:
            e["titre"] = titre.strip() or e["id"]
            self.enregistrer()

    def supprimer(self, ident, effacer_fichiers=False):
        e = self.entrees.pop(ident, None)
        if e and effacer_fichiers:
            for c in list(e.get("fichiers", {}).values()):
                try:
                    os.remove(c)
                except OSError:
                    pass
        self.enregistrer()

    # ----------------------------------------------------- synchronisation --
    def synchroniser(self):
        """Aligne l'index sur le contenu reel du dossier."""
        vus = {}
        for nom in os.listdir(self.dossier):
            chemin = os.path.join(self.dossier, nom)
            if not os.path.isfile(chemin):
                continue
            racine, ext = os.path.splitext(nom)
            if ext.lower() not in EXTS_AUDIO:
                continue

            # "base.moi.wav" / "base.correspondant.wav" -> une seule entree
            role = "mono"
            ident = racine
            for suffixe, r in ((".moi", "micro"), (".correspondant", "correspondant")):
                if racine.endswith(suffixe):
                    ident, role = racine[: -len(suffixe)], r
                    break

            e = vus.setdefault(ident, {"id": ident, "fichiers": {}})
            e["fichiers"][role] = chemin

        # Fusion avec l'existant
        nouvelles = {}
        for ident, trouve in vus.items():
            ancienne = self.entrees.get(ident, {})
            e = dict(ancienne)
            e["id"] = ident
            e["fichiers"] = trouve["fichiers"]
            e.setdefault("titre", ident)
            e.setdefault("etat", "nouveau")
            e.setdefault("progression", 0)
            e.setdefault("erreur", None)

            principal = e["fichiers"].get("mono") or e["fichiers"].get("micro")
            if not e.get("date"):
                ts = os.path.getmtime(principal)
                e["date"] = _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
            if not e.get("duree"):
                e["duree"] = _duree(principal)
            e["deux_canaux"] = "correspondant" in e["fichiers"]

            # L'etat reel prime : une transcription presente sur disque = termine
            t = self._transcription_existante(e)
            if t:
                e["transcription"] = t
                if e["etat"] != "en_cours":
                    e["etat"] = "termine"
                    e["progression"] = 100
            elif e["etat"] == "termine":
                e["etat"] = "nouveau"          # fichier supprime entre-temps
                e["progression"] = 0
                e["transcription"] = None

            nouvelles[ident] = e

        self.entrees = nouvelles
        self.enregistrer()

    def _transcription_existante(self, e):
        base = os.path.join(self.dossier, e["id"])
        for suffixe in (".dialogue.txt", ".txt"):
            if os.path.exists(base + suffixe):
                return base + suffixe
        return None


def formater_duree(secondes):
    if not secondes:
        return "—"
    s = int(secondes)
    h, reste = divmod(s, 3600)
    m, s = divmod(reste, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def formater_date(iso):
    try:
        d = _dt.datetime.fromisoformat(iso)
    except Exception:
        return iso or "—"
    return d.strftime("%d/%m/%Y à %Hh%M")
