import os, sys, subprocess, threading, random
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QStandardPaths, QUrl, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QPoint
from PySide6.QtGui import QFont, QFontDatabase, QPixmap, QDesktopServices, QColor, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QProgressBar, QFileDialog, QMenu, QMessageBox, QInputDialog, QGraphicsOpacityEffect, QScrollArea,
    QSlider, QSpinBox, QWidgetAction, QSystemTrayIcon)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from dataclasses import replace
from companions import GlassShell, SniffyCompanion, PixelEye
from sounds import Sounds
from dialogue import COMPLETION_LINES, UPDATE_LINES, choose_line
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
    def __init__(self,settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings('StinkWind', 'StinkSNIFFER')
        default = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)) / 'StinkSNIFFER')
        self.folder = self.settings.value('folder', default)
        self.source = None
        self.busy = False
        self.jobs = []
        self.animations = []
        self.cancel_event = threading.Event()
        self.storage_generation = 0
        self.estimated = None
        self.stage = 'ready'; self.exit_ready = False; self.closing = False
        self.update_pending = False
        self.last_activity = time.monotonic(); self.docked = False
        self.sounds = Sounds(self.settings,self); self.sounds.shutdown_finished.connect(self.finish_exit)
        self.setWindowTitle('StinkSNIFFER')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(510, min(900, QApplication.primaryScreen().availableGeometry().height()-40))
        self.setMinimumSize(440, 580)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8,8,8,8)
        self.shell = GlassShell()
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
        # Transparency lives in the main status row.
        self.transparency_slider = QSlider(Qt.Orientation.Horizontal)
        self.transparency_slider.setRange(0,100); self.transparency_slider.setFixedWidth(110)
        self.transparency_slider.setToolTip('Transparency: 0% opaque / 100% transparent')
        self.transparency_value = QLabel('0%',objectName='muted'); self.transparency_value.setFixedWidth(34)
        self.transparency_slider.valueChanged.connect(self.set_transparency)
        self.transparency_slider.setValue(max(0,min(100,self.settings.value('transparency',0,type=int))))
        self.shell.set_transparency(self.transparency_slider.value())
        self.global_mute_action = menu.addAction('Mute all sounds'); self.global_mute_action.setCheckable(True)
        self.global_mute_action.setChecked(self.settings.value('music_muted',False,type=bool))
        self.global_mute_action.triggered.connect(self.toggle_mute)
        menu.addSeparator()
        self.hide_sniffy_action = menu.addAction('Hide Sniffy'); self.hide_sniffy_action.setCheckable(True)
        self.hide_sniffy_action.setChecked(self.settings.value('hide_sniffy',False,type=bool))
        self.hide_sniffy_action.toggled.connect(self.hide_sniffy)
        menu.addAction('Show tips', self.show_tips)
        menu.addSeparator()
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
        self.update_sniffy_slot = QWidget(); self.update_sniffy_slot.hide()
        self.update_sniffy_layout = QVBoxLayout(self.update_sniffy_slot); self.update_sniffy_layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.update_sniffy_slot)
        self.status = QLabel('• Local capture  //  ready', objectName='muted')
        self.status.setWordWrap(True)
        status_row = QHBoxLayout(); status_row.addWidget(self.status,1)
        self.eye = PixelEye(); status_row.addWidget(self.eye)
        status_row.addWidget(self.transparency_slider); status_row.addWidget(self.transparency_value)
        layout.addLayout(status_row)
        source_header = QHBoxLayout(); source_header.addWidget(QLabel('SOURCE',objectName='muted')); source_header.addStretch()
        self.history = QComboBox(); self.history.setFixedWidth(210); self.history.setToolTip('VOD links often expire after ~30 days. Saved links are checked again.')
        source_header.addWidget(self.history); layout.addLayout(source_header)
        try: self.recent = json.loads(self.settings.value('history','[]'))[:5]
        except (ValueError,TypeError): self.recent = []
        self.refresh_history(); self.history.activated.connect(self.load_history)
        source_bar = QWidget(objectName='sourceBar'); source_row = QHBoxLayout(source_bar); source_row.setContentsMargins(0,0,5,0); source_row.setSpacing(0)
        self.input = QLineEdit(objectName='sourceInput'); self.input.setPlaceholderText('Kick username / M3U8 URL'); self.input.returnPressed.connect(self.sniff)
        source_row.addWidget(self.input,1)
        self.clear_button = QPushButton('×',objectName='inlineSniff'); self.clear_button.setToolTip('Clear source and start fresh')
        self.clear_button.clicked.connect(self.clear_source); source_row.addWidget(self.clear_button)
        self.sniff_button = QPushButton('[ SNIFF ]'); self.sniff_button.clicked.connect(self.sniff)
        self.sniff_button.setObjectName('inlineSniff'); source_row.addWidget(self.sniff_button)
        layout.addWidget(source_bar)
        self.sniffy = SniffyCompanion(self.settings,self.shell)
        self.sniffy.spoken.connect(self.speech_sound)
        self.sniffy_target = self.input; self.last_quip = None
        self.follow_timer = QTimer(self); self.follow_timer.timeout.connect(self.position_sniffy); self.follow_timer.start(100)
        self.scroll = scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget {background: transparent; border: none;}')
        content = QWidget(); scroll.setWidget(content); body = QVBoxLayout(content); body.setContentsMargins(0,0,0,0); body.setSpacing(16)
        layout.addWidget(scroll, 1)
        self.card = QWidget(); card = QVBoxLayout(self.card); card.setContentsMargins(0,0,0,0); card.setSpacing(12)
        card.addWidget(QLabel('──────── NEW CAPTURE ────────', objectName='faint'), alignment=Qt.AlignmentFlag.AlignCenter)
        self.thumbnail = QLabel('[ preview unavailable ]'); self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); self.thumbnail.setMinimumHeight(160)
        self.thumbnail.setObjectName('thumbnail'); card.addWidget(self.thumbnail)
        self.title = QLabel(); self.title.setWordWrap(True); card.addWidget(self.title)
        self.metadata = QLabel(objectName='muted'); self.metadata.setWordWrap(True); card.addWidget(self.metadata)
        self.naming = QWidget(); naming_layout = QVBoxLayout(self.naming); naming_layout.setContentsMargins(0,0,0,0); naming_layout.setSpacing(7)
        naming_layout.addWidget(QLabel('EXPORT NAME  //  source metadata unavailable',objectName='muted'))
        naming_row = QHBoxLayout()
        self.streamer_name = QLineEdit(); self.streamer_name.setPlaceholderText('Streamer name'); self.streamer_name.setAccessibleName('Streamer name')
        self.live_date = QLineEdit(); self.live_date.setPlaceholderText('Live date: YYYY-MM-DD'); self.live_date.setAccessibleName('VOD live date')
        naming_row.addWidget(self.streamer_name); naming_row.addWidget(self.live_date); naming_layout.addLayout(naming_row)
        self.naming_hint = QLabel('Enter the name and actual live date before SAVE.',objectName='muted'); self.naming_hint.setWordWrap(True); naming_layout.addWidget(self.naming_hint)
        self.streamer_name.textChanged.connect(self.refresh_export_gate); self.live_date.textChanged.connect(self.refresh_export_gate)
        card.addWidget(self.naming); self.naming.hide()
        card.addWidget(QLabel('QUALITY', objectName='muted'))
        self.quality = QComboBox(); self.quality.currentIndexChanged.connect(self.select_quality); card.addWidget(self.quality)
        body.addWidget(self.card)
        self.sniffy_slot = QWidget(); self.sniffy_slot.hide()
        self.sniffy_slot_layout = QVBoxLayout(self.sniffy_slot); self.sniffy_slot_layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.sniffy_slot)
        self.storage_label = QLabel(objectName='muted'); self.storage_label.setWordWrap(True); layout.addWidget(self.storage_label); self.storage_label.hide()
        self.save = QPushButton('[ SAVE / EXPORT ]'); self.save.clicked.connect(self.export); layout.addWidget(self.save)
        self.capture_panel = QWidget(); progress_layout = QVBoxLayout(self.capture_panel); progress_layout.setContentsMargins(0,0,0,0)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0,1000); self.progress_bar.setTextVisible(False); progress_layout.addWidget(self.progress_bar)
        self.telemetry = QLabel(); self.telemetry.setWordWrap(True); progress_layout.addWidget(self.telemetry)
        self.cancel_button = QPushButton('[ CANCEL ]'); self.cancel_button.clicked.connect(self.cancel_capture); progress_layout.addWidget(self.cancel_button)
        self.mute_button = QPushButton(); self.mute_button.clicked.connect(self.toggle_mute)
        progress_layout.addWidget(self.mute_button,0,Qt.AlignmentFlag.AlignRight)
        self.music_output = QAudioOutput(self); self.music_output.setVolume(.1)
        self.music_output.setMuted(self.settings.value('music_muted',False,type=bool))
        self.music = QMediaPlayer(self); self.music.setAudioOutput(self.music_output)
        self.music.setLoops(QMediaPlayer.Loops.Once)
        self.music.setSource(QUrl.fromLocalFile(str(ROOT/'assets/media/capture-music.mp3')))
        self.music_wait_timer = QTimer(self); self.music_wait_timer.setSingleShot(True); self.music_wait_timer.timeout.connect(self.start_capture_music)
        self.sounds.players['laugh'].mediaStatusChanged.connect(self.laugh_status)
        self.sounds.players['laugh'].errorOccurred.connect(lambda *args:self.start_capture_music())
        self.sounds.players['laugh'].durationChanged.connect(self.laugh_duration)
        self.refresh_mute_button()
        layout.addWidget(self.capture_panel)
        self.done = QWidget(); done_layout = QVBoxLayout(self.done); done_layout.setContentsMargins(0,0,0,0)
        self.completed = QLabel(); self.completed.setWordWrap(True); done_layout.addWidget(self.completed)
        actions = QHBoxLayout(); open_btn = QPushButton('Open Folder'); open_btn.clicked.connect(self.open_folder); actions.addWidget(open_btn)
        self.play = QPushButton('Play in VLC'); self.play.clicked.connect(self.play_vlc); actions.addWidget(self.play); done_layout.addLayout(actions); layout.addWidget(self.done)
        self.youtube_button = QPushButton('[ VISIT @THESTINKWIND ]')
        self.youtube_button.setToolTip('YouTube archives / meme documentaries')
        self.youtube_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://www.youtube.com/@TheStinkWind')))
        done_layout.addWidget(self.youtube_button)
        body.addStretch()
        self.folder_label = QLabel(objectName='faint'); self.folder_label.setWordWrap(True); layout.addWidget(self.folder_label); self.refresh_folder()
        for w in (self.card,self.save,self.capture_panel,self.done,self.storage_label): w.hide()
        self.setStyleSheet('''
            QWidget { color: #dedede; font-size: 13px; }
            QLabel { background: transparent; border: none; }
            QLabel#brand { font-size: 12px; letter-spacing: 1px; font-weight: bold; }
            QLabel#muted { color: #999; font-size: 11px; }
            QLabel#faint { color: #737373; font-size: 10px; }
            QLabel#thumbnail { border: 1px solid #353538; border-radius: 7px; color:#777; background:rgba(0,0,0,30); }
            QLineEdit, QComboBox { background: rgba(255,255,255,5); border: 1px solid #454548; border-radius: 6px; padding: 10px; selection-background-color:#666; }
            QWidget#sourceBar { background:rgba(255,255,255,5); border:1px solid #454548; border-radius:6px; }
            QLineEdit#sourceInput { background:transparent; border:none; }
            QPushButton#inlineSniff { background:transparent; border:none; padding:7px; }
            QPushButton#inlineSniff:hover { background:rgba(255,255,255,12); }
            QWidget#sniffyBubble { background:#202124; border:1px solid #545458; }
            QWidget#sniffyBubble QLabel { font-size:11px; }
            QSlider::groove:horizontal { background:#414144; height:3px; }
            QSlider::handle:horizontal { background:#dedede; width:9px; margin:-5px 0; }
            QSpinBox { background:#202124; border:1px solid #454548; padding:4px; }
            QPushButton { background: rgba(255,255,255,6); border: 1px solid #414144; border-radius: 5px; padding: 7px 10px; }
            QPushButton:hover { background:rgba(255,255,255,17); border-color:#777; }
            QPushButton:disabled { color:#606060; border-color:#303033; }
            QProgressBar { border:1px solid #444; border-radius:3px; height: 9px; background:#222; }
            QProgressBar::chunk { background:#b8b8b8; }
            QMenu, QComboBox QAbstractItemView { background:#202124; color:#dedede; border:1px solid #444; padding:5px; selection-background-color:#444; }
            QScrollBar:vertical { width:5px; background:transparent; } QScrollBar::handle:vertical {background:#444;min-height:20px;}
        ''')
        for control in (self.input,self.history,self.quality,self.streamer_name,self.live_date,self.save): control.installEventFilter(self)
        icon = QIcon(str(ROOT/'assets/sniffy.ico')); self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(self.tray_icon(icon),self); self.tray.setToolTip('StinkSNIFFER')
        tray_menu = QMenu(self); tray_menu.addAction('Show StinkSNIFFER',self.restore_window); tray_menu.addAction('Exit',self.close)
        self.tray.setContextMenu(tray_menu); self.tray.activated.connect(lambda reason:self.restore_window() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable(): self.tray.show()
        QApplication.instance().installEventFilter(self)
        self.idle_timer = QTimer(self); self.idle_timer.timeout.connect(self.idle_sniffy); self.idle_timer.start(500)
        if '--smoke-test' not in sys.argv:
            QTimer.singleShot(1000,self.check_updates); QTimer.singleShot(250,lambda:self.sounds.play('startup'))

    def restore_window(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    @staticmethod
    def tray_icon(icon):
        result = QIcon()
        # Windows chooses its tray slot size. Add transparent padding to reduce
        # the visible skull by 15%, including common display-scaling sizes.
        for size in (16,20,24,28,32,40,48,64):
            canvas = QPixmap(size,size); canvas.fill(Qt.GlobalColor.transparent)
            skull = icon.pixmap(round(size*.85),round(size*.85))
            painter = QPainter(canvas)
            painter.drawPixmap((size-skull.width())//2,(size-skull.height())//2,skull)
            painter.end(); result.addPixmap(canvas)
        return result

    def refresh_history(self):
        self.history.blockSignals(True); self.history.clear(); self.history.addItem('Recent streams…',None)
        for entry in self.recent: self.history.addItem(entry.get('title','Unnamed stream'),entry)
        self.history.blockSignals(False)

    def load_history(self,index):
        entry = self.history.itemData(index)
        if not entry or self.busy: return
        self.input.setText(entry['url']); self.history_entry = entry; self.sniff()
        self.status.setText('[ checking saved link ] VOD links often expire after ~30 days.')

    def eventFilter(self,watched,event):
        if isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched)):
            if event.type() in (QEvent.Type.MouseButtonPress,QEvent.Type.KeyPress,QEvent.Type.Wheel,QEvent.Type.MouseMove):
                self.last_activity = time.monotonic()
            if event.type() in (QEvent.Type.FocusIn,QEvent.Type.MouseButtonPress) and watched in (self.input,self.history,self.quality,self.streamer_name,self.live_date,self.save):
                self.sniffy_target = watched
        return super().eventFilter(watched,event)

    def speech_sound(self):
        self.last_activity = time.monotonic()
        if self.stage != 'error': self.sounds.play('speech')

    def idle_sniffy(self):
        if self.closing or self.busy or self.stage != 'quality' or self.sniffy.tip_open or not self.sniffy.isVisible() or not self.save.isVisible(): return
        if time.monotonic()-self.last_activity >= 10:
            self.sniffy.sprite.bounce(); self.export_quip()

    def dock_sniffy(self,dock):
        self.update_sniffy_layout.removeWidget(self.sniffy); self.update_sniffy_slot.hide()
        self.docked = dock
        if dock:
            self.sniffy_slot_layout.addWidget(self.sniffy); self.sniffy_slot.setVisible(not self.settings.value('hide_sniffy',False,type=bool))
            self.sniffy.setMinimumWidth(0); self.sniffy.setMaximumWidth(16777215)
        else:
            self.sniffy_slot_layout.removeWidget(self.sniffy); self.sniffy.setParent(self.shell); self.sniffy_slot.hide()
        self.sniffy.setVisible(not self.settings.value('hide_sniffy',False,type=bool))

    def clear_source(self):
        if self.busy or self.closing: return
        self.storage_generation += 1; self.source = None; self.estimated = None; self.stage = 'ready'; self.history_entry = None
        self.music.stop(); self.sounds.stop_capture(); self.music_wait_timer.stop()
        self.input.clear(); self.thumbnail.clear(); self.title.clear(); self.metadata.clear()
        self.quality.blockSignals(True); self.quality.clear(); self.quality.blockSignals(False)
        self.streamer_name.clear(); self.live_date.clear(); self.history.setCurrentIndex(0)
        for widget in (self.card,self.save,self.capture_panel,self.done,self.storage_label): widget.hide()
        if hasattr(self,'output'): del self.output
        self.dock_sniffy(False); self.sniffy_target = self.input
        self.status.setText('• Local capture  //  ready'); self.sniffy.say('Fresh start. My favourite kind of suspicious activity.')
        self.input.setFocus()
        if hasattr(self,'release'): self.show_update_sniffy()

    def laugh_status(self,status):
        if status in (QMediaPlayer.MediaStatus.EndOfMedia,QMediaPlayer.MediaStatus.InvalidMedia): self.start_capture_music()

    def laugh_duration(self,duration):
        if self.music_wait_timer.isActive() and self.stage == 'capture':
            self.music_wait_timer.start(max(3000,duration+2000))

    def start_capture_music(self):
        if self.stage != 'capture' or not self.busy or self.cancel_event.is_set() or self.closing: return
        if self.music.playbackState() == QMediaPlayer.PlaybackState.PlayingState: return
        self.music_wait_timer.stop(); self.sounds.stop_capture(); self.music.setPosition(0); self.music.play()

    def finish_exit(self):
        self.exit_ready = True; self.close()

    def position_sniffy(self):
        self.shell.work_area_top = self.input.mapTo(self.shell,QPoint(0,self.input.height())).y()
        if self.docked: return
        if not hasattr(self,'sniffy') or not self.sniffy.isVisible(): return
        target = self.sniffy_target
        if not target.isVisible(): target = self.input
        point = target.mapTo(self.shell,QPoint(0,target.height()))
        width = min(350,self.shell.width()-44) if self.sniffy.bubble.isVisible() else 36
        self.sniffy.setFixedWidth(width); self.sniffy.adjustSize()
        x = max(8,min(self.shell.width()-width-8,point.x()))
        y = max(70,min(self.shell.height()-self.sniffy.height()-24,point.y()+4))
        # An overlay follows focus without changing layout or covering the active control.
        if y < point.y() and self.sniffy.bubble.isVisible():
            y = max(70,point.y()-target.height()-self.sniffy.height()-4)
        self.sniffy.move(x,y); self.sniffy.raise_()

    def export_quip(self):
        lines = [
            "Save it. Tomorrow's apology video needs a flashback.",
            'Export the evidence. The donation goal can wait.',
            'Go on. Preserve this important contribution to unemployment.',
            'One small click for you. One permanent receipt for them.',
            "They said ‘clip that.’ I've taken that personally.",
            'Save before ‘out of context’ becomes the official statement.',
            'The internet forgets. Your hard drive has other plans.',
            'Another historic moment in asking strangers for rent.',
            'Go on. Give the future reaction video some source material.',
            "Looks like you're collecting receipts. Finally, my qualifications."]
        self.last_quip = random.choice([line for line in lines if line != self.last_quip])
        self.sniffy.say(self.last_quip)

    def set_transparency(self,value):
        self.shell.set_transparency(value); self.transparency_value.setText(f'{value}%')
        self.settings.setValue('transparency',value)

    def hide_sniffy(self,hidden):
        self.sniffy.set_hidden(hidden)
        if self.sniffy.parentWidget() is self.update_sniffy_slot: self.update_sniffy_slot.setVisible(not hidden)
        elif self.docked: self.sniffy_slot.setVisible(not hidden)

    def show_tips(self):
        self.hide_sniffy_action.setChecked(False); self.sniffy.show_tips()
        if self.sniffy.parentWidget() is self.update_sniffy_slot: self.update_sniffy_slot.show()
        elif self.docked: self.sniffy_slot.show()

    def refresh_mute_button(self):
        self.mute_button.setText('[ UNMUTE SOUND ]' if self.music_output.isMuted() else '[ MUTE SOUND ]')
        self.global_mute_action.setChecked(self.music_output.isMuted())

    def toggle_mute(self):
        self.music_output.setMuted(not self.music_output.isMuted())
        self.sounds.set_muted(self.music_output.isMuted())
        self.settings.setValue('music_muted',self.music_output.isMuted()); self.refresh_mute_button()

    def export_source(self):
        if self.naming.isVisible():
            return replace(self.source,streamer=self.streamer_name.text().strip(),date=self.live_date.text().strip())
        return self.source

    def refresh_export_gate(self):
        if not self.source or self.busy or self.estimated is None: return
        try:
            output_name = filename(self.export_source())
            self.naming_hint.setText(output_name)
            enough = storage_check(self.folder,self.estimated)['sufficient']
        except Exception as e:
            self.naming_hint.setText(str(e)); self.save.hide(); return
        if enough:
            if not self.save.isVisible(): self.reveal(self.save)
        else: self.save.hide()

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
        self.music.stop(); self.sounds.stop_capture(); self.music_wait_timer.stop()
        self.stage = 'error'; self.clear_button.setEnabled(True)
        self.busy = False; self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.quality.setEnabled(True)
        self.cancel_button.setEnabled(True); self.capture_panel.hide()
        if getattr(self,'history_entry',None):
            message = 'Saved link could not be opened. VOD links often expire after ~30 days; search the streamer again. ' + message
            self.history_entry = None
        self.status.setText('[ error ] ' + message)
        self.sniffy.say('Capture cancelled. No stationery was harmed.' if self.cancel_event.is_set() else "That didn't finish. Diagnostics have the details.")
        if not self.cancel_event.is_set(): self.sounds.play('error')
        if self.source: self.select_quality()

    def sniff(self):
        if self.busy or not self.input.text().strip(): return
        self.cancel_event.clear()
        self.stage = 'resolving'; self.clear_button.setEnabled(False)
        self.dock_sniffy(False)
        self.busy = True; self.source = None; self.estimated = None
        self.input.setEnabled(False); self.sniff_button.setEnabled(False)
        self.storage_generation += 1
        for widget in (self.card,self.save,self.capture_panel,self.done,self.storage_label): widget.hide()
        self.status.setText('[ sniffing ] resolving metadata / inspecting HLS…')
        self.thumbnail.clear(); self.thumbnail.setText('[ refreshing preview… ]')
        self.sniffy.say('Looking for your stream. The paperclip never managed that.')
        value = self.input.text(); self.pending_search = value
        entry = getattr(self,'history_entry',None)
        if entry and entry.get('url') == value:
            metadata = {'title':entry.get('title'), 'streamer':entry.get('streamer'),
                'date':entry.get('date'), 'thumbnail':entry.get('thumbnail_url')}
            self.job(lambda:inspect(value,metadata),self.resolved)
        else:
            self.job(lambda: resolve(value), self.resolved)

    def resolved(self, source):
        entry = getattr(self,'history_entry',None)
        if entry and entry.get('url') == source.master:
            source = replace(source,title=entry.get('title') or source.title,streamer=source.streamer or entry.get('streamer',''),date=source.date or entry.get('date',''))
        self.history_entry = None
        self.stage = 'source'; self.clear_button.setEnabled(True); self.dock_sniffy(True)
        self.busy = False; self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.source = source; self.estimated = None
        self.recent = [entry for entry in self.recent if entry.get('url') != source.master]
        self.recent.insert(0,{'title':source.title or source.streamer or 'Unnamed stream','url':source.master,'streamer':source.streamer,'date':source.date,'thumbnail_url':source.thumbnail_url,'searched':datetime.now().isoformat()})
        self.recent = self.recent[:5]; self.settings.setValue('history',json.dumps(self.recent)); self.refresh_history()
        self.title.setText(source.title); self.metadata.setText(f"{source.streamer or 'streamer unknown'} • {source.date or 'live date unknown'} • {clock(source.duration)}")
        self.naming.setVisible(not source.streamer or not source.date)
        self.streamer_name.setText(source.streamer); self.live_date.setText(source.date)
        self.thumbnail.clear()
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
        self.sniffy_target = self.quality
        self.reveal(self.card)
        self.sniffy.say("That's the one? Pick a size.")

    def select_quality(self,index=None):
        if not self.source: return
        if index is not None and not self.busy: self.stage = 'source'
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
                self.refresh_export_gate()
                self.sniffy_target = self.save if self.save.isVisible() else self.naming
                if self.save.isVisible() and self.stage != 'error':
                    self.stage = 'quality'; self.dock_sniffy(True); self.export_quip()
            else:
                self.sniffy_target = self.storage_label
                self.stage = 'storage'
                self.sniffy.say('Your drive needs more room before we collect these receipts.')
                self.storage_label.setText(f"INSUFFICIENT DISK SPACE\nNeed ~{storage['required']/1024**3:.1f} GB\nAvailable {storage['free']/1024**3:.1f} GB")
        def failure(message):
            if generation == self.storage_generation:
                self.stage = 'error'; self.storage_label.setText('[ storage ] ' + message)
                self.sniffy.say('Storage check failed. We need that sorted before saving.'); self.sounds.play('error')
        self.job(lambda:storage_check(folder,estimate_bytes(source,variant)),success,failure)

    def export(self):
        variant = self.quality.currentData()
        if self.busy or not variant or not self.source or self.estimated is None: return
        try:
            if not storage_check(self.folder,self.estimated)['sufficient']:
                self.select_quality(); return
        except Exception as e: return self.error(str(e))
        source = self.export_source()
        try: filename(source)
        except Exception as e: return self.error(str(e))
        self.stage = 'capture'; self.clear_button.setEnabled(False)
        self.dock_sniffy(True)
        self.busy = True; self.cancel_event.clear(); self.save.hide(); self.done.hide()
        self.input.setEnabled(False); self.sniff_button.setEnabled(False); self.quality.setEnabled(False)
        self.cancel_button.setEnabled(True); self.progress_bar.setValue(0); self.telemetry.setText('Starting capture…'); self.reveal(self.capture_panel)
        self.status.setText('[ capture ] stream copy → MP4')
        self.sounds.play('laugh')
        self.music_wait_timer.start(max(3000,self.sounds.players['laugh'].duration()+2000))
        self.sniffy.say("No need to write a letter. I'm already helping.")
        job = Job(lambda: capture(source, variant, self.folder, lambda p: job.progress.emit(p), self.cancel_event))
        self.jobs.append(job); job.progress.connect(self.on_progress); job.result.connect(self.finished_capture); job.failed.connect(self.error)
        job.finished.connect(lambda: self.jobs.remove(job)); job.start()

    def on_progress(self, p):
        self.progress_bar.setValue(min(990, int(p['seconds']/self.source.duration*1000)))
        self.telemetry.setText(f"{clock(p['seconds'])} / {clock(self.source.duration)}\n{p['speed']} • {p['size']/1024**3:.2f} GB • elapsed {clock(p['elapsed'])}")
        if p['seconds'] >= self.source.duration-1: self.status.setText('[ finalizing ] preparing MP4 for playback…')

    def cancel_capture(self):
        self.music.stop(); self.sounds.stop_capture(); self.music_wait_timer.stop()
        self.cancel_event.set(); self.cancel_button.setEnabled(False); self.status.setText('[ cancelling ] cleaning partial export…')

    def finished_capture(self, result):
        self.music.stop(); self.sounds.stop_capture(); self.music_wait_timer.stop()
        self.stage = 'complete'; self.clear_button.setEnabled(True)
        self.sniffy_target = self.done
        path = result.path
        self.busy = False; self.output = path; self.progress_bar.setValue(1000); self.capture_panel.hide()
        self.input.setEnabled(True); self.sniff_button.setEnabled(True); self.quality.setEnabled(True)
        headline = 'CAPTURE COMPLETE — SOURCE READ WARNINGS' if result.state != 'Success' else 'CAPTURE COMPLETE'
        self.status.setText('[ capture ] ' + result.state.lower())
        self.completed.setText(f'{headline}\n\n{Path(path).name}\n{Path(path).stat().st_size/1024**3:.2f} GB\n{result.details}')
        self.play.setVisible(bool(vlc_path())); self.reveal(self.done); QApplication.alert(self,5000)
        self.dock_sniffy(True)
        line = choose_line(COMPLETION_LINES,self.settings.value('last_completion_line',''))
        self.settings.setValue('last_completion_line',line)
        warning = 'SOURCE READ WARNINGS. Diagnostics have the details.\n' if result.state != 'Success' else ''
        self.sniffy.say(warning+line,force=True)

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
        repo = self.settings.value('repo','') or RELEASE_REPO
        if not repo:
            if manual: QMessageBox.information(self,'Updates','Set the GitHub release repository in Options first.')
            return
        def success(release):
            if release:
                self.release = release; self.update_button.setText('[ UPDATE AVAILABLE ] ' + release['tag_name']); self.update_button.show()
                self.update_pending = True; self.show_update_sniffy()
                if manual: self.show_release()
            elif manual: QMessageBox.information(self,'Updates','You have the latest release.')
        def failure(message):
            if manual:
                self.sounds.play('error'); QMessageBox.warning(self,'Updates',message)
        self.job(lambda:latest_release(repo),success,failure)

    def show_update_sniffy(self):
        # Finish the capture conversation before bringing up software updates.
        if self.busy or self.closing or self.stage in ('capture','error','complete'): return
        self.sniffy_slot_layout.removeWidget(self.sniffy); self.sniffy_slot.hide()
        self.update_sniffy_layout.addWidget(self.sniffy)
        self.sniffy.setMinimumWidth(0); self.sniffy.setMaximumWidth(16777215)
        self.docked = True
        self.stage = 'update'
        self.update_sniffy_slot.setVisible(not self.settings.value('hide_sniffy',False,type=bool))
        line = choose_line(UPDATE_LINES,self.settings.value('last_update_line',''))
        self.settings.setValue('last_update_line',line); self.update_pending = False
        self.sniffy.say(line,force=True)
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
        if not self.exit_ready and '--smoke-test' not in sys.argv:
            event.ignore()
            if not self.closing:
                self.closing = True; self.setEnabled(False); self.music.stop(); self.music_wait_timer.stop(); self.idle_timer.stop()
                self.sounds.begin_shutdown()
            return
        event.accept()
        QApplication.instance().removeEventFilter(self)
        self.music.stop(); self.shell.watermark.stop(); self.sniffy.sprite.movie.stop(); self.tray.hide()

def main():
    app = QApplication(sys.argv)
    font = ROOT / 'assets/CascadiaMono.ttf'
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Cascadia Mono',10))
    test_folder = None
    settings = None
    if '--smoke-test' in sys.argv:
        import tempfile
        test_folder = tempfile.TemporaryDirectory(prefix='stinksniffer-smoke-')
        settings = QSettings(str(Path(test_folder.name)/'settings.ini'),QSettings.Format.IniFormat)
    window = Window(settings); window.show()
    if '--smoke-test' in sys.argv:
        window.music_output.setMuted(True); window.music.play()
        def finish_test():
            checks = {'version':VERSION,'watermark_frames':not window.shell.frame.isNull(),
                'sniffy_frames':bool(window.sniffy.sprite.frame_cache),'music_loaded':window.music.duration()>0,
                'default_transparency':window.shell.transparency,'window_size':[window.width(),window.height()],
                'inline_sniff':window.input.parentWidget() is window.sniff_button.parentWidget()}
            path = Path(sys.argv[sys.argv.index('--smoke-test')+1])
            path.write_text(json.dumps(checks,indent=2),encoding='utf-8')
            window.grab().save(str(path.with_suffix('.png')))
            window.close(); app.exit(0 if checks['watermark_frames'] and checks['sniffy_frames'] and checks['music_loaded'] else 1)
        QTimer.singleShot(2500,finish_test)
    if '--screenshot' in sys.argv:
        QTimer.singleShot(500,lambda: (window.grab().save(str(ROOT/'preview.png')),app.quit()))
    sys.exit(app.exec())

if __name__ == '__main__': main()
