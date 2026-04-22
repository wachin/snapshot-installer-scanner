import csv
import os
import sqlite3
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

APP_NAME = "Snapshot Installer Scanner"
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    snapshot_name TEXT NOT NULL,
    path TEXT NOT NULL,
    item_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL,
    ctime REAL,
    PRIMARY KEY (snapshot_name, path)
);
CREATE INDEX IF NOT EXISTS idx_entries_snapshot ON entries(snapshot_name);
CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(snapshot_name, item_type);
"""

TRANSLATIONS = {
    "en": {
        "window_title": APP_NAME,
        "app_subtitle": "Windows snapshot scanner and installer change analyzer.",
        "scan_root": "Scan root",
        "database": "Database",
        "reports_dir": "Reports folder",
        "snapshot_before": "First snapshot name",
        "snapshot_after": "Second snapshot name",
        "browse": "Browse...",
        "create_before": "1) Create initial snapshot",
        "create_after": "2) Create post-install snapshot",
        "compare": "3) Compare snapshots",
        "lang": "Language",
        "status_ready": "Ready.",
        "log_intro": "Use this tool to capture two filesystem snapshots and compare them.",
        "desktop_note": "Important: reports are saved to the selected folder. 'Desktop' in code is not always the visible Windows Desktop; verify the exact full path shown here.",
        "new_root_folders": "New top-level created folders",
        "name": "Name",
        "files": "Files",
        "folders": "Folders",
        "size": "Size",
        "date": "Date",
        "path": "Full path",
        "root_missing": "Please choose a scan root.",
        "db_missing": "Please choose a database file.",
        "reports_missing": "Please choose a reports folder.",
        "snapshot_name_missing": "Please enter both snapshot names.",
        "busy": "A task is already running.",
        "scan_started": "Scanning started: {snapshot}",
        "scan_done": "Scan finished: {snapshot}",
        "compare_done": "Comparison finished.",
        "install_now": "Now install the program you want to analyze, then create the second snapshot.",
        "reports_saved": "Reports saved to: {path}",
        "created_roots_count": "Detected {count} new top-level created folders.",
        "no_created_roots": "No new top-level created folders were detected.",
        "confirm_overwrite": "A snapshot with this name already exists. It will be replaced. Continue?",
        "error": "Error",
        "task_failed": "Task failed:\n{msg}",
        "summary_header": "Summary of new top-level created folders",
        "summary_none": "No new top-level created folders.",
        "summary_item": "Folder {idx}: \"{name}\", {files} Files, {folders} Folders, {size_human} ({size_bytes} bytes), {date}, \"{path}\"",
        "about_export": "The comparison exports CSV reports for created, deleted and modified items, plus a summary of newly created top-level folders.",
    },
    "es": {
        "window_title": APP_NAME,
        "app_subtitle": "Escáner de snapshots de Windows y analizador de cambios tras instalaciones.",
        "scan_root": "Ruta a escanear",
        "database": "Base de datos",
        "reports_dir": "Carpeta de informes",
        "snapshot_before": "Nombre del primer snapshot",
        "snapshot_after": "Nombre del segundo snapshot",
        "browse": "Examinar...",
        "create_before": "1) Crear snapshot inicial",
        "create_after": "2) Crear snapshot después de instalar",
        "compare": "3) Comparar snapshots",
        "lang": "Idioma",
        "status_ready": "Listo.",
        "log_intro": "Use esta herramienta para capturar dos snapshots del sistema de archivos y compararlos.",
        "desktop_note": "Importante: los informes se guardan en la carpeta seleccionada. 'Desktop' en el código no siempre es el Escritorio visible de Windows; revise la ruta completa exacta que aparece aquí.",
        "new_root_folders": "Carpetas principales nuevas creadas",
        "name": "Nombre",
        "files": "Archivos",
        "folders": "Carpetas",
        "size": "Tamaño",
        "date": "Fecha",
        "path": "Ruta completa",
        "root_missing": "Por favor elija una ruta a escanear.",
        "db_missing": "Por favor elija un archivo de base de datos.",
        "reports_missing": "Por favor elija una carpeta de informes.",
        "snapshot_name_missing": "Por favor escriba ambos nombres de snapshots.",
        "busy": "Ya hay una tarea en ejecución.",
        "scan_started": "Escaneo iniciado: {snapshot}",
        "scan_done": "Escaneo finalizado: {snapshot}",
        "compare_done": "Comparación finalizada.",
        "install_now": "Ahora instale el programa que desea analizar y luego cree el segundo snapshot.",
        "reports_saved": "Informes guardados en: {path}",
        "created_roots_count": "Se detectaron {count} carpetas principales nuevas.",
        "no_created_roots": "No se detectaron carpetas principales nuevas.",
        "confirm_overwrite": "Ya existe un snapshot con este nombre. Se reemplazará. ¿Desea continuar?",
        "error": "Error",
        "task_failed": "La tarea falló:\n{msg}",
        "summary_header": "Resumen de carpetas principales nuevas creadas",
        "summary_none": "No se detectaron carpetas principales nuevas.",
        "summary_item": "Carpeta {idx}: \"{name}\", {files} Files, {folders} Folders, {size_human} ({size_bytes} bytes), {date}, \"{path}\"",
        "about_export": "La comparación exporta informes CSV de elementos creados, eliminados y modificados, además de un resumen de carpetas principales nuevas creadas.",
    },
}


def human_size(num_bytes: int) -> str:
    units = ["bytes", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024.0
        unit += 1
    if unit == 0:
        return f"{int(size)} bytes"
    return f"{size:.2f} {units[unit]}"


def format_dt(ts: Optional[float]) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class Translator:
    def __init__(self, language: str = "en"):
        self.language = language if language in TRANSLATIONS else "en"

    def set_language(self, language: str) -> None:
        self.language = language if language in TRANSLATIONS else "en"

    def t(self, key: str, **kwargs) -> str:
        text = TRANSLATIONS[self.language].get(key, key)
        return text.format(**kwargs)


class SnapshotDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(DB_SCHEMA)
        return conn

    def _ensure_db(self):
        with self.connect() as conn:
            conn.executescript(DB_SCHEMA)

    def delete_snapshot(self, snapshot_name: str):
        with self.connect() as conn:
            self.delete_snapshot_conn(conn, snapshot_name)

    def delete_snapshot_conn(self, conn, snapshot_name: str):
        conn.execute("DELETE FROM entries WHERE snapshot_name = ?", (snapshot_name,))

    def snapshot_exists(self, snapshot_name: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM entries WHERE snapshot_name = ? LIMIT 1", (snapshot_name,)
            ).fetchone()
        return row is not None

    def insert_entries(self, snapshot_name: str, entries: Iterable[Tuple[str, str, int, float, float]]):
        with self.connect() as conn:
            self.insert_entries_conn(conn, snapshot_name, entries)

    def insert_entries_conn(self, conn, snapshot_name: str, entries: Iterable[Tuple[str, str, int, float, float]]):
        conn.executemany(
            "INSERT OR REPLACE INTO entries (snapshot_name, path, item_type, size, mtime, ctime) VALUES (?, ?, ?, ?, ?, ?)",
            ((snapshot_name, *entry) for entry in entries),
        )

    def load_snapshot(self, snapshot_name: str) -> Dict[str, Tuple[str, int, Optional[float], Optional[float]]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT path, item_type, size, mtime, ctime FROM entries WHERE snapshot_name = ?",
                (snapshot_name,),
            ).fetchall()
        return {path: (item_type, size, mtime, ctime) for path, item_type, size, mtime, ctime in rows}


class ScanWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, db_path: str, root_path: str, snapshot_name: str, reports_dir: str = ""):
        super().__init__()
        self.db_path = os.path.abspath(db_path)
        self.root_path = os.path.abspath(root_path)
        self.snapshot_name = snapshot_name
        self.reports_dir = os.path.abspath(reports_dir) if reports_dir else ""

    def _should_skip_path(self, path: str) -> bool:
        path_norm = os.path.normcase(os.path.normpath(path))
        db_norm = os.path.normcase(os.path.normpath(self.db_path))
        if path_norm == db_norm:
            return True
        wal_norm = db_norm + "-wal"
        shm_norm = db_norm + "-shm"
        if path_norm in (wal_norm, shm_norm):
            return True
        if self.reports_dir:
            reports_norm = os.path.normcase(os.path.normpath(self.reports_dir))
            if path_norm == reports_norm or path_norm.startswith(reports_norm + os.sep):
                return True
        return False

    def run(self):
        try:
            db = SnapshotDB(self.db_path)
            batch = []
            scanned = 0
            root_norm = os.path.normpath(self.root_path)

            with db.connect() as conn:
                db.delete_snapshot_conn(conn, self.snapshot_name)

                for current_root, dirs, files in os.walk(self.root_path, topdown=True, followlinks=False):
                    current_root_norm = os.path.normpath(current_root)
                    if self._should_skip_path(current_root_norm):
                        dirs[:] = []
                        continue

                    # prune directories that should never be scanned while this app is writing to them
                    dirs[:] = [d for d in dirs if not self._should_skip_path(os.path.join(current_root, d))]

                    try:
                        st_dir = os.stat(current_root_norm)
                        batch.append((current_root_norm, "dir", 0, st_dir.st_mtime, st_dir.st_ctime))
                    except Exception:
                        pass

                    for name in files:
                        full_path = os.path.normpath(os.path.join(current_root, name))
                        if self._should_skip_path(full_path):
                            continue
                        try:
                            st = os.stat(full_path)
                            batch.append((full_path, "file", int(st.st_size), st.st_mtime, st.st_ctime))
                        except Exception as exc:
                            self.progress.emit(f"[WARN] {full_path} -> {exc}")
                        scanned += 1
                        if scanned % 5000 == 0:
                            db.insert_entries_conn(conn, self.snapshot_name, batch)
                            conn.commit()
                            batch.clear()
                            self.progress.emit(f"Scanned {scanned:,} files...")

                if batch:
                    db.insert_entries_conn(conn, self.snapshot_name, batch)
                    conn.commit()

            self.finished.emit(self.snapshot_name)
        except Exception:
            self.failed.emit(traceback.format_exc())


@dataclass
class RootFolderSummary:
    name: str
    path: str
    files_count: int
    folders_count: int
    size_bytes: int
    date_ts: Optional[float]


class CompareWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, db_path: str, reports_dir: str, snapshot_before: str, snapshot_after: str):
        super().__init__()
        self.db_path = db_path
        self.reports_dir = reports_dir
        self.snapshot_before = snapshot_before
        self.snapshot_after = snapshot_after

    def run(self):
        try:
            db = SnapshotDB(self.db_path)
            before = db.load_snapshot(self.snapshot_before)
            after = db.load_snapshot(self.snapshot_after)
            before_paths = set(before.keys())
            after_paths = set(after.keys())

            created_paths = sorted(after_paths - before_paths)
            deleted_paths = sorted(before_paths - after_paths)
            common_paths = before_paths & after_paths
            modified_paths = []
            for path in sorted(common_paths):
                if before[path] != after[path]:
                    modified_paths.append(path)

            os.makedirs(self.reports_dir, exist_ok=True)
            created_csv = os.path.join(self.reports_dir, "created_items.csv")
            deleted_csv = os.path.join(self.reports_dir, "deleted_items.csv")
            modified_csv = os.path.join(self.reports_dir, "modified_items.csv")
            roots_csv = os.path.join(self.reports_dir, "created_root_folders_summary.csv")
            summary_txt = os.path.join(self.reports_dir, "created_root_folders_summary.txt")

            self._write_items_csv(created_csv, created_paths, after)
            self._write_items_csv(deleted_csv, deleted_paths, before)
            self._write_modified_csv(modified_csv, modified_paths, before, after)

            root_summaries = self._summarize_created_root_folders(created_paths, after)
            self._write_roots_csv(roots_csv, root_summaries)
            self._write_summary_txt(summary_txt, root_summaries)

            self.finished.emit(
                {
                    "created_csv": created_csv,
                    "deleted_csv": deleted_csv,
                    "modified_csv": modified_csv,
                    "roots_csv": roots_csv,
                    "summary_txt": summary_txt,
                    "root_summaries": root_summaries,
                }
            )
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _write_items_csv(self, path: str, items: List[str], data: Dict[str, Tuple[str, int, Optional[float], Optional[float]]]):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "type", "size_bytes", "mtime", "ctime"])
            for item_path in items:
                item_type, size, mtime, ctime = data[item_path]
                writer.writerow([item_path, item_type, size, format_dt(mtime), format_dt(ctime)])

    def _write_modified_csv(self, path: str, items: List[str], before, after):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "path",
                    "type_before",
                    "size_before",
                    "mtime_before",
                    "ctime_before",
                    "type_after",
                    "size_after",
                    "mtime_after",
                    "ctime_after",
                ]
            )
            for item_path in items:
                b = before[item_path]
                a = after[item_path]
                writer.writerow(
                    [
                        item_path,
                        b[0],
                        b[1],
                        format_dt(b[2]),
                        format_dt(b[3]),
                        a[0],
                        a[1],
                        format_dt(a[2]),
                        format_dt(a[3]),
                    ]
                )

    def _summarize_created_root_folders(self, created_paths: List[str], after: Dict[str, Tuple[str, int, Optional[float], Optional[float]]]) -> List[RootFolderSummary]:
        created_dirs = sorted([p for p in created_paths if after[p][0] == "dir"])
        created_files = [p for p in created_paths if after[p][0] == "file"]
        created_set = set(created_paths)

        root_dirs = []
        created_dirs_set = set(created_dirs)
        for path in created_dirs:
            parent = os.path.dirname(path)
            if parent not in created_dirs_set:
                root_dirs.append(path)

        summaries: List[RootFolderSummary] = []
        for root in root_dirs:
            prefix = root + os.sep
            desc_dirs = [p for p in created_dirs if p.startswith(prefix)]
            desc_files = [p for p in created_files if p.startswith(prefix)]
            size_bytes = sum(after[p][1] for p in desc_files)
            root_mtime = after[root][2]
            summaries.append(
                RootFolderSummary(
                    name=os.path.basename(root) or root,
                    path=root,
                    files_count=len(desc_files),
                    folders_count=len(desc_dirs),
                    size_bytes=size_bytes,
                    date_ts=root_mtime,
                )
            )

        summaries.sort(key=lambda x: (-x.size_bytes, x.path.lower()))
        return summaries

    def _write_roots_csv(self, path: str, roots: List[RootFolderSummary]):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "files_count", "folders_count", "size_human", "size_bytes", "date", "path"])
            for item in roots:
                writer.writerow([
                    item.name,
                    item.files_count,
                    item.folders_count,
                    human_size(item.size_bytes),
                    item.size_bytes,
                    format_dt(item.date_ts),
                    item.path,
                ])

    def _write_summary_txt(self, path: str, roots: List[RootFolderSummary]):
        with open(path, "w", encoding="utf-8") as f:
            f.write("Summary of new top-level created folders\n")
            f.write("=" * 44 + "\n\n")
            if not roots:
                f.write("No new top-level created folders.\n")
                return
            for idx, item in enumerate(roots, start=1):
                f.write(
                    f'Folder {idx}: "{item.name}", {item.files_count} Files, {item.folders_count} Folders, '
                    f'{human_size(item.size_bytes)} ({item.size_bytes} bytes), {format_dt(item.date_ts)}, "{item.path}"\n'
                )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.translator = Translator("en")
        self.worker_thread: Optional[QThread] = None
        self._build_ui()
        self.retranslate_ui()

    def _build_ui(self):
        self.setMinimumSize(1100, 720)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        form_group = QGroupBox()
        form_layout = QGridLayout(form_group)

        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Español", "es")
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)

        self.root_label = QLabel()
        self.root_edit = QLineEdit("C:\\")
        self.root_btn = QPushButton()
        self.root_btn.clicked.connect(self.choose_root)

        self.db_label = QLabel()
        self.db_edit = QLineEdit(str(Path.home() / "snapshots.sqlite"))
        self.db_btn = QPushButton()
        self.db_btn.clicked.connect(self.choose_db)

        self.reports_label = QLabel()
        self.reports_edit = QLineEdit(str(Path.home() / "snapshot_reports"))
        self.reports_btn = QPushButton()
        self.reports_btn.clicked.connect(self.choose_reports)

        self.before_label = QLabel()
        self.before_edit = QLineEdit("before_install")
        self.after_label = QLabel()
        self.after_edit = QLineEdit("after_install")

        form_layout.addWidget(self.lang_label, 0, 0)
        form_layout.addWidget(self.lang_combo, 0, 1)
        form_layout.addWidget(self.root_label, 1, 0)
        form_layout.addWidget(self.root_edit, 1, 1)
        form_layout.addWidget(self.root_btn, 1, 2)
        form_layout.addWidget(self.db_label, 2, 0)
        form_layout.addWidget(self.db_edit, 2, 1)
        form_layout.addWidget(self.db_btn, 2, 2)
        form_layout.addWidget(self.reports_label, 3, 0)
        form_layout.addWidget(self.reports_edit, 3, 1)
        form_layout.addWidget(self.reports_btn, 3, 2)
        form_layout.addWidget(self.before_label, 4, 0)
        form_layout.addWidget(self.before_edit, 4, 1)
        form_layout.addWidget(self.after_label, 5, 0)
        form_layout.addWidget(self.after_edit, 5, 1)

        btn_layout = QHBoxLayout()
        self.before_btn = QPushButton()
        self.before_btn.clicked.connect(self.create_before_snapshot)
        self.after_btn = QPushButton()
        self.after_btn.clicked.connect(self.create_after_snapshot)
        self.compare_btn = QPushButton()
        self.compare_btn.clicked.connect(self.compare_snapshots)
        btn_layout.addWidget(self.before_btn)
        btn_layout.addWidget(self.after_btn)
        btn_layout.addWidget(self.compare_btn)

        self.subtitle_label = QLabel()
        self.subtitle_label.setWordWrap(True)
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #9b5d00;")

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.table_group = QGroupBox()
        table_layout = QVBoxLayout(self.table_group)
        self.roots_table = QTableWidget(0, 6)
        self.roots_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.roots_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.roots_table.setWordWrap(False)
        self.roots_table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.roots_table)
        splitter.addWidget(self.log_edit)
        splitter.addWidget(self.table_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(self.subtitle_label)
        main_layout.addWidget(self.note_label)
        main_layout.addWidget(form_group)
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self.progress)
        main_layout.addWidget(splitter)

        self.statusBar().showMessage("Ready")

    def retranslate_ui(self):
        t = self.translator.t
        self.setWindowTitle(t("window_title"))
        self.subtitle_label.setText(t("app_subtitle"))
        self.note_label.setText(t("desktop_note"))
        self.lang_label.setText(t("lang"))
        self.root_label.setText(t("scan_root"))
        self.db_label.setText(t("database"))
        self.reports_label.setText(t("reports_dir"))
        self.before_label.setText(t("snapshot_before"))
        self.after_label.setText(t("snapshot_after"))
        self.root_btn.setText(t("browse"))
        self.db_btn.setText(t("browse"))
        self.reports_btn.setText(t("browse"))
        self.before_btn.setText(t("create_before"))
        self.after_btn.setText(t("create_after"))
        self.compare_btn.setText(t("compare"))
        self.table_group.setTitle(t("new_root_folders"))
        self.roots_table.setHorizontalHeaderLabels(
            [t("name"), t("files"), t("folders"), t("size"), t("date"), t("path")]
        )
        self.statusBar().showMessage(t("status_ready"))
        if not self.log_edit.toPlainText().strip():
            self.log(t("log_intro"))
            self.log(t("about_export"))

    def on_language_changed(self):
        self.translator.set_language(self.lang_combo.currentData())
        self.retranslate_ui()

    def choose_root(self):
        path = QFileDialog.getExistingDirectory(self, APP_NAME, self.root_edit.text() or "C:\\")
        if path:
            self.root_edit.setText(path)

    def choose_db(self):
        path, _ = QFileDialog.getSaveFileName(self, APP_NAME, self.db_edit.text(), "SQLite (*.sqlite *.db)")
        if path:
            self.db_edit.setText(path)

    def choose_reports(self):
        path = QFileDialog.getExistingDirectory(self, APP_NAME, self.reports_edit.text() or str(Path.home()))
        if path:
            self.reports_edit.setText(path)

    def validate_common(self) -> bool:
        t = self.translator.t
        if self.worker_thread is not None:
            QMessageBox.warning(self, APP_NAME, t("busy"))
            return False
        if not self.root_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, t("root_missing"))
            return False
        if not self.db_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, t("db_missing"))
            return False
        if not self.reports_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, t("reports_missing"))
            return False
        if not self.before_edit.text().strip() or not self.after_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, t("snapshot_name_missing"))
            return False
        return True

    def _confirm_overwrite_if_needed(self, snapshot_name: str) -> bool:
        db = SnapshotDB(self.db_edit.text().strip())
        if not db.snapshot_exists(snapshot_name):
            return True
        return QMessageBox.question(
            self,
            APP_NAME,
            self.translator.t("confirm_overwrite"),
        ) == QMessageBox.StandardButton.Yes

    def create_before_snapshot(self):
        if not self.validate_common():
            return
        snap = self.before_edit.text().strip()
        if not self._confirm_overwrite_if_needed(snap):
            return
        self.run_scan(snap)

    def create_after_snapshot(self):
        if not self.validate_common():
            return
        snap = self.after_edit.text().strip()
        if not self._confirm_overwrite_if_needed(snap):
            return
        self.run_scan(snap)

    def compare_snapshots(self):
        if not self.validate_common():
            return
        worker = CompareWorker(
            self.db_edit.text().strip(),
            self.reports_edit.text().strip(),
            self.before_edit.text().strip(),
            self.after_edit.text().strip(),
        )
        self._run_worker(worker, self.on_compare_finished)
        self.log(f"Comparing snapshots '{self.before_edit.text().strip()}' vs '{self.after_edit.text().strip()}'...")

    def run_scan(self, snapshot_name: str):
        worker = ScanWorker(self.db_edit.text().strip(), self.root_edit.text().strip(), snapshot_name, self.reports_edit.text().strip())
        self._run_worker(worker, self.on_scan_finished)
        self.log(self.translator.t("scan_started", snapshot=snapshot_name))

    def _run_worker(self, worker: QObject, finished_handler):
        self.progress.show()
        self._set_buttons_enabled(False)
        thread = QThread(self)
        self.worker_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.log)
        worker.finished.connect(finished_handler)
        worker.failed.connect(self.on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _on_thread_finished(self):
        self.worker_thread = None
        self.progress.hide()
        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled: bool):
        self.before_btn.setEnabled(enabled)
        self.after_btn.setEnabled(enabled)
        self.compare_btn.setEnabled(enabled)

    def on_scan_finished(self, snapshot_name: str):
        self.log(self.translator.t("scan_done", snapshot=snapshot_name))
        if snapshot_name == self.before_edit.text().strip():
            self.log(self.translator.t("install_now"))

    def on_compare_finished(self, result: dict):
        self.log(self.translator.t("compare_done"))
        self.log(self.translator.t("reports_saved", path=self.reports_edit.text().strip()))
        roots: List[RootFolderSummary] = result["root_summaries"]
        self.populate_roots_table(roots)
        if roots:
            self.log(self.translator.t("created_roots_count", count=len(roots)))
            self.log(self.translator.t("summary_header"))
            for idx, item in enumerate(roots, start=1):
                self.log(
                    self.translator.t(
                        "summary_item",
                        idx=idx,
                        name=item.name,
                        files=item.files_count,
                        folders=item.folders_count,
                        size_human=human_size(item.size_bytes),
                        size_bytes=item.size_bytes,
                        date=format_dt(item.date_ts),
                        path=item.path,
                    )
                )
        else:
            self.log(self.translator.t("no_created_roots"))

    def on_worker_failed(self, msg: str):
        QMessageBox.critical(self, self.translator.t("error"), self.translator.t("task_failed", msg=msg))
        self.log(msg)

    def populate_roots_table(self, roots: List[RootFolderSummary]):
        self.roots_table.setRowCount(len(roots))
        for row, item in enumerate(roots):
            values = [
                item.name,
                str(item.files_count),
                str(item.folders_count),
                f"{human_size(item.size_bytes)} ({item.size_bytes} bytes)",
                format_dt(item.date_ts),
                item.path,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col in (1, 2):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.roots_table.setItem(row, col, cell)
        self.roots_table.resizeColumnsToContents()

    def log(self, text: str):
        self.log_edit.appendPlainText(text)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
