import sys
from PyQt5.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
label = QLabel('Hello, Raspberry Pi with PyQt5!')
label.show()
sys.exit(app.exec_())
