from PyQt6.QtWidgets import (QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QTextEdit,
                             QScrollArea, QWidget, QListWidget, QComboBox, QTreeWidget, QTreeWidgetItem, QGridLayout)
from PyQt6.QtCore import Qt, QFileSystemWatcher

import style_sheet as ss


from Backend_lib.Linux import hci_commands as hci
class TestControllerUI(QWidget):
    """
    UI component for displaying and executing HCI commands for a Bluetooth controller.

    Allows dynamic construction of command parameter inputs, executes commands through a backend controller,
    and displays real-time HCI dump logs using QFileSystemWatcher.
    """

    def __init__(self, controller, log, bluez_logger, back_callback):
        """
        Initializes the TestControllerUI widget.

        Args:
            controller: An instance of the backend controller handling Bluetooth communication.
            log: Logger instance to log debug or operational messages.
            bluez_logger: An instance of BluezLogger used for handling HCI dump logs.
            back_callback (function): Callback function to return to the previous UI screen.

        returns:
            None
        """
        super().__init__()
        self.controller = controller
        self.log = log
        self.back_callback = back_callback
        self.bluez_logger = bluez_logger
        self.scroll = None
        self.content_layout = None
        self.content_widget = None
        self.handle = None
        self.ocf = None
        self.ogf = None
        self.command_input_layout = None
        self.commands_list_tree_widget = None
        self.empty_list = None
        self.logs_layout = None
        self.dump_log_output = None
        self.file_watcher = None

        self.controller_ui()

    def controller_ui(self):
        """
        Constructs the main UI layout, including the command tree,
        input fields, dump log viewer, and back button.

        args: None
        returns: None

        """
        main_layout = QGridLayout(self)  # Pass self to the QGridLayout
        main_layout.setColumnStretch(0, 1)
        main_layout.setColumnStretch(1, 1)
        main_layout.setColumnStretch(2, 1)

        # Left column: Command tree
        vertical_layout = QGridLayout()
        self.commands_list_tree_widget = QTreeWidget()
        self.commands_list_tree_widget.setHeaderLabels(["HCI Commands"])
        self.commands_list_tree_widget.setStyleSheet(ss.cmd_list_widget_style_sheet)

        items = []
        for item in list(hci.hci_commands.keys()):
            _item = QTreeWidgetItem([item])
            for value in list(getattr(hci, item.lower().replace(' ', '_')).keys()):
                child = QTreeWidgetItem([value])
                _item.addChild(child)
            items.append(_item)

        self.commands_list_tree_widget.insertTopLevelItems(0, items)
        self.commands_list_tree_widget.clicked.connect(self.run_hci_cmd)

        vertical_layout.addWidget(self.commands_list_tree_widget, 0, 0)
        vertical_layout.setRowStretch(0, 1)
        vertical_layout.setRowStretch(1, 1)
        main_layout.addLayout(vertical_layout, 0, 0)

        # Middle column: Input area for selected command parameters
        self.command_input_layout = QVBoxLayout()
        self.empty_list = QListWidget()
        self.empty_list.setStyleSheet("background: transparent; border: 2px solid black;")
        self.command_input_layout.addWidget(self.empty_list)
        main_layout.addLayout(self.command_input_layout, 0, 1)

        # Right column: Dump logs
        self.logs_layout = QVBoxLayout()
        logs_label = QLabel("DUMP LOGS")
        logs_label.setStyleSheet("border: 2px solid black; color: black; font-size:18px; font-weight: bold;")
        logs_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.logs_layout.addWidget(logs_label)

        self.dump_log_output = QTextEdit()
        # Remove setMaximumWidth(700) as it can restrict the width of the log output
        # self.dump_log_output.setMaximumWidth(700)
        self.dump_log_output.setReadOnly(True)
        self.dump_log_output.setStyleSheet("background: transparent;color: black;border: 2px solid black;")

        # Start HCI dump logging
        self.bluez_logger.start_dump_logs(interface=self.controller.interface, log_text_browser=self.dump_log_output)

        self.bluez_logger.logfile_fd = open(self.bluez_logger.hcidump_log_name, 'r')
        if self.bluez_logger.logfile_fd:
            content = self.bluez_logger.logfile_fd.read()
            self.dump_log_output.append(content)
            self.bluez_logger.file_position = self.bluez_logger.logfile_fd.tell()
            self.logs_layout.addWidget(self.dump_log_output)
            
        '''
        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.addPath(self.bluez_logger.hcidump_log_name)
        self.file_watcher.fileChanged.connect(self.update_log)
        '''
        # Add the logs_layout to the main_layout in column 2, row 0
        main_layout.addLayout(self.logs_layout, 0, 2)

        # Back button
        back_button = QPushButton("Back")
        back_button.setFixedSize(100, 40)
        back_button.setStyleSheet("""
                    QPushButton {
                        background-color: black;
                        color: white;
                        border: 2px solid gray;
                        padding: 6px;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #333333;
                    }
                """)
        back_button.clicked.connect(self.back_callback)

        # Create a horizontal layout for the back button and align it to the right
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)  # This will push the button to the right
        button_layout.addWidget(back_button)

        main_layout.addLayout(button_layout, 1, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        # Set a row stretch for the row containing the main content to push the button to the bottom
        main_layout.setRowStretch(0, 1)  # Give all vertical space to the content
        main_layout.setRowStretch(1, 0)  # The row with the button takes minimal space

        self.setLayout(main_layout)

    def update_log(self):
        """
        Updates the log output widget when the log file changes.

        args: None
        returns: None
        """
        if self.bluez_logger.logfile_fd is None:
            return
        self.bluez_logger.logfile_fd.seek(self.bluez_logger.file_position)
        content = self.bluez_logger.logfile_fd.read()
        self.bluez_logger.file_position = self.bluez_logger.logfile_fd.tell()
        self.dump_log_output.append(content)

    def run_hci_cmd(self, text_selected):
        """
        Builds the dynamic UI input form for a selected HCI command.

        Args:
            text_selected (QModelIndex): The tree view item selected by the user.
        returns:
            None
        """
        if text_selected.parent().data():
            self.ocf = text_selected.parent().data()
            self.ogf = text_selected.data()
        else:
            self.ocf = text_selected.data()
            return

        if not self.scroll:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)

        if self.content_layout:
            while self.content_layout.count():
                item = self.content_layout.itemAt(0).widget()
                self.content_layout.removeWidget(item)
                if item is not None:
                    item.deleteLater()
            self.content_widget.hide()

        self.empty_list.hide()
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)

        parameters = getattr(hci, self.ocf.lower().replace(' ', '_'))[self.ogf][1]
        index = 0

        for parameter in parameters:
            key = list(parameter.keys())[0]
            default_val = list(parameter.values())[0]
            label = QLabel(key)
            label.setStyleSheet("color: black; font-size:12px;")
            label.setMaximumHeight(30)

            if 'Connection_Handle' in key:
                setattr(self, key, QComboBox())
                combo_box = getattr(self, key)
                combo_box.setPlaceholderText("Connection Handles")
                combo_box.addItems(list(self.controller.get_connection_handles().keys()))
                combo_box.currentTextChanged.connect(self.current_text_changed)
                combo_box.setMaximumHeight(30)
            else:
                setattr(self, key, QTextEdit(default_val))
                widget = getattr(self, key)
                widget.setMaximumHeight(30)
                if hasattr(self, f"{self.ogf}_values"):
                    values = getattr(self, f"{self.ogf}_values")
                    if values:
                        widget.setText(values[index])
                        index += 1

            self.content_layout.addWidget(label)
            self.content_layout.addWidget(getattr(self, key))
            self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if not parameters:
            no_params_widget = QTextEdit("No parameters")
            no_params_widget.setMaximumHeight(30)
            no_params_widget.setReadOnly(True)
            self.content_layout.addWidget(no_params_widget)
            self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Execute button
        execute_btn = QPushButton("Execute")
        execute_btn.setStyleSheet(
            "font-size: 18px; color: white; background: transparent; padding: 10px;"
        )
        execute_btn.clicked.connect(self.execute_hci_cmd)
        self.content_layout.addWidget(execute_btn)

        if parameters:
            reset_btn = QPushButton("Reset to default")
            reset_btn.setStyleSheet(
                "font-size: 18px; color: white; background: transparent; padding: 10px;"
            )
            reset_btn.clicked.connect(self.reset_default_params)
            self.content_layout.addWidget(reset_btn)

        self.scroll.setWidget(self.content_widget)
        self.command_input_layout.addWidget(self.scroll)

    def current_text_changed(self, text):
        """
        Triggered when the user selects a different handle in the combo box.

        Args:
            text (str): The currently selected connection handle.
        returns:
            None
        """
        self.handle = text

    def execute_hci_cmd(self):
        """
        Gathers parameters from the UI and sends the HCI command via the backend controller.

        args: None
        returns: None
        """
        parameters = []
        self.controller.get_connection_handles()

        for parameter in getattr(hci, self.ocf.lower().replace(' ', '_'))[self.ogf][1]:
            key = list(parameter.keys())[0]

            if isinstance(getattr(self, key), QComboBox):
                parameters.append(self.controller.handles[self.handle])
                self.handle = None
                continue

            text_value = getattr(self, key).toPlainText()
            if text_value == 'None':
                break
            parameters.append(text_value)

        setattr(self, f"{self.ogf}_values", parameters)
        self.log.debug(f"{self.ocf=} {self.ogf=} {parameters=}")
        self.controller.run_hci_cmd(self.ocf, self.ogf, parameters)

    def reset_default_params(self):
        """
        Resets all command input fields to their default values.

        args: None
        returns: None
        """
        parameters = getattr(hci, self.ocf.lower().replace(' ', '_'))[self.ogf][1]
        for parameter in parameters:
            key = list(parameter.keys())[0]
            default_val = list(parameter.values())[0]
            getattr(self, key).setText(default_val)