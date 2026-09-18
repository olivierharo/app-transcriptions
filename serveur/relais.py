"""
Relais Transcriptions : boite aux lettres entre l'iPhone et l'ordinateur.

L'iPhone depose un enregistrement (cle d'ENVOI), l'application du PC vient le
chercher puis le supprime (cle de RETRAIT). Chaque membre de l'equipe a sa
propre boite. Le serveur ne contacte jamais le PC : rien a ouvrir sur la box.

    GET    /                    page d'envoi (la cle est dans le fragment #cle=...)
    POST   /api/depot           corps = fichier audio ; ?nom= &titre= ; cle d'envoi
    GET    /api/verifier        {utilisateur, type} ; l'une ou l'autre cle
    GET    /api/boite           liste des fichiers en attente ; cle de retrait
    GET    /api/boite/<id>      telecharge un fichier ; cle de retrait
    DELETE /api/boite/<id>      supprime un fichier ; cle de retrait

Cle : en-tete "Authorization: Bearer <cle>" ou parametre ?cle=<cle> (raccourcis).
Les cles ne sont stockees que sous forme d'empreinte SHA-256.

Bibliotheque standard uniquement. Prevu pour tourner derriere Caddy (HTTPS).
    python relais.py                (ecoute sur 0.0.0.0:8000, donnees dans ./donnees)
"""
import os
import re
import sys
import json
import time
import hmac
import hashlib
import secrets
import threading
import datetime as _dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.environ.get("RELAIS_DONNEES", os.path.join(ICI, "donnees"))
PORT = int(os.environ.get("RELAIS_PORT", "8000"))
TAILLE_MAX = int(os.environ.get("RELAIS_TAILLE_MAX_MO", "2048")) * 1024 ** 2
QUOTA_BOITE = int(os.environ.get("RELAIS_QUOTA_MO", "5120")) * 1024 ** 2
CONSERVATION = int(os.environ.get("RELAIS_CONSERVATION_JOURS", "7")) * 86400
EXTS = {".m4a", ".aac", ".mp3", ".wav", ".ogg", ".opus", ".webm", ".flac", ".mp4", ".caf"}
TYPES = {"audio/x-m4a": ".m4a", "audio/m4a": ".m4a", "audio/mp4": ".m4a", "audio/aac": ".aac",
         "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
         "audio/wave": ".wav", "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/flac": ".flac",
         "video/mp4": ".m4a", "video/quicktime": ".m4a", "audio/x-caf": ".caf"}
# Signatures des formats audio acceptes : un depot qui n'en est pas un est refuse.
SIGNATURES = (b"ftyp", b"RIFF", b"ID3", b"OggS", b"fLaC", b"\x1aE\xdf\xa3", b"caff",
              b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xf1", b"\xff\xf9")   # MP3 / AAC bruts
_VERROU = threading.Lock()


# --------------------------------------------------------------------------- #
# Comptes
# --------------------------------------------------------------------------- #
def _empreinte(cle):
    return hashlib.sha256(cle.encode()).hexdigest()


def _fichier_comptes():
    return os.path.join(DONNEES, "comptes.json")


def lire_comptes():
    try:
        with open(_fichier_comptes(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def ecrire_comptes(comptes):
    os.makedirs(DONNEES, exist_ok=True)
    tmp = _fichier_comptes() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(comptes, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _fichier_comptes())


def creer_cles(nom):
    """Cree (ou renouvelle) les cles d'un membre. Retourne (envoi, retrait) en clair :
    c'est la seule fois ou elles sont visibles."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,39}", nom):
        raise ValueError("Nom invalide : minuscules, chiffres, . _ - (40 caractères max).")
    envoi, retrait = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with _VERROU:
        comptes = lire_comptes()
        comptes[nom] = {"envoi": _empreinte(envoi), "retrait": _empreinte(retrait),
                        "cree": comptes.get(nom, {}).get("cree") or _dt.datetime.now().isoformat(timespec="seconds")}
        ecrire_comptes(comptes)
    return envoi, retrait


def identifier(cle):
    """(utilisateur, 'envoi'|'retrait') ou (None, None)."""
    if not cle:
        return None, None
    e = _empreinte(cle)
    trouve = (None, None)
    for nom, c in lire_comptes().items():
        for type_ in ("envoi", "retrait"):
            if hmac.compare_digest(e, c.get(type_, "")):
                trouve = (nom, type_)
    return trouve


def boite(nom):
    d = os.path.join(DONNEES, "boites", nom)
    os.makedirs(d, exist_ok=True)
    return d


def contenu_boite(nom):
    d = boite(nom)
    res = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    res.append(json.load(fh))
            except (OSError, ValueError):
                pass
    return res


def purger():
    """Supprime les depots jamais recuperes et les envois interrompus."""
    racine = os.path.join(DONNEES, "boites")
    if not os.path.isdir(racine):
        return
    for nom in os.listdir(racine):
        d = os.path.join(racine, nom)
        for f in os.listdir(d):
            chemin = os.path.join(d, f)
            age_max = 3600 if f.endswith(".part") else CONSERVATION
            try:
                if os.path.getmtime(chemin) < time.time() - age_max:
                    os.remove(chemin)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Serveur HTTP
# --------------------------------------------------------------------------- #
class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "Transcriptions-relais"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Journal minimal : jamais d'URL complete (elle peut contenir une cle).
        sys.stderr.write(f"{self.log_date_time_string()} {self.command} "
                         f"{urlparse(self.path).path} {args[1] if len(args) > 1 else ''}\n")

    # ------------------------------------------------------------ outils --
    def _repondre(self, code, corps=b"", type_="application/json; charset=utf-8", entetes=None):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False).encode()
        elif isinstance(corps, str):
            corps = corps.encode()
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def _erreur(self, code, message):
        self._repondre(code, {"erreur": message})

    def _params(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _cle(self):
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self._params().get("cle", "")

    def _auth(self, type_attendu):
        nom, type_ = identifier(self._cle())
        if nom and (type_attendu is None or type_ == type_attendu):
            return nom, type_
        time.sleep(1)                         # freine les essais de cles au hasard
        self._erreur(403, "Clé invalide.")
        return None, None

    def _vider_corps(self):
        """Lit le corps d'une requete refusee, pour garder la connexion saine."""
        reste = int(self.headers.get("Content-Length") or 0)
        while reste > 0:
            bloc = self.rfile.read(min(reste, 1 << 20))
            if not bloc:
                break
            reste -= len(bloc)

    # ----------------------------------------------------------- routes --
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin in ("/", "/index.html"):
            with open(os.path.join(ICI, "page.html"), "rb") as f:
                return self._repondre(200, f.read(), "text/html; charset=utf-8")
        if chemin == "/icone.png":
            with open(os.path.join(ICI, "icone.png"), "rb") as f:
                return self._repondre(200, f.read(), "image/png", {"Cache-Control": "max-age=86400"})
        if chemin == "/sante":
            return self._repondre(200, {"ok": True})
        if chemin == "/api/verifier":
            nom, type_ = self._auth(None)
            if nom:
                self._repondre(200, {"utilisateur": nom, "type": type_})
            return
        if chemin == "/api/boite":
            nom, _ = self._auth("retrait")
            if nom:
                self._repondre(200, contenu_boite(nom))
            return
        m = re.fullmatch(r"/api/boite/([A-Za-z0-9_-]+)", chemin)
        if m:
            nom, _ = self._auth("retrait")
            if not nom:
                return
            meta = self._meta(nom, m.group(1))
            if not meta:
                return self._erreur(404, "Fichier introuvable.")
            fichier = os.path.join(boite(nom), meta["id"] + meta["ext"])
            taille = os.path.getsize(fichier)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(taille))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                with open(fichier, "rb") as f:
                    while True:
                        bloc = f.read(1 << 20)
                        if not bloc:
                            break
                        self.wfile.write(bloc)
            return
        self._erreur(404, "Introuvable.")

    def do_DELETE(self):
        m = re.fullmatch(r"/api/boite/([A-Za-z0-9_-]+)", urlparse(self.path).path)
        if not m:
            return self._erreur(404, "Introuvable.")
        nom, _ = self._auth("retrait")
        if not nom:
            return
        meta = self._meta(nom, m.group(1))
        if not meta:
            return self._erreur(404, "Fichier introuvable.")
        for suffixe in (meta["ext"], ".json"):
            try:
                os.remove(os.path.join(boite(nom), meta["id"] + suffixe))
            except OSError:
                pass
        self._repondre(200, {"ok": True})

    def do_POST(self):
        if urlparse(self.path).path != "/api/depot":
            self._vider_corps()
            return self._erreur(404, "Introuvable.")
        nom, _ = self._auth("envoi")
        if not nom:
            self._vider_corps()
            return
        try:
            meta = self._deposer(nom)
        except ValueError as e:
            self.close_connection = True
            return self._erreur(400, str(e))
        self._repondre(200, {"ok": True, "id": meta["id"], "taille": meta["taille"]})

    # ---------------------------------------------------------- depots --
    def _meta(self, nom, ident):
        try:
            with open(os.path.join(boite(nom), ident + ".json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _deposer(self, nom):
        p = self._params()
        original = os.path.basename(p.get("nom") or "")[:120]
        ext = os.path.splitext(original)[1].lower()
        if ext not in EXTS:
            type_ = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = TYPES.get(type_, ".m4a")
        d = boite(nom)
        occupe = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
        annonce = int(self.headers.get("Content-Length") or 0)
        if annonce > TAILLE_MAX:
            raise ValueError("Fichier trop volumineux.")
        if occupe + annonce > QUOTA_BOITE:
            raise ValueError("Boîte pleine : ouvrez l'application sur l'ordinateur pour la vider.")
        ident = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)
        partiel = os.path.join(d, ident + ".part")
        try:
            with open(partiel, "wb") as f:
                recu, debut = self._copier(f)
            if recu == 0:
                raise ValueError("Fichier vide.")
            if not any(sig in debut[:16] for sig in SIGNATURES):
                raise ValueError("Ce fichier n'est pas un enregistrement audio reconnu.")
            os.replace(partiel, os.path.join(d, ident + ext))
        except Exception:
            try:
                os.remove(partiel)
            except OSError:
                pass
            raise
        meta = {"id": ident, "ext": ext, "nom": original, "titre": (p.get("titre") or "").strip()[:120],
                "taille": recu, "date": _dt.datetime.now().isoformat(timespec="seconds")}
        with open(os.path.join(d, ident + ".json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        return meta

    def _copier(self, f):
        """Copie le corps (Content-Length ou chunked). Retourne (taille, debut)."""
        recu, debut = 0, b""

        def ecrire(bloc):
            nonlocal recu, debut
            recu += len(bloc)
            if recu > TAILLE_MAX:
                raise ValueError("Fichier trop volumineux.")
            if len(debut) < 16:
                debut += bloc[:16]
            f.write(bloc)

        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            while True:
                taille = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if taille == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    break
                reste = taille
                while reste:
                    bloc = self.rfile.read(min(reste, 1 << 20))
                    if not bloc:
                        raise ValueError("Transfert interrompu.")
                    ecrire(bloc)
                    reste -= len(bloc)
                self.rfile.readline()
            return recu, debut
        reste = int(self.headers.get("Content-Length") or 0)
        while reste > 0:
            bloc = self.rfile.read(min(reste, 1 << 20))
            if not bloc:
                raise ValueError("Transfert interrompu.")
            ecrire(bloc)
            reste -= len(bloc)
        return recu, debut


class Serveur(ThreadingHTTPServer):
    daemon_threads = True


def main():
    os.makedirs(DONNEES, exist_ok=True)

    def purge_periodique():
        while True:
            purger()
            time.sleep(3600)

    threading.Thread(target=purge_periodique, daemon=True).start()
    serveur = Serveur(("0.0.0.0", PORT), Gestionnaire)
    print(f"Relais Transcriptions sur le port {PORT}, données dans {DONNEES}", flush=True)
    serveur.serve_forever()


if __name__ == "__main__":
    main()
