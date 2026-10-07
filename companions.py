"""Local-only visual layers and Sniffy's compact onboarding."""
from PySide6.QtCore import Qt, QUrl, QRectF, QRect, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QColor, QMovie, QPixmap, QImage
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from core import ROOT

class GlassShell(QWidget):
    def __init__(self):
        super().__init__(objectName='shell')
        self.transparency = 0
        self.frame = QImage()
        self.watermark = QMovie(str(ROOT/'assets/media/watermark.gif'))
        self.watermark.setCacheMode(QMovie.CacheMode.CacheAll)
        self.watermark.frameChanged.connect(self.on_frame)
        self.watermark.start()

    def on_frame(self, index):
        self.frame = self.watermark.currentImage()
        self.update()

    def set_transparency(self, value):
        self.transparency = max(0,min(100,int(value)))
        self.update()

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        path = QPainterPath(); path.addRoundedRect(rect,14,14)
        painter.setClipPath(path)
        alpha = 1-self.transparency/100
        painter.fillPath(path,QColor(17,18,20,round(255*alpha)))
        if not self.frame.isNull() and alpha:
            # Fit, don't stretch or crop. Draw behind every child widget.
            size = self.frame.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            painter.setOpacity(.085*alpha)
            painter.drawImage(target,self.frame)
        painter.setOpacity(1); painter.setClipping(False)
        painter.setPen(QColor('#3b3b3e')); painter.drawPath(path)

class SniffySprite(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedSize(36,36)
        self.pixmap = QPixmap()
        self.frame_cache = {}
        self.movie = QMovie(str(ROOT/'assets/media/sniffy.gif'))
        self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self.movie.frameChanged.connect(self.on_frame)
        self.setToolTip('Sniffy — your suspiciously familiar capture companion')
        self.movie.start()

    def on_frame(self,index):
        if index not in self.frame_cache:
            image = self.movie.currentImage().convertToFormat(QImage.Format.Format_ARGB32)
            # Runtime chroma key. Preserve black pixel outlines; remove the yellow matte.
            for y in range(image.height()):
                for x in range(image.width()):
                    colour = image.pixelColor(x,y)
                    if colour.red()>190 and colour.green()>190 and colour.blue()<90:
                        colour.setAlpha(0); image.setPixelColor(x,y,colour)
            self.frame_cache[index] = QPixmap.fromImage(image)
        self.pixmap = self.frame_cache[index]
        self.update()

    def paintEvent(self,event):
        if self.pixmap.isNull(): return
        painter = QPainter(self)
        # Nearest-neighbour scaling keeps the original pixel edges sharp.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
        size = self.pixmap.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        painter.drawPixmap((self.width()-size.width())//2,(self.height()-size.height())//2,
            self.pixmap.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation))

class SniffyCompanion(QWidget):
    def __init__(self,settings,parent=None):
        super().__init__(parent)
        self.settings = settings
        self.tip_open = False
        row = QHBoxLayout(self); row.setContentsMargins(0,0,0,0); row.setSpacing(10)
        self.sprite = SniffySprite(self); row.addWidget(self.sprite,0,Qt.AlignmentFlag.AlignTop)
        self.bubble = QWidget(objectName='sniffyBubble')
        layout = QVBoxLayout(self.bubble); layout.setContentsMargins(9,7,9,7); layout.setSpacing(6)
        self.dialogue = QLabel(); self.dialogue.setWordWrap(True); self.dialogue.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.dialogue)
        self.dismiss = QPushButton('[ GOT IT ]'); self.dismiss.clicked.connect(self.dismiss_tip)
        layout.addWidget(self.dismiss,0,Qt.AlignmentFlag.AlignRight)
        row.addWidget(self.bubble,1)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.quiet)
        self.setVisible(not settings.value('hide_sniffy',False,type=bool))
        if not settings.value('tips_seen',False,type=bool): self.show_tips()
        else: self.quiet()

    def show_tips(self):
        self.setVisible(True); self.settings.setValue('hide_sniffy',False)
        self.tip_open = True; self.timer.stop(); self.dismiss.show(); self.bubble.show()
        self.dialogue.setText("SNIFFY\nLooks like you're trying to save a stream. Legally, I'm a skull.\n\nPaste an M3U8 or enter a Kick name → SNIFF → pick a size → SAVE.")
        QTimer.singleShot(0,self.fit_dialogue)

    def dismiss_tip(self):
        self.settings.setValue('tips_seen',True); self.tip_open = False; self.dismiss.hide()
        self.say('Understood. Folding myself into the system tray emotionally.')

    def say(self,text):
        if self.tip_open or self.settings.value('hide_sniffy',False,type=bool): return
        self.dialogue.setText('SNIFFY  //  '+text); self.dismiss.hide(); self.bubble.show()
        QTimer.singleShot(0,self.fit_dialogue)
        self.timer.start(8000)

    def quiet(self):
        if not self.tip_open:
            self.dialogue.setText('SNIFFY'); self.dismiss.hide(); self.bubble.hide()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        QTimer.singleShot(0,self.fit_dialogue)

    def fit_dialogue(self):
        if not self.bubble.isVisible(): return
        width=max(120,self.width()-self.sprite.width()-30)
        height=self.dialogue.fontMetrics().boundingRect(QRect(0,0,width,10000),Qt.TextFlag.TextWordWrap,self.dialogue.text()).height()
        self.dialogue.setMinimumHeight(height+4)

    def set_hidden(self,hidden):
        self.settings.setValue('hide_sniffy',hidden); self.setVisible(not hidden)
        if hidden: self.movie_pause()
        else: self.sprite.movie.start()

    def movie_pause(self): self.sprite.movie.setPaused(True)
