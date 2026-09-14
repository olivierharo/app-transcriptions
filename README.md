# app-transcriptions

Transcription automatique de conversations (français) en local, accélérée par GPU,
avec identification optionnelle des locuteurs.

Déposez un fichier audio dans un dossier surveillé : un fichier `.txt` apparaît à côté.

## Fonctionnement

| Étape | Outil | Sortie |
|---|---|---|
| Transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`large-v3`) | `X.txt`, `X.segments.json` |
| Diarisation *(optionnelle)* | [pyannote.audio](https://github.com/pyannote/pyannote-audio) | `X.speakers.json` |
| Fusion | — | `X.dialogue.txt` (`Olivier : …` / `Christian : …`) |

Aucun audio ne quitte la machine : tout est calculé en local.

## Prérequis

- Windows, Python 3.14 (fonctionne aussi en 3.11/3.12)
- GPU NVIDIA recommandé (testé sur RTX 3070 8 Go)
- Aucun `ffmpeg` à installer : le décodage passe par `av`

## Installation

### 1. Transcription

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Diarisation (optionnelle)

Environnement **séparé** : PyTorch embarque ses propres bibliothèques CUDA, qui
entrent en conflit avec celles de CTranslate2.

```bat
py -m venv .venv-diar
.venv-diar\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
.venv-diar\Scripts\python.exe -m pip install -r requirements-diarisation.txt
```

> Installez `torch` **avant** `requirements-diarisation.txt`, sinon pyannote tire
> la version CPU de PyTorch depuis PyPI et l'accélération GPU est perdue.

### 3. Configuration

```bat
copy .env.example .env
```

Renseignez `.env` (jamais versionné). Pour la diarisation, il faut un compte
Hugging Face, accepter les conditions de
[`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0) et
[`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1),
puis créer un token de type *Read*.

## Utilisation

### Transcription d'un fichier

```bat
.venv\Scripts\python.exe src\transcrire.py "mon_audio.m4a"
```

Options : `--model medium` (plus léger), `--device cpu`, `--lang en`.
Le GPU et le modèle `large-v3` sont choisis automatiquement s'ils sont disponibles.

### Surveillance d'un dossier

Double-cliquez sur **`Surveiller les enregistrements.bat`**, ou :

```bat
.venv\Scripts\python.exe src\surveiller.py
```

Au lancement, tout audio sans `.txt` est transcrit (rattrapage du retard) ; ensuite
les nouveaux fichiers déposés sont traités au fil de l'eau.

### Identification des locuteurs

```bat
.venv-diar\Scripts\python.exe src\diariser.py "mon_audio.m4a" --noms "Olivier,Christian"
```

Les noms sont attribués dans l'ordre d'apparition. Sans `--noms`, les étiquettes
brutes (`SPEAKER_00`…) sont conservées. `--speakers 0` laisse le modèle deviner
le nombre de locuteurs.

## Performances constatées

Conversation téléphonique de 29 min, RTX 3070 laptop :

| Configuration | Durée | Vitesse |
|---|---|---|
| `medium`, CPU (int8) | 21 min | 1,4× temps réel |
| `large-v3`, GPU (float16) | 3 min | 9,5× temps réel |

`large-v3` corrige aussi de vraies erreurs de sens (vocabulaire métier, noms propres).

## Pièges rencontrés

- **`RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`**
  Deux causes cumulées : le paquet `nvidia-cuda-runtime-cu12` manquait (`cublas`
  dépend de `cudart`), et CTranslate2 charge ses DLL via `LoadLibrary` à
  l'exécution — ce qui **ignore `os.add_dll_directory`**. `src/transcrire.py`
  préfixe donc aussi le `PATH` avec les dossiers `nvidia/*/bin`.
- **WhisperX** n'est pas utilisable ici : il épingle `ctranslate2==4.4.0`, sans
  distribution pour Python 3.14. D'où le choix d'ajouter pyannote séparément
  plutôt que de migrer vers WhisperX.
- Un fichier encore en cours d'écriture est attendu (taille stable) avant
  traitement, pour ne pas transcrire un enregistrement incomplet.

## Confidentialité

Les enregistrements et leurs transcriptions sont des **données personnelles**.
Le `.gitignore` exclut les fichiers audio, les transcriptions, les journaux,
le dossier `local/` et le fichier `.env`. Vérifiez `git status` avant tout commit.
