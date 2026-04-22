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
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Snapshot Installer Scanner"
WRITE_BATCH_SIZE = 50000
PROGRESS_EVERY_FILES = 10000
DEFAULT_SCAN_ROOTS = [
    r"C:\\Program Files",
    r"C:\\Program Files (x86)",
    r"C:\\ProgramData",
    r"C:\\Users",
]
DEFAULT_EXCLUDED_FOLDERS = [
    r"C:\\Windows",
    r"C:\\$Recycle.Bin",
    r"C:\\System Volume Information",
    r"C:\\Recovery",
    r"C:\\Config.Msi",
    r"C:\\MSOCache",
    r"C:\\ProgramData\\Microsoft\\Search",
    r"C:\\ProgramData\\Microsoft\\Windows\\WER",
    r"C:\\ProgramData\\Package Cache",
    r"C:\\Users\\Default",
    r"C:\\Users\\Public\\Documents\\Sample Music",
    r"C:\\Users\\Public\\Documents\\Sample Pictures",
    r"C:\\Users\\Public\\Documents\\Sample Videos",
    r"C:\\Users\\*\\AppData\\Local\\Temp",
    r"C:\\Users\\*\\AppData\\Local\\Microsoft\\Windows\\INetCache",
    r"C:\\Users\\*\\AppData\\Local\\CrashDumps",
    r"C:\\Users\\*\\AppData\\Local\\D3DSCache",
    r"C:\\Users\\*\\AppData\\Local\\NVIDIA\\DXCache",
    r"C:\\Users\\*\\AppData\\Local\\NVIDIA\\GLCache",
]
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
        "app_subtitle": "Optimized Windows snapshot scanner and installer change analyzer.",
        "tab_run": "Run",
        "tab_settings": "Settings",
        "tab_filters": "Scan folders and exclusions",
        "database": "Database",
        "reports_dir": "Reports folder",
        "snapshot_before": "First snapshot name",
        "snapshot_after": "Second snapshot name",
        "scan_roots": "Scan folders",
        "excluded_folders": "Excluded folders",
        "lang": "Language",
        "browse": "Browse...",
        "edit_defaults": "Load recommended defaults",
        "clear_list": "Clear",
        "create_before": "1) Create initial snapshot",
        "create_after": "2) Create post-install snapshot",
        "compare": "3) Compare snapshots",
        "status_ready": "Ready.",
        "log_intro": "Use this tool to capture two filesystem snapshots and compare them.",
        "desktop_note": "Important: reports are saved to the selected folder. Verify the exact full path shown here.",
        "filters_note": "Enter one folder per line. Wildcard * is supported in exclusions, for example C:\\Users\\*\\AppData\\Local\\Temp",
        "new_root_folders": "New top-level created folders",
        "name": "Name",
        "files": "Files",
        "folders": "Folders",
        "size": "Size",
        "date": "Date",
        "path": "Full path",
        "db_missing": "Please choose a database file.",
        "reports_missing": "Please choose a reports folder.",
        "snapshot_name_missing": "Please enter both snapshot names.",
        "scan_roots_missing": "Please enter at least one scan folder.",
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
        "summary_item": "Folder {idx}: \"{name}\", {files} Files, {folders} Folders, {size_human} ({size_bytes} bytes), {date}, \"{path}\"",
        "summary_none": "No new top-level created folders.",
        "about_export": "The comparison exports CSV reports for created, deleted and modified items, plus a summary of newly created top-level folders.",
        "progress_dirs": "Folders processed: {dirs:,} | Files processed: {files:,}",
        "progress_path": "Current folder: {path}",
        "scanning_root": "Scanning root: {path}",
        "skipping_root": "Skipped missing root: {path}",
        "loaded_defaults": "Recommended scan and exclusion lists loaded.",
    },
    "es": {
        "window_title": APP_NAME,
        "app_subtitle": "Escáner optimizado de snapshots de Windows y analizador de cambios tras instalaciones.",
        "tab_run": "Ejecución",
        "tab_settings": "Opciones",
        "tab_filters": "Carpetas a escanear y exclusiones",
        "database": "Base de datos",
        "reports_dir": "Carpeta de informes",
        "snapshot_before": "Nombre del primer snapshot",
        "snapshot_after": "Nombre del segundo snapshot",
        "scan_roots": "Carpetas a escanear",
        "excluded_folders": "Carpetas excluidas",
        "lang": "Idioma",
        "browse": "Examinar...",
        "edit_defaults": "Cargar valores recomendados",
        "clear_list": "Limpiar",
        "create_before": "1) Crear snapshot inicial",
        "create_after": "2) Crear snapshot después de instalar",
        "compare": "3) Comparar snapshots",
        "status_ready": "Listo.",
        "log_intro": "Use esta herramienta para capturar dos snapshots del sistema de archivos y compararlos.",
        "desktop_note": "Importante: los informes se guardan en la carpeta seleccionada. Revise la ruta completa exacta que aparece aquí.",
        "filters_note": "Escriba una carpeta por línea. Se admite comodín * en exclusiones, por ejemplo C:\\Users\\*\\AppData\\Local\\Temp",
        "new_root_folders": "Carpetas principales nuevas creadas",
        "name": "Nombre",
        "files": "Archivos",
        "folders": "Carpetas",
        "size": "Tamaño",
        "date": "Fecha",
        "path": "Ruta completa",
        "db_missing": "Por favor elija un archivo de base de datos.",
        "reports_missing": "Por favor elija una carpeta de informes.",
        "snapshot_name_missing": "Por favor escriba ambos nombres de snapshots.",
        "scan_roots_missing": "Por favor escriba al menos una carpeta a escanear.",
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
        "summary_item": "Carpeta {idx}: \"{name}\", {files} Files, {folders} Folders, {size_human} ({size_bytes} bytes), {date}, \"{path}\"",
        "summary_none": "No se detectaron carpetas principales nuevas.",
        "about_export": "La comparación exporta informes CSV de elementos creados, eliminados y modificados, además de un resumen de carpetas principales nuevas creadas.",
        "progress_dirs": "Carpetas procesadas: {dirs:,} | Archivos procesados: {files:,}",
        "progress_path": "Carpeta actual: {path}",
        "scanning_root": "Escaneando raíz: {path}",
        "skipping_root": "Se omitió la raíz inexistente: {path}",
        "loaded_defaults": "Se cargaron listas recomendadas de escaneo y exclusión.",
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


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def parse_multiline_paths(text: str) -> List[str]:
    items: List[str] = []
    for line in text.replace(";", "\n").splitlines():
        value = line.strip().strip('"')
        if value:
            items.append(os.path.normpath(value))
    return items


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
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-20000")
        conn.executescript(DB_SCHEMA)
        return conn

    def _ensure_db(self):
        with self.connect() as conn:
            conn.executescript(DB_SCHEMA)

    def delete_snapshot(self, snapshot_name: str):
        with self.connect() as conn:
            self.delete_snapshot_conn(conn, snapshot_name)
            conn.commit()

    def delete_snapshot_conn(self, conn, snapshot_name: str):
        conn.execute("DELETE FROM entries WHERE snapshot_name = ?", (snapshot_name,))

    def snapshot_exists(self, snapshot_name: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM entries WHERE snapshot_name = ? LIMIT 1", (snapshot_name,)
            ).fetchone()
        return row is not None

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

    def __init__(
        self,
        db_path: str,
        root_paths: List[str],
        excluded_patterns: List[str],
        snapshot_name: str,
        reports_dir: str = "",
    ):
        super().__init__()
        self.db_path = os.path.abspath(db_path)
        self.root_paths = [os.path.abspath(path) for path in root_paths]
        self.excluded_patterns = excluded_patterns
        self.snapshot_name = snapshot_name
        self.reports_dir = os.path.abspath(reports_dir) if reports_dir else ""
        self.files_scanned = 0
        self.dirs_scanned = 0
        self._last_progress_files = 0

    def _should_skip_path(self, path: str) -> bool:
        path_norm = normalize_path(path)
        db_norm = normalize_path(self.db_path)
        if path_norm == db_norm:
            return True
        if path_norm in (db_norm + "-wal", db_norm + "-shm"):
            return True
        if self.reports_dir:
            reports_norm = normalize_path(self.reports_dir)
            if path_norm == reports_norm or path_norm.startswith(reports_norm + os.sep):
                return True
        for pattern in self.excluded_patterns:
            if self._path_matches_pattern(path_norm, pattern):
                return True
        return False

    def _path_matches_pattern(self, path_norm: str, pattern: str) -> bool:
        pattern = pattern.strip()
        if not pattern:
            return False
        pattern_norm = normalize_path(pattern.replace("*", "__WILDCARD__")).replace("__wildcard__", "__WILDCARD__")
        if "__WILDCARD__" not in pattern_norm:
            return path_norm == pattern_norm or path_norm.startswith(pattern_norm + os.sep)

        parts = pattern_norm.split("__WILDCARD__")
        cursor = 0
        for index, part in enumerate(parts):
            if not part:
                continue
            pos = path_norm.find(part, cursor)
            if pos == -1:
                return False
            if index == 0 and not path_norm.startswith(part):
                return False
            cursor = pos + len(part)
        if parts[-1] and not path_norm.endswith(parts[-1]) and not path_norm.startswith(pattern_norm.rstrip("__WILDCARD__") + os.sep):
            tail = parts[-1]
            if tail and tail not in path_norm[cursor - len(tail):]:
                return False
        return True

    def _flush_batch(self, conn, db: SnapshotDB, batch: List[Tuple[str, str, int, float, float]]):
        if not batch:
            return
        db.insert_entries_conn(conn, self.snapshot_name, batch)
        batch.clear()

    def _scan_dir(self, path: str, conn, db: SnapshotDB, batch: List[Tuple[str, str, int, float, float]]):
        if self._should_skip_path(path):
            return

        try:
            with os.scandir(path) as iterator:
                self.dirs_scanned += 1
                if self.dirs_scanned <= 30 or self.dirs_scanned % 500 == 0:
                    self.progress.emit(TRANSLATIONS["en"]["progress_path"].format(path=path))
                for entry in iterator:
                    full_path = os.path.normpath(entry.path)
                    if self._should_skip_path(full_path):
                        continue
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                        if entry.is_dir(follow_symlinks=False):
                            batch.append((full_path, "dir", 0, stat_result.st_mtime, stat_result.st_ctime))
                            if len(batch) >= WRITE_BATCH_SIZE:
                                self._flush_batch(conn, db, batch)
                            self._scan_dir(full_path, conn, db, batch)
                        elif entry.is_file(follow_symlinks=False):
                            batch.append((full_path, "file", int(stat_result.st_size), stat_result.st_mtime, stat_result.st_ctime))
                            self.files_scanned += 1
                            if len(batch) >= WRITE_BATCH_SIZE:
                                self._flush_batch(conn, db, batch)
                            if self.files_scanned - self._last_progress_files >= PROGRESS_EVERY_FILES:
                                self._last_progress_files = self.files_scanned
                                self.progress.emit(
                                    TRANSLATIONS["en"]["progress_dirs"].format(
                                        dirs=self.dirs_scanned,
                                        files=self.files_scanned,
                                    )
                                )
                    except Exception as exc:
                        self.progress.emit(f"[WARN] {full_path} -> {exc}")
        except Exception as exc:
            self.progress.emit(f"[WARN] {path} -> {exc}")

    def run(self):
        try:
            db = SnapshotDB(self.db_path)
            batch: List[Tuple[str, str, int, float, float]] = []
            with db.connect() as conn:
                db.delete_snapshot_conn(conn, self.snapshot_name)
                for root_path in self.root_paths:
                    root_norm = os.path.normpath(root_path)
                    if not os.path.exists(root_norm):
                        self.progress.emit(f"[WARN] Missing root: {root_norm}")
                        continue
                    self.progress.emit(f"[ROOT] {root_norm}")
                    try:
                        st_root = os.stat(root_norm)
                        batch.append((root_norm, "dir", 0, st_root.st_mtime, st_root.st_ctime))
                    except Exception:
                        pass
                    self._scan_dir(root_norm, conn, db, batch)
                self._flush_batch(conn, db, batch)
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
            modified_paths = [path for path in sorted(common_paths) if before[path] != after[path]]

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
        created_dirs_set = set(created_dirs)

        root_dirs = []
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
        self.translator = Translator("es")
        self.worker_thread: Optional[QThread] = None
        self._build_ui()
        self.retranslate_ui()

    def _build_ui(self):
        self.setMinimumSize(1180, 760)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.subtitle_label = QLabel()
        self.subtitle_label.setWordWrap(True)
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #9b5d00;")
        main_layout.addWidget(self.subtitle_label)
        main_layout.addWidget(self.note_label)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_run_tab()
        self._build_settings_tab()
        self._build_filters_tab()

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        main_layout.addWidget(self.progress)

        self.statusBar().showMessage("Ready")

    def _build_run_tab(self):
        run_tab = QWidget()
        layout = QVBoxLayout(run_tab)

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
        layout.addLayout(btn_layout)

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
        layout.addWidget(splitter)

        self.tabs.addTab(run_tab, "")

    def _build_settings_tab(self):
        settings_tab = QWidget()
        layout = QVBoxLayout(settings_tab)
        form_group = QGroupBox()
        form_layout = QGridLayout(form_group)

        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Español", "es")
        self.lang_combo.setCurrentIndex(1)
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)

        self.scan_roots_label = QLabel()
        self.scan_roots_edit = QLineEdit("; ".join(DEFAULT_SCAN_ROOTS))

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
        form_layout.addWidget(self.scan_roots_label, 1, 0)
        form_layout.addWidget(self.scan_roots_edit, 1, 1, 1, 2)
        form_layout.addWidget(self.db_label, 2, 0)
        form_layout.addWidget(self.db_edit, 2, 1)
        form_layout.addWidget(self.db_btn, 2, 2)
        form_layout.addWidget(self.reports_label, 3, 0)
        form_layout.addWidget(self.reports_edit, 3, 1)
        form_layout.addWidget(self.reports_btn, 3, 2)
        form_layout.addWidget(self.before_label, 4, 0)
        form_layout.addWidget(self.before_edit, 4, 1, 1, 2)
        form_layout.addWidget(self.after_label, 5, 0)
        form_layout.addWidget(self.after_edit, 5, 1, 1, 2)
        layout.addWidget(form_group)
        layout.addStretch(1)

        self.tabs.addTab(settings_tab, "")

    def _build_filters_tab(self):
        filters_tab = QWidget()
        layout = QVBoxLayout(filters_tab)

        self.filters_note_label = QLabel()
        self.filters_note_label.setWordWrap(True)
        layout.addWidget(self.filters_note_label)

        roots_group = QGroupBox()
        roots_layout = QVBoxLayout(roots_group)
        self.scan_roots_label_2 = QLabel()
        roots_layout.addWidget(self.scan_roots_label_2)
        self.scan_roots_text = QPlainTextEdit("\n".join(DEFAULT_SCAN_ROOTS))
        roots_layout.addWidget(self.scan_roots_text)
        roots_btns = QHBoxLayout()
        self.load_defaults_btn = QPushButton()
        self.load_defaults_btn.clicked.connect(self.load_recommended_defaults)
        self.clear_roots_btn = QPushButton()
        self.clear_roots_btn.clicked.connect(lambda: self.scan_roots_text.setPlainText(""))
        roots_btns.addWidget(self.load_defaults_btn)
        roots_btns.addWidget(self.clear_roots_btn)
        roots_btns.addStretch(1)
        roots_layout.addLayout(roots_btns)
        layout.addWidget(roots_group)

        excl_group = QGroupBox()
        excl_layout = QVBoxLayout(excl_group)
        self.excluded_label = QLabel()
        excl_layout.addWidget(self.excluded_label)
        self.excluded_text = QPlainTextEdit("\n".join(DEFAULT_EXCLUDED_FOLDERS))
        excl_layout.addWidget(self.excluded_text)
        excl_btns = QHBoxLayout()
        self.clear_excluded_btn = QPushButton()
        self.clear_excluded_btn.clicked.connect(lambda: self.excluded_text.setPlainText(""))
        excl_btns.addWidget(self.clear_excluded_btn)
        excl_btns.addStretch(1)
        excl_layout.addLayout(excl_btns)
        layout.addWidget(excl_group)

        self.scan_roots_text.textChanged.connect(self.sync_scan_roots_line_edit)
        layout.addStretch(1)

        self.tabs.addTab(filters_tab, "")

    def retranslate_ui(self):
        t = self.translator.t
        self.setWindowTitle(t("window_title"))
        self.subtitle_label.setText(t("app_subtitle"))
        self.note_label.setText(t("desktop_note"))
        self.tabs.setTabText(0, t("tab_run"))
        self.tabs.setTabText(1, t("tab_settings"))
        self.tabs.setTabText(2, t("tab_filters"))
        self.lang_label.setText(t("lang"))
        self.scan_roots_label.setText(t("scan_roots"))
        self.db_label.setText(t("database"))
        self.reports_label.setText(t("reports_dir"))
        self.before_label.setText(t("snapshot_before"))
        self.after_label.setText(t("snapshot_after"))
        self.db_btn.setText(t("browse"))
        self.reports_btn.setText(t("browse"))
        self.before_btn.setText(t("create_before"))
        self.after_btn.setText(t("create_after"))
        self.compare_btn.setText(t("compare"))
        self.table_group.setTitle(t("new_root_folders"))
        self.roots_table.setHorizontalHeaderLabels([t("name"), t("files"), t("folders"), t("size"), t("date"), t("path")])
        self.filters_note_label.setText(t("filters_note"))
        self.scan_roots_label_2.setText(t("scan_roots"))
        self.excluded_label.setText(t("excluded_folders"))
        self.load_defaults_btn.setText(t("edit_defaults"))
        self.clear_roots_btn.setText(t("clear_list"))
        self.clear_excluded_btn.setText(t("clear_list"))
        self.statusBar().showMessage(t("status_ready"))
        if not self.log_edit.toPlainText().strip():
            self.log(t("log_intro"))
            self.log(t("about_export"))

    def on_language_changed(self):
        self.translator.set_language(self.lang_combo.currentData())
        self.retranslate_ui()

    def sync_scan_roots_line_edit(self):
        roots = parse_multiline_paths(self.scan_roots_text.toPlainText())
        self.scan_roots_edit.setText("; ".join(roots))

    def load_recommended_defaults(self):
        self.scan_roots_text.setPlainText("\n".join(DEFAULT_SCAN_ROOTS))
        self.excluded_text.setPlainText("\n".join(DEFAULT_EXCLUDED_FOLDERS))
        self.sync_scan_roots_line_edit()
        self.log(self.translator.t("loaded_defaults"))

    def choose_db(self):
        path, _ = QFileDialog.getSaveFileName(self, APP_NAME, self.db_edit.text(), "SQLite (*.sqlite *.db)")
        if path:
            self.db_edit.setText(path)

    def choose_reports(self):
        path = QFileDialog.getExistingDirectory(self, APP_NAME, self.reports_edit.text() or str(Path.home()))
        if path:
            self.reports_edit.setText(path)

    def get_scan_roots(self) -> List[str]:
        text_roots = parse_multiline_paths(self.scan_roots_text.toPlainText())
        if text_roots:
            return text_roots
        return parse_multiline_paths(self.scan_roots_edit.text())

    def get_excluded_folders(self) -> List[str]:
        return parse_multiline_paths(self.excluded_text.toPlainText())

    def validate_common(self) -> bool:
        t = self.translator.t
        if self.worker_thread is not None:
            QMessageBox.warning(self, APP_NAME, t("busy"))
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
        if not self.get_scan_roots():
            QMessageBox.warning(self, APP_NAME, t("scan_roots_missing"))
            return False
        return True

    def _confirm_overwrite_if_needed(self, snapshot_name: str) -> bool:
        db = SnapshotDB(self.db_edit.text().strip())
        if not db.snapshot_exists(snapshot_name):
            return True
        return QMessageBox.question(self, APP_NAME, self.translator.t("confirm_overwrite")) == QMessageBox.StandardButton.Yes

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
        worker = ScanWorker(
            self.db_edit.text().strip(),
            self.get_scan_roots(),
            self.get_excluded_folders(),
            snapshot_name,
            self.reports_edit.text().strip(),
        )
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
