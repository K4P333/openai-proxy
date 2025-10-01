# IACT.py modificado para funcionar con server.py
import sys, os, io, base64, requests, uuid, hashlib, socket, platform
from PIL import ImageGrab
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, QAction, 
                             QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QInputDialog, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QCursor, QPainter, QPen, QColor, QBrush

# URLs
BACKEND_ASK = "http://127.0.0.1:8000/ask"
ACTIVATE_URL = "http://127.0.0.1:8000/activate"

SHORTCUT_KEY = "Alt+Shift+S"
RESULT_POPUP_DURATION = 10000  # ms

# -----------------------------------------
# Helpers
# -----------------------------------------
def get_device_id():
    mac = hex(uuid.getnode())
    hostname = socket.gethostname()
    system = platform.platform()
    raw = f"{mac}-{hostname}-{system}"
    return hashlib.sha256(raw.encode()).hexdigest()

def save_device_token(token):
    p = os.path.join(os.path.expanduser("~"), ".mi_app_token")
    with open(p, "w") as f:
        f.write(token)

def load_device_token():
    p = os.path.join(os.path.expanduser("~"), ".mi_app_token")
    if os.path.exists(p):
        return open(p).read().strip()
    return None

def activate_license_flow_gui(parent, license_key):
    device_id = get_device_id()
    try:
        r = requests.post(ACTIVATE_URL, json={"license_key": license_key, "device_id": device_id}, timeout=20)
        if r.status_code == 200:
            token = r.json().get("device_token")
            save_device_token(token)
            return True, "Activated"
        else:
            return False, r.text
    except Exception as e:
        return False, str(e)

# -----------------------------------------
# Qt GUI
# -----------------------------------------
class SignalHandler(QObject):
    capture_triggered = pyqtSignal()

class SnippingWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setWindowState(Qt.WindowFullScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        self.begin = QPoint()
        self.end = QPoint()
        self.is_capturing = False
        cursor_pixmap = QPixmap(16,16)
        cursor_pixmap.fill(Qt.transparent)
        painter = QPainter(cursor_pixmap)
        painter.setPen(QPen(Qt.black,1))
        painter.drawLine(7,0,7,5)
        painter.drawLine(7,10,7,15)
        painter.drawLine(0,7,5,7)
        painter.drawLine(10,7,15,7)
        painter.end()
        self.setCursor(QCursor(cursor_pixmap,7,7))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def paintEvent(self, event):
        qp = QPainter(self)
        overlay = QColor(0,0,0,1)
        qp.fillRect(self.rect(), overlay)
        if not self.begin.isNull() and not self.end.isNull():
            rect = QRect(self.begin,self.end)
            qp.setPen(QPen(Qt.lightGray,0.5))
            qp.setBrush(QBrush(QColor(0,0,0,0)))
            qp.drawRect(rect)

    def mousePressEvent(self,event):
        if event.button() == Qt.LeftButton:
            self.begin = event.pos()
            self.end = event.pos()
            self.is_capturing = True
            self.update()

    def mouseMoveEvent(self,event):
        if self.is_capturing:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self,event):
        if event.button() == Qt.LeftButton and self.is_capturing:
            self.is_capturing = False
            self.hide()
            QTimer.singleShot(100, self.capture_screenshot)

    def capture_screenshot(self):
        x1,y1 = min(self.begin.x(),self.end.x()), min(self.begin.y(),self.end.y())
        x2,y2 = max(self.begin.x(),self.end.x()), max(self.begin.y(),self.end.y())
        if x2-x1>0 and y2-y1>0:
            screenshot = ImageGrab.grab(bbox=(x1,y1,x2,y2))
            self.send_to_backend(screenshot)
        else:
            self.close()

    def send_to_backend(self, image):
        try:
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            base64_image = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')

            device_token = load_device_token()
            if not device_token:
                license_key, ok = QInputDialog.getText(self,"License Key","Introduce tu license key:")
                if not ok or not license_key:
                    QMessageBox.critical(self,"Error","No se introdujo license key. Cerrando.")
                    self.close()
                    return
                ok2, msg = activate_license_flow_gui(self, license_key)
                if not ok2:
                    QMessageBox.critical(self,"Error",f"Activación fallida:\n{msg}")
                    self.close()
                    return
                device_token = load_device_token()

            headers = {"Authorization": f"Bearer {device_token}"}
            payload = {"base64_image": base64_image}

            r = requests.post(BACKEND_ASK, json=payload, headers=headers, timeout=60)
            if r.status_code==200:
                data = r.json()
                answer = data.get("answer","(sin respuesta)")
                self.show_result_popup(answer)
            else:
                self.show_result_popup(f"Error: {r.status_code}\n{r.text}")

        except Exception as e:
            self.show_result_popup(f"Error: {str(e)}")
        self.close()

    def show_result_popup(self,text):
        self.result_widget = ResultPopup(text)
        self.result_widget.show()

# -----------------------------------------
class ResultPopup(QWidget):
    def __init__(self,text):
        super().__init__()
        self.setup_ui(text)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        QTimer.singleShot(RESULT_POPUP_DURATION, self.close)

    def setup_ui(self,text):
        layout = QVBoxLayout()
        self.setLayout(layout)
        container = QWidget()
        container.setStyleSheet("""
            background-color: rgba(255,255,255,220);
            border-radius:10px;
            color:black;
            font-size:10px;
        """)
        container_layout = QVBoxLayout(container)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("font-size:12px;")
        container_layout.addWidget(label)
        layout.addWidget(container)
        self.setFixedWidth(300)
        self.adjustSize()

# -----------------------------------------
class ScreenCaptureApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.setup_tray_icon()

    def setup_tray_icon(self):
        icon = QIcon(QPixmap(32,32))
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(icon)
        self.tray.setVisible(True)

        menu = QMenu()
        menu_capture = QAction("Capture Screen", self.app)
        menu_capture.triggered.connect(self.start_capture)
        menu.addAction(menu_capture)

        menu_exit = QAction("Exit", self.app)
        menu_exit.triggered.connect(self.app.quit)
        menu.addAction(menu_exit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.showMessage("Screen Capture Tool","App running. Click tray icon to capture.",QSystemTrayIcon.Information,3000)

    def tray_activated(self,reason):
        if reason==QSystemTrayIcon.Trigger:
            self.start_capture()

    def start_capture(self):
        self.snipper = SnippingWidget()
        self.snipper.show()

    def run(self):
        return self.app.exec_()

if __name__=="__main__":
    app = ScreenCaptureApp()
    sys.exit(app.run())
