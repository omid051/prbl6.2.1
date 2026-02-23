import sys
import json
import threading
import os
import time
import uuid
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QMessageBox, QDialog, QFormLayout, 
    QDialogButtonBox, QRadioButton, QGroupBox, QGridLayout, QTableWidget, 
    QTableWidgetItem, QHeaderView, QCheckBox, QTabWidget, QAbstractItemView, QButtonGroup, QTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QIcon, QFont
from bot_worker import VisaBotWorker
from logger import setup_logger
from sms_handler import send_slot_sms, send_error_sms_req, API_KEY

LOG_FILE = "visa_checker.log"
ACCOUNTS_FILE = "accounts.json"
CONFIG_FILE = "config.json"
VERSION = "6.2.1"

LEGALIZATION_MAP = {
    "ACTA DE DIVORCIO": "سند طلاق",
    "ACTA DE MATRIMONIO": "سند ازدواج",
    "ANUNCIO DE CAMBIOS DE EMPRESA": "آگهی تغییرات شرکت",
    "ANUNCIO DE CONSTITUCIÓN": "آگهی تاسیس",
    "BOTELÍN DE NOTAS": "کارنامه تحصیلی",
    "CARNET DE EXTENCION DEL SERVICIO MILITAR": "کارت معافیت خدمت سربازی",
    "CERTIFICADO DE ANTECEDENTES NO PENALES": "گواهی عدم سوء پیشینه",
    "CERTIFICADO MÉDICO": "گواهی پزشکی",
    "DOCUMENTO NACIONAL DE IDENTIDAD": "کارت ملی",
    "ESCRITURA DE COMPROMISO NO FINANCIERO": "تعهدنامه غیرمالی",
    "ESCRITURA DE PODER NOTARIAL": "وکالت نامه محضری",
    "FÉ DE SOLTERÍA": "گواهی تجرد",
    "LISTADO DE SEGURIDAD SOCIAL": "لیست بیمه تامین اجتماعی",
    "OTRO": "سایر موارد",
    "PERMISO DE COMERCIO": "جواز کسب",
    "SHENASNAMEH": "شناسنامه",
    "TÍTULO ACADÉMICO CERTIFICADO DE FINALIZACIÓN DE ESTUDIOS": "دانشنامه پایان تحصیلات",
    "TÍTULO DE PROPIEDAD": "سند مالکیت",
    "VIDA LABORAL": "سوابق کاری"
}

LEGALIZATION_DOCS = sorted(list(LEGALIZATION_MAP.keys()))

DEFAULT_VISA_TYPES = {
    "Schengen Visa/ Short Term Visa": ["Schengen Visa"],
    "National Visa/ Long Term Visa": [
        "Business Visa", "Digital Nomad Visa", 
        "Family Member of EEA/EU Citizens (Parents or Children only)",
        "General Scheme for the Family Reunification Visa",
        "Ley 14/2013 (except digital nomad visa)",
        "Non-Working Residence Visa", "Student Visa", "Tourist Visa",
        "Work Visa"
    ],
    "Legalization": ["Legalization"]
}

MODERN_STYLESHEET = """
QMainWindow, QDialog { background-color: #2b2b2b; color: #ffffff; }
QLabel { color: #e0e0e0; font-size: 14px; }
QGroupBox { border: 1px solid #555; border-radius: 5px; margin-top: 20px; font-weight: bold; color: #eee; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
QLineEdit, QSpinBox, QComboBox, QListWidget, QTableWidget, QTextEdit {
    background-color: #3b3b3b; color: #ffffff; border: 1px solid #555; border-radius: 4px; padding: 5px;
}
QCheckBox, QRadioButton { color: #ffffff; spacing: 5px; } 
QPushButton { background-color: #0d6efd; color: white; border: none; border-radius: 4px; padding: 8px 15px; font-weight: bold; }
QPushButton:hover { background-color: #0b5ed7; }
QPushButton:pressed { background-color: #0a58ca; }
QPushButton.mgmt-btn { background-color: #6c757d; color: white; }
QPushButton.mgmt-btn:hover { background-color: #5c636a; }
QPushButton.mgmt-btn:pressed { background-color: #565e64; }
QListWidget::item:selected, QTableWidget::item:selected { background-color: #0d6efd; }
QHeaderView::section { background-color: #3b3b3b; color: white; border: 1px solid #555; padding: 4px; }
QTabWidget::pane { border: 1px solid #555; }
QTabBar::tab { background: #3b3b3b; color: #fff; padding: 8px 12px; border: 1px solid #555; border-bottom-color: #555; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #555; border-bottom-color: #555; }
"""

setup_logger(LOG_FILE)

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def kill_all_chrome():
    try:
        if os.name == 'nt':
            os.system("taskkill /F /IM chrome.exe /T")
            os.system("taskkill /F /IM chromedriver.exe /T")
    except Exception as e:
        print(f"Error killing chrome: {e}")

class WorkerSignals(QObject):
    status_updated = pyqtSignal(str, str, str)

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(650, 650)
        self.config = config
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        tabs = QTabWidget()

        # TAB 1: General
        tab_gen = QWidget()
        layout_gen = QVBoxLayout(tab_gen)
        
        mode_group = QGroupBox("حالت بررسی (سرعت و دور زدن کپچا)")
        mode_layout = QGridLayout()
        self.bg_mode = QButtonGroup(self)
        self.rb_reopen = QRadioButton("حالت عادی (بستن و باز کردن مجدد کروم)")
        self.rb_keep_alive = QRadioButton("حالت سریع (نگه داشتن کروم و فقط رفرش فرم)")
        self.bg_mode.addButton(self.rb_reopen)
        self.bg_mode.addButton(self.rb_keep_alive)
        
        mode_layout.addWidget(self.rb_reopen, 0, 0, 1, 2)
        mode_layout.addWidget(self.rb_keep_alive, 1, 0, 1, 2)

        mode_layout.addWidget(QLabel("ریستارت مرورگر در حالت سریع (دقیقه):"), 2, 0)
        self.restart_spin = QSpinBox()
        self.restart_spin.setRange(5, 1440)
        self.restart_spin.setValue(self.config.get("browser_restart_minutes", 60))
        mode_layout.addWidget(self.restart_spin, 2, 1)

        if self.config.get("check_mode", "reopen") == "keep_alive":
            self.rb_keep_alive.setChecked(True)
        else:
            self.rb_reopen.setChecked(True)

        self.rb_reopen.toggled.connect(lambda: self.restart_spin.setEnabled(False))
        self.rb_keep_alive.toggled.connect(lambda: self.restart_spin.setEnabled(True))
        self.restart_spin.setEnabled(self.rb_keep_alive.isChecked())

        mode_group.setLayout(mode_layout)
        layout_gen.addWidget(mode_group)

        time_group = QGroupBox("تنظیمات تایمرها")
        time_layout = QGridLayout()
        time_layout.addWidget(QLabel("حداقل وقفه (دقیقه):"), 0, 0)
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 480)
        self.min_spin.setValue(self.config.get("min_interval", 30))
        time_layout.addWidget(self.min_spin, 0, 1)

        time_layout.addWidget(QLabel("حداکثر وقفه (دقیقه):"), 1, 0)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 480)
        self.max_spin.setValue(self.config.get("max_interval", 60))
        time_layout.addWidget(self.max_spin, 1, 1)

        time_layout.addWidget(QLabel("زمان تشخیص گیر کردن (دقیقه):"), 2, 0)
        self.err_to_spin = QSpinBox()
        self.err_to_spin.setRange(1, 1440)
        self.err_to_spin.setValue(self.config.get("error_timeout_minutes", 15))
        time_layout.addWidget(self.err_to_spin, 2, 1)
        time_group.setLayout(time_layout)
        layout_gen.addWidget(time_group)

        err_group = QGroupBox("استراتژی مدیریت خطا")
        err_layout = QVBoxLayout()
        self.bg_error = QButtonGroup(self)
        self.rb_retry = QRadioButton("تلاش مجدد خودکار (بستن و اجرای دوباره)")
        self.rb_manual = QRadioButton("مداخله دستی (باز ماندن مرورگر هنگام خطا)")
        
        self.bg_error.addButton(self.rb_retry)
        self.bg_error.addButton(self.rb_manual)
        
        if self.config.get("error_strategy", "retry") == "manual":
            self.rb_manual.setChecked(True)
        else:
            self.rb_retry.setChecked(True)
            
        err_layout.addWidget(self.rb_retry)
        err_layout.addWidget(self.rb_manual)
        err_group.setLayout(err_layout)
        layout_gen.addWidget(err_group)

        sch_group = QGroupBox("زمان‌بندی‌های پیشرفته")
        sch_layout = QVBoxLayout()
        self.chk_sleep = QCheckBox("حالت خواب (عدم بررسی بین ۳ تا ۷ صبح)")
        self.chk_sleep.setChecked(self.config.get("sleep_mode", False))
        sch_layout.addWidget(self.chk_sleep)

        self.chk_special = QCheckBox("بررسی سر ساعت (XX:58)")
        self.chk_special.setChecked(self.config.get("special_times", False))
        sch_layout.addWidget(self.chk_special)

        self.chk_half_hour = QCheckBox("بررسی نیم‌ساعت (XX:28)")
        self.chk_half_hour.setChecked(self.config.get("half_hour_times", False))
        sch_layout.addWidget(self.chk_half_hour)

        sch_group.setLayout(sch_layout)
        layout_gen.addWidget(sch_group)
        layout_gen.addStretch()
        tabs.addTab(tab_gen, "General")

        # TAB 2: SMS & Recipients
        tab_sms = QWidget()
        layout_sms = QVBoxLayout(tab_sms)
        
        self.slot_sms_enabled = self.config.get("slot_sms_enabled", True)
        self.error_sms_enabled = self.config.get("error_sms_enabled", True)
        self.sms_server_type = self.config.get("sms_server_type", "iran")
        
        sms_opts_group = QGroupBox("تنظیمات سیستم ارسال پیامک")
        sms_opts_layout = QVBoxLayout()
        
        self.chk_enable_slot_sms = QCheckBox("فعال بودن ارسال پیامک (اسلات موجود)")
        self.chk_enable_slot_sms.setChecked(self.slot_sms_enabled)
        sms_opts_layout.addWidget(self.chk_enable_slot_sms)

        self.chk_enable_error_sms = QCheckBox("فعال بودن ارسال پیامک (خطا/گیر کردن برنامه)")
        self.chk_enable_error_sms.setChecked(self.error_sms_enabled)
        sms_opts_layout.addWidget(self.chk_enable_error_sms)
        
        server_layout = QHBoxLayout()
        self.bg_server = QButtonGroup(self)
        self.rb_iran = QRadioButton("مستقیم / سرور ایران (IPPanel)")
        self.rb_foreign = QRadioButton("ارسال از طریق سرور واسط (هاست خارج)")
        self.bg_server.addButton(self.rb_iran)
        self.bg_server.addButton(self.rb_foreign)
        
        if self.sms_server_type == "foreign":
            self.rb_foreign.setChecked(True)
        else:
            self.rb_iran.setChecked(True)
            
        server_layout.addWidget(self.rb_iran)
        server_layout.addWidget(self.rb_foreign)
        sms_opts_layout.addLayout(server_layout)
        sms_opts_group.setLayout(sms_opts_layout)
        layout_sms.addWidget(sms_opts_group)

        layout_sms.addWidget(QLabel("لیست دریافت‌کنندگان پیامک:"))
        self.table_sms = QTableWidget()
        self.table_sms.setColumnCount(3)
        self.table_sms.setHorizontalHeaderLabels(["Name", "Number (+98...)", "Receive Error SMS"])
        self.table_sms.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_sms.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout_sms.addWidget(self.table_sms)
        
        btn_box_sms = QHBoxLayout()
        self.btn_add_sms = QPushButton("Add Recipient")
        self.btn_add_sms.setProperty("class", "mgmt-btn")
        self.btn_del_sms = QPushButton("Remove Recipient")
        self.btn_del_sms.setProperty("class", "mgmt-btn")
        self.btn_test_sms = QPushButton("Test SMS")
        self.btn_test_sms.setProperty("class", "mgmt-btn")
        
        btn_box_sms.addWidget(self.btn_add_sms)
        btn_box_sms.addWidget(self.btn_del_sms)
        btn_box_sms.addWidget(self.btn_test_sms)
        layout_sms.addLayout(btn_box_sms)
        
        self.load_recipients()
        self.btn_add_sms.clicked.connect(self.add_recipient)
        self.btn_del_sms.clicked.connect(self.del_recipient)
        self.btn_test_sms.clicked.connect(self.test_sms)
        tabs.addTab(tab_sms, "Recipients & SMS")

        # TAB 3: Visa Types
        tab_visa = QWidget()
        layout_visa = QVBoxLayout(tab_visa)
        layout_visa.addWidget(QLabel("Visa Types Configuration:"))
        self.table_visa = QTableWidget()
        self.table_visa.setColumnCount(2)
        self.table_visa.setHorizontalHeaderLabels(["Visa Type", "Visa Subtype"])
        self.table_visa.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout_visa.addWidget(self.table_visa)
        
        btn_box_visa = QHBoxLayout()
        self.btn_add_visa = QPushButton("Add Visa Type")
        self.btn_add_visa.setProperty("class", "mgmt-btn")
        self.btn_del_visa = QPushButton("Remove Selected")
        self.btn_del_visa.setProperty("class", "mgmt-btn")
        
        btn_box_visa.addWidget(self.btn_add_visa)
        btn_box_visa.addWidget(self.btn_del_visa)
        layout_visa.addLayout(btn_box_visa)
        
        self.load_visa_types()
        self.btn_add_visa.clicked.connect(self.add_visa_row)
        self.btn_del_visa.clicked.connect(self.del_visa_row)
        tabs.addTab(tab_visa, "Visa Types")

        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def load_recipients(self):
        recipients = self.config.get("recipients", [])
        if not recipients:
            recipients = [{"name": "مدیر", "number": "+989031101717", "receive_error": True}]
            
        self.table_sms.setRowCount(0)
        for r in recipients:
            row = self.table_sms.rowCount()
            self.table_sms.insertRow(row)
            self.table_sms.setItem(row, 0, QTableWidgetItem(r.get("name", "")))
            self.table_sms.setItem(row, 1, QTableWidgetItem(r.get("number", "")))
            
            chk = QCheckBox()
            chk.setChecked(r.get("receive_error", False))
            widget = QWidget()
            cb_layout = QHBoxLayout(widget)
            cb_layout.addWidget(chk)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table_sms.setCellWidget(row, 2, widget)

            if r.get("number") == "+989031101717":
                self.table_sms.item(row, 0).setFlags(Qt.ItemIsEnabled)
                self.table_sms.item(row, 1).setFlags(Qt.ItemIsEnabled)

    def add_recipient(self):
        row = self.table_sms.rowCount()
        self.table_sms.insertRow(row)
        chk = QCheckBox()
        widget = QWidget()
        cb_layout = QHBoxLayout(widget)
        cb_layout.addWidget(chk)
        cb_layout.setAlignment(Qt.AlignCenter)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        self.table_sms.setCellWidget(row, 2, widget)

    def del_recipient(self):
        row = self.table_sms.currentRow()
        if row < 0: return
        if self.table_sms.item(row, 1) and self.table_sms.item(row, 1).text() == "+989031101717": return
        self.table_sms.removeRow(row)

    def test_sms(self):
        row = self.table_sms.currentRow()
        if row < 0: return
        num = self.table_sms.item(row, 1).text() if self.table_sms.item(row, 1) else ""
        if not num: return
        
        sms_conf = {
            "slot_sms_enabled": self.chk_enable_slot_sms.isChecked(),
            "server_type": "foreign" if self.rb_foreign.isChecked() else "iran",
        }
        
        success, msg = send_slot_sms(API_KEY, num, "TEST_TYPE", "TEST_NAME", sms_conf)
        if success: QMessageBox.information(self, "Result", msg)
        else: QMessageBox.warning(self, "Error", msg)

    def load_visa_types(self):
        visa_dict = self.config.get("visa_types", DEFAULT_VISA_TYPES)
        self.table_visa.setRowCount(0)
        for v_type, sub_list in visa_dict.items():
            for sub in sub_list:
                row = self.table_visa.rowCount()
                self.table_visa.insertRow(row)
                self.table_visa.setItem(row, 0, QTableWidgetItem(v_type))
                self.table_visa.setItem(row, 1, QTableWidgetItem(sub))
                
    def add_visa_row(self): self.table_visa.insertRow(self.table_visa.rowCount())
    
    def del_visa_row(self):
        row = self.table_visa.currentRow()
        if row >= 0: self.table_visa.removeRow(row)

    def get_settings(self):
        new_recs = []
        for r in range(self.table_sms.rowCount()):
            nm = self.table_sms.item(r, 0).text() if self.table_sms.item(r, 0) else ""
            nu = self.table_sms.item(r, 1).text() if self.table_sms.item(r, 1) else ""
            
            widget = self.table_sms.cellWidget(r, 2)
            recv_err = False
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk: recv_err = chk.isChecked()
                
            if nu: new_recs.append({"name": nm, "number": nu, "receive_error": recv_err})
        
        new_visas = {}
        for r in range(self.table_visa.rowCount()):
            vt = self.table_visa.item(r, 0).text().strip() if self.table_visa.item(r, 0) else ""
            vs = self.table_visa.item(r, 1).text().strip() if self.table_visa.item(r, 1) else ""
            if vt and vs:
                if vt not in new_visas: new_visas[vt] = []
                new_visas[vt].append(vs)
        
        strategy = "manual" if self.rb_manual.isChecked() else "retry"
        sms_server = "foreign" if self.rb_foreign.isChecked() else "iran"
        mode = "keep_alive" if self.rb_keep_alive.isChecked() else "reopen"
        
        return {
            "check_mode": mode,
            "browser_restart_minutes": self.restart_spin.value(),
            "min_interval": self.min_spin.value(),
            "max_interval": self.max_spin.value(),
            "error_timeout_minutes": self.err_to_spin.value(),
            "recipients": new_recs,
            "visa_types": new_visas,
            "sleep_mode": self.chk_sleep.isChecked(),
            "special_times": self.chk_special.isChecked(),
            "half_hour_times": self.chk_half_hour.isChecked(), 
            "error_strategy": strategy,
            "slot_sms_enabled": self.chk_enable_slot_sms.isChecked(),
            "error_sms_enabled": self.chk_enable_error_sms.isChecked(),
            "sms_server_type": sms_server
        }

class VisaCheckerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"BLS Spain Visa Bot - v{VERSION}")
        self.setWindowIcon(QIcon(resource_path("spain.ico")))
        self.resize(950, 600)
        self.accounts = self.load_accounts()
        self.config = self.load_config()
        self.workers = {}
        self.last_activity = {}
        self.global_lock = threading.Lock()
        
        self.signals = WorkerSignals()
        self.signals.status_updated.connect(self.handle_status_update)
        
        self.init_ui()
        if not os.path.exists("profiles"): os.makedirs("profiles")

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self.check_watchdog)
        self.watchdog_timer.start(60000)

    def init_ui(self):
        self.setStyleSheet(MODERN_STYLESHEET)
        main_layout = QVBoxLayout()
        self.status_label = QLabel("Bot Status: Ready")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #ffc107;")
        main_layout.addWidget(self.status_label)

        main_layout.addWidget(QLabel("Accounts Status:"))
        self.table_accounts = QTableWidget()
        self.table_accounts.setColumnCount(5)
        self.table_accounts.setHorizontalHeaderLabels(["Email", "Visa Type", "Subtype", "Last Status", "Next Check"])
        self.table_accounts.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_accounts.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_accounts.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.load_account_table()
        main_layout.addWidget(self.table_accounts)

        btn_layout = QGridLayout()
        self.add_btn = QPushButton("Add Account")
        self.edit_btn = QPushButton("Edit Account")
        self.remove_btn = QPushButton("Remove Account")
        self.settings_btn = QPushButton("Settings")
        btn_layout.addWidget(self.add_btn, 0, 0)
        btn_layout.addWidget(self.edit_btn, 0, 1)
        btn_layout.addWidget(self.remove_btn, 0, 2)
        btn_layout.addWidget(self.settings_btn, 1, 0, 1, 3)
        main_layout.addLayout(btn_layout)

        action_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Checker")
        self.start_btn.setStyleSheet("background-color: #198754;")
        self.stop_btn = QPushButton("Stop & Kill Chrome")
        self.stop_btn.setStyleSheet("background-color: #dc3545;")
        action_layout.addWidget(self.start_btn)
        action_layout.addWidget(self.stop_btn)
        main_layout.addLayout(action_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.add_btn.clicked.connect(self.open_add_account)
        self.edit_btn.clicked.connect(self.open_edit_account)
        self.remove_btn.clicked.connect(self.remove_account)
        self.settings_btn.clicked.connect(self.open_settings)
        self.start_btn.clicked.connect(self.start_checker)
        self.stop_btn.clicked.connect(self.stop_checker)

    def load_accounts(self):
        try:
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    accounts = json.load(f)
                    for acc in accounts:
                        if 'id' not in acc:
                            acc['id'] = str(uuid.uuid4())
                    return accounts
        except: pass
        return []

    def save_accounts(self):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.accounts, f, indent=2, ensure_ascii=False)

    def load_config(self):
        defaults = {
            "check_mode": "reopen",
            "browser_restart_minutes": 60,
            "min_interval": 30, "max_interval": 60,
            "error_timeout_minutes": 15,
            "sleep_mode": False,
            "special_times": False,
            "half_hour_times": False,
            "error_strategy": "retry",
            "slot_sms_enabled": True,
            "error_sms_enabled": True,
            "sms_server_type": "iran"
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                    defaults.update(saved)
        except: pass
        
        if "recipients" not in defaults:
            defaults["recipients"] = [{"name": "مدیر", "number": "+989031101717", "receive_error": True}]
        if "visa_types" not in defaults:
            defaults["visa_types"] = DEFAULT_VISA_TYPES
            
        return defaults

    def save_config(self):
        cfg_copy = dict(self.config)
        
        default_rec = [{"name": "مدیر", "number": "+989031101717", "receive_error": True}]
        if cfg_copy.get("recipients") == default_rec or not cfg_copy.get("recipients"):
            cfg_copy.pop("recipients", None)
            
        if cfg_copy.get("visa_types") == DEFAULT_VISA_TYPES:
            cfg_copy.pop("visa_types", None)
            
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: 
            json.dump(cfg_copy, f, indent=2, ensure_ascii=False)

    def load_account_table(self):
        self.table_accounts.setRowCount(0)
        for acc in self.accounts:
            row = self.table_accounts.rowCount()
            self.table_accounts.insertRow(row)
            
            item_email = QTableWidgetItem(acc.get('email', ''))
            item_email.setData(Qt.UserRole, acc['id'])
            
            self.table_accounts.setItem(row, 0, item_email)
            self.table_accounts.setItem(row, 1, QTableWidgetItem(acc.get('visa_type', '')))
            self.table_accounts.setItem(row, 2, QTableWidgetItem(acc.get('visa_subtype', '')))
            self.table_accounts.setItem(row, 3, QTableWidgetItem("Idle"))
            self.table_accounts.setItem(row, 4, QTableWidgetItem("-"))

    def handle_status_update(self, acc_id, status_msg, next_check):
        self.last_activity[acc_id] = time.time()
        for row in range(self.table_accounts.rowCount()):
            if self.table_accounts.item(row, 0).data(Qt.UserRole) == acc_id:
                self.table_accounts.setItem(row, 3, QTableWidgetItem(status_msg))
                if next_check: self.table_accounts.setItem(row, 4, QTableWidgetItem(next_check))
                break

    def check_watchdog(self):
        now = time.time()
        timeout_seconds = self.config.get("error_timeout_minutes", 15) * 60
        for acc_id, worker in self.workers.items():
            if worker.running:
                last_active = self.last_activity.get(acc_id, now)
                if now - last_active > timeout_seconds:
                    self.last_activity[acc_id] = now
                    print(f"Watchdog Triggered: No activity for {timeout_seconds/60} mins on {worker.account['email']}")
                    self.trigger_error_sms(worker.account)

    def trigger_error_sms(self, account):
        recipients = self.config.get("recipients", [])
        sms_config = {
            "error_sms_enabled": self.config.get("error_sms_enabled", True),
            "server_type": self.config.get("sms_server_type", "iran")
        }
        for user in recipients:
            if user.get("receive_error", False):
                name = user.get("name", "کاربر")
                number = user.get("number", "")
                if number:
                    try:
                        send_error_sms_req(API_KEY, number, account.get('visa_type', 'Legalisation'), name, sms_config)
                    except Exception as e:
                        print(f"Error sending watchdog SMS: {e}")

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() == QDialog.Accepted:
            self.config = dlg.get_settings()
            self.save_config()
            QMessageBox.information(self, "Saved", "Settings saved.")

    def account_dialog(self, edit=False, row=-1):
        acc = self.accounts[row] if edit else None
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage Account")
        dialog.resize(650, 650)
        
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        
        tab_basic = QWidget()
        form = QFormLayout(tab_basic)
        
        email = QLineEdit(acc['email'] if acc else "")
        pwd = QLineEdit(acc['password'] if acc else "")
        pwd.setEchoMode(QLineEdit.Password)
        
        last_name = QLineEdit(acc.get('last_name', '') if acc else "")
        last_name.setPlaceholderText("Used for Submit Page (Required)")

        visa_types_dict = self.config.get("visa_types", DEFAULT_VISA_TYPES)
        visa_type_combo = QComboBox()
        visa_type_combo.addItems(list(visa_types_dict.keys()))
        visa_subtype_combo = QComboBox()
        category = QComboBox()
        category.addItems(["Normal", "Prime Time"])
        
        date_pref_label = QLabel("Preferred Date (Normal):")
        date_pref_combo = QComboBox()
        date_pref_combo.addItems(["Earliest (First Available)", "Latest (Last Available)", "Random"])
        
        legal_date_label = QLabel("Target Days (Legalization):")
        legal_date_input = QLineEdit()
        legal_date_input.setPlaceholderText("e.g., 8, 9, 10, 11")
        
        r_group = QWidget()
        r_layout = QHBoxLayout(r_group)
        r1 = QRadioButton("Individual")
        r2 = QRadioButton("Family")
        r_layout.addWidget(r1)
        r_layout.addWidget(r2)
        r1.setChecked(True)
        
        if acc:
            if acc.get('visa_type') in visa_types_dict:
                visa_type_combo.setCurrentText(acc.get('visa_type'))
            category.setCurrentText(acc.get('category', 'Normal'))
            if acc.get('for_type') == "Family": r2.setChecked(True)
            
            date_pref_combo.setCurrentText(acc.get('date_pref', 'Earliest (First Available)'))
            legal_date_input.setText(acc.get('target_days', ''))

        def update_sub_and_date_ui(index):
            visa_subtype_combo.clear()
            v_t = visa_type_combo.currentText()
            subs = visa_types_dict.get(v_t, [])
            visa_subtype_combo.addItems(subs)
            if acc and acc.get('visa_type') == v_t:
                visa_subtype_combo.setCurrentText(acc.get('visa_subtype', ''))
            
            if "Legalization" in v_t:
                date_pref_label.setVisible(False)
                date_pref_combo.setVisible(False)
                legal_date_label.setVisible(True)
                legal_date_input.setVisible(True)
            else:
                date_pref_label.setVisible(True)
                date_pref_combo.setVisible(True)
                legal_date_label.setVisible(False)
                legal_date_input.setVisible(False)

        visa_type_combo.currentIndexChanged.connect(update_sub_and_date_ui)
        
        form.addRow("Email:", email)
        form.addRow("Password:", pwd)
        form.addRow("Last Name:", last_name)
        form.addRow("Visa Type:", visa_type_combo)
        form.addRow("Sub Type:", visa_subtype_combo)
        form.addRow("Category:", category)
        form.addRow("Type:", r_group)
        
        form.addRow(date_pref_label, date_pref_combo)
        form.addRow(legal_date_label, legal_date_input)

        tabs.addTab(tab_basic, "Basic Info")

        tab_legal = QWidget()
        layout_legal = QVBoxLayout(tab_legal)
        
        layout_legal.addWidget(QLabel("Reason For Legalization (Only if type is Legalization):"))
        reason_txt = QTextEdit()
        reason_txt.setMaximumHeight(60)
        if acc: reason_txt.setPlainText(acc.get('reason', ''))
        layout_legal.addWidget(reason_txt)
        
        layout_legal.addWidget(QLabel("Legalization Documents:"))
        table_docs = QTableWidget()
        table_docs.setColumnCount(3)
        table_docs.setHorizontalHeaderLabels(["Document Type (Spanish)", "Persian Translation", "Count"])
        table_docs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout_legal.addWidget(table_docs)
        
        btn_layout_docs = QHBoxLayout()
        btn_add_doc = QPushButton("Add Document")
        btn_add_doc.setProperty("class", "mgmt-btn")
        btn_del_doc = QPushButton("Remove Document")
        btn_del_doc.setProperty("class", "mgmt-btn")
        
        btn_layout_docs.addWidget(btn_add_doc)
        btn_layout_docs.addWidget(btn_del_doc)
        layout_legal.addLayout(btn_layout_docs)

        def update_persian_label(combo, row_idx):
            txt = combo.currentText()
            persian = LEGALIZATION_MAP.get(txt, "-")
            table_docs.setItem(row_idx, 1, QTableWidgetItem(persian))
            table_docs.item(row_idx, 1).setFlags(Qt.ItemIsEnabled)

        def add_doc_row(doc_type="", count=1):
            r = table_docs.rowCount()
            table_docs.insertRow(r)
            
            combo = QComboBox()
            combo.addItems(LEGALIZATION_DOCS)
            combo.setCurrentText(doc_type)
            table_docs.setCellWidget(r, 0, combo)
            
            table_docs.setItem(r, 1, QTableWidgetItem(""))
            update_persian_label(combo, r)
            combo.currentTextChanged.connect(lambda t: update_persian_label(combo, r))
            
            spin = QSpinBox()
            spin.setRange(1, 15)
            spin.setValue(count)
            table_docs.setCellWidget(r, 2, spin)

        if acc and 'documents' in acc:
            for d in acc['documents']:
                add_doc_row(d.get('type', ''), d.get('count', 1))
        
        btn_add_doc.clicked.connect(lambda: add_doc_row())
        btn_del_doc.clicked.connect(lambda: table_docs.removeRow(table_docs.currentRow()) if table_docs.currentRow() >= 0 else None)
        
        tabs.addTab(tab_legal, "Legalization")
        layout.addWidget(tabs)
        
        update_sub_and_date_ui(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            if not email.text().strip(): return
            
            docs = []
            for r in range(table_docs.rowCount()):
                cmb = table_docs.cellWidget(r, 0)
                spn = table_docs.cellWidget(r, 2)
                if cmb and spn:
                    docs.append({"type": cmb.currentText(), "count": spn.value()})

            new_acc = {
                "id": acc['id'] if acc and 'id' in acc else str(uuid.uuid4()),
                "email": email.text().strip(),
                "password": pwd.text().strip(),
                "last_name": last_name.text().strip(),
                "visa_type": visa_type_combo.currentText(),
                "visa_subtype": visa_subtype_combo.currentText(),
                "category": category.currentText(),
                "for_type": "Family" if r2.isChecked() else "Individual",
                "date_pref": date_pref_combo.currentText(),
                "target_days": legal_date_input.text().strip(),
                "reason": reason_txt.toPlainText().strip(),
                "documents": docs
            }
            if edit: self.accounts[row] = new_acc
            else: self.accounts.append(new_acc)
            self.save_accounts()
            self.load_account_table()

    def open_add_account(self): self.account_dialog(edit=False)
    
    def open_edit_account(self):
        row = self.table_accounts.currentRow()
        if row >= 0: self.account_dialog(edit=True, row=row)
    
    def remove_account(self):
        row = self.table_accounts.currentRow()
        if row >= 0 and QMessageBox.question(self, "Delete", "Sure?") == QMessageBox.Yes:
            del self.accounts[row]
            self.save_accounts()
            self.load_account_table()

    def start_checker(self):
        row = self.table_accounts.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Warning", "Select an account from the table.")
            return
        
        acc_id = self.table_accounts.item(row, 0).data(Qt.UserRole)
        target_acc = next((a for a in self.accounts if a['id'] == acc_id), None)
        
        if not target_acc: return
        
        if acc_id in self.workers and self.workers[acc_id].running:
            QMessageBox.warning(self, "Info", "Already running.")
            return

        def worker_status_callback(a_id, m, n):
            self.signals.status_updated.emit(a_id, m, n)
            
        worker = VisaBotWorker(
            target_acc, 
            self.config, 
            self.global_lock, 
            LOG_FILE,
            status_callback=worker_status_callback
        )
        t = threading.Thread(target=worker.run, daemon=True)
        t.start()
        self.workers[acc_id] = worker
        
        self.status_label.setText(f"Status: Running for {target_acc['email']}")
        self.status_label.setStyleSheet("color: #28a745; font-weight: bold; font-size: 16px;")

    def stop_checker(self):
        for acc_id, worker in self.workers.items():
            worker.stop()
        self.workers.clear()
        kill_all_chrome()
        self.status_label.setText("Status: Stopped (All Chrome instances closed)")
        self.status_label.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 16px;")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VisaCheckerApp()
    win.show()
    sys.exit(app.exec_())