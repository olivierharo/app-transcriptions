# app-transcriptions

Application locale d'enregistrement et de transcription de conversations (français),
accélérée par GPU, avec identification des locuteurs.

Tout est calculé sur la machine : aucun audio n'est envoyé sur Internet.

## L'application

Une fenêtre native qui couvre tout le cycle :

- **enregistrer** directement, au format idéal pour Whisper (WAV 16 kHz mono) ;
- **lister** les enregistrements avec leur durée et leur état ;
- **transcrire** d'un clic, en tâche de fond, avec progression en direct ;
- **lire** la transcription attribuée (`Olivier : … / Christian : …`).

```bat
Transcriptions.exe
```

Fenetre native Qt, demarrage en ~2,5 s.

### Deux modes de capture

| Situation | Mode | Identification des locuteurs |
|---|---|---|
| Téléphone en haut-parleur, rendez-vous physique | **Micro seul** | diarisation pyannote (via WhisperX) |
| Appel Teams / Zoom / navigateur | **Micro + son du PC** | **exacte** : une piste par personne, sans IA |

Le second mode enregistre deux fichiers séparés (`…moi.wav`, `…correspondant.wav`)
grâce à la boucle WASAPI. Chaque piste ne contenant qu'une voix, l'attribution
est certaine — pas d'erreur possible sur les chevauchements.

## Installation

### Application complète (recommandé)

WhisperX ne supporte pas encore Python 3.14 : l'application tourne donc sur **3.12**.

```bat
py -3.12 -m venv .venv-whisperx
.venv-whisperx\Scripts\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
.venv-whisperx\Scripts\python.exe -m pip install -r requirements-app.txt
```

> Installez `torch` **avant** `requirements-app.txt`, sinon pyannote tire la
> version CPU de PyTorch depuis PyPI et l'accélération GPU est perdue.

### Transcription simple, sans interface (optionnel)

Chaîne légère fondée sur faster-whisper, compatible Python 3.14, sans PyTorch :

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configuration

```bat
copy .env.example .env
```

Pour la diarisation (mode micro seul), il faut un compte Hugging Face, accepter
les conditions de [`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0)
et [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1),
puis créer un token *Read* et le renseigner dans `.env`. Le mode deux pistes
n'en a pas besoin.

## Outils en ligne de commande

```bat
:: transcription d'un fichier (chaîne légère)
.venv\Scripts\python.exe src\transcrire.py "mon_audio.m4a"

:: surveillance d'un dossier : rattrape le retard puis traite les nouveaux fichiers
.venv\Scripts\python.exe src\surveiller.py

:: transcription + locuteurs (moteur de l'application)
cd src && ..\.venv-whisperx\Scripts\python.exe -m app.moteur "audio.wav" --noms "Olivier,Christian"
```

## Construire l'executable

```bat
.venv-whisperx\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
  --name Transcriptions --paths src --distpath dist --workpath build/pyinstaller --specpath build ^
  --exclude-module torch --exclude-module whisperx --exclude-module transformers ^
  --exclude-module matplotlib --exclude-module pandas --exclude-module scipy ^
  lanceur.py
```

Puis copier `dist\Transcriptions.exe` **a la racine du projet** : l'application
y cherche `src\` et `.venv-whisperx\`.

L'executable (~82 Mo) n'embarque **pas** PyTorch : le moteur de transcription
etant lance en sous-processus, il utilise l'environnement Python installe.
C'est ce qui garde l'.exe leger et rapide a reconstruire.

## Structure

```
Transcriptions.exe      l'application (genere par PyInstaller)
lanceur.py              point d'entree pour PyInstaller
src/
├── config.py           lecture du .env, chemins (aucun secret dans le code)
├── transcrire.py       transcription simple (faster-whisper)
├── surveiller.py       surveillance d'un dossier
└── app/
    ├── __main__.py     point d'entree en developpement (python -m app)
    ├── fenetre.py      interface PySide6
    ├── enregistreur.py capture audio 16 kHz mono, mono ou deux pistes
    ├── bibliotheque.py index des enregistrements et de leur état
    └── moteur.py       WhisperX en sous-processus, progression en JSON
```

Le moteur tourne dans un **processus séparé** : l'interface ne gèle jamais et un
plantage GPU ne fait pas tomber l'application.

## Performances constatées

Conversation de 29 min, RTX 3070 laptop (8 Go) :

| Configuration | Durée | Vitesse |
|---|---|---|
| `medium`, CPU (int8) | 21 min | 1,4× temps réel |
| `large-v3`, GPU (float16) | 3 min | 9,5× temps réel |

`large-v3` corrige aussi de vraies erreurs de sens : « plateau repas » au lieu de
« plat de repas », « on écaille » au lieu d'une bouillie phonétique.

## Pièges rencontrés

- **`RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`**
  Deux causes cumulées : le paquet `nvidia-cuda-runtime-cu12` manquait (`cublas`
  dépend de `cudart`), et CTranslate2 charge ses DLL via `LoadLibrary` à
  l'exécution — ce qui **ignore `os.add_dll_directory`**. `src/transcrire.py`
  préfixe donc aussi le `PATH` avec les dossiers `nvidia/*/bin`.
- **WhisperX « impossible à installer »** : faux diagnostic. L'erreur
  `No matching distribution found for ctranslate2==4.4.0` ne vient pas de
  WhisperX lui-même, mais de pip qui se rabat sur une version très ancienne
  faute de support de Python 3.14. Sur Python 3.12, WhisperX 3.8+ s'installe
  normalement et utilise `ctranslate2` 4.8.
- Un fichier encore en cours d'écriture est attendu (taille stable) avant
  traitement, pour ne pas transcrire un enregistrement incomplet.
- Si le périphérique refuse 16 kHz, on enregistre à sa fréquence native puis on
  rééchantillonne avec PyAV plutôt que de laisser le pilote bricoler la conversion.

## Confidentialité

Les enregistrements et leurs transcriptions sont des **données personnelles**.
Le `.gitignore` exclut les fichiers audio, les transcriptions, les journaux, le
dossier `local/` et le fichier `.env`. Vérifiez `git status` avant tout commit.
