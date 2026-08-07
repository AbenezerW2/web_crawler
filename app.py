from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app_model import AppValidationError, ExtractionOptions, build_crawler_command


APP_DIR = Path(__file__).resolve().parent
CRAWLER_PATH = APP_DIR / "crawler.py"


class CrawlerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.process: QProcess | None = None
        self.active_options: ExtractionOptions | None = None
        self.saved_outputs = 0

        self.setWindowTitle("Book Extractor")
        self.setMinimumSize(820, 720)
        self.resize(920, 790)
        self._build_ui()
        self._connect_signals()
        self._mode_changed()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        page = QVBoxLayout(root)
        page.setContentsMargins(28, 24, 28, 24)
        page.setSpacing(18)

        title = QLabel("Book Extractor")
        title.setObjectName("title")
        subtitle = QLabel(
            "Turn public web chapters into clean Markdown, JSON, or text—without repeating commands."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        page.addWidget(title)
        page.addWidget(subtitle)

        form_card = QFrame()
        form_card.setObjectName("card")
        form = QFormLayout(form_card)
        form.setContentsMargins(22, 22, 22, 22)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Whole book", True)
        self.mode_combo.addItem("Single page", False)
        form.addRow("Extraction type", self.mode_combo)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/book/")
        self.url_edit.setClearButtonEnabled(True)
        form.addRow("Book or page URL", self.url_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Book Name")
        self.name_edit.setClearButtonEnabled(True)
        form.addRow("Book / output name", self.name_edit)

        chapter_row = QWidget()
        chapter_layout = QHBoxLayout(chapter_row)
        chapter_layout.setContentsMargins(0, 0, 0, 0)
        chapter_layout.setSpacing(10)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, 10_000)
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, 10_000)
        self.end_spin.setValue(12)
        chapter_layout.addWidget(QLabel("Start"))
        chapter_layout.addWidget(self.start_spin)
        chapter_layout.addSpacing(14)
        chapter_layout.addWidget(QLabel("End"))
        chapter_layout.addWidget(self.end_spin)
        chapter_layout.addStretch()
        self.chapter_row = chapter_row
        form.addRow("Chapter range", chapter_row)

        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(8)
        self.output_edit = QLineEdit("outputs/book-name")
        self.output_edit.setClearButtonEnabled(True)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setObjectName("secondaryButton")
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(self.browse_button)
        form.addRow("Output folder", output_row)

        option_row = QWidget()
        option_layout = QGridLayout(option_row)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setHorizontalSpacing(18)
        option_layout.setVerticalSpacing(10)
        self.format_combo = QComboBox()
        self.format_combo.addItem("Markdown (.md)", "markdown")
        self.format_combo.addItem("JSON (.json)", "json")
        self.format_combo.addItem("Plain text (.txt)", "text")
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0, 3_600)
        self.delay_spin.setDecimals(1)
        self.delay_spin.setValue(1)
        self.delay_spin.setSuffix(" sec")
        option_layout.addWidget(QLabel("Format"), 0, 0)
        option_layout.addWidget(self.format_combo, 0, 1)
        option_layout.addWidget(QLabel("Delay between chapters"), 0, 2)
        option_layout.addWidget(self.delay_spin, 0, 3)
        form.addRow("Output settings", option_row)

        browser_row = QWidget()
        browser_layout = QHBoxLayout(browser_row)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(18)
        self.playwright_check = QCheckBox("Render JavaScript")
        self.playwright_check.setChecked(True)
        self.headed_check = QCheckBox("Show browser")
        self.headed_check.setChecked(True)
        self.wait_check = QCheckBox("Wait for verification")
        self.wait_check.setChecked(True)
        self.overwrite_check = QCheckBox("Overwrite existing files")
        browser_layout.addWidget(self.playwright_check)
        browser_layout.addWidget(self.headed_check)
        browser_layout.addWidget(self.wait_check)
        browser_layout.addWidget(self.overwrite_check)
        browser_layout.addStretch()
        form.addRow("Browser options", browser_row)
        page.addWidget(form_card)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start extraction")
        self.start_button.setObjectName("primaryButton")
        self.verify_button = QPushButton("Verification complete")
        self.verify_button.setObjectName("verifyButton")
        self.verify_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.open_output_button = QPushButton("Open output folder")
        self.open_output_button.setObjectName("secondaryButton")
        controls.addWidget(self.start_button)
        controls.addWidget(self.verify_button)
        controls.addWidget(self.stop_button)
        controls.addStretch()
        controls.addWidget(self.open_output_button)
        page.addLayout(controls)

        progress_card = QFrame()
        progress_card.setObjectName("card")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(20, 16, 20, 16)
        progress_header = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("muted")
        progress_header.addWidget(self.status_label)
        progress_header.addStretch()
        progress_header.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addLayout(progress_header)
        progress_layout.addWidget(self.progress_bar)
        page.addWidget(progress_card)

        log_label = QLabel("Activity")
        log_label.setObjectName("sectionTitle")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Extraction details will appear here.")
        self.log.setMinimumHeight(150)
        fixed_font = QFont("Menlo")
        fixed_font.setStyleHint(QFont.Monospace)
        fixed_font.setPointSize(11)
        self.log.setFont(fixed_font)
        page.addWidget(log_label)
        page.addWidget(self.log, 1)

        self.setCentralWidget(root)
        self.setStyleSheet(STYLESHEET)

    def _connect_signals(self) -> None:
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.browse_button.clicked.connect(self._browse_output)
        self.start_button.clicked.connect(self._start_extraction)
        self.verify_button.clicked.connect(self._verification_complete)
        self.stop_button.clicked.connect(self._stop_extraction)
        self.open_output_button.clicked.connect(self._open_output)
        self.playwright_check.toggled.connect(self._browser_options_changed)
        self.headed_check.toggled.connect(self._browser_options_changed)

    def _mode_changed(self) -> None:
        whole_book = bool(self.mode_combo.currentData())
        self.chapter_row.setEnabled(whole_book)
        if whole_book:
            self.playwright_check.setChecked(True)
            self.playwright_check.setEnabled(False)
        else:
            self.playwright_check.setEnabled(True)
        self._browser_options_changed()

    def _browser_options_changed(self) -> None:
        playwright = self.playwright_check.isChecked()
        self.headed_check.setEnabled(playwright)
        if not playwright:
            self.headed_check.setChecked(False)
        headed = playwright and self.headed_check.isChecked()
        self.wait_check.setEnabled(headed)
        if not headed:
            self.wait_check.setChecked(False)

    def _browse_output(self) -> None:
        initial = self._resolved_output_dir()
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", str(initial))
        if folder:
            self.output_edit.setText(folder)

    def _resolved_output_dir(self) -> Path:
        value = self.output_edit.text().strip() or "outputs"
        path = Path(value).expanduser()
        return path if path.is_absolute() else APP_DIR / path

    def _options(self) -> ExtractionOptions:
        return ExtractionOptions(
            url=self.url_edit.text(),
            name=self.name_edit.text(),
            output_dir=self.output_edit.text(),
            output_format=str(self.format_combo.currentData()),
            whole_book=bool(self.mode_combo.currentData()),
            start_chapter=self.start_spin.value(),
            end_chapter=self.end_spin.value(),
            playwright=self.playwright_check.isChecked(),
            headed=self.headed_check.isChecked(),
            wait_for_user=self.wait_check.isChecked(),
            delay=self.delay_spin.value(),
            overwrite=self.overwrite_check.isChecked(),
        ).validated()

    def _start_extraction(self) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        try:
            options = self._options()
            command = build_crawler_command(options, sys.executable, CRAWLER_PATH)
        except AppValidationError as exc:
            QMessageBox.warning(self, "Check the form", str(exc))
            return

        self.active_options = options
        self.saved_outputs = 0
        self.progress_bar.setRange(0, options.expected_outputs)
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0 / {options.expected_outputs}")
        self.log.clear()
        self.log.appendPlainText("Starting extraction…")
        self.status_label.setText("Launching browser…" if options.playwright else "Fetching page…")
        self._set_running(True)

        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(APP_DIR))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self.process = process
        process.start(command[0], command[1:])

    def _read_output(self) -> None:
        if not self.process:
            return
        output = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not output:
            return
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(output)
        self.log.ensureCursorVisible()

        lowered = output.lower()
        if "complete any verification" in lowered:
            self.status_label.setText("Complete verification in the browser")
            self.verify_button.setEnabled(True)
        saved_now = sum(1 for line in output.splitlines() if line.lower().startswith("saved:"))
        if saved_now:
            self.saved_outputs += saved_now
            maximum = self.active_options.expected_outputs if self.active_options else self.saved_outputs
            self.progress_bar.setValue(min(self.saved_outputs, maximum))
            self.progress_label.setText(f"{min(self.saved_outputs, maximum)} / {maximum}")
            self.status_label.setText("Extracting chapters…")

    def _verification_complete(self) -> None:
        if not self.process or self.process.state() == QProcess.NotRunning:
            return
        self.process.write(b"\n")
        self.verify_button.setEnabled(False)
        self.status_label.setText("Verification confirmed—extracting…")
        self.log.appendPlainText("\nVerification confirmed in the app.")

    def _stop_extraction(self) -> None:
        if not self.process or self.process.state() == QProcess.NotRunning:
            return
        self.status_label.setText("Stopping…")
        self.process.terminate()
        QTimer.singleShot(3_000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _process_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_output()
        self._set_running(False)
        if exit_code == 0:
            if self.active_options:
                self.progress_bar.setValue(self.active_options.expected_outputs)
                self.progress_label.setText(
                    f"{self.active_options.expected_outputs} / {self.active_options.expected_outputs}"
                )
            self.status_label.setText("Extraction complete")
            self.log.appendPlainText("\nDone. Your files are ready.")
        else:
            self.status_label.setText("Extraction stopped or failed")
            self.log.appendPlainText("\nThe extraction did not finish. Review the activity log above.")

    def _process_error(self, _error: QProcess.ProcessError) -> None:
        if self.process and self.process.state() == QProcess.NotRunning:
            self._set_running(False)
            self.status_label.setText("Could not start the crawler")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        if not running:
            self.verify_button.setEnabled(False)

    def _open_output(self) -> None:
        path = self._resolved_output_dir()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.process and self.process.state() != QProcess.NotRunning:
            answer = QMessageBox.question(
                self,
                "Stop extraction?",
                "An extraction is still running. Stop it and close the app?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.process.kill()
        event.accept()


STYLESHEET = """
QMainWindow, QWidget#root {
    background: #0e1420;
}
QWidget {
    color: #e7edf7;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
}
QLabel#title { font-size: 30px; font-weight: 750; color: #f7f9fc; }
QLabel#subtitle, QLabel#muted { color: #94a3b8; }
QLabel#sectionTitle { font-size: 16px; font-weight: 650; }
QLabel#status { font-weight: 650; color: #dbeafe; }
QFrame#card {
    background: #151e2d;
    border: 1px solid #263449;
    border-radius: 12px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #0b1220;
    color: #edf2f7;
    border: 1px solid #334155;
    border-radius: 7px;
    padding: 8px 10px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #60a5fa;
}
QCheckBox { spacing: 7px; color: #cbd5e1; }
QPushButton {
    border: 0;
    border-radius: 8px;
    padding: 10px 15px;
    font-weight: 650;
}
QPushButton#primaryButton { background: #2563eb; color: white; }
QPushButton#primaryButton:hover { background: #3b82f6; }
QPushButton#verifyButton { background: #059669; color: white; }
QPushButton#dangerButton { background: #7f1d1d; color: #fecaca; }
QPushButton#secondaryButton { background: #263449; color: #dbe5f2; }
QPushButton:disabled { background: #202b3c; color: #64748b; }
QPushButton#primaryButton:disabled,
QPushButton#verifyButton:disabled,
QPushButton#dangerButton:disabled,
QPushButton#secondaryButton:disabled { background: #202b3c; color: #64748b; }
QProgressBar {
    background: #0b1220;
    border: 0;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
QPlainTextEdit { padding: 12px; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Book Extractor")
    window = CrawlerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
