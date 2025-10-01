import sys
import os
import io
import json
import base64
import requests
from PIL import Image, ImageGrab
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction, 
                             QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, QSize, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QCursor, QPainter, QPen, QColor, QKeySequence, QBrush

# Configuracion
SHORTCUT_KEY = "Alt+Shift+S"
RESULT_POPUP_DURATION = 10000  # ms

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

        cursor_pixmap = QPixmap(16, 16)
        cursor_pixmap.fill(Qt.transparent)
        painter = QPainter(cursor_pixmap)
        painter.setPen(QPen(Qt.black, 1))
        painter.drawLine(7, 0, 7, 5)
        painter.drawLine(7, 10, 7, 15)
        painter.drawLine(0, 7, 5, 7)
        painter.drawLine(10, 7, 15, 7)
        painter.end()
        self.setCursor(QCursor(cursor_pixmap, 7, 7))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def paintEvent(self, event):
        qp = QPainter(self)
        overlay = QColor(0, 0, 0, 1)
        qp.fillRect(self.rect(), overlay)
        if not self.begin.isNull() and not self.end.isNull():
            rect = QRect(self.begin, self.end)
            qp.setPen(QPen(Qt.lightGray, 0.5))
            qp.setBrush(QBrush(QColor(0, 0, 0, 0)))
            qp.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.begin = event.pos()
            self.end = event.pos()
            self.is_capturing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_capturing:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_capturing:
            self.is_capturing = False
            self.hide()
            QTimer.singleShot(100, lambda: self.capture_screenshot())

    def capture_screenshot(self):
        x1, y1 = min(self.begin.x(), self.end.x()), min(self.begin.y(), self.end.y())
        x2, y2 = max(self.begin.x(), self.end.x()), max(self.begin.y(), self.end.y())
        if x2 - x1 > 0 and y2 - y1 > 0:
            screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            self.send_to_backend(screenshot)
        else:
            self.close()

    # Reemplaza la funcion send_to_openai por esta:
    def send_to_backend(self, image):
        try:
            import io, base64, requests

            # Convertir imagen a base64
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            base64_image = base64.b64encode(img_byte_arr).decode('utf-8')

            # Configura tu servidor local y usuario
            BACKEND_URL = "http://127.0.0.1:8000/ask"  # dirección del backend
            USER_ID = "nacho"                          # tu usuario
            USER_TOKEN = "clave_usuario123"            # token asignado por backend

            # Payload que enviamos al backend
            payload = {
                "user_id": USER_ID,
                "token": USER_TOKEN,
                "image": base64_image
            }

            # Petición POST al backend
            r = requests.post(BACKEND_URL, json=payload, timeout=60)

            if r.status_code == 200:
                data = r.json()
                answer = data.get("answer", "(sin respuesta)")
                self.show_result_popup(answer)
            else:
                self.show_result_popup(f"Error: {r.status_code}\n{r.text}")

        except Exception as e:
            self.show_result_popup(f"Error: {str(e)}")

        self.close()


    def show_result_popup(self, text):
        self.result_widget = ResultPopup(text)
        self.result_widget.show()

class ResultPopup(QWidget):
    def __init__(self, text):
        super().__init__()
        self.setup_ui(text)
        self.setup_window_properties()
        QTimer.singleShot(RESULT_POPUP_DURATION, self.close)

    def setup_window_properties(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        screen_geometry = QApplication.desktop().availableGeometry()
        self.move(screen_geometry.width() - self.width() - 20, screen_geometry.height() - self.height() - 20)

    def setup_ui(self, text):
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        container = QWidget()
        container.setStyleSheet("""
            background-color: rgba(255, 255, 255, 200);
            border-radius: 10px;
            color: black;
            font-size: 10px;
        """)
        container_layout = QVBoxLayout(container)

        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet("font-size: 12px;")
        container_layout.addWidget(text_label)

        button_layout = QHBoxLayout()
        close_button = QPushButton("×")
        close_button.setMaximumSize(20, 20)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 30);
                border-radius: 10px;
                color: black;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 50);
            }
        """)
        close_button.clicked.connect(self.close)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        container_layout.addLayout(button_layout)

        main_layout.addWidget(container)
        self.setFixedWidth(300)
        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.close()

class ScreenCaptureApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.signal_handler = SignalHandler()
        self.signal_handler.capture_triggered.connect(self.start_capture)
        self.setup_tray_icon()
        self.register_global_shortcut()

    def setup_tray_icon(self):
        icon = self.create_tray_icon()
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(icon)
        self.tray.setVisible(True)

        menu = QMenu()
        capture_action = QAction("Capture Screen", self.app)
        capture_action.triggered.connect(self.start_capture)
        menu.addAction(capture_action)

        exit_action = QAction("Exit", self.app)
        exit_action.triggered.connect(self.app.quit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)

    def create_tray_icon(self):
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(0, 120, 215), 2))
        painter.drawRect(8, 8, 16, 16)
        painter.drawLine(8, 8, 24, 24)
        painter.drawLine(24, 8, 8, 24)
        painter.end()
        return QIcon(pixmap)

    def register_global_shortcut(self):
        self.shortcut = QKeySequence(SHORTCUT_KEY)
        print(f"Registered shortcut: {SHORTCUT_KEY}")
        print("Note: This demo version doesn't implement actual global shortcuts.")
        print("Press the tray icon to trigger screen capture.")

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.start_capture()

    def start_capture(self):
        self.snipper = SnippingWidget()
        self.snipper.show()

    def run(self):
        self.show_startup_message()
        self.setup_tray_icon()
        return self.app.exec_()

    def show_startup_message(self):
        self.tray.showMessage(
            "Screen Capture Tool",
            f"App is running. Use {SHORTCUT_KEY} or click the tray icon to capture.",
            QSystemTrayIcon.Information,
            3000
        )

if __name__ == "__main__":
    app = ScreenCaptureApp()
    sys.exit(app.run())