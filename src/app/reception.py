"""
Reception d'enregistrements depuis un telephone, en reseau local.

L'application ouvre un petit serveur web sur le reseau local. Le telephone
(meme Wi-Fi) l'atteint en scannant un QR code : une page lui permet
d'envoyer un fichier du Dictaphone, et un raccourci iPhone peut envoyer
directement ses enregistrements.

    GET  /?cle=...        page d'envoi (pour Safari)
    POST /envoi?cle=...   corps = le fichier audio brut ; &nom= et &titre= facultatifs
    GET  /icone.png       icone (ecran d'accueil de l'iPhone)

Aucun cloud : l'audio va directement du telephone au PC. Chaque requete doit
porter la cle secrete du QR code (128 bits), sans quoi elle est refusee.
"""
import os
import hmac
import json
import socket
import secrets
import datetime as _dt
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import config

PORT_DEFAUT = 47800
TAILLE_MAX = 4 * 1024 ** 3                 # 4 Go : ~24 h d'audio m4a
EXTENSIONS = {"audio/x-m4a": ".m4a", "audio/m4a": ".m4a", "audio/mp4": ".m4a", "audio/aac": ".aac",
              "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
              "audio/wave": ".wav", "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/flac": ".flac",
              "video/mp4": ".mp4", "video/quicktime": ".m4a"}
EXTS_ACCEPTEES = {".m4a", ".aac", ".mp3", ".wav", ".ogg", ".opus", ".webm", ".flac", ".mp4", ".caf"}
ICONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icone.png")


def cle_reception(nouvelle=False):
    """Cle secrete persistante : les raccourcis iPhone la conservent."""
    cle = config.lire_parametres().get("reception_cle")
    if nouvelle or not cle:
        cle = secrets.token_urlsafe(16)
        config.ecrire_parametre("reception_cle", cle)
    return cle


def ip_locale():
    """Adresse du PC sur le reseau local (interface qui sort vers le routeur).

    Un "connect" UDP n'envoie aucun paquet : il demande seulement au systeme
    quelle interface il utiliserait.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))           # adresse de documentation, jamais contactee
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _nom_fichier(dossier, titre, ext):
    """Meme convention que les enregistrements faits dans l'application."""
    from app.enregistreur import _nettoyer
    horo = _dt.datetime.now().strftime("%Y-%m-%d_%Hh%M")
    base = f"{horo}_{_nettoyer(titre)}" if titre else f"{horo}_iPhone"
    chemin, n = os.path.join(dossier, base + ext), 2
    while os.path.exists(chemin):
        chemin = os.path.join(dossier, f"{base} ({n}){ext}")
        n += 1
    return chemin


def _est_audio(chemin):
    try:
        import av
        with av.open(chemin) as c:
            return bool(c.streams.audio)
    except Exception:
        return False


class _Serveur(ThreadingHTTPServer):
    daemon_threads = True
    # Sous Windows, SO_REUSEADDR permettrait a un autre programme d'ecouter
    # sur le meme port en meme temps que nous.
    allow_reuse_address = os.name != "nt"


class Reception:
    """Serveur de reception. au_fichier_recu(chemin) est appele depuis un
    fil secondaire : l'interface doit le relayer vers son propre fil."""

    def __init__(self, dossier, au_fichier_recu):
        self.dossier = dossier
        self.au_fichier_recu = au_fichier_recu
        self.cle = cle_reception()
        self.serveur = None
        self.port = None

    @property
    def actif(self):
        return self.serveur is not None

    def demarrer(self):
        if self.serveur:
            return self.port
        port_prefere = int(config.lire_parametres().get("reception_port") or PORT_DEFAUT)
        derniere = None
        for port in [port_prefere] + [p for p in range(PORT_DEFAUT, PORT_DEFAUT + 10) if p != port_prefere]:
            try:
                self.serveur = _Serveur(("0.0.0.0", port), self._gestionnaire())
                self.port = port
                break
            except OSError as e:
                derniere = e
        if not self.serveur:
            raise RuntimeError(f"Aucun port disponible pour la réception ({derniere}).")
        if port != port_prefere:
            config.ecrire_parametre("reception_port", port)   # garder un port stable pour les raccourcis
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        return self.port

    def arreter(self):
        if self.serveur:
            self.serveur.shutdown()
            self.serveur.server_close()
            self.serveur = None

    def nouvelle_cle(self):
        self.cle = cle_reception(nouvelle=True)

    def url_page(self, ip):
        return f"http://{ip}:{self.port}/?cle={self.cle}"

    def url_envoi(self, ip):
        return f"http://{ip}:{self.port}/envoi?cle={self.cle}"

    # ----------------------------------------------------------- serveur --
    def _gestionnaire(self):
        reception = self

        class Gestionnaire(BaseHTTPRequestHandler):
            server_version = "Transcriptions"
            sys_version = ""

            def log_message(self, *args):
                pass

            def _repondre(self, code, corps, type_="application/json; charset=utf-8"):
                if isinstance(corps, (dict, list)):
                    corps = json.dumps(corps, ensure_ascii=False)
                if isinstance(corps, str):
                    corps = corps.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", type_)
                self.send_header("Content-Length", str(len(corps)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(corps)

            def _parametres(self):
                return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

            def _autorise(self, p):
                cle = p.get("cle") or self.headers.get("X-Cle") or ""
                return hmac.compare_digest(cle.encode(), reception.cle.encode())

            def do_GET(self):
                chemin = urlparse(self.path).path
                if chemin == "/icone.png":
                    with open(ICONE, "rb") as f:
                        return self._repondre(200, f.read(), "image/png")
                if chemin not in ("/", "/index.html"):
                    return self._repondre(404, {"erreur": "introuvable"})
                if not self._autorise(self._parametres()):
                    return self._repondre(403, PAGE_REFUS, "text/html; charset=utf-8")
                self._repondre(200, PAGE, "text/html; charset=utf-8")

            def do_POST(self):
                if urlparse(self.path).path != "/envoi":
                    return self._repondre(404, {"erreur": "introuvable"})
                p = self._parametres()
                if not self._autorise(p):
                    return self._repondre(403, {"erreur": "Clé invalide : scannez à nouveau le QR code."})
                try:
                    chemin = self._recevoir(p)
                except ValueError as e:
                    return self._repondre(400, {"erreur": str(e)})
                reception.au_fichier_recu(chemin)
                self._repondre(200, {"ok": True, "fichier": os.path.basename(chemin)})

            def _recevoir(self, p):
                nom = os.path.basename(p.get("nom") or "")
                ext = os.path.splitext(nom)[1].lower()
                if ext not in EXTS_ACCEPTEES:
                    type_ = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                    ext = EXTENSIONS.get(type_, ".m4a")
                titre = (p.get("titre") or "").strip()
                if not titre and nom and not nom.lower().startswith(("nouvel enregistrement", "new recording",
                                                                      "enregistrement", "recording", "audio")):
                    titre = os.path.splitext(nom)[0]
                destination = _nom_fichier(reception.dossier, titre, ext)
                partiel = destination + ".part"      # ignore par la bibliotheque tant qu'incomplet
                try:
                    with open(partiel, "wb") as f:
                        recu = self._copier(f)
                    if recu == 0:
                        raise ValueError("Fichier vide.")
                    if not _est_audio(partiel):
                        raise ValueError("Ce fichier ne contient pas d'audio lisible.")
                    os.replace(partiel, destination)
                except Exception:
                    try:
                        os.remove(partiel)
                    except OSError:
                        pass
                    raise
                return destination

            def _copier(self, f):
                """Copie le corps de la requete, avec ou sans Content-Length
                (les raccourcis iPhone peuvent envoyer en 'chunked')."""
                recu = 0
                if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                    while True:
                        taille = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                        if taille == 0:
                            self.rfile.readline()
                            break
                        recu += taille
                        if recu > TAILLE_MAX:
                            raise ValueError("Fichier trop volumineux.")
                        f.write(self.rfile.read(taille))
                        self.rfile.readline()
                    return recu
                reste = int(self.headers.get("Content-Length") or 0)
                if reste > TAILLE_MAX:
                    raise ValueError("Fichier trop volumineux.")
                while reste > 0:
                    bloc = self.rfile.read(min(reste, 1024 * 1024))
                    if not bloc:
                        raise ValueError("Transfert interrompu.")
                    f.write(bloc)
                    recu += len(bloc)
                    reste -= len(bloc)
                return recu

        return Gestionnaire


# --------------------------------------------------------------------------- #
# Page servie au telephone
# --------------------------------------------------------------------------- #
PAGE_REFUS = """<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Transcriptions</title>
<body style="font-family:-apple-system,system-ui,sans-serif;padding:32px;text-align:center;color:#111827">
<h2>Accès refusé</h2><p>Scannez le QR code affiché dans l'application Transcriptions,
sur votre ordinateur (bouton « Recevoir depuis l'iPhone »).</p></body></html>"""

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Transcriptions">
<link rel="apple-touch-icon" href="/icone.png">
<title>Transcriptions</title>
<style>
  :root { --bleu:#1d4ed8; --fonce:#1e3a8a; --gris:#6b7280; --fond:#f3f4f6; --vert:#15803d; --rouge:#b91c1c; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,system-ui,"Segoe UI",sans-serif; background:var(--fond); color:#111827; }
  header { background:linear-gradient(135deg,#2563eb,var(--fonce)); color:#fff; padding:28px 20px 22px;
           padding-top:max(28px, env(safe-area-inset-top)); display:flex; gap:14px; align-items:center; }
  header img { width:52px; height:52px; border-radius:12px; }
  header h1 { margin:0; font-size:22px; } header p { margin:2px 0 0; opacity:.85; font-size:14px; }
  main { padding:18px 16px 40px; max-width:560px; margin:0 auto; }
  .carte { background:#fff; border-radius:16px; padding:18px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .bouton { display:block; width:100%; border:0; border-radius:12px; padding:16px; font-size:17px; font-weight:600;
            background:var(--bleu); color:#fff; text-align:center; }
  .bouton:active { background:var(--fonce); }
  label.titre { display:block; font-size:14px; color:var(--gris); margin:14px 0 6px; }
  input[type=text] { width:100%; font-size:16px; padding:12px; border:1px solid #d1d5db; border-radius:10px; }
  .envoi { margin-top:14px; font-size:15px; }
  .barre { height:8px; background:#e5e7eb; border-radius:4px; overflow:hidden; margin-top:6px; }
  .barre div { height:100%; width:0; background:var(--bleu); transition:width .2s; }
  .ok { color:var(--vert); } .ko { color:var(--rouge); }
  h2 { font-size:17px; margin:0 0 10px; }
  ol { padding-left:20px; margin:8px 0; line-height:1.5; } li { margin-bottom:6px; }
  .note { font-size:13px; color:var(--gris); }
  details summary { font-weight:600; font-size:17px; cursor:pointer; }
  .copie { display:flex; gap:8px; margin-top:8px; }
  .copie input { font-size:13px; font-family:ui-monospace,monospace; }
  .copie button { border:1px solid #d1d5db; background:#fff; border-radius:10px; padding:0 14px; font-size:15px; }
  b.action { color:var(--fonce); }
</style>
</head>
<body>
<header>
  <img src="/icone.png" alt="">
  <div><h1>Transcriptions</h1><p>Envoyer un enregistrement à l'ordinateur</p></div>
</header>
<main>
  <div class="carte">
    <input id="fichier" type="file" accept="audio/*,.m4a,.mp3,.wav,.aac" multiple hidden>
    <button class="bouton" onclick="document.getElementById('fichier').click()">🎙️ Choisir un enregistrement</button>
    <label class="titre" for="titre">Titre (facultatif)</label>
    <input id="titre" type="text" placeholder="ex. Réunion projet – devis" autocomplete="off">
    <div id="envois"></div>
    <p class="note"><b>Les mémos du Dictaphone ne sont pas visibles d'ici</b> : il faut d'abord les copier
      dans l'app Fichiers.</p>
    <ol class="note">
      <li>Dans le <b>Dictaphone</b>, touchez l'enregistrement, puis <b>•••</b> › <b>Partager</b>
          › <b>Enregistrer dans Fichiers</b> › <b>Sur mon iPhone</b> › <b>Enregistrer</b>.</li>
      <li>Revenez ici, touchez <b>Choisir un enregistrement</b> › <b>Choisir un fichier</b>
          (ou <b>Parcourir</b>) › <b>Sur mon iPhone</b>, puis le mémo.</li>
    </ol>
    <p class="note">Plus rapide : le raccourci <b>« Envoyer à Transcriptions »</b> ci-dessous envoie
      directement depuis le bouton Partager du Dictaphone, sans passer par Fichiers.
      Il est transcrit automatiquement sur l'ordinateur.</p>
  </div>

  <div class="carte">
    <details>
      <summary>⚡ Raccourcis iPhone (recommandé)</summary>
      <p class="note">À créer une seule fois, dans l'app <b>Raccourcis</b>. Ils ont besoin de cette adresse :</p>
      <div class="copie"><input id="url" type="text" readonly><button onclick="copier()">Copier</button></div>
      <p id="copie-ok" class="note ok"></p>

      <h2 style="margin-top:18px">1. « Envoyer à Transcriptions »</h2>
      <p class="note">Envoie un mémo du Dictaphone en deux touches, depuis le bouton Partager.</p>
      <ol>
        <li>Raccourcis › <b>+</b> › renommez-le <i>Envoyer à Transcriptions</i>.</li>
        <li>Touchez <b>ⓘ</b> (en bas) › activez <b>Afficher dans la feuille de partage</b>.
            En haut, « Recevoir <i>Tout</i> » : ne gardez que <b>Fichiers</b> et <b>Média</b>.</li>
        <li>Ajoutez l'action <b class="action">Obtenir le contenu de l'URL</b> :
          collez l'adresse ci-dessus, touchez <b>Afficher plus</b> ›
          Méthode <b>POST</b> › Corps de la requête <b>Fichier</b> › Fichier = <b>Entrée du raccourci</b>.</li>
        <li>Ajoutez <b class="action">Afficher la notification</b> : <i>Envoyé à l'ordinateur</i>.</li>
      </ol>
      <p class="note">Ensuite, dans le Dictaphone : <b>•••</b> › <b>Partager</b> › <b>Envoyer à Transcriptions</b>.</p>

      <h2 style="margin-top:18px">2. « Enregistrer un appel »</h2>
      <p class="note">Un bouton sur l'écran d'accueil qui enregistre, garde une copie sur l'iPhone, puis envoie.</p>
      <ol>
        <li>Raccourcis › <b>+</b> › renommez-le <i>Enregistrer un appel</i>.</li>
        <li><b class="action">Enregistrer de l'audio</b> : Début <b>Immédiatement</b>, Fin <b>Lors du toucher</b>.</li>
        <li><b class="action">Enregistrer le fichier</b> : désactivez <b>Demander où enregistrer</b>,
            dossier <i>Fichiers › Sur mon iPhone › Transcriptions</i>.
            <br><span class="note">Si l'envoi échoue (hors Wi-Fi), l'enregistrement reste là.</span></li>
        <li><b class="action">Obtenir le contenu de l'URL</b> : même réglage qu'au 1, avec
            Fichier = <b>Audio enregistré</b>.</li>
        <li><b class="action">Afficher la notification</b> : <i>Envoyé à l'ordinateur</i>.</li>
        <li>Touchez <b>ⓘ</b> › <b>Ajouter à l'écran d'accueil</b>.</li>
      </ol>
    </details>
  </div>

  <p class="note">🔒 Les fichiers vont directement de l'iPhone à l'ordinateur, sur votre réseau Wi-Fi,
    sans passer par Internet. Astuce : Partager › <b>Sur l'écran d'accueil</b> pour retrouver cette page.</p>
</main>
<script>
  const cle = new URLSearchParams(location.search).get("cle") || "";
  const urlEnvoi = location.origin + "/envoi?cle=" + encodeURIComponent(cle);
  document.getElementById("url").value = urlEnvoi;

  function copier() {
    const champ = document.getElementById("url");
    champ.focus(); champ.setSelectionRange(0, champ.value.length);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    if (!ok && navigator.clipboard) { navigator.clipboard.writeText(champ.value).then(() => {}, () => {}); ok = true; }
    document.getElementById("copie-ok").textContent = ok ? "Adresse copiée." : "Sélectionnez l'adresse et copiez-la.";
  }

  document.getElementById("fichier").addEventListener("change", (ev) => {
    for (const f of ev.target.files) envoyer(f);
    ev.target.value = "";
  });

  function taille(o) { return o > 1048576 ? (o / 1048576).toFixed(1).replace(".", ",") + " Mo" : Math.ceil(o / 1024) + " Ko"; }

  function envoyer(fichier) {
    const bloc = document.createElement("div");
    bloc.className = "envoi";
    bloc.innerHTML = '<div class="nom"></div><div class="barre"><div></div></div><div class="etat note"></div>';
    bloc.querySelector(".nom").textContent = fichier.name + " (" + taille(fichier.size) + ")";
    document.getElementById("envois").prepend(bloc);
    const barre = bloc.querySelector(".barre div"), etat = bloc.querySelector(".etat");
    const titre = document.getElementById("titre").value.trim();
    const xhr = new XMLHttpRequest();
    xhr.open("POST", urlEnvoi + "&nom=" + encodeURIComponent(fichier.name) + "&titre=" + encodeURIComponent(titre));
    xhr.setRequestHeader("Content-Type", fichier.type || "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { barre.style.width = (100 * e.loaded / e.total) + "%";
      etat.textContent = "Envoi… " + Math.round(100 * e.loaded / e.total) + " %"; } };
    xhr.onload = () => {
      let r = {}; try { r = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status === 200) { barre.style.width = "100%"; etat.className = "etat ok";
        etat.textContent = "✓ Reçu par l'ordinateur : " + r.fichier; document.getElementById("titre").value = ""; }
      else { etat.className = "etat ko"; etat.textContent = "✗ " + (r.erreur || ("Erreur " + xhr.status)); }
    };
    xhr.onerror = () => { etat.className = "etat ko";
      etat.textContent = "✗ Ordinateur injoignable : même Wi-Fi ? application ouverte ?"; };
    xhr.send(fichier);
  }
</script>
</body>
</html>"""
