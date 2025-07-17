import sys
import os
import subprocess
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QIcon
from PyQt6.QtGui import QPalette
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QScrollArea
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QGridLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWidgets import QToolButton
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget


import style_sheet as ss
from logger import Logger
from utils import run

from Backend_lib.Linux.bluez_utils import BluezLogger
from UI_lib.controller_lib import Controller
from UI_lib.uihost import TestApplication
#from UI_lib.test_host import TestApplication
from UI_lib.test_controller import TestControllerUI
from UI_lib.agent_runner import AgentRunner
from Backend_lib.Linux.daemons import BluezServices
from Backend_lib.Linux.bluez_test import  BluetoothDeviceManager


def kill_previous_processes():
    """
    Forcefully kills any running instances of dbus-daemon and pulseaudio to prevent conflicts
    when restarting the application.

    Args: None
    returns: None
    """
    subprocess.run("kill -9 /usr/local/bluez/dbus-1.12.20/bin/dbus-daemon", shell=True)
    subprocess.run("kill -9 /usr/local/bluez/pulseaudio-13.0_for_bluez-5.65/bin/pulseaudio", shell=True)


class CustomDialog(QDialog):

    """ Dialog window shown when no controller is selected but an action is attempted.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Warning!")
        layout = QVBoxLayout()
        message = QLabel("Select the controller!!")
        layout.addWidget(message)
        self.setLayout(layout)

    def showEvent(self, event):
        """ Centers the dialog box on top of the parent widget when displayed

         Args :
            event (QShowEvent) : Qt show event object

         returns: None
         """
        parent_geometry = self.parent().geometry()
        dialog_geometry = self.geometry()
        x = (parent_geometry.x() + (parent_geometry.width() - dialog_geometry.width()) // 2)
        y = (parent_geometry.y() + (parent_geometry.height() - dialog_geometry.height()) // 2)
        self.move(x, y)
        super().showEvent(event)



class BluetoothUIApp(QMainWindow):
    """
    Main window for the Bluetooth testing UI application.
    Handles controller discovery,logger setup and UI navigation between modules

    """
    def __init__(self):
        """
        Initializes the main Bluetooth UI application.
        args: None
        returns: None
        """
        super().__init__()
        self.log=Logger("UI")
        self.logger_init()
        self.bluez_logger = BluezLogger(self.log_path)
        self.bluez_logger.start_dbus_service()
        self.bluez_logger.start_bluetoothd_logs()
        self.bluez_logger.start_pulseaudio_logs()

        self.agent_runner = AgentRunner()
        self.agent_registered=False
        self.register_agent_once()


        self.scroll = None
        self.content_layout = None
        self.content_widget = None
        self.controller = Controller(self.log)
        self.handle = None
        self.bluez_logger.controller = self.controller
        self.ocf = None
        self.ogf = None
        self.file_watcher = None
        self.dump_log_output = None
        self.empty_list = None
        self.command_input_layout = None
        self.commands_list_tree_widget = None
        self.controllers_list_widget = None
        self.test_application = None
        self.test_controller = None
        self.devices_button = None
        self.previous_row_selected = None
        self.previous_cmd_list = []
        self.controllers_list_layout = None
        self.test_application_widget = None
        self.list_controllers()


    def register_agent_once(self):
        """
        Starts the agent runner only once to avoid multiple registrations.
        Logs agent registration success or failure

        args: None
        returns: None
        """
        try:
            self.agent_runner.start()
            self.agent_registered = True
            self.log.info("Agent registered")
        except Exception as e:
            self.log.error(e)

    def logger_init(self):
        """ Creates a timestamped log directory and sets up the logger
         This ensures every app session logs to its own unique folder

         args: None
         returns: None
         """
        log_time = time.strftime('%Y_%m_%d_%H_%M_%S', time.localtime(time.time()))
        base_log_dir=os.path.join('/root/Desktop/BT_BLE_Automation/test_automation/UI', 'logs')
        os.makedirs(base_log_dir, exist_ok=True)
        self.log_path = os.path.join(base_log_dir, f"{log_time}logs")
        os.makedirs(self.log_path, exist_ok=True)
        if not os.path.exists(self.log_path):
            os.mkdir(self.log_path)
        self.log.setup_logger_file(self.log_path)

    def closeEvent(self, a0):
        """
        Logs the window close event

        args:
            a0(QCloseEvent): The event triggered on application close.
        returns:
            None
        """
        self.log.debug(f"closing {a0}")

    def list_controllers(self):
        """
        Creates and displays the main UI layout to list Bluetooth controllers and provide navigation options.

        args: None
        returns: None
        """
        self.setWindowTitle("Bluetooth UI Application")

        palette = QPalette()
        self.background_path = "/root/Desktop/BT_BLE_Automation/test_automation/images/main_window_background.jpg"
        self.setAutoFillBackground(True)
        self.update_background()
        main_layout = QVBoxLayout()
        main_layout.addStretch(1)
        application_label_layout = QHBoxLayout()
        application_label = QLabel("BLUETOOTH TEST APPLICATION")
        font = QFont("Aptos Black", 28, QFont.Weight.Bold)
        application_label.setFont(font)
        application_label.setStyleSheet("color: black;")
        application_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        application_label_layout.addStretch(1)
        application_label_layout.addWidget(application_label)
        application_label_layout.addStretch(1)
        main_layout.addLayout(application_label_layout)
        main_layout.addStretch(1)
        self.controllers_list_layout = QHBoxLayout()
        self.controllers_list_widget = QListWidget()
        self.controllers_list_widget.setMinimumSize(800, 400)

        self.add_items(
            self.controllers_list_widget,
            list(self.controller.get_controllers_connected().keys()),
            Qt.AlignmentFlag.AlignHCenter
        )
        self.controllers_list_widget.setStyleSheet(ss.list_widget_style_sheet)
        self.controllers_list_widget.itemClicked.connect(self.controller_selected)
        self.controllers_list_layout.addStretch(1)
        self.controllers_list_layout.addWidget(self.controllers_list_widget)
        self.controllers_list_layout.addStretch(1)
        main_layout.addLayout(self.controllers_list_layout)
        main_layout.addStretch(1)
        buttons_layout = QGridLayout()
        button_layout = QHBoxLayout()
        self.test_controller = QToolButton()
        self.test_controller.setText("Test Controller")
        #self.test_controller.setGeometry(100, 100, 200, 100)
        self.test_controller.setFixedSize(200, 80)
        self.test_controller.clicked.connect(self.check_controller_selected)
        self.test_controller.setStyleSheet(ss.select_button_style_sheet)
        button_layout.addWidget(self.test_controller)
        buttons_layout.addLayout(button_layout, 0, 0)
        button_layout1 = QHBoxLayout()
        self.test_application = QToolButton()
        self.test_application.setText("Test Host")
        self.test_application.clicked.connect(self.check_application_selected)
        #self.test_application.setGeometry(100, 100, 200, 100)
        self.test_application.setFixedSize(200, 80)
        self.test_application.setStyleSheet(ss.select_button_style_sheet)
        button_layout1.addWidget(self.test_application)
        buttons_layout.addLayout(button_layout1, 0, 1)
        main_layout.addLayout(buttons_layout)
        main_layout.addStretch(1)
        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)
        self.test_controller.show()
        self.test_application.show()

    def update_background(self):
        pixmap = QPixmap(self.background_path)
        scaled_pixmap = pixmap.scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        palette = self.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(scaled_pixmap))
        self.setPalette(palette)

    def resizeEvent(self, event):
        self.update_background()  # Re-apply background on resize
        super().resizeEvent(event)



    def add_items(self, widget, items, align):
        """
        Adds a list of items to a QListWidget with a specified alignment.

        Args:
             widget (QWidget): The target widget to populate.
             items (list[str]): List of string items to be added.
             align (Qt.AlignmentFlag): Alignment setting for each item.

        returns: None
        """

        for test_item in items:
            item = QListWidgetItem(test_item)
            item.setTextAlignment(align)
            widget.addItem(item)

    def controller_selected(self, address):
        """
        Handles logic when  a controller is selected from the list. Stores the bd_address and interface.

        Args:
            address: selected controller bd_address.

        returns: None

        """
        controller=address.text()
        self.log.info(f"Controller Selected: {controller}")
        self.controller.bd_address = controller

        if controller in self.controller.controllers_list:
            self.controller.interface=self.controller.controllers_list[controller]
        bluetooth_device_manager=BluetoothDeviceManager(interface=self.controller.interface)
        #run(self.log, f"hciconfig -a {self.controller.interface} up")
        bluetooth_device_manager.power_on_adapter()


        if self.previous_row_selected:
            self.controllers_list_widget.takeItem(self.previous_row_selected)


        row = self.controllers_list_widget.currentRow()
        item = QListWidgetItem(self.controller.get_controller_interface_details())
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.controllers_list_widget.insertItem(row + 1, item)
        self.previous_row_selected = row + 1



    def check_controller_selected(self):
        """
        Checks if a controller is selected before navigating to the controller testing screen.
        Displays a warning dialog if None is selected.

        args: None
        returns: None
        """
        if self.controller.bd_address:
            self.setWindowTitle('Test Controller')
            self.setCentralWidget(TestControllerUI(self.controller, self.log, self.bluez_logger, back_callback=self.show_main))


        else:
            dlg = CustomDialog(self)
            if not dlg.exec():
                self.list_controllers()

    def check_application_selected(self):
        """
        Checks if controller is selected before navigating to the application testing screen.
        Displays a warning dialog if None is selected.

        args: None
        returns: None
        """
        if self.controller.bd_address:
            self.test_application_clicked()
        else:
            dlg = CustomDialog(self)
            if not dlg.exec():
                self.list_controllers()

    def current_text_changed(self, text):
        """
        Stores the currently selected text for HCI command execution.

        args:
            The selected text from the dropdown
        returns:
            None
        """
        self.handle = text


    def test_application_clicked(self):
        """
        Launches the test Host window inside the main application using the selected controller.

        args: None
        returns: None
        """
        if self.centralWidget():
            self.centralWidget().deleteLater()


        run(self.log, f"hciconfig -a {self.controller.interface} up")
        self.setWindowTitle('Test Host')
        self.setCentralWidget(TestApplication(interface=self.controller.interface, log_path=self.log_path,
                                                       back_callback=self.show_main))

    def show_main(self):
        """
        Navigates the UI back to the main controller list screen from test views.
        args: None
        returns: None

        """
        #if self.centralWidget():
         #   self.centralWidget().deleteLater()
        self.list_controllers()

if __name__ == "__main__":
    kill_previous_processes()
    app = QApplication(sys.argv)
    app_window = BluetoothUIApp()
    app_window.setWindowIcon(QIcon('/root/Desktop/BT_BLE_Automation/test_automation/images/app_icon.jpg'))
    app_window.showMaximized()


    def stop_logs():
        """
        Stops all active logging processes before application quit (bluetoothd, pulseaudio, hcidump)
        args: None
        returns: None
        """
        app_window.bluez_logger.stop_pulseaudio_logs()
        app_window.bluez_logger.stop_bluetoothd_logs()
        app_window.bluez_logger.stop_dump_logs()

    app.aboutToQuit.connect(stop_logs)
    sys.exit(app.exec())


