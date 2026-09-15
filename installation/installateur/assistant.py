"""
Assistant graphique d'installation et de desinstallation (PySide6).

Meme apparence sous Windows et Ubuntu : bandeau lateral bleu aux couleurs de
l'icone, pages successives, progression detaillee pendant les
telechargements, choix des raccourcis a la fin.
"""
import os
import sys
import time

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPalette, QPixmap, QPainter, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

import operations as op

BLEU = "#1d4ed8"
BLEU_FONCE = "#1e3a8a"
VERT = "#15803d"
ROUGE = "#b91c1c"
GRIS = "#6b7280"


def chemin_ressource(nom):
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "ressources", nom)
    return os.path.join(op.dossier_charge(), "src", "app", nom)


def _coche():
    """Dessine la coche blanche des cases a cocher dans un fichier temporaire :
    une feuille de style Qt ne sait afficher une image que depuis un fichier."""
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    pix = QPixmap(32, 32)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("white"), 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(7, 17), QPointF(13, 23), QPointF(25, 9)])
    p.end()
    chemin = os.path.join(tempfile.gettempdir(), "transcriptions-coche.png")
    pix.save(chemin)
    return chemin.replace("\\", "/")


def appliquer_theme(app):
    """Theme clair impose : l'assistant garde la meme allure quel que soit le
    theme du systeme (et reste lisible, les couleurs etant choisies pour lui)."""
    app.setStyle("Fusion")
    p = QPalette()
    for role, couleur in ((QPalette.Window, "#ffffff"), (QPalette.WindowText, "#111827"),
                          (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f3f4f6"),
                          (QPalette.Text, "#111827"), (QPalette.Button, "#f3f4f6"),
                          (QPalette.ButtonText, "#111827"), (QPalette.Highlight, BLEU),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#9ca3af"),
                          (QPalette.ToolTipBase, "#ffffff"), (QPalette.ToolTipText, "#111827"),
                          (QPalette.Link, BLEU)):
        p.setColor(role, QColor(couleur))
    app.setPalette(p)
    app.setStyleSheet(f"""
        QPushButton {{ padding: 7px 18px; border-radius: 6px; border: 1px solid #d1d5db; background: #ffffff; }}
        QPushButton:hover {{ background: #f3f4f6; }}
        QPushButton:disabled {{ color: #9ca3af; }}
        QPushButton#principal {{ background: {BLEU}; color: white; border: 1px solid {BLEU}; font-weight: bold; }}
        QPushButton#principal:hover {{ background: {BLEU_FONCE}; }}
        QPushButton#principal:disabled {{ background: #93c5fd; border-color: #93c5fd; }}
        QLineEdit {{ padding: 6px; border: 1px solid #d1d5db; border-radius: 6px; }}
        QLineEdit:focus {{ border-color: {BLEU}; }}
        QProgressBar {{ border: none; background: #e5e7eb; border-radius: 6px; height: 12px; text-align: center; }}
        QProgressBar::chunk {{ background: {BLEU}; border-radius: 6px; }}
        QPlainTextEdit {{ background: #111827; color: #d1d5db; border-radius: 6px;
                          font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; }}
        QCheckBox {{ spacing: 10px; font-size: 11pt; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid #9ca3af; border-radius: 4px;
                                background: #ffffff; }}
        QCheckBox::indicator:checked {{ background: {BLEU}; border-color: {BLEU}; image: url("{_coche()}"); }}
    """)


def label(texte, taille=10, gras=False, couleur=None, riche=False):
    l = QLabel(texte)
    l.setWordWrap(True)
    f = QFont()
    f.setPointSize(taille)
    f.setBold(gras)
    l.setFont(f)
    if couleur:
        l.setStyleSheet(f"color:{couleur};")
    if riche:
        l.setTextFormat(Qt.RichText)
        l.setOpenExternalLinks(True)
    return l


class Bandeau(QWidget):
    """Colonne de gauche : icone, nom, liste des etapes de l'assistant."""

    def __init__(self, titres):
        super().__init__()
        self.setFixedWidth(220)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 30, 18, 24)
        icone = QLabel()
        icone.setPixmap(QPixmap(chemin_ressource("icone.png")).scaled(
            72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        v.addWidget(icone)
        v.addSpacing(8)
        v.addWidget(label("Transcriptions", 16, True, "white"))
        version = op.version_application()
        v.addWidget(label(f"Version {version}" if version else "", 9, False, "#bfdbfe"))
        v.addSpacing(26)
        self.titres = []
        for t in titres:
            l = label(t, 10, False, "#bfdbfe")
            self.titres.append(l)
            v.addWidget(l)
            v.addSpacing(6)
        v.addStretch()

    def activer(self, index):
        for i, l in enumerate(self.titres):
            if i < index:
                l.setText("✓  " + l.text().lstrip("✓• "))
                l.setStyleSheet("color:#bfdbfe;")
            elif i == index:
                l.setText("•  " + l.text().lstrip("✓• "))
                l.setStyleSheet("color:white; font-weight:bold;")
            else:
                l.setText("    " + l.text().lstrip("✓• "))
                l.setStyleSheet("color:#93c5fd;")

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#2563eb"))
        g.setColorAt(1, QColor(BLEU_FONCE))
        p.fillRect(self.rect(), g)


class Page(QWidget):
    def __init__(self, titre, sous_titre=""):
        super().__init__()
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(36, 32, 36, 16)
        self.v.addWidget(label(titre, 18, True, BLEU_FONCE))
        if sous_titre:
            self.v.addSpacing(4)
            self.v.addWidget(label(sous_titre, 10, False, GRIS))
        self.v.addSpacing(18)


class FilInstallation(QThread):
    etape = Signal(int, str)
    progression = Signal(float, str)
    journal = Signal(str)
    fini = Signal(bool, str, str)          # succes, message, detail

    def __init__(self, destination, token):
        super().__init__()
        self.installation = op.Installation(
            destination, token, etape=self.etape.emit,
            progression=self.progression.emit, journal=self.journal.emit)

    def run(self):
        try:
            self.installation.executer()
            self.fini.emit(True, "", "")
        except op.Annule:
            self.fini.emit(False, "Installation annulée.", "")
        except op.ErreurInstallation as e:
            self.fini.emit(False, str(e), e.detail)
        except Exception as e:
            import traceback
            self.fini.emit(False, f"Erreur inattendue : {e}", traceback.format_exc())


# --------------------------------------------------------------------------- #
class AssistantInstallation(QWidget):
    TITRES = ["Bienvenue", "Emplacement", "Séparation des voix", "Installation", "Terminé"]

    def __init__(self, auto=False, destination=None):
        super().__init__()
        self.auto = auto
        self.setWindowTitle("Installation de Transcriptions")
        self.setWindowIcon(QIcon(chemin_ressource("icone.png")))
        self.setFixedSize(820, 560)
        self.fil = None
        self.gpu = None

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.bandeau = Bandeau(self.TITRES)
        h.addWidget(self.bandeau)
        droite = QVBoxLayout()
        droite.setContentsMargins(0, 0, 0, 0)
        h.addLayout(droite, 1)

        self.pages = QStackedWidget()
        droite.addWidget(self.pages, 1)

        barre = QHBoxLayout()
        barre.setContentsMargins(36, 10, 28, 22)
        self.bouton_annuler = QPushButton("Annuler")
        self.bouton_precedent = QPushButton("Précédent")
        self.bouton_suivant = QPushButton("Suivant")
        self.bouton_suivant.setObjectName("principal")
        barre.addWidget(self.bouton_annuler)
        barre.addStretch()
        barre.addWidget(self.bouton_precedent)
        barre.addWidget(self.bouton_suivant)
        droite.addLayout(barre)

        self.bouton_annuler.clicked.connect(self.close)
        self.bouton_precedent.clicked.connect(self._precedent)
        self.bouton_suivant.clicked.connect(self._suivant)

        self._page_bienvenue()
        self._page_emplacement(destination or op.destination_par_defaut())
        self._page_token()
        self._page_progression()
        self._page_fin()
        self._aller(0)
        QTimer.singleShot(50, self._verifier_gpu)

    # ------------------------------------------------------------ pages --
    def _page_bienvenue(self):
        p = Page("Bienvenue", "Cet assistant installe Transcriptions sur votre ordinateur.")
        p.v.addWidget(label(
            "Transcriptions enregistre vos appels et rendez-vous, puis les transcrit en texte. "
            "Tout est calculé sur votre ordinateur : aucune conversation n'est envoyée sur Internet.", 11))
        p.v.addSpacing(14)
        p.v.addWidget(label(
            "L'installation télécharge le moteur d'intelligence artificielle et ses modèles "
            "(environ 13 Go). Comptez de 15 à 45 minutes selon votre connexion ; "
            "vous pourrez continuer à utiliser l'ordinateur pendant ce temps.", 11))
        p.v.addSpacing(22)
        self.label_gpu = label("Vérification de la carte graphique…", 11, False, GRIS)
        p.v.addWidget(self.label_gpu)
        p.v.addStretch()
        p.v.addWidget(label(
            'Logiciel libre sous <a href="https://github.com/olivierharo/app-transcriptions/blob/main/LICENSE">'
            "licence MIT</a>, fourni sans garantie.", 9, False, GRIS, riche=True))
        self.pages.addWidget(p)

    def _page_emplacement(self, destination):
        p = Page("Emplacement", "Où installer l'application ?")
        ligne = QHBoxLayout()
        self.champ_dest = QLineEdit(destination)
        self.champ_dest.textChanged.connect(self._maj_espace)
        parcourir = QPushButton("Parcourir…")
        parcourir.clicked.connect(self._parcourir)
        ligne.addWidget(self.champ_dest, 1)
        ligne.addWidget(parcourir)
        p.v.addLayout(ligne)
        p.v.addSpacing(12)
        self.label_espace = label("", 10)
        p.v.addWidget(self.label_espace)
        p.v.addSpacing(8)
        self.label_maj = label("", 10, False, BLEU)
        p.v.addWidget(self.label_maj)
        p.v.addStretch()
        p.v.addWidget(label("Aucun droit administrateur n'est nécessaire : l'application est installée "
                            "pour votre compte uniquement. Vos enregistrements seront rangés dans "
                            "Documents › Enregistrements audio.", 9, False, GRIS))
        self.pages.addWidget(p)

    def _page_token(self):
        p = Page("Séparation des voix", "Facultatif — vous pourrez le faire plus tard.")
        p.v.addWidget(label(
            "Le mode <b>« Micro seul »</b> (téléphone en haut-parleur, rendez-vous) sépare les voix "
            "grâce à des modèles gratuits hébergés sur Hugging Face, qui demandent un <b>token</b> "
            "d'accès personnel.<br><br>"
            "Le mode <b>« Micro + son du PC »</b> (Teams, Zoom…) n'en a pas besoin.", 11, riche=True))
        p.v.addSpacing(14)
        p.v.addWidget(label(
            f'1. Créez un compte puis un token de type <i>Read</i> sur <a href="{op.LIEN_TOKEN}">'
            "huggingface.co/settings/tokens</a><br>"
            '2. Acceptez les conditions de <a href="https://huggingface.co/pyannote/speaker-diarization-community-1">'
            'speaker-diarization-community-1</a>, <a href="https://huggingface.co/pyannote/speaker-diarization-3.1">'
            'speaker-diarization-3.1</a> et <a href="https://huggingface.co/pyannote/segmentation-3.0">'
            "segmentation-3.0</a>", 10, riche=True))
        p.v.addSpacing(14)
        ligne = QHBoxLayout()
        self.champ_token = QLineEdit()
        self.champ_token.setEchoMode(QLineEdit.Password)
        self.champ_token.setPlaceholderText("hf_…  (laisser vide pour passer)")
        voir = QPushButton("Afficher")
        voir.setCheckable(True)
        voir.toggled.connect(lambda on: self.champ_token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        ligne.addWidget(self.champ_token, 1)
        ligne.addWidget(voir)
        p.v.addLayout(ligne)
        self.label_token = label("", 9, False, VERT)
        p.v.addWidget(self.label_token)
        p.v.addStretch()
        p.v.addWidget(label("Le token reste sur votre ordinateur, dans le dossier d'installation.",
                            9, False, GRIS))
        self.pages.addWidget(p)

    def _page_progression(self):
        p = Page("Installation en cours", "Vous pouvez réduire cette fenêtre, l'installation continue.")
        self.label_etape = label("Préparation…", 12, True)
        p.v.addWidget(self.label_etape)
        p.v.addSpacing(6)
        ligne = QHBoxLayout()
        self.barre = QProgressBar()
        self.barre.setRange(0, 1000)
        self.barre.setTextVisible(False)
        self.label_pourcent = label("0 %", 11, True, BLEU)
        self.label_pourcent.setFixedWidth(52)
        self.label_pourcent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ligne.addWidget(self.barre, 1)
        ligne.addWidget(self.label_pourcent)
        p.v.addLayout(ligne)
        self.label_detail = label("", 10, False, GRIS)
        p.v.addWidget(self.label_detail)
        p.v.addSpacing(12)

        self.etapes = []
        for _, libelle, _ in op.ETAPES:
            l = label("○   " + libelle, 10, False, GRIS)
            self.etapes.append(l)
            p.v.addWidget(l)
        p.v.addSpacing(8)

        bas = QHBoxLayout()
        self.label_temps = label("", 9, False, GRIS)
        self.bouton_details = QPushButton("Afficher les détails")
        self.bouton_details.setCheckable(True)
        bas.addWidget(self.label_temps, 1)
        bas.addWidget(self.bouton_details)
        p.v.addLayout(bas)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setMaximumBlockCount(3000)
        self.journal.setVisible(False)
        self.bouton_details.toggled.connect(self._basculer_details)
        p.v.addWidget(self.journal, 1)
        p.v.addStretch()
        self.pages.addWidget(p)

    def _page_fin(self):
        self.page_fin = Page("Installation terminée", "Transcriptions est prête à l'emploi.")
        self.label_fin = label("", 11)
        self.page_fin.v.addWidget(self.label_fin)
        self.page_fin.v.addSpacing(18)
        systeme = "menu Démarrer" if op.WINDOWS else "menu des applications"
        self.case_menu = QCheckBox(f"Ajouter au {systeme}")
        self.case_bureau = QCheckBox("Créer un raccourci sur le Bureau")
        self.case_lancer = QCheckBox("Lancer Transcriptions maintenant")
        for c in (self.case_menu, self.case_bureau, self.case_lancer):
            c.setChecked(True)
            self.page_fin.v.addWidget(c)
            self.page_fin.v.addSpacing(6)
        self.page_fin.v.addStretch()
        self.label_desinstaller = label("", 9, False, GRIS)
        self.page_fin.v.addWidget(self.label_desinstaller)
        self.pages.addWidget(self.page_fin)

    # ------------------------------------------------------- navigation --
    def _aller(self, index):
        self.pages.setCurrentIndex(index)
        self.bandeau.activer(index)
        self.bouton_precedent.setVisible(index in (1, 2))
        self.bouton_annuler.setVisible(index < 4)
        self.bouton_suivant.setVisible(index != 3)
        self.bouton_suivant.setEnabled(True)
        self.bouton_suivant.setText({2: "Installer", 3: "Installer", 4: "Terminer"}.get(index, "Suivant"))
        if index == 0:
            self.bouton_suivant.setEnabled(self.gpu is not None)
        elif index == 1:
            self._maj_espace()
        elif index == 2:
            deja = op.token_existant(self.champ_dest.text())
            self.label_token.setText("✓ Un token est déjà configuré sur ce poste : vous pouvez passer."
                                     if deja else "")
        elif index == 3:
            self.bouton_suivant.setEnabled(False)

    def _precedent(self):
        self._aller(self.pages.currentIndex() - 1)

    def _suivant(self):
        i = self.pages.currentIndex()
        if i == 2:
            self._demarrer()
        elif i == 4:
            self._terminer()
        else:
            self._aller(i + 1)

    # ------------------------------------------------------------ logique --
    def _verifier_gpu(self):
        gpu = op.detecter_gpu()
        if gpu is None:
            self._bloquer(
                "🤷 🍫", "Pas de bras, pas de chocolat !",
                "Aucune carte graphique NVIDIA n'a été détectée sur cet ordinateur.",
                "Transcriptions fait tourner de gros modèles d'intelligence artificielle directement "
                "sur votre machine, pour qu'aucune conversation ne quitte l'ordinateur. Sans carte "
                "graphique NVIDIA, transcrire une heure d'appel prendrait plusieurs heures : "
                "l'application n'est donc pas utilisable sur ce poste.<br><br>"
                "Rien n'a été téléchargé ni modifié."
                + ("<br><br>Si l'ordinateur possède bien une carte NVIDIA, installez son pilote "
                   "(<code>sudo ubuntu-drivers install</code>), redémarrez puis relancez l'installateur."
                   if op.LINUX else ""))
            return
        nom, pilote = gpu
        if not op.pilote_suffisant(pilote):
            lien = "https://www.nvidia.com/fr-fr/drivers/"
            self._bloquer(
                "🔧", "Pilote graphique trop ancien",
                f"Carte détectée : {nom}, pilote {pilote}.",
                f"Transcriptions demande le pilote NVIDIA <b>{op.PILOTE_MINIMUM}</b> ou plus récent. "
                + (f'Mettez-le à jour depuis <a href="{lien}">nvidia.com</a>'
                   if op.WINDOWS else "Mettez-le à jour avec <code>sudo ubuntu-drivers install</code>")
                + ", redémarrez, puis relancez l'installateur.")
            return
        self.gpu = gpu
        self.label_gpu.setText(f"✓  Carte graphique compatible : {nom} (pilote {pilote})")
        self.label_gpu.setStyleSheet(f"color:{VERT};")
        self.bouton_suivant.setEnabled(True)
        if self.auto:
            QTimer.singleShot(300, self._demarrer)

    def _bloquer(self, emoji, titre, resume, texte):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(40, 30, 40, 10)
        v.addStretch()
        e = label(emoji, 48)
        e.setAlignment(Qt.AlignCenter)
        v.addWidget(e)
        t = label(titre, 22, True, BLEU_FONCE)
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        v.addSpacing(6)
        r = label(resume, 11, True)
        r.setAlignment(Qt.AlignCenter)
        v.addWidget(r)
        v.addSpacing(12)
        c = label(texte, 10, riche=True)
        c.setAlignment(Qt.AlignCenter)
        v.addWidget(c)
        v.addStretch(2)
        self.pages.addWidget(p)
        self.pages.setCurrentWidget(p)
        self.bouton_precedent.hide()
        self.bouton_suivant.hide()
        self.bouton_annuler.setText("Fermer")
        if self.auto:
            print("BLOQUE:", titre, flush=True)
            QTimer.singleShot(500, lambda: QApplication.exit(2))

    def _parcourir(self):
        choisi = QFileDialog.getExistingDirectory(self, "Dossier d'installation", self.champ_dest.text())
        if choisi:
            self.champ_dest.setText(os.path.join(os.path.normpath(choisi), op.NOM))

    def _maj_espace(self):
        dest = self.champ_dest.text().strip()
        libre = op.espace_libre(dest) if dest else None
        maj = op.deja_installe(dest)
        self.label_maj.setText("Une installation existe déjà ici : elle sera mise à jour, "
                               "sans retélécharger ce qui est déjà présent." if maj else "")
        if libre is None:
            self.label_espace.setText("Emplacement invalide.")
            self.label_espace.setStyleSheet(f"color:{ROUGE};")
            ok = False
        else:
            ok = maj or libre >= op.ESPACE_REQUIS
            self.label_espace.setText(
                f"Espace nécessaire : {op.ESPACE_REQUIS // 1024 ** 3} Go  —  "
                f"disponible : {libre / 1024 ** 3:.0f} Go".replace(".", ",")
                + ("" if ok else "\nEspace insuffisant : libérez de la place ou choisissez un autre disque."))
            self.label_espace.setStyleSheet(f"color:{'#374151' if ok else ROUGE};")
        if self.pages.currentIndex() == 1:
            self.bouton_suivant.setEnabled(ok and bool(dest))

    def _demarrer(self):
        self._aller(3)
        self.debut = time.time()
        self.fil = FilInstallation(self.champ_dest.text().strip(), self.champ_token.text())
        self.fil.etape.connect(self._etape)
        self.fil.progression.connect(self._progression)
        self.fil.journal.connect(self.journal.appendPlainText)
        if self.auto:
            self.fil.journal.connect(lambda l: print(l, flush=True))
            self.fil.etape.connect(lambda i, l: print(f"== ETAPE {i} : {l}", flush=True))
        self.fil.fini.connect(self._fini)
        self.chrono = QTimer(self)
        self.chrono.timeout.connect(self._maj_temps)
        self.chrono.start(1000)
        self.fil.start()

    def _etape(self, index, libelle):
        self.label_etape.setText(libelle)
        for i, l in enumerate(self.etapes):
            nom = op.ETAPES[i][1]
            if i < index:
                l.setText("✓   " + nom)
                l.setStyleSheet(f"color:{VERT};")
            elif i == index:
                l.setText("●   " + nom)
                l.setStyleSheet(f"color:{BLEU}; font-weight:bold;")
            else:
                l.setText("○   " + nom)
                l.setStyleSheet(f"color:{GRIS};")

    def _progression(self, fraction, texte):
        self.barre.setValue(int(fraction * 1000))
        self.label_pourcent.setText(f"{int(fraction * 100)} %")
        if texte:
            self.label_detail.setText(texte)

    def _maj_temps(self):
        s = int(time.time() - self.debut)
        self.label_temps.setText(f"Temps écoulé : {s // 60} min {s % 60:02d} s")

    def _basculer_details(self, visible):
        self.journal.setVisible(visible)
        self.bouton_details.setText("Masquer les détails" if visible else "Afficher les détails")
        for l in self.etapes:
            l.setVisible(not visible)

    def _fini(self, succes, message, detail):
        self.chrono.stop()
        if not succes:
            if self.auto:
                print("ECHEC:", message, detail[-1500:], flush=True)
                QApplication.exit(1)
                return
            self.label_etape.setText("L'installation n'a pas abouti")
            self.label_etape.setStyleSheet(f"color:{ROUGE};")
            self.label_detail.setText(message + "\n\nVous pouvez relancer l'installateur : "
                                      "ce qui a déjà été téléchargé sera conservé.")
            if detail:
                self.journal.appendPlainText("\n" + detail)
                self.bouton_details.setChecked(True)
            self.bouton_annuler.setText("Fermer")
            self.bouton_suivant.hide()
            self.fil = None
            return
        dest = self.champ_dest.text().strip()
        s = int(time.time() - self.debut)
        texte = f"Installation réussie en {s // 60} min."
        avert = self.fil.installation.avertissements
        if avert:
            texte += ("<br><br><span style='color:#b45309'>Certains modèles n'ont pas pu être téléchargés ; "
                      "ils le seront à la première utilisation.</span>")
        self.label_fin.setTextFormat(Qt.RichText)
        self.label_fin.setText(texte)
        self.label_desinstaller.setText(
            "Pour désinstaller : Paramètres › Applications installées › Transcriptions."
            if op.WINDOWS else "Pour désinstaller : « Désinstaller Transcriptions » dans le menu des applications.")
        self.fil = None
        self._aller(4)
        if self.auto:
            print("SUCCES", texte, flush=True)
            self.case_lancer.setChecked(False)
            QTimer.singleShot(300, self._terminer)

    def _terminer(self):
        dest = self.champ_dest.text().strip()
        try:
            op.creer_raccourcis(dest, menu=self.case_menu.isChecked(), bureau=self.case_bureau.isChecked())
            if self.case_lancer.isChecked():
                op.lancer_application(dest)
        except Exception as e:
            QMessageBox.warning(self, "Raccourcis", f"Création des raccourcis incomplète : {e}")
        QApplication.exit(0)

    def closeEvent(self, ev):
        if self.fil is not None and self.fil.isRunning():
            r = QMessageBox.question(self, "Annuler l'installation",
                                     "Interrompre l'installation ?\n\nCe qui a déjà été téléchargé "
                                     "sera conservé pour la prochaine tentative.")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
            self.fil.installation.annuler()
            self.fil.wait(10000)
        ev.accept()
        QApplication.exit(0)


# --------------------------------------------------------------------------- #
class AssistantDesinstallation(QWidget):
    def __init__(self, destination, auto=False):
        super().__init__()
        self.dest = destination
        self.auto = auto
        self.setWindowTitle("Désinstallation de Transcriptions")
        self.setWindowIcon(QIcon(chemin_ressource("icone.png")))
        self.setFixedSize(620, 400)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        bandeau = Bandeau([])
        bandeau.setFixedWidth(170)
        h.addWidget(bandeau)
        v = QVBoxLayout()
        v.setContentsMargins(30, 30, 26, 22)
        h.addLayout(v, 1)
        self.titre = label("Désinstaller Transcriptions ?", 17, True, BLEU_FONCE)
        v.addWidget(self.titre)
        v.addSpacing(10)
        self.texte = label("L'application, ses raccourcis et son environnement (~9 Go) seront supprimés.<br><br>"
                           "<b>Vos enregistrements et transcriptions sont conservés.</b>", 11, riche=True)
        v.addWidget(self.texte)
        v.addSpacing(14)
        self.case_modeles = QCheckBox("Supprimer aussi les modèles d'IA téléchargés (~3,5 Go)")
        v.addWidget(self.case_modeles)
        self.barre = QProgressBar()
        self.barre.setRange(0, 0)
        self.barre.setTextVisible(False)
        self.barre.hide()
        v.addWidget(self.barre)
        v.addStretch()
        bas = QHBoxLayout()
        bas.addStretch()
        self.bouton_non = QPushButton("Annuler")
        self.bouton_oui = QPushButton("Désinstaller")
        self.bouton_oui.setObjectName("principal")
        bas.addWidget(self.bouton_non)
        bas.addWidget(self.bouton_oui)
        v.addLayout(bas)
        self.bouton_non.clicked.connect(lambda: QApplication.exit(0))
        self.bouton_oui.clicked.connect(self._desinstaller)
        if auto:
            QTimer.singleShot(300, self._desinstaller)

    def _desinstaller(self):
        self.bouton_oui.setEnabled(False)
        self.bouton_non.setEnabled(False)
        self.case_modeles.setEnabled(False)
        self.barre.show()
        self.titre.setText("Désinstallation…")
        QApplication.processEvents()
        try:
            restes = op.desinstaller(self.dest, self.case_modeles.isChecked())
            if restes:
                message = "Désinstallation presque terminée. Ce dossier n'a pas pu être supprimé :<br>" + restes[0]
            else:
                message = "Transcriptions a été désinstallée.<br><br>Vos enregistrements sont conservés."
            titre = "C'est fait"
        except op.ErreurInstallation as e:
            titre, message = "Désinstallation impossible", f"{e}<br>{e.detail}"
        self.barre.hide()
        self.case_modeles.hide()
        self.titre.setText(titre)
        self.texte.setText(message)
        self.bouton_non.hide()
        self.bouton_oui.setEnabled(True)
        self.bouton_oui.setText("Fermer")
        self.bouton_oui.clicked.disconnect()
        self.bouton_oui.clicked.connect(lambda: QApplication.exit(0))
        if self.auto:
            print("DESINSTALLATION:", titre, message, flush=True)
            QApplication.exit(0)
