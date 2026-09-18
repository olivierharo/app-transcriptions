"""Interface de l'application (PySide6)."""
import os
import sys
import json

from PySide6.QtCore import Qt, QTimer, QProcess, QProcessEnvironment, QUrl, QObject, Signal
from PySide6.QtGui import QDesktopServices, QFont, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QGroupBox, QSplitter, QHeaderView, QMessageBox,
    QAbstractItemView, QInputDialog, QFileDialog, QStackedWidget, QDialog, QCheckBox,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from app import enregistreur as enr
from app.bibliotheque import Bibliotheque, formater_duree, formater_date
from app import relais as rl

LIBELLES_ETAT = {
    "nouveau": "Non transcrit",
    "en_attente": "En attente…",
    "en_cours": "Transcription…",
    "termine": "Transcrit",
    "erreur": "Erreur",
}
COULEURS_ETAT = {
    "nouveau": "#6b7280", "en_attente": "#b45309",
    "en_cours": "#1d4ed8", "termine": "#15803d", "erreur": "#b91c1c",
}



def _racine():
    """Racine du projet : dossier de l'.exe si gele, sinon parent de src/."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _python_moteur():
    """Interpreteur qui execute le moteur de transcription.

    Une fois l'application gelee par PyInstaller, sys.executable designe
    l'.exe lui-meme : il faut pointer explicitement vers l'environnement
    Python qui contient WhisperX.
    """
    if not getattr(sys, "frozen", False):
        # Lancee par un raccourci via pythonw.exe (sans console) : le moteur,
        # lui, a besoin de python.exe pour ecrire sa progression.
        dossier, nom = os.path.split(sys.executable)
        if nom.lower() == "pythonw.exe":
            return os.path.join(dossier, "python.exe")
        return sys.executable
    if sys.platform == "win32":
        candidat = os.path.join(_racine(), ".venv-whisperx", "Scripts", "python.exe")
    else:
        candidat = os.path.join(_racine(), ".venv-whisperx", "bin", "python")
    if os.path.exists(candidat):
        return candidat
    return os.environ.get("PYTHON_MOTEUR") or "python"


def _environnement_moteur():
    """Environnement du sous-processus moteur.

    Sous Linux, CTranslate2 (Whisper) cherche cuBLAS/cuDNN via le chargeur
    systeme : les bibliotheques installees par pip dans nvidia/*/lib doivent
    figurer dans LD_LIBRARY_PATH, sinon la transcription echoue sur GPU.
    """
    env = QProcessEnvironment.systemEnvironment()
    if sys.platform.startswith("linux"):
        import glob
        python = _python_moteur()
        venv = os.path.dirname(os.path.dirname(python))
        libs = glob.glob(os.path.join(venv, "lib", "python3*", "site-packages",
                                      "nvidia", "*", "lib"))
        if libs:
            existant = env.value("LD_LIBRARY_PATH", "")
            env.insert("LD_LIBRARY_PATH", os.pathsep.join(libs + ([existant] if existant else [])))
    env.insert("PYTHONIOENCODING", "utf-8")
    return env


class Fenetre(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transcriptions")
        self.resize(1150, 760)

        self.dossier = config.dossier_enregistrements()
        self.biblio = Bibliotheque(self.dossier)
        self.enregistreur = enr.Enregistreur(self.dossier)

        self.proc = None          # QProcess du moteur
        self.ident_en_cours = None
        self.file_attente = []

        # Boite aux lettres iPhone : relevee dans un fil secondaire, les
        # signaux ramenent fichiers et etat dans le fil de l'interface.
        self.pont = _Pont()
        self.pont.fichier_recu.connect(self._fichier_recu)
        self.pont.statut.connect(self._statut_relais)
        self.relais = rl.Relais(self.dossier, self.pont.fichier_recu.emit, self.pont.statut.emit)
        self.dialogue_iphone = None

        self._construire()
        self._charger_peripheriques()
        self.rafraichir()

        self.chrono = QTimer(self)
        self.chrono.timeout.connect(self._tic_enregistrement)
        self.chrono.setInterval(200)

    # ------------------------------------------------------------------ UI --
    def _construire(self):
        # Trois ecrans : verification du GPU au lancement, application
        # normale, ou message bloquant si la transcription est impossible.
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.page_attente = self._page_message(
            "", "Vérification de la carte graphique…",
            "Quelques secondes, le temps de charger le moteur de transcription.")
        self.pages.addWidget(self.page_attente)

        central = QWidget()
        self.page_principale = central
        self.pages.addWidget(central)
        principal = QVBoxLayout(central)
        principal.setContentsMargins(12, 12, 12, 12)
        principal.setSpacing(10)

        principal.addWidget(self._barre_dossier())
        principal.addWidget(self._bloc_enregistrement())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._bloc_liste())
        split.addWidget(self._bloc_lecture())
        split.setSizes([560, 560])
        principal.addWidget(split, 1)

        self.statut = self.statusBar()
        self.statut.showMessage(f"Dossier : {self.dossier}")
        self.label_reception = QLabel()
        self.label_reception.setContentsMargins(8, 0, 8, 0)
        self.label_reception.hide()
        self.statut.addPermanentWidget(self.label_reception)
        self.label_gpu = QLabel()
        self.label_gpu.setContentsMargins(8, 0, 8, 0)
        self.statut.addPermanentWidget(self.label_gpu)
        self._detecter_gpu()

    # ------------------------------------------------------------------ GPU --
    def _page_message(self, emoji, titre, texte, detail=""):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(60, 40, 60, 40)
        v.addStretch(2)
        # Couleurs lisibles en theme clair comme sombre : bleu moyen pour le
        # titre, couleur du theme pour le reste.
        for contenu, taille, gras, couleur in ((emoji, 64, False, None),
                                               (titre, 26, True, "#3b82f6"),
                                               (texte, 12, False, None),
                                               (detail, 9, False, "#9ca3af")):
            if not contenu:
                continue
            l = QLabel(contenu)
            l.setAlignment(Qt.AlignCenter)
            l.setWordWrap(True)
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f = QFont(); f.setPointSize(taille); f.setBold(gras)
            l.setFont(f)
            if couleur:
                l.setStyleSheet(f"color:{couleur};")
            v.addWidget(l)
            v.addSpacing(12)
        v.addStretch(3)
        return page

    def _bloquer(self, page):
        """Remplace toute l'application par un message."""
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        self.statut.hide()

    def _afficher_gpu(self, texte, couleur, detail):
        self.label_gpu.setText(f"<span style='color:{couleur}'>●</span> {texte}")
        self.label_gpu.setToolTip(detail)

    def _detecter_gpu(self):
        """Interroge le moteur en tache de fond : charger PyTorch prend
        quelques secondes, pendant lesquelles un ecran d'attente s'affiche."""
        self.pages.setCurrentWidget(self.page_attente)
        self.proc_gpu = QProcess(self)
        self.proc_gpu.setWorkingDirectory(os.path.join(_racine(), "src"))
        self.proc_gpu.setProcessEnvironment(_environnement_moteur())
        self.proc_gpu.finished.connect(self._gpu_detecte)
        self.proc_gpu.errorOccurred.connect(self._gpu_erreur)
        self.proc_gpu.start(_python_moteur(), ["-m", "app.moteur", "--diagnostic"])

    def _moteur_absent(self, detail):
        self._bloquer(self._page_message(
            "🔧", "Installation incomplète",
            "Le moteur de transcription est introuvable ou ne démarre pas.\n"
            "Relancez l'installateur de l'application.", detail))

    def _gpu_erreur(self, _erreur):
        if self.proc_gpu.error() == QProcess.FailedToStart:
            self._moteur_absent("Environnement Python introuvable : " + _python_moteur())

    def _gpu_detecte(self, code, _statut):
        brut = bytes(self.proc_gpu.readAllStandardOutput()).decode("utf-8", "replace")
        for ligne in brut.splitlines():
            try:
                diag = json.loads(ligne).get("diagnostic")
            except (json.JSONDecodeError, AttributeError):
                continue
            if not diag:
                continue
            if diag.get("gpu"):
                self._afficher_gpu("GPU : " + diag.get("nom", ""), "#15803d",
                                   "Transcription accélérée par la carte graphique ("
                                   + diag.get("detail", "") + ").")
                self.pages.setCurrentWidget(self.page_principale)
                self.relais.demarrer()
            else:
                self._bloquer(self._page_message(
                    "🤷 🍫", "Pas de bras, pas de chocolat !",
                    "Pas de carte graphique NVIDIA, pas de transcription.\n\n"
                    "Cette application fait tourner de gros modèles d'intelligence "
                    "artificielle directement sur votre ordinateur, pour qu'aucune "
                    "conversation ne quitte la machine. Sans carte graphique NVIDIA, "
                    "transcrire une heure d'appel prendrait plusieurs heures : "
                    "l'application n'est donc pas utilisable sur ce poste.",
                    "Raison technique : " + diag.get("detail", "") + "."))
            return
        erreur = bytes(self.proc_gpu.readAllStandardError()).decode("utf-8", "replace")
        self._moteur_absent(erreur[-400:] or f"code de sortie {code}")

    def _barre_dossier(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Dossier des enregistrements :"))
        self.label_dossier = QLabel(self.dossier)
        self.label_dossier.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label_dossier.setStyleSheet("color:#374151; font-weight:bold;")
        h.addWidget(self.label_dossier, 1)
        b = QPushButton("Changer…")
        b.clicked.connect(self._changer_dossier)
        h.addWidget(b)
        return w

    def _changer_dossier(self):
        if self.enregistreur.en_cours:
            QMessageBox.information(self, "Dossier",
                                    "Enregistrement en cours : arretez-le d'abord.")
            return
        if self.proc is not None or self.file_attente:
            QMessageBox.information(self, "Dossier",
                                    "Transcription en cours : attendez la fin.")
            return
        choisi = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier des enregistrements", self.dossier)
        if not choisi:
            return
        choisi = os.path.abspath(choisi)
        if choisi == os.path.abspath(self.dossier):
            return
        try:
            config.definir_dossier_enregistrements(choisi)
            self.dossier = choisi
            self.biblio = Bibliotheque(choisi)
            self.enregistreur = enr.Enregistreur(choisi)
            self.relais.dossier = choisi
        except Exception as ex:
            QMessageBox.critical(self, "Dossier inutilisable", str(ex))
            return
        self.label_dossier.setText(choisi)
        self.vue.clear()
        self.rafraichir()
        self.statut.showMessage("Dossier : " + choisi, 8000)

    def _bloc_enregistrement(self):
        boite = QGroupBox("Nouvel enregistrement")
        g = QGridLayout(boite)
        g.setHorizontalSpacing(10)

        g.addWidget(QLabel("Situation :"), 0, 0)
        self.mode = QComboBox()
        self.mode.addItem("Micro seul  (téléphone en haut-parleur, rendez-vous)", "micro")
        self.mode.addItem("Micro + son du PC  (Teams, Zoom, navigateur)", "micro+systeme")
        self.mode.currentIndexChanged.connect(self._maj_mode)
        g.addWidget(self.mode, 0, 1, 1, 3)

        g.addWidget(QLabel("Micro :"), 1, 0)
        self.combo_micro = QComboBox()
        g.addWidget(self.combo_micro, 1, 1, 1, 3)

        self.label_sortie = QLabel("Son du PC :")
        g.addWidget(self.label_sortie, 2, 0)
        self.combo_sortie = QComboBox()
        g.addWidget(self.combo_sortie, 2, 1, 1, 3)

        g.addWidget(QLabel("Titre :"), 3, 0)
        self.champ_titre = QLineEdit()
        self.champ_titre.setPlaceholderText("facultatif — ex. « Réunion projet – devis »")
        g.addWidget(self.champ_titre, 3, 1)

        self.bouton_rec = QPushButton("● Démarrer l'enregistrement")
        self.bouton_rec.setMinimumHeight(38)
        self.bouton_rec.clicked.connect(self._basculer_enregistrement)
        g.addWidget(self.bouton_rec, 3, 2)

        self.label_chrono = QLabel("0:00")
        f = QFont(); f.setPointSize(16); f.setBold(True)
        self.label_chrono.setFont(f)
        self.label_chrono.setAlignment(Qt.AlignCenter)
        self.label_chrono.setMinimumWidth(90)
        g.addWidget(self.label_chrono, 3, 3)

        self.vumetre = QProgressBar()
        self.vumetre.setRange(0, 100)
        self.vumetre.setTextVisible(False)
        self.vumetre.setMaximumHeight(8)
        g.addWidget(self.vumetre, 4, 0, 1, 4)

        self._maj_mode()
        return boite

    def _bloc_liste(self):
        boite = QGroupBox("Enregistrements")
        v = QVBoxLayout(boite)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Titre", "Date", "Durée", "État"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changee)
        e = self.table.horizontalHeader()
        e.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            e.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        v.addWidget(self.table)

        self.barre = QProgressBar()
        self.barre.setVisible(False)
        v.addWidget(self.barre)

        h = QHBoxLayout()
        self.bouton_transcrire = QPushButton("Transcrire")
        self.bouton_transcrire.clicked.connect(self._transcrire_selection)
        self.bouton_renommer = QPushButton("Renommer")
        self.bouton_renommer.clicked.connect(self._renommer)
        self.bouton_dossier = QPushButton("Ouvrir le dossier")
        self.bouton_dossier.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dossier)))
        self.bouton_iphone = QPushButton("📱 iPhone")
        self.bouton_iphone.clicked.connect(self._ouvrir_iphone)
        for b in (self.bouton_transcrire, self.bouton_renommer, self.bouton_dossier, self.bouton_iphone):
            h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        return boite

    def _bloc_lecture(self):
        boite = QGroupBox("Transcription")
        v = QVBoxLayout(boite)
        self.vue = QTextEdit()
        self.vue.setReadOnly(True)
        self.vue.setPlaceholderText(
            "Sélectionnez un enregistrement pour lire sa transcription.")
        police = QFont("Segoe UI", 11)
        self.vue.setFont(police)
        v.addWidget(self.vue)
        return boite

    # ------------------------------------------------------- peripheriques --
    def _charger_peripheriques(self):
        self.combo_micro.clear()
        for d in enr.peripheriques_entree():
            self.combo_micro.addItem(f"{d['nom']}", d["id"])
        defaut = enr.peripherique_defaut_entree()
        if defaut is not None:
            i = self.combo_micro.findData(defaut)
            if i >= 0:
                self.combo_micro.setCurrentIndex(i)

        self.combo_sortie.clear()
        for d in enr.peripheriques_sortie():
            self.combo_sortie.addItem(f"{d['nom']}", d["id"])
        defaut = enr.peripherique_defaut_sortie()
        if defaut is not None:
            i = self.combo_sortie.findData(defaut)
            if i >= 0:
                self.combo_sortie.setCurrentIndex(i)

    def _maj_mode(self):
        deux = self.mode.currentData() == "micro+systeme"
        self.combo_sortie.setEnabled(deux)
        self.label_sortie.setEnabled(deux)

    # -------------------------------------------------------- enregistrement --
    def _basculer_enregistrement(self):
        if self.enregistreur.en_cours:
            self._arreter_enregistrement()
        else:
            self._demarrer_enregistrement()

    def _demarrer_enregistrement(self):
        micro = self.combo_micro.currentData()
        if micro is None:
            QMessageBox.warning(self, "Micro", "Aucun micro disponible.")
            return
        systeme = self.combo_sortie.currentData() if self.mode.currentData() == "micro+systeme" else None
        try:
            self.enregistreur.demarrer(micro, systeme, self.champ_titre.text())
        except Exception as e:
            QMessageBox.critical(self, "Enregistrement impossible", str(e))
            return
        self.bouton_rec.setText("■ Arrêter")
        self.bouton_rec.setStyleSheet("background:#b91c1c; color:white; font-weight:bold;")
        self.mode.setEnabled(False)
        self.combo_micro.setEnabled(False)
        self.combo_sortie.setEnabled(False)
        self.chrono.start()

    def _arreter_enregistrement(self):
        self.chrono.stop()
        try:
            self.enregistreur.arreter()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))
        self.bouton_rec.setText("● Démarrer l'enregistrement")
        self.bouton_rec.setStyleSheet("")
        self.mode.setEnabled(True)
        self.combo_micro.setEnabled(True)
        self._maj_mode()
        self.label_chrono.setText("0:00")
        self.vumetre.setValue(0)
        self.champ_titre.clear()
        self.rafraichir()
        self.statut.showMessage("Enregistrement terminé.", 4000)

    def _tic_enregistrement(self):
        self.label_chrono.setText(formater_duree(self.enregistreur.duree))
        niveaux = self.enregistreur.niveaux
        if niveaux:
            self.vumetre.setValue(int(min(1.0, max(niveaux) * 6) * 100))

    # ----------------------------------------------------------------- liste --
    def rafraichir(self):
        self.biblio.synchroniser()
        entrees = self.biblio.liste()
        self.table.setRowCount(len(entrees))
        for r, e in enumerate(entrees):
            # On affiche le NOM DE FICHIER reel : c'est ce qu'on retrouve
            # en ouvrant le dossier.
            fichiers = e.get("fichiers", {})
            principal = fichiers.get("mono") or fichiers.get("micro")
            if e.get("deux_canaux"):
                titre = e["id"] + "  ⟨2 pistes⟩"
            else:
                titre = os.path.basename(principal) if principal else e["id"]
            items = [
                QTableWidgetItem(titre),
                QTableWidgetItem(formater_date(e.get("date"))),
                QTableWidgetItem(formater_duree(e.get("duree"))),
                QTableWidgetItem(self._libelle_etat(e)),
            ]
            items[0].setData(Qt.UserRole, e["id"])
            items[3].setForeground(QColor(COULEURS_ETAT.get(e.get("etat"), "#6b7280")))
            for c, it in enumerate(items):
                self.table.setItem(r, c, it)

    def _libelle_etat(self, e):
        etat = e.get("etat", "nouveau")
        if etat == "en_cours":
            return f"Transcription… {e.get('progression', 0)} %"
        return LIBELLES_ETAT.get(etat, etat)

    def _ident_selectionne(self):
        lignes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not lignes:
            return None
        item = self.table.item(lignes[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _selection_changee(self):
        ident = self._ident_selectionne()
        if not ident:
            return
        e = self.biblio.get(ident)
        chemin = e.get("transcription") if e else None
        if chemin and os.path.exists(chemin):
            try:
                with open(chemin, encoding="utf-8") as f:
                    self.vue.setPlainText(f.read())
            except Exception as ex:
                self.vue.setPlainText(f"Lecture impossible : {ex}")
        elif e and e.get("etat") == "erreur":
            self.vue.setPlainText("Échec de la transcription :\n\n" + (e.get("erreur") or ""))
        else:
            self.vue.setPlainText("")
            self.vue.setPlaceholderText("Pas encore transcrit. Cliquez sur « Transcrire ».")

    def _selectionner(self, ident):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.data(Qt.UserRole) == ident:
                self.table.selectRow(r)
                return

    def _renommer(self):
        ident = self._ident_selectionne()
        if not ident:
            return
        if ident == self.ident_en_cours or ident in self.file_attente:
            QMessageBox.information(
                self, "Renommer",
                "Transcription en cours sur cet enregistrement : attendez la fin.")
            return
        nom, ok = QInputDialog.getText(
            self, "Renommer",
            "Nom du fichier (sans extension). Les fichiers seront renommes sur le disque :", text=ident)
        if not ok:
            return
        try:
            nouveau = self.biblio.renommer(ident, nom)
        except ValueError as ex:
            QMessageBox.warning(self, "Renommage impossible", str(ex))
            return
        self.rafraichir()
        self._selectionner(nouveau)
        self.statut.showMessage(f"Fichiers renommes en « {nouveau} »", 6000)

    # ---------------------------------------------------------- transcription --
    def _transcrire_selection(self):
        ident = self._ident_selectionne()
        if not ident:
            QMessageBox.information(self, "Transcription",
                                    "Sélectionnez d'abord un enregistrement.")
            return
        self._mettre_en_file(ident)

    def _mettre_en_file(self, ident):
        if ident in self.file_attente or ident == self.ident_en_cours:
            return
        self.file_attente.append(ident)
        self.biblio.definir_etat(ident, "en_attente")
        self.rafraichir()
        self._traiter_file()

    def _traiter_file(self):
        if self.proc is not None or not self.file_attente:
            return
        ident = self.file_attente.pop(0)
        e = self.biblio.get(ident)
        if not e:
            return self._traiter_file()

        fichiers = e.get("fichiers", {})
        principal = fichiers.get("mono") or fichiers.get("micro")
        correspondant = fichiers.get("correspondant")

        args = ["-m", "app.moteur", principal]
        if correspondant:
            args += ["--correspondant", correspondant]
        args += ["--sortie", os.path.join(self.dossier, e["id"] + ".dialogue.txt")]

        self.ident_en_cours = ident
        self.biblio.definir_etat(ident, "en_cours", progression=0)
        self.rafraichir()
        self.barre.setVisible(True)
        self.barre.setValue(0)

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(os.path.join(_racine(), "src"))
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.proc.setProcessEnvironment(_environnement_moteur())
        self.proc.readyReadStandardOutput.connect(self._sortie_moteur)
        self.proc.finished.connect(self._moteur_termine)
        self.proc.start(_python_moteur(), args)

    def _sortie_moteur(self):
        if not self.proc:
            return
        brut = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for ligne in brut.splitlines():
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                ev = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if "progression" in ev:
                pct = int(ev["progression"])
                self.barre.setValue(pct)
                if self.ident_en_cours:
                    self.biblio.definir_etat(self.ident_en_cours, "en_cours", progression=pct)
                    self.rafraichir()
                self.statut.showMessage(f"{ev.get('etape', '')} — {ev.get('message', '')}")
            elif ev.get("fini"):
                self.biblio.definir_etat(self.ident_en_cours, "termine",
                                         transcription=ev.get("sortie"))
            elif "erreur" in ev:
                self.biblio.definir_etat(self.ident_en_cours, "erreur", erreur=ev["erreur"])

    def _moteur_termine(self, code, _statut):
        e = self.biblio.get(self.ident_en_cours) if self.ident_en_cours else None
        if e and e.get("etat") == "en_cours":
            detail = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")[-600:]
            self.biblio.definir_etat(self.ident_en_cours, "erreur",
                                     erreur=detail or f"arrêt inattendu (code {code})")
        self.proc = None
        self.ident_en_cours = None
        self.barre.setVisible(False)
        self.rafraichir()
        self._selection_changee()
        self._traiter_file()

    # ---------------------------------------------------------------- sortie --
    def closeEvent(self, ev):
        if self.enregistreur.en_cours:
            r = QMessageBox.question(self, "Enregistrement en cours",
                                     "Arrêter l'enregistrement et quitter ?")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
            self.enregistreur.arreter()
        if self.proc is not None:
            self.proc.kill()
        self.relais.arreter()
        ev.accept()

    # ------------------------------------------------------------- iPhone --
    def _ouvrir_iphone(self):
        d = DialogueIphone(self)
        self.dialogue_iphone = d
        d.exec()
        self.dialogue_iphone = None

    def _statut_relais(self, texte, ok):
        if not self.relais.configure:
            self.label_reception.hide()
            return
        self.label_reception.setText("📱 Boîte iPhone" + ("" if ok else " ⚠"))
        self.label_reception.setToolTip(texte)
        self.label_reception.show()
        if self.dialogue_iphone:
            self.dialogue_iphone.afficher_statut(texte, ok)

    def _fichier_recu(self, chemin):
        ident = os.path.splitext(os.path.basename(chemin))[0]
        self.rafraichir()
        self._selectionner(ident)
        self.statut.showMessage(f"Reçu depuis l'iPhone : {os.path.basename(chemin)}", 10000)
        if self.dialogue_iphone:
            self.dialogue_iphone.signaler(os.path.basename(chemin))
        if config.lire_parametres().get("reception_auto", True):
            self._mettre_en_file(ident)


class _Pont(QObject):
    fichier_recu = Signal(str)
    statut = Signal(str, bool)


class DialogueIphone(QDialog):
    """Connexion a la boite aux lettres, et QR code a scanner avec l'iPhone."""

    def __init__(self, fenetre):
        super().__init__(fenetre)
        self.fenetre = fenetre
        self.relais = fenetre.relais
        self.setWindowTitle("Envoyer depuis l'iPhone")
        self.setMinimumWidth(660)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(20, 18, 20, 16)
        self._construire()

    def _vider(self):
        while self.v.count():
            item = self.v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _vider_layout(item.layout())

    def _construire(self):
        self._vider()
        if self.relais.configure:
            self._page_connecte()
        else:
            self._page_connexion()

    # --------------------------------------------------- pas encore connecte --
    def _page_connexion(self):
        titre = QLabel("Recevoir les enregistrements de votre iPhone")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        titre.setFont(f)
        self.v.addWidget(titre)
        texte = QLabel(
            "Votre iPhone dépose ses enregistrements dans une <b>boîte aux lettres</b> sur le serveur "
            "de l'équipe, où que vous soyez (Wi-Fi, 4G). L'application les récupère et les transcrit, "
            "même si l'ordinateur était éteint au moment de l'envoi.<br><br>"
            "Collez ci-dessous le <b>code de connexion</b> (il commence par <code>TR1-</code>) "
            "fourni par l'administrateur du serveur.")
        texte.setWordWrap(True)
        texte.setTextFormat(Qt.RichText)
        self.v.addWidget(texte)
        self.champ_code = QLineEdit()
        self.champ_code.setPlaceholderText("TR1-…")
        self.v.addWidget(self.champ_code)
        self.erreur = QLabel()
        self.erreur.setWordWrap(True)
        self.erreur.setStyleSheet("color:#dc2626;")
        self.v.addWidget(self.erreur)
        bas = QHBoxLayout()
        bas.addStretch()
        annuler = QPushButton("Fermer")
        annuler.clicked.connect(self.reject)
        connecter = QPushButton("Se connecter")
        connecter.setDefault(True)
        connecter.clicked.connect(self._connecter)
        bas.addWidget(annuler)
        bas.addWidget(connecter)
        self.v.addLayout(bas)

    def _connecter(self):
        self.erreur.setText("Vérification auprès du serveur…")
        QApplication.processEvents()
        try:
            self.relais.connecter(self.champ_code.text())
        except rl.ErreurRelais as e:
            self.erreur.setText(str(e))
            return
        self.relais.demarrer()
        self._construire()

    # ------------------------------------------------------------- connecte --
    def _page_connecte(self):
        import io
        import segno
        r = self.relais.reglages()
        haut = QHBoxLayout()
        qr = QLabel()
        qr.setFixedSize(236, 236)
        qr.setAlignment(Qt.AlignCenter)
        qr.setStyleSheet("background:white; border-radius:8px;")
        tampon = io.BytesIO()
        segno.make(self.relais.url_iphone(), error="m").save(tampon, kind="png", scale=6, border=2)
        pix = QPixmap()
        pix.loadFromData(tampon.getvalue(), "PNG")
        qr.setPixmap(pix.scaled(228, 228, Qt.KeepAspectRatio, Qt.FastTransformation))
        haut.addWidget(qr)
        haut.addSpacing(16)
        droite = QVBoxLayout()
        titre = QLabel(f"Boîte de {r['relais_nom']}")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        titre.setFont(f)
        droite.addWidget(titre)
        serveur = QLabel(r["relais_url"].replace("https://", ""))
        serveur.setStyleSheet("color:#9ca3af;")
        droite.addWidget(serveur)
        etapes = QLabel(
            "1. Scannez ce QR code avec l'<b>Appareil photo</b> de l'iPhone.<br>"
            "2. Dans Safari : <b>Partager › Sur l'écran d'accueil</b>.<br>"
            "3. Enregistrez depuis cette page (bouton ● REC), ou envoyez vos mémos du "
            "Dictaphone avec les <b>raccourcis iPhone</b> décrits sur la page.<br><br>"
            "Ça marche partout (Wi-Fi, 4G) : les enregistrements arrivent ici et se transcrivent.")
        etapes.setWordWrap(True)
        etapes.setTextFormat(Qt.RichText)
        droite.addWidget(etapes)
        droite.addStretch()
        haut.addLayout(droite, 1)
        self.v.addLayout(haut)

        self.label_statut = QLabel(self.fenetre.label_reception.toolTip() or "Relève en cours…")
        self.label_statut.setWordWrap(True)
        self.v.addWidget(self.label_statut)
        self.recus = QLabel()
        self.recus.setStyleSheet("color:#15803d; font-weight:bold;")
        self.v.addWidget(self.recus)

        case_auto = QCheckBox("Transcrire automatiquement les enregistrements reçus")
        case_auto.setChecked(config.lire_parametres().get("reception_auto", True))
        case_auto.toggled.connect(lambda on: config.ecrire_parametre("reception_auto", on))
        self.v.addWidget(case_auto)
        note = QLabel("🔒 Connexion chiffrée (HTTPS). Les fichiers ne restent sur le serveur que le temps "
                      "d'être récupérés, puis en sont supprimés (au plus tard après 7 jours).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9ca3af;")
        self.v.addWidget(note)

        bas = QHBoxLayout()
        deconnecter = QPushButton("Se déconnecter…")
        deconnecter.clicked.connect(self._deconnecter)
        relever = QPushButton("Relever maintenant")
        relever.clicked.connect(self.relais.relever_maintenant)
        fermer = QPushButton("Fermer")
        fermer.setDefault(True)
        fermer.clicked.connect(self.accept)
        bas.addWidget(deconnecter)
        bas.addStretch()
        bas.addWidget(relever)
        bas.addWidget(fermer)
        self.v.addLayout(bas)
        self.relais.relever_maintenant()

    def _deconnecter(self):
        r = QMessageBox.question(self, "Se déconnecter",
                                 "Cet ordinateur ne relèvera plus la boîte iPhone. Il faudra le code de "
                                 "connexion pour la reconnecter. Continuer ?")
        if r == QMessageBox.Yes:
            self.relais.deconnecter()
            self.fenetre.label_reception.hide()
            self._construire()

    def afficher_statut(self, texte, ok):
        if getattr(self, "label_statut", None) is not None:
            try:
                self.label_statut.setText(texte)
                self.label_statut.setStyleSheet("" if ok else "color:#dc2626;")
            except RuntimeError:          # widget detruit entre-temps
                pass

    def signaler(self, nom):
        if getattr(self, "recus", None) is not None:
            try:
                self.recus.setText("✓ Reçu : " + nom)
            except RuntimeError:
                pass


def _vider_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _vider_layout(item.layout())


def _chemin_icone():
    """icone.ico, a cote de ce module ou extrait par PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "app", "icone.ico")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icone.ico")


def _identifiant_windows():
    """Donne a l'application sa propre identite dans la barre des taches.

    Sans cela, lancee via python.exe, Windows la range sous l'icone de
    Python au lieu d'afficher la sienne.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "OlivierHaro.Transcriptions")
    except Exception:
        pass


def lancer():
    _identifiant_windows()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Transcriptions")
    app.setDesktopFileName("transcriptions")    # Linux : lie la fenetre au .desktop
    app.setWindowIcon(QIcon(_chemin_icone()))
    f = Fenetre()
    f.show()
    sys.exit(app.exec())
