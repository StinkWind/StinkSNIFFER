import os, sys, subprocess, threading
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QStandardPaths, QUrl, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QFontDatabase, QPixmap, QDesktopServices, QColor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QProgressBar, QFileDialog, QMenu, QMessageBox, QInputDialog, QGraphicsOpacityEffect, QScrollArea)
from core import *

class Job(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    def __init__(self, function):
        super().__init__()
        self.function = function
    def run(self):
        try: self.result.emit(self.function())
        except Exception as e: self.failed.emit(str(e))

class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('StinkWind', 'StinkSNIFFER')
        default = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)) / 'StinkSNIFFER')
        self.folder = self.settings.value('folder', default)
        self.source = None
        self.busy = False
        self.jobs = []
        self.animations = []
        self.cancel_event = threading.Event()
        self.storage_generation = 0
        self.estimated = None
        self.setWindowTitle('StinkSNIFFER')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(510, 730)
        self.setMinimumSize(440, 580)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8,8,8,8)
        self.shell = QWidget(objectName='shell')
        outer.addWidget(self.shell)
        layout = QVBoxLayout(self.shell)
        layout.setContentsMargins(22,18,22,18)
        layout.setSpacing(20)
        header = QHBoxLayout()
        header.addWidget(QLabel('>_ STINKSNIFFER / 01', objectName='brand'))
        header.addStretch()
        self.options = QPushButton('≡')
        self.options.setToolTip('Options')
        menu = QMenu(self)
        menu.addAction('Export folder…', self.choose_folder)
        menu.addAction('Open export folder', self.open_folder)
        menu.addAction('Diagnostics', self.open_diagnostics)
        menu.addSeparator()
        menu.addAction('GitHub release repository…', self.set_repo)
        menu.addAction('Check for updates', lambda: self.check_updates(True))
        menu.addAction('About', lambda: QMessageBox.information(self, 'StinkSNIFFER', f'StinkSNIFFER {VERSION}\nLocal HLS capture • native rendition • stream copy\nCascadia Mono / GlassChat'))
        self.options.setMenu(menu)
        header.addWidget(self.options)
        minimize = QPushButton('—'); minimize.clicked.connect(self.showMinimized); header.addWidget(minimize)
        close = QPushButton('×'); close.clicked.connect(self.close); header.addWidget(close)
        layout.addLayout(header)
        self.update_button = QPushButton(''); self.update_button.hide(); self.update_button.clicked.connect(self.show_release)
        layout.addWidget(self.update_button)
        self.status = QLabel('• Local capture  //  ready', objectName='muted')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addWidget(QLabel('SOURCE', objectName='muted'))
        self.input = QLineEdit(); self.input.setPlaceholderText('Kick username / M3U8 URL'); self.input.returnPressed.connect(self.sniff)
        layout.addWidget(self.input)
        self.sniff_button = QPushButton('[ SNIFF ]'); self.sniff_button.clicked.connect(self.sniff)
        layout.addWidget(self.sniff_button, alignment=Qt.AlignmentFlag.AlignRight)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget {background: transparent; border: none;}')
        content = QWidget(); scroll.setWidget(content); body = QVBoxLayout(content); body.setContentsMargins(0,0,0,0); body.setSpacing(16)
        layout.addWidget(scroll, 1)
        self.card = QWidget(); card = QVBoxLayout(self.card); card.setContentsMargins(0,0,0,0); card.setSpacing(12)
        card.addWidget(QLabel('──────── NEW CAPTURE ────────', objectName='faint'), alignment=Qt.AlignmentFlag.AlignCenter)
        self.thumbnail = QLabel('[ preview unavailable ]'); self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); self.thumbnail.setMinimumHeight(160)
        self.thumbnail.setObjectName('thumbnail'); card.addWidget(self.thumbnail)
        self.title = QLabel(); self.title.setWordWrap(True); card.addWidget(self.title)
        self.metadata = QLabel(objectName='muted'); self.metadata.setWordWrap(True); card.addWidget(self.metadata)
        card.addWidget(QLabel('QUALITY', objectName='muted'))
        self.quality = QComboBox(); self.quality.currentIndexChanged.connect(self.select_quality); card.addWidget(self.quality)
        body.addWidget(self.card)
        self.storage_label = QLabel(objectName='muted'); self.storage_label.setWordWrap(True); body.addWidget(self.storage_label); self.storage_label.hide()
        self.save = QPushButton('[ SAVE / EXPORT ]'); self.save.clicked.connect(self.export); body.addWidget(self.save)
        self.capture_panel = QWidget(); progress_layout = QVBoxLayout(self.capture_panel); progress_layout.setContentsMargins(0,0,0,0)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0,1000); self.progress_bar.setTextVisible(False); progress_layout.addWidget(self.progress_bar)
        self.telemetry = QLabel(); self.telemetry.setWordWrap(True); progress_layout.addWidget(self.telemetry)
        self.cancel_button = QPushButton('[ CANCEL ]'); self.cancel_button.clicked.connect(self.cancel_capture); progress_layout.addWidget(self.cancel_button)
        body.addWidget(self.capture_panel)
        self.done = QWidget(); done_layout = QVBoxLayout(self.done); done_layout.setContentsMargins(0,0,0,0)
        self.completed = QLabel(); self.completed.setWordWrap(True); done_layout.addWidget(self.completed)
        actions = QHBoxLayout(); open_btn = QPushButton('Open Folder'); open_btn.clicked.connect(self.open_folder); actions.addWidget(open_btn)
        self.play = QPushButton('Play in VLC'); self.play.clicked.connect(self.play_vlc); actions.addWidget(self.play); done_layout.addLayout(actions); body.addWidget(self.done)
        body.addStretch()
        self.folder_label = QLabel(objectName='faint'); self.folder_label.setWordWrap(True); layout.addWidget(self.folder_label); self.refresh_folder()
        for w in (self.card,self.save,self.capture_panel,self.done,self.storage_label): w.hide()
        self.setStyleSheet('''
            QWidget { color: #dedede; font-size: 13px; }
            QWidget#shell { background: rgba(17,18,20,205); border: 1px solid #3b3b3e; border-radius: 14px; }
            QLabel { background: transparent; border: none; }
            QLabel#brand { font-size: 12px; letter-spacing: 1px; font-weight: bold; }
            QLabel#muted { color: #999; font-size: 11px; }
            QLabel#faint { color: #737373; font-size: 10px; }
            QLabel#thumbnail { border: 1px solid #353538; border-radius: 7px; color:#777; background:rgba(0,0,0,30); }
            QLineEdit, QComboBox { background: rgba(255,255,255,5); border: 1px solid #454548; border-radius: 6px; padding: 10px; selection-background-color:#666; }
            QPushButton { background: rgba(255,255,255,6); border: 1px solid #414144; border-radius: 5px; padding: 7px 10px; }
            QPushButton:hover { background:rgba(255,255,255,17); border-color:#777; }
            QPushButton:disabled { color:#606060; border-color:#303033; }
            QProgressBar { border:1px solid #444; border-radius:3px; height: 9px; background:#222; }
            QProgressBar::chunk { background:#b8b8b8; }
            QMenu, QComboBox QAbstractItemView { background:#202124; color:#dedede; border:1px solid #444; padding:5px; selection-background-color:#444; }
            QScrollBar:vertical { width:5px; background:transparent; } QScrollBar::handle:vertical {background:#444;min-height:20px;}
        ''')
        QTimer.singleShot(1000, self.check_updates)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 65:
            self.windowHandle().startSystemMove()

    def reveal(self, widget):
        widget.show()
        effect = QGraphicsOpacityEffect(widget); widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b'opacity', self); animation.setDuration(240)
        animation.setStartValue(0); animation.setEndValue(1); animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None)); self.animations.append(animation); animation.start()

    def job(self, function, result, failure=None):
        job = Job(function); self.jobs.append(job)
        job.result.connect(result); job.failed.connect(failure or self.error)
        job.finished.connect(lambda: self.jobs.remove(job))
        job.start(); return job

    def error(self, message):
        self.busy = False; self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.quality.setEnabled(True)
        self.cancel_button.setEnabled(True); self.capture_panel.hide()
        self.status.setText('[ error ] ' + message)
        if self.source: self.select_quality()

    def sniff(self):
        if self.busy or not self.input.text().strip(): return
        self.busy = True; self.source = None
        self.input.setEnabled(False); self.sniff_button.setEnabled(False)
        self.storage_generation += 1
        for widget in (self.card,self.save,self.capture_panel,self.done,self.storage_label): widget.hide()
        self.status.setText('[ sniffing ] resolving metadata / inspecting HLS…')
        value = self.input.text()
        self.job(lambda: resolve(value), self.resolved)

    def resolved(self, source):
        self.busy = False; self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.source = source
        self.title.setText(source.title); self.metadata.setText(f'{source.streamer} • {source.date} • {clock(source.duration)}')
        pix = QPixmap(); pix.loadFromData(source.thumbnail)
        if not pix.isNull(): self.thumbnail.setPixmap(pix.scaled(410,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else: self.thumbnail.setText('[ preview unavailable ]')
        self.quality.blockSignals(True); self.quality.clear(); self.quality.addItem('Select quality…', None)
        available = []
        for label,height in [('Small',480),('Medium',720),('Large',1080)]:
            variant = max((v for v in source.variants if v.height == height), key=lambda v:v.bandwidth, default=None)
            self.quality.addItem(f'{label} — {height}p' + (' / unavailable' if not variant else ''), variant)
            self.quality.model().item(self.quality.count()-1).setEnabled(variant is not None)
            if variant: available.append(self.quality.count()-1)
        if not available:
            for v in sorted(source.variants,key=lambda v:v.height):
                self.quality.addItem(f'Native — {v.height}p',v); available.append(self.quality.count()-1)
        self.quality.setCurrentIndex(0); self.quality.blockSignals(False)
        self.status.setText(f'[ source confirmed ] {len(source.variants)} native renditions')
        self.reveal(self.card)

    def select_quality(self):
        self.storage_generation += 1
        generation = self.storage_generation
        self.save.hide(); self.estimated = None
        variant = self.quality.currentData()
        if not variant or self.busy:
            self.storage_label.hide(); return
        self.storage_label.setText('[ storage ] estimating rendition size…'); self.reveal(self.storage_label)
        source, folder = self.source, self.folder
        def success(storage):
            if generation != self.storage_generation: return
            self.estimated = storage['estimated']
            if storage['sufficient']:
                self.storage_label.setText(f"Estimated size: ~{storage['estimated']/1024**3:.1f} GB\nFree space: {storage['free']/1024**3:.1f} GB")
                self.reveal(self.save)
            else:
                self.storage_label.setText(f"INSUFFICIENT DISK SPACE\nNeed ~{storage['required']/1024**3:.1f} GB\nAvailable {storage['free']/1024**3:.1f} GB")
        def failure(message):
            if generation == self.storage_generation: self.storage_label.setText('[ storage ] ' + message)
        self.job(lambda:storage_check(folder,estimate_bytes(source,variant)),success,failure)

    def export(self):
        variant = self.quality.currentData()
        if self.busy or not variant or not self.source or self.estimated is None: return
        try:
            if not storage_check(self.folder,self.estimated)['sufficient']:
                self.select_quality(); return
        except Exception as e: return self.error(str(e))
        self.busy = True; self.cancel_event.clear(); self.save.hide(); self.done.hide()
        self.input.setEnabled(False); self.sniff_button.setEnabled(False); self.quality.setEnabled(False)
        self.cancel_button.setEnabled(True); self.progress_bar.setValue(0); self.telemetry.setText('Starting capture…'); self.reveal(self.capture_panel)
        self.status.setText('[ capture ] stream copy → MP4')
        job = Job(lambda: capture(self.source, variant, self.folder, lambda p: job.progress.emit(p), self.cancel_event))
        self.jobs.append(job); job.progress.connect(self.on_progress); job.result.connect(self.finished_capture); job.failed.connect(self.error)
        job.finished.connect(lambda: self.jobs.remove(job)); job.start()

    def on_progress(self, p):
        self.progress_bar.setValue(min(990, int(p['seconds']/self.source.duration*1000)))
        self.telemetry.setText(f"{clock(p['seconds'])} / {clock(self.source.duration)}\n{p['speed']} • {p['size']/1024**3:.2f} GB • elapsed {clock(p['elapsed'])}")
        if p['seconds'] >= self.source.duration-1: self.status.setText('[ finalizing ] preparing MP4 for playback…')

    def cancel_capture(self):
        self.cancel_event.set(); self.cancel_button.setEnabled(False); self.status.setText('[ cancelling ] cleaning partial export…')

    def finished_capture(self, result):
        path = result.path
        self.busy = False; self.output = path; self.progress_bar.setValue(1000); self.capture_panel.hide()
        self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.quality.setEnabled(True)
        headline = 'CAPTURE COMPLETE — SOURCE READ WARNINGS' if result.state != 'Success' else 'CAPTURE COMPLETE'
        self.status.setText('[ capture ] ' + result.state.lower())
        self.completed.setText(f'{headline}\n\n{Path(path).name}\n{Path(path).stat().st_size/1024**3:.2f} GB\n{result.details}')
        self.play.setVisible(bool(vlc_path())); self.reveal(self.done); QApplication.alert(self,5000)

    def refresh_folder(self): self.folder_label.setText('EXPORTS → ' + self.folder)
    def choose_folder(self):
        if self.busy: return
        path = QFileDialog.getExistingDirectory(self,'Export folder',self.folder)
        if path:
            self.folder = path; self.settings.setValue('folder',path); self.refresh_folder(); self.select_quality()
    def open_diagnostics(self):
        DIAGNOSTICS.mkdir(parents=True,exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(DIAGNOSTICS)))
    def open_folder(self):
        path = Path(self.folder); path.mkdir(parents=True,exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def play_vlc(self):
        if vlc_path() and hasattr(self,'output'): subprocess.Popen([vlc_path(),self.output],creationflags=FLAGS)
    def set_repo(self):
        text, ok = QInputDialog.getText(self,'GitHub releases','Repository (owner/name):',text=self.settings.value('repo',''))
        if ok:
            if text and not re.fullmatch(r'[\w.-]+/[\w.-]+',text): return self.error('Use owner/repository for GitHub updates.')
            self.settings.setValue('repo',text); self.check_updates(True)
    def check_updates(self, manual=False):
        repo = self.settings.value('repo','')
        if not repo:
            if manual: QMessageBox.information(self,'Updates','Set the GitHub release repository in Options first.')
            return
        def success(release):
            if release:
                self.release = release; self.update_button.setText('[ UPDATE AVAILABLE ] ' + release['tag_name']); self.update_button.show()
                if manual: self.show_release()
            elif manual: QMessageBox.information(self,'Updates','You have the latest release.')
        self.job(lambda:latest_release(repo),success,lambda message: QMessageBox.warning(self,'Updates',message) if manual else None)
    def show_release(self):
        dialog = QMessageBox(self); dialog.setWindowTitle('StinkSNIFFER update'); dialog.setText(self.release['tag_name'])
        dialog.setInformativeText((self.release.get('body') or 'No release notes provided.')[:12000]); dialog.setTextFormat(Qt.TextFormat.PlainText)
        open_button = dialog.addButton('Open release / download',QMessageBox.ButtonRole.AcceptRole); dialog.addButton('Later',QMessageBox.ButtonRole.RejectRole); dialog.exec()
        if dialog.clickedButton() == open_button: QDesktopServices.openUrl(QUrl(self.release['html_url']))
    def closeEvent(self,event):
        if self.jobs:
            event.ignore()
            if self.busy and self.source: self.cancel_capture()
            self.status.setText('[ wait ] background task finishing; close again shortly.')
            return
        event.accept()

def main():
    app = QApplication(sys.argv)
    font = ROOT / 'assets/CascadiaMono.ttf'
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Cascadia Mono',10))
    window = Window(); window.show()
    if '--screenshot' in sys.argv:
        QTimer.singleShot(500,lambda: (window.grab().save(str(ROOT/'preview.png')),app.quit()))
    sys.exit(app.exec())

if __name__ == '__main__': main()
