"""
Client du relais : releve la boite aux lettres de l'utilisateur sur le serveur.

L'iPhone depose ses enregistrements sur le relais (HTTPS, n'importe ou) ;
l'application les recupere regulierement, les range dans le dossier des
enregistrements, puis les supprime du serveur. C'est toujours le PC qui
contacte le serveur : rien a ouvrir sur la box, et le PC peut etre eteint au
moment de l'envoi.

Le « code de connexion » (TR1-...) est fourni par l'administrateur du relais
(serveur/admin.py). Il contient l'adresse du relais et les deux cles :
  - envoi   : sert uniquement a afficher le QR code de l'iPhone ;
  - retrait : permet de lister, telecharger et supprimer les depots.
"""
import os
import json
import base64
import threading
import datetime as _dt
import urllib.error
import urllib.request

import config

INTERVALLE = 30          # secondes entre deux releves
DELAI_RESEAU = 20
PARAMETRES = ("relais_url", "relais_nom", "relais_envoi", "relais_retrait")
TITRES_GENERIQUES = ("nouvel enregistrement", "new recording", "enregistrement", "recording", "audio")


class ErreurRelais(Exception):
    pass


def decoder_code(code):
    code = "".join(code.split())
    if not code.startswith("TR1-"):
        raise ErreurRelais("Ce n'est pas un code de connexion Transcriptions (il commence par « TR1- »).")
    brut = code[4:]
    try:
        d = json.loads(base64.urlsafe_b64decode(brut + "=" * (-len(brut) % 4)))
        return {"relais_url": d["u"].rstrip("/"), "relais_nom": d["n"],
                "relais_envoi": d["e"], "relais_retrait": d["r"]}
    except Exception:
        raise ErreurRelais("Code de connexion incomplet ou abîmé : recopiez-le en entier.")


def _requete(url, cle, methode="GET"):
    req = urllib.request.Request(url, method=methode, headers={
        "Authorization": "Bearer " + cle, "User-Agent": "Transcriptions"})
    try:
        return urllib.request.urlopen(req, timeout=DELAI_RESEAU)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ErreurRelais("Clé refusée par le serveur : demandez un nouveau code de connexion.")
        raise ErreurRelais(f"Erreur du serveur ({e.code}).")
    except (urllib.error.URLError, OSError) as e:
        raise ErreurRelais(f"Serveur injoignable ({getattr(e, 'reason', e)}).")


def _json(url, cle, methode="GET"):
    with _requete(url, cle, methode) as r:
        return json.loads(r.read().decode("utf-8"))


def _nom_fichier(dossier, meta):
    """Meme convention que les enregistrements faits dans l'application :
    date de l'enregistrement sur l'iPhone, puis le titre s'il y en a un."""
    from app.enregistreur import _nettoyer
    try:
        date = _dt.datetime.fromisoformat(meta.get("date", ""))
    except ValueError:
        date = _dt.datetime.now()
    titre = (meta.get("titre") or "").strip()
    original = os.path.splitext(meta.get("nom") or "")[0].strip()
    if not titre and original and not original.lower().startswith(TITRES_GENERIQUES):
        titre = original
    base = date.strftime("%Y-%m-%d_%Hh%M") + "_" + (_nettoyer(titre) if titre else "iPhone")
    ext = meta.get("ext") or ".m4a"
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


class Relais:
    """Releve periodique, dans un fil secondaire. Les rappels sont appeles
    depuis ce fil : l'interface doit les relayer vers le sien.

        au_fichier_recu(chemin)
        au_statut(texte, ok)
    """

    def __init__(self, dossier, au_fichier_recu, au_statut):
        self.dossier = dossier
        self.au_fichier_recu = au_fichier_recu
        self.au_statut = au_statut
        self._reveil = threading.Event()
        self._fil = None
        self._arret = False
        self.derniere_releve = None

    # ------------------------------------------------------- configuration --
    @staticmethod
    def reglages():
        p = config.lire_parametres()
        return {k: p.get(k) for k in PARAMETRES} if all(p.get(k) for k in PARAMETRES) else None

    @property
    def configure(self):
        return self.reglages() is not None

    def connecter(self, code):
        """Verifie le code aupres du serveur puis l'enregistre. Retourne le nom du compte."""
        r = decoder_code(code)
        rep = _json(r["relais_url"] + "/api/verifier", r["relais_retrait"])
        if rep.get("type") != "retrait":
            raise ErreurRelais("Ce code ne permet pas de relever la boîte.")
        for k, v in r.items():
            config.ecrire_parametre(k, v)
        self.relever_maintenant()
        return rep.get("utilisateur")

    def deconnecter(self):
        for k in PARAMETRES:
            config.ecrire_parametre(k, None)

    def url_iphone(self):
        r = self.reglages()
        return f"{r['relais_url']}/#cle={r['relais_envoi']}" if r else None

    # --------------------------------------------------------------- releve --
    def demarrer(self):
        if self._fil is None:
            self._fil = threading.Thread(target=self._boucle, daemon=True)
            self._fil.start()

    def arreter(self):
        self._arret = True
        self._reveil.set()

    def relever_maintenant(self):
        self._reveil.set()

    def _boucle(self):
        while not self._arret:
            if self.configure:
                try:
                    n = self.relever()
                    self.derniere_releve = _dt.datetime.now()
                    self.au_statut("Boîte iPhone relevée à " + self.derniere_releve.strftime("%H:%M")
                                   + (f" — {n} reçu(s)" if n else ""), True)
                except ErreurRelais as e:
                    self.au_statut(str(e), False)
                except Exception as e:           # ne jamais tuer le fil de releve
                    self.au_statut(f"Relève impossible : {e}", False)
            self._reveil.wait(INTERVALLE)
            self._reveil.clear()

    def relever(self):
        """Recupere tous les depots en attente. Retourne le nombre de fichiers recus."""
        r = self.reglages()
        if not r:
            return 0
        url, cle = r["relais_url"], r["relais_retrait"]
        recus = 0
        for meta in _json(url + "/api/boite", cle):
            if self._arret:
                break
            destination = _nom_fichier(self.dossier, meta)
            partiel = destination + ".part"       # ignore par la bibliotheque tant qu'incomplet
            try:
                with _requete(f"{url}/api/boite/{meta['id']}", cle) as rep, open(partiel, "wb") as f:
                    while True:
                        bloc = rep.read(1 << 20)
                        if not bloc:
                            break
                        f.write(bloc)
                if os.path.getsize(partiel) != meta.get("taille", os.path.getsize(partiel)):
                    raise ErreurRelais("Téléchargement incomplet, nouvel essai à la prochaine relève.")
                valide = _est_audio(partiel)
                if valide:
                    os.replace(partiel, destination)
            except BaseException:
                try:
                    os.remove(partiel)
                except OSError:
                    pass
                raise
            # Supprime du serveur seulement une fois le fichier en lieu sur.
            _json(f"{url}/api/boite/{meta['id']}", cle, "DELETE")
            if valide:
                recus += 1
                self.au_fichier_recu(destination)
            else:
                os.remove(partiel)
                self.au_statut(f"Fichier illisible ignoré : {meta.get('nom') or meta['id']}", False)
        return recus
