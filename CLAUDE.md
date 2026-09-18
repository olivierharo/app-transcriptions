# Transcriptions — notes pour Claude

Application de bureau (PySide6) qui enregistre et transcrit des conversations en
français avec WhisperX, sur GPU NVIDIA. Auteur : Olivier Haro. Code, commentaires,
messages et documentation **en français** (identifiants sans accents dans le code).

## Décisions prises avec l'utilisateur (ne pas remettre en cause sans lui)

- **GPU NVIDIA obligatoire.** Pas de repli CPU : sans GPU, l'application et
  l'installateur affichent « Pas de bras, pas de chocolat ! » avec une explication.
- **Pas de noms de locuteurs** : un tiret « - » à chaque changement de voix.
- **Windows 10/11 et Ubuntu 22.04/24.04** : environ la moitié de l'équipe est
  sous Ubuntu. Tout changement doit fonctionner sur les deux (capture audio :
  WASAPI/PyAudioWPatch sous Windows, `parec` PulseAudio/PipeWire sous Ubuntu).
- **Distribution** : installateur graphique maison (`installation/installateur/`),
  construit et publié par GitHub Actions à chaque tag `vX.Y.Z`
  (`.github/workflows/release.yml`). Le tag doit égaler `__version__` de
  `src/app/__init__.py`. Installateurs non signés (SmartScreen accepté).
- **Dépôt public**, licence MIT. Aucune donnée client dans git : `local/`,
  audio, transcriptions et `.env` sont ignorés. Vérifier `git status` avant commit.
- **iPhone** : boîte aux lettres sur le relais **Symfony** `relais/`
  (https://transcriptions.arobases.fr), une boîte par membre, clés d'envoi / de
  retrait séparées. Choix de l'utilisateur : Symfony + MySQL/Doctrine sur son
  serveur Apache (pas de Docker). Le mode réseau local a été abandonné.

## Structure

- `src/app/` : application — `fenetre.py` (UI), `enregistreur.py` (capture),
  `moteur.py` (WhisperX en sous-processus, progression JSON sur stdout),
  `bibliotheque.py` (index des enregistrements), `relais.py` (relève de la boîte
  iPhone), `prechargement.py` (modèles téléchargés à l'installation),
  `mise_a_jour.py` (release GitHub → installateur lancé en `--mise-a-jour`).
- `installation/` : installateur graphique (`operations.py` = logique,
  `assistant.py` = écrans, `lanceur.py` = entrée / désinstallation).
- `relais/` : relais iPhone Symfony 7.4 (API `src/Controller/RelaisController.php`,
  stockage `src/Service/Boites.php`, commandes `app:compte:*` et `app:purger`).

## Pièges connus

- WhisperX exige Python 3.10–3.13 (3.12 recommandé). Installer `torch` (index
  cu128) **avant** `requirements-app.txt`, sinon version CPU.
- `whisperx.load_audio` appelle ffmpeg : on décode avec PyAV (`moteur.charger_audio`).
- Linux : CTranslate2 a besoin de `LD_LIBRARY_PATH` vers `site-packages/nvidia/*/lib`
  (fait par `fenetre._environnement_moteur`).
- Exécutable PyInstaller : nettoyer l'environnement des sous-processus
  (`LD_LIBRARY_PATH`, variables `QT_*`), voir `operations.environnement_propre`.
- Sous Windows, le `python.exe` d'un venv relance le Python principal : pour
  retrouver les processus de l'app, chercher par ligne de commande.
- Les modèles pyannote exigent d'accepter leurs conditions sur Hugging Face,
  dont `speaker-diarization-community-1`, même si l'on demande la 3.1.

## Tests

Pas de suite automatisée. Vérifier par des scripts ponctuels, hors du dépôt :
- relais : compte temporaire (`php bin/console app:compte:creer essai-…`), appels
  `curl` sur https://transcriptions.arobases.fr, puis `app:compte:supprimer` ;
- application de bureau (sur un poste NVIDIA) : fenêtre Qt pilotée par `QTimer`,
  avec `APPDATA` et `DOSSIER_ENREGISTREMENTS` pointant vers des dossiers
  temporaires, pour ne jamais toucher aux réglages ni aux enregistrements réels.

## Environnement de travail : le serveur vps4

Le projet vit désormais sur le serveur Ubuntu 22.04 `vps4.arobases.fr` (SSH port
**1664**, compte `transcriptions`), dans `~/app-transcriptions`. Le relais y est en
production : `~/www` → `relais/`, Apache + PHP 8.2 (mod_php), MySQL (base et
utilisateur `transcriptions`, accès dans `relais/.env.local`), purge par crontab.

- **Pas de GPU ni d'environnement graphique** sur ce serveur : on n'y lance ni
  l'application de bureau ni une transcription. Les tester sur un poste NVIDIA.
- **Pas de sudo** : toute modification d'Apache, de PHP ou de paquets système se
  fait par l'utilisateur (root). Lui fournir les lignes exactes à ajouter.
- Modifier le relais, c'est modifier la production : tester avec un compte
  temporaire (`app:compte:creer essai-…` puis `app:compte:supprimer`), jamais
  avec les comptes réels.
