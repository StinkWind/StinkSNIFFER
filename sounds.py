"""Local audio cues with a shared persisted mute setting."""
from PySide6.QtCore import QObject, QUrl, Signal, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from core import ROOT

class Sounds(QObject):
    shutdown_finished = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.players = {}
        self.outputs = {}
        self.shutting_down = False
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setSingleShot(True)
        self.shutdown_timer.timeout.connect(self.finish_shutdown)
        for name in ('speech','error','startup','shutdown','laugh'):
            output = QAudioOutput(self); output.setVolume(.1)
            output.setMuted(settings.value('music_muted',False,type=bool))
            player = QMediaPlayer(self); player.setAudioOutput(output)
            player.setSource(QUrl.fromLocalFile(str(ROOT/f'assets/media/{name}.wav')))
            self.players[name] = player; self.outputs[name] = output
        self.players['shutdown'].mediaStatusChanged.connect(self.shutdown_status)
        self.players['shutdown'].errorOccurred.connect(lambda *args:self.finish_shutdown())

    def set_muted(self, muted):
        for output in self.outputs.values(): output.setMuted(muted)

    def play(self, name):
        if name in ('speech','error'):
            self.players['speech'].stop(); self.players['error'].stop()
        player = self.players[name]; player.setPosition(0); player.play()

    def stop_capture(self): self.players['laugh'].stop()

    def begin_shutdown(self):
        self.shutting_down = True
        for player in self.players.values(): player.stop()
        if self.settings.value('music_muted',False,type=bool):
            QTimer.singleShot(0,self.finish_shutdown)
        else:
            # A broken/missing device must never prevent exit.
            self.shutdown_timer.start(5000); self.play('shutdown')

    def shutdown_status(self, status):
        if status in (QMediaPlayer.MediaStatus.EndOfMedia,QMediaPlayer.MediaStatus.InvalidMedia): self.finish_shutdown()

    def finish_shutdown(self):
        if not self.shutting_down: return
        self.shutting_down = False; self.shutdown_timer.stop()
        self.players['shutdown'].stop(); self.shutdown_finished.emit()
