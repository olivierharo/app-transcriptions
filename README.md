# app-transcriptions

Application locale d'enregistrement et de transcription de conversations
(français), accélérée par GPU, avec identification des locuteurs.
Windows 10, Windows 11 et Ubuntu (22.04, 24.04).

La transcription est calculée sur la machine : aucun audio n'est envoyé à un
service d'IA. Seuls les enregistrements envoyés depuis l'iPhone transitent,
chiffrés, par le relais de l'équipe, qui les supprime dès leur récupération.

---

## Installer l'application

Prérequis : **carte graphique NVIDIA** (pilote ≥ 570), ~14 Go d'espace disque.

| Système | Télécharger | Lancer |
|---|---|---|
| Windows 10 / 11 | [**Transcriptions-Setup.exe**](https://github.com/olivierharo/app-transcriptions/releases/latest/download/Transcriptions-Setup.exe) | double-clic |
| Ubuntu 22.04 / 24.04 | [**Transcriptions-Setup-Ubuntu**](https://github.com/olivierharo/app-transcriptions/releases/latest/download/Transcriptions-Setup-Ubuntu) | clic droit › Propriétés › *Autoriser l'exécution*, puis double-clic |

> **« Windows a protégé votre ordinateur » ?** L'installateur n'est pas signé
> numériquement : cliquer sur **Informations complémentaires**, puis
> **Exécuter quand même**.

Un assistant graphique, identique sur les deux systèmes, guide l'installation
**sans droits administrateur** (sous Ubuntu, seuls les paquets système manquants
demandent le mot de passe, via la fenêtre standard) :

1. **Bienvenue** — vérifie la carte NVIDIA et son pilote. Sans carte NVIDIA :
   « Pas de bras, pas de chocolat ! », avant tout téléchargement ;
2. **Emplacement** — dossier et espace disque disponible ;
3. **Séparation des voix** — token Hugging Face, facultatif ;
4. **Installation** — progression détaillée (Go téléchargés, étapes, journal
   consultable) : Python 3.12 si besoin, PyTorch, WhisperX (~9 Go), modèles
   d'IA (~3,5 Go) ;
5. **Terminé** — cases à cocher : menu Démarrer / menu des applications,
   Bureau, lancer l'application.

Relancer l'installateur met l'application à jour sans retélécharger ce qui est
déjà présent. Désinstallation : « Applications installées » sous Windows,
« Désinstaller Transcriptions » dans le menu des applications sous Ubuntu ; les
enregistrements sont conservés.

### Publier une nouvelle version

1. Mettre à jour `__version__` dans `src/app/__init__.py` (ex. `1.1.0`) et commiter.
2. Pousser le tag correspondant :

```bat
git tag v1.1.0
git push origin v1.1.0
```

Le workflow `.github/workflows/release.yml` construit alors l'installateur sur
une machine Windows et sur une machine Ubuntu 22.04, puis crée la release avec
les deux fichiers. Il refuse de publier si le tag ne correspond pas à
`__version__`.

Construire l'installateur en local (pour le système courant) :

```bat
.venv-whisperx\Scripts\python.exe installation\construire_installateur.py
```

→ `dist\Transcriptions-Setup.exe` (Windows) ou `dist/Transcriptions-Setup-Ubuntu`.

---

## L'application

Fenêtre native Qt. Elle couvre tout le cycle :

- **vérifier la carte graphique** au lancement (~5 s) : sans GPU NVIDIA
  utilisable, l'application est remplacée par un écran « Pas de bras, pas de
  chocolat ! » qui explique pourquoi ; avec GPU, son nom s'affiche en bas à droite ;
- **enregistrer** directement, au format natif de Whisper (WAV 16 kHz mono) ;
- **choisir le dossier** de travail (bouton « Changer… ») ;
- **lister** les enregistrements avec durée et état ;
- **renommer** — les fichiers sont réellement renommés sur le disque ;
- **transcrire** d'un clic, en tâche de fond, avec progression en direct ;
- **lire** le dialogue : un tiret marque chaque changement de locuteur.

```
- Tu passes demain soir ?

- Oui.

- Bon, super.
```

Les locuteurs ne sont volontairement **pas nommés** : la diarisation se trompe
parfois sur *qui* parle, bien plus rarement sur le fait que *quelqu'un d'autre*
parle. En mode micro seul, un mot isolé attribué à l'autre voix au milieu d'une
phrase est rattaché à la phrase, pour éviter un tiret parasite ; une réplique
brève ponctuée (« Oui. ») est conservée.

### Deux modes de capture

| Situation | Mode | Identification des locuteurs |
|---|---|---|
| Téléphone en haut-parleur, rendez-vous physique | **Micro seul** | diarisation pyannote — bonne, mais imparfaite |
| Appel Teams / Zoom / navigateur | **Micro + son du PC** | **exacte** : une piste par personne, sans IA |

Le second mode enregistre deux fichiers (`…moi.wav`, `…correspondant.wav`) :
boucle WASAPI sous Windows, source « monitor » PulseAudio/PipeWire sous Ubuntu
(via `parec`). Chaque piste ne contenant qu'une voix, l'attribution est certaine.

### Envoyer depuis l'iPhone

L'iPhone dépose ses enregistrements dans une **boîte aux lettres** sur le relais
de l'équipe (serveur `serveur/`, en HTTPS). L'application relève la boîte toutes
les 30 s, range les fichiers dans le dossier des enregistrements, les supprime du
serveur, puis les transcrit.

- **Partout** : Wi-Fi, 4G/5G, adresse fixe. Le PC peut être éteint au moment de
  l'envoi : le fichier attend (7 jours au plus). Rien à ouvrir sur la box.
- **Première fois** : bouton **« 📱 iPhone »** → coller le *code de connexion*
  (`TR1-…`) fourni par l'administrateur → l'application affiche un QR code à
  scanner avec l'iPhone.
- **Sur l'iPhone** : la page peut **enregistrer directement** (bouton ● REC,
  écran maintenu allumé), envoyer un fichier, et explique les deux **raccourcis
  iPhone** (*Envoyer à Transcriptions* depuis le Dictaphone, *Enregistrer un
  appel* sur l'écran d'accueil). Pour un appel téléphonique, passer par le
  Dictaphone : Safari coupe l'enregistrement quand on change d'application.
- **Sécurité** : deux clés par personne. La clé d'*envoi* (iPhone) ne permet que
  de déposer ; seule la clé de *retrait* (PC) permet de lire. Le serveur ne garde
  que leurs empreintes SHA-256, et ne journalise ni les URL ni les clés.

---

## État du projet

**Validé de bout en bout** : capture 16 kHz mono, capture deux pistes,
transcription `large-v3` sur GPU, alignement au mot, diarisation, fusion en
dialogue, interface, renommage, choix du dossier, exécutable.

**Reste à faire :**

1. Tester la capture audio sur un **vrai poste Ubuntu** (micro et son du PC).
2. Éventuellement : export Word/PDF, suppression depuis l'interface
   (`Bibliotheque.supprimer` existe mais n'est pas câblée à un bouton).

---

## Qualité de l'identification des locuteurs

Mesuré sur une conversation téléphonique réelle de 29 min (mono) :

| Indicateur | Résultat |
|---|---|
| Tours produits | 128 |
| Attribution sur les échanges normaux | correcte |
| Attribution sur répliques brèves | **défaillante par endroits** |

**Limite constatée, non corrigeable côté logiciel.** Sur certains passages,
pyannote fusionne les deux voix : là où l'interlocuteur répond réellement par
une réplique brève, le modèle ne lui attribue que 0,1 à 0,4 seconde.
Vérifié en inspectant directement la sortie de diarisation — ce n'est pas un
défaut du regroupement, l'information n'existe pas en amont.

C'est inhérent à un enregistrement **mono** où les deux voix transitent par le
même canal. Le mode deux pistes est la seule réponse fiable.

---

## Installation pour le développement

### Application complète

WhisperX ne supporte pas Python 3.14 : l'application tourne sur **3.12**.

```bat
py -3.12 -m venv .venv-whisperx
.venv-whisperx\Scripts\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
.venv-whisperx\Scripts\python.exe -m pip install -r requirements-app.txt
```

> Installez `torch` **avant** `requirements-app.txt`, sinon pyannote tire la
> version CPU depuis PyPI et l'accélération GPU est perdue.

> Le téléchargement de PyTorch fait 3,4 Go. Si la connexion coupe les transferts
> longs, `pip` reste bloqué à zéro sans jamais expirer. Préférer alors `curl`
> avec reprise (`-C -`) sur `https://download-r2.pytorch.org/whl/cu128/…`, puis
> `pip install` sur le fichier local.

### Chaîne légère, sans interface (optionnel)

faster-whisper seul, compatible Python 3.14, sans PyTorch :

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## Configuration

### Licences Hugging Face (mode micro seul uniquement)

Il faut un compte Hugging Face et **accepter les conditions des trois modèles** :

- [`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0)
- [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) ← **indispensable**

Le troisième est le piège : `pyannote.audio` 4.x va chercher ses fichiers dans
`community-1` **même si l'on demande explicitement `speaker-diarization-3.1`**.
Accepter les deux premiers ne suffit pas.

Créer ensuite un token *Read* sur https://huggingface.co/settings/tokens, puis
le stocker **sans le faire transiter ailleurs** :

```bat
setx HF_TOKEN "hf_xxxxx"
```

Le code le lit via `HF_TOKEN`, avec repli sur l'environnement utilisateur du
registre (`setx` n'atteint pas les processus déjà lancés). Il peut aussi être
placé dans un fichier `.env` (jamais versionné) — voir `.env.example`.

Le mode deux pistes ne nécessite ni compte ni token.

### Dossier des enregistrements

Il se choisit **dans l'application** (bouton « Changer… »). Le choix est mémorisé
dans `%APPDATA%\Transcriptions\parametres.json`, donc il survit aux
reconstructions de l'exécutable.

Priorité : choix fait dans l'application, puis `DOSSIER_ENREGISTREMENTS` (`.env`
ou variable d'environnement), puis `Documents\Enregistrements audio` de
l'utilisateur **qui lance l'application**. Le dossier Documents est demandé à
Windows, donc correct même s'il est redirigé vers OneDrive. Un dossier mémorisé
devenu inaccessible (lecteur réseau, clé USB) est ignoré au démarrage.

---

## Outils en ligne de commande

```bat
:: transcription simple (chaîne légère, sans locuteurs)
.venv\Scripts\python.exe src\transcrire.py "mon_audio.m4a"

:: surveillance d'un dossier : rattrape le retard puis traite les nouveaux
.venv\Scripts\python.exe src\surveiller.py

:: moteur complet : transcription + alignement + locuteurs
cd src && ..\.venv-whisperx\Scripts\python.exe -m app.moteur "audio.wav"

:: mode deux pistes
cd src && ..\.venv-whisperx\Scripts\python.exe -m app.moteur "appel.moi.wav" --correspondant "appel.correspondant.wav"
```

---

## Construire l'exécutable

```bat
.venv-whisperx\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
  --name Transcriptions --paths src --distpath dist --workpath build/pyinstaller --specpath build ^
  --icon "%CD%\src\app\icone.ico" --add-data "%CD%\src\app\icone.ico;app" ^
  --exclude-module torch --exclude-module whisperx --exclude-module transformers ^
  --exclude-module matplotlib --exclude-module pandas --exclude-module scipy ^
  lanceur.py
```

Puis copier `dist\Transcriptions.exe` **à la racine du projet** : l'application y
cherche `src\` et `.venv-whisperx\`.

L'exécutable (~82 Mo) n'embarque **pas** PyTorch : le moteur tournant en
sous-processus, il utilise l'environnement Python installé.

> Fermer l'application avant de reconstruire : sinon la copie échoue
> silencieusement (fichier verrouillé) et l'ancien exe reste en place.

---

## Structure

```
installation/
├── construire_installateur.py   produit dist\Transcriptions-Setup(.exe|-Ubuntu)
└── installateur/
    ├── lanceur.py               point d'entrée (installation / --desinstaller)
    ├── assistant.py             assistant graphique PySide6
    └── operations.py            GPU, Python, pip, modèles, raccourcis, registre
.github/workflows/release.yml    construit et publie les installateurs à chaque tag
Transcriptions.exe      l'application pour ce poste de développement (PyInstaller)
lanceur.py              point d'entrée pour PyInstaller
local/                  données personnelles, jamais versionnées
src/
├── config.py           .env, préférences, chemins (aucun secret dans le code)
├── transcrire.py       transcription simple (faster-whisper)
├── surveiller.py       surveillance d'un dossier
└── app/
    ├── __main__.py     point d'entrée en développement (python -m app)
    ├── fenetre.py      interface PySide6
    ├── icone.ico       icône de l'application (fenêtre, barre des tâches, exe)
    ├── enregistreur.py capture 16 kHz mono, une ou deux pistes
    ├── bibliotheque.py index des enregistrements, renommage disque
    ├── moteur.py       WhisperX en sous-processus, progression en JSON
    ├── relais.py       relève de la boîte aux lettres iPhone sur le serveur
    └── prechargement.py  téléchargement des modèles pendant l'installation
```

Le moteur tourne dans un **processus séparé** : l'interface ne gèle jamais et un
plantage GPU ne fait pas tomber l'application.

---

## Relais iPhone (serveur)

Dossier `serveur/` : Python (bibliothèque standard uniquement) derrière Caddy,
qui fournit le HTTPS (certificat Let's Encrypt automatique).

**Déploiement sur un VPS** (Docker installé, ports 80 et 443 ouverts) :

1. Chez le registrar, créer un enregistrement DNS **A** :
   `transcriptions.mondomaine.fr` → adresse IP du VPS.
2. Sur le VPS :

   ```bash
   git clone https://github.com/olivierharo/app-transcriptions.git
   cd app-transcriptions/serveur
   cp .env.exemple .env          # puis y mettre DOMAINE=transcriptions.mondomaine.fr
   docker compose up -d --build
   ```

3. Créer un compte par membre de l'équipe ; la commande affiche son code de
   connexion `TR1-…`, à lui transmettre par un canal sûr :

   ```bash
   docker compose exec relais python admin.py creer olivier
   docker compose exec relais python admin.py lister
   docker compose exec relais python admin.py supprimer olivier
   ```

   `creer` sur un compte existant renouvelle ses clés (en cas de perte ou de fuite).

4. Mise à jour : `git pull && docker compose up -d --build`.

Réglages (variables d'environnement du service `relais`) : `RELAIS_TAILLE_MAX_MO`
(2048), `RELAIS_QUOTA_MO` par boîte (5120), `RELAIS_CONSERVATION_JOURS` (7).

---

## Performances constatées

Conversation de 29 min, RTX 3070 laptop (8 Go) :

| Configuration | Durée | Vitesse |
|---|---|---|
| `medium`, CPU (int8) | 21 min | 1,4× temps réel |
| `large-v3`, GPU (float16) | 3 min | 9,5× temps réel |

`large-v3` corrige de vraies erreurs de sens (mots confondus, passages rendus
en bouillie phonétique par `medium`).

La chaîne complète (transcription + alignement + diarisation) prend environ
8 min pour 29 min d'audio.

---

## Pièges rencontrés

Chacun a coûté du temps ; ils sont documentés pour ne pas y retomber.

- **`cublas64_12.dll is not found or cannot be loaded`**
  Deux causes cumulées : `nvidia-cuda-runtime-cu12` manquait (`cublas` dépend de
  `cudart`), et CTranslate2 charge ses DLL via `LoadLibrary` à l'exécution — ce
  qui **ignore `os.add_dll_directory`**. `src/transcrire.py` préfixe donc aussi
  le `PATH` avec les dossiers `nvidia/*/bin`.

- **WhisperX « impossible à installer »** — faux diagnostic.
  `No matching distribution found for ctranslate2==4.4.0` ne vient pas de
  WhisperX mais de pip, qui se rabat sur une version archaïque faute de support
  de Python 3.14. Sur 3.12, WhisperX 3.8+ s'installe et utilise `ctranslate2` 4.8.

- **`WinError 2` sur `whisperx.load_audio()`** — c'est `ffmpeg` qui manque, pas
  l'audio. WhisperX l'appelle en sous-processus. Contourné par un décodage PyAV
  (`app/moteur.py:charger_audio`), utilisé aussi pour la diarisation.

- **`sounddevice` ne sait pas faire de loopback.** Sa classe `WasapiSettings`
  n'expose que `exclusive` / `auto_convert` / `explicit_sample_format`. La
  capture du son du PC passe par **PyAudioWPatch**. Et seuls les périphériques
  **WASAPI** conviennent — proposer un périphérique MME ou DirectSound échoue.

- **Le loopback ne délivre rien pendant les silences.** Sans rattrapage, les
  silences de l'interlocuteur disparaissent et sa piste se désynchronise du
  micro **sans limite**. `_PisteLoopback._combler()` comble en s'appuyant sur
  l'horloge ; l'écart reste borné à ~0,15 s.

- **Attribution des locuteurs : au mot, pas au segment.** Attribuer par segment
  revient à voter à la majorité : une réplique brève tombant dans un long
  segment est absorbée par le bavard.

- **`model_info()` réussit sur un dépôt sous licence non acceptée** — faux
  positif qui masque le problème. Seul `hf_hub_download()` est probant.

- Un fichier en cours d'écriture est attendu (taille stable) avant traitement.

- Si le périphérique refuse 16 kHz, on enregistre à sa fréquence native puis on
  rééchantillonne avec PyAV plutôt que de laisser le pilote bricoler.

---

## Confidentialité

Les enregistrements et leurs transcriptions sont des **données personnelles**
(conversations client). Le `.gitignore` exclut les fichiers audio, les
transcriptions, les journaux, le dossier `local/`, le `.env` et les artefacts de
build. **Vérifier `git status` avant tout commit.**

---

## Licence

[MIT](LICENSE) — libre d'utilisation, de modification et de redistribution,
sans garantie.
