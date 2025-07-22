def test_application_clicked(self):
    self.bluetooth_device_manager = BluetoothDeviceManager(self.interface)
    self.bluez_logger = BluetoothDeviceManager(log_path=self.log_path)
    self.restart_daemons()

    self.main_grid_layout = QGridLayout()

    bold_font = QFont()
    bold_font.setBold(True)

    # Profiles List
    self.profiles_list_widget = QListWidget()
    self.profiles_list_label = QLabel("List of Profiles:")
    self.profiles_list_label.setFont(bold_font)
    self.profiles_list_label.setStyleSheet("color:black")
    self.main_grid_layout.addWidget(self.profiles_list_label, 0, 0)
    self.profiles_list_widget.addItem("GAP")
    self.profiles_list_widget.setFont(bold_font)
    self.profiles_list_widget.setStyleSheet("border: 2px solid black; color: black; background: transparent;")
    self.profiles_list_widget.itemSelectionChanged.connect(self.profile_selected)
    self.profiles_list_widget.setFixedWidth(350)
    self.main_grid_layout.addWidget(self.profiles_list_widget, 1, 0, 2, 2)

    # Controller Details
    controller_details_widget = QWidget()
    controller_details_layout = QVBoxLayout()
    controller_details_widget.setStyleSheet("border: 2px solid black; color: black; background: transparent;")
    self.main_grid_layout.addWidget(controller_details_widget, 3, 0, 8, 2)
    controller_details_layout.setContentsMargins(0, 0, 0, 0)
    controller_details_layout.setSpacing(0)

    self.bluez_logger.get_controller_details(interface=self.interface)
    self.controller.name = self.bluez_logger.name
    self.controller.bd_address = self.bluez_logger.bd_address
    self.controller.link_policy = self.bluez_logger.link_policy
    self.controller.lmp_version = self.bluez_logger.lmp_version
    self.controller.link_mode = self.bluez_logger.link_mode
    self.controller.hci_version = self.bluez_logger.hci_version
    self.controller.manufacturer = self.bluez_logger.manufacturer

    labels = [
        ("Controller Name:", self.controller.name),
        ("Controller Address:", self.controller.bd_address),
        ("Link Mode:", self.controller.link_mode),
        ("Link Policy:", self.controller.link_policy),
        ("HCI Version:", self.controller.hci_version),
        ("LMP Version:", self.controller.lmp_version),
        ("Manufacturer:", self.controller.manufacturer)
    ]
    for label, value in labels:
        layout = QHBoxLayout()
        left = QLabel(label)
        left.setFont(bold_font)
        layout.addWidget(left)
        right = QLabel(value)
        layout.addWidget(right)
        controller_details_layout.addLayout(layout)

    controller_details_widget.setLayout(controller_details_layout)
    controller_details_widget.setFixedWidth(350)

    # Profile Methods Panel
    profile_description_label = QLabel("Profile Methods or Procedures:")
    profile_description_label.setFont(bold_font)
    profile_description_label.setStyleSheet("color: black;")
    self.main_grid_layout.addWidget(profile_description_label, 0, 2)

    self.profile_description_text_browser = QTextBrowser()
    self.profile_description_text_browser.setStyleSheet("background: transparent; color: black; border: 2px solid black;")
    self.profile_description_text_browser.setFixedWidth(500)
    self.main_grid_layout.addWidget(self.profile_description_text_browser, 1, 2, 10, 2)

    # Dump Logs Tabs
    dump_logs_label = QLabel("Dump Logs:")
    dump_logs_label.setFont(bold_font)
    dump_logs_label.setStyleSheet("color: black;")
    self.main_grid_layout.addWidget(dump_logs_label, 0, 4)

    self.dump_logs_text_browser = QTabWidget()
    self.dump_logs_text_browser.setFixedWidth(400)
    self.dump_logs_text_browser.setStyleSheet("""
        QTabWidget::pane { background: transparent; border: 2px solid black; margin-top: 8px; }
        QTabBar::tab {
            background: transparent;
            color: black;
            border-top: 2px solid black;
            border-bottom: 2px solid black;
            border-left: 2px solid black;
            border-right: none;
            padding: 7px;
            height: 20px;
        }
        QTabBar::tab:last { border-right: 2px solid black; }
    """)

    tab_bar = self.dump_logs_text_browser.tabBar()
    tab_bar.setUsesScrollButtons(False)
    tab_bar.setExpanding(True)

    transparent_style = "QTextEdit { background: transparent; color: black; border: none; }"

    self.bluetoothd_log_text_browser = QTextEdit()
    self.bluetoothd_log_text_browser.setReadOnly(True)
    self.bluetoothd_log_text_browser.setStyleSheet(transparent_style)

    self.pulseaudio_log_text_browser = QTextEdit()
    self.pulseaudio_log_text_browser.setReadOnly(True)
    self.pulseaudio_log_text_browser.setStyleSheet(transparent_style)

    self.hci_dump_log_text_browser = QTextEdit()
    self.hci_dump_log_text_browser.setReadOnly(True)
    self.hci_dump_log_text_browser.setStyleSheet(transparent_style)

    self.dump_logs_text_browser.addTab(self.bluetoothd_log_text_browser, "Bluetoothd_Logs")
    self.dump_logs_text_browser.addTab(self.pulseaudio_log_text_browser, "Pulseaudio_Logs")
    self.dump_logs_text_browser.addTab(self.hci_dump_log_text_browser, "HCI_Dump_Logs")
    self.main_grid_layout.addWidget(self.dump_logs_text_browser, 1, 4, 10, 2)

    # Get log file paths from bluez_logger (BluetoothDeviceManager)
    self.bluetoothd_log_file = self.bluez_logger.start_bluetoothd_logs()
    self.pulseaudio_log_file = self.bluez_logger.start_pulseaudio_logs()
    self.hcidump_log_file = self.bluez_logger.start_dump_logs(interface=self.interface)

    # Track positions for file reading
    self.bluetoothd_pos = 0
    self.pulseaudio_pos = 0
    self.hcidump_pos = 0

    # Periodically update logs
    QTimer.singleShot(1000, self.read_logs_periodically)

    # Back button
    back_button = QPushButton("Back")
    back_button.setFixedSize(100, 40)
    back_button.setStyleSheet("""
        QPushButton {
            font-size: 16px;
            padding: 6px;
            background-color: black;
            color: white;
            border: 2px solid gray;
            border-radius: 6px;
        }
        QPushButton:hover { background-color: #333333; }
    """)
    back_button.clicked.connect(lambda: self.back_callback())
    back_button_layout = QHBoxLayout()
    back_button_layout.addWidget(back_button)
    back_button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
    self.main_grid_layout.addLayout(back_button_layout, 999, 5)

    self.setLayout(self.main_grid_layout)
    QTimer.singleShot(1000, self.load_connected_devices)


def read_logs_periodically(self):
    self._read_log(self.bluetoothd_log_file, self.bluetoothd_log_text_browser, 'bluetoothd_pos')
    self._read_log(self.pulseaudio_log_file, self.pulseaudio_log_text_browser, 'pulseaudio_pos')
    self._read_log(self.hcidump_log_file, self.hci_dump_log_text_browser, 'hcidump_pos')
    QTimer.singleShot(1000, self.read_logs_periodically)

def _read_log(self, log_file_path, text_browser, pos_attr):
    try:
        with open(log_file_path, "r") as f:
            f.seek(getattr(self, pos_attr))
            new_logs = f.read()
            if new_logs:
                text_browser.append(new_logs)
                text_browser.verticalScrollBar().setValue(text_browser.verticalScrollBar().maximum())
            setattr(self, pos_attr, f.tell())
    except Exception as e:
        print(f"[LOG READ ERROR] {log_file_path}: {e}")


