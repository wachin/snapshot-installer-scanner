import os
import sys
import csv
import time
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget, QTabWidget
)


APP_TITLE = "Snapshot Installer Scanner"
DB_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    root_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    snapshot_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    is_dir INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    ctime_ns INTEGER NOT NULL,
    mode INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, path),
    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_snapshot_path ON files(snapshot_id, path);
CREATE INDEX IF NOT EXISTS idx_files_snapshot_mtime ON files(snapshot_id, mtime_ns);

CREATE TABLE IF NOT EXISTS scan_errors (
    snapshot_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    error TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);
"""

DEFAULT_EXCLUDES = [
    r"C:\\Windows\\Temp",
    r"C:\\$Recycle.Bin",
    r"C:\\System Volume Information",
    r"C:\\ProgramData\\Microsoft\\Windows\\WER",
    r"C:\\ProgramData\\Microsoft\\Windows\\Caches",
    r"C:\\ProgramData\\Package Cache",
]

DEFAULT_SCAN_HINTS = [
    r"C:\\Program Files",
    r"C:\\Program Files (x86)",
    r"C:\\ProgramData",
    r"C:\\Users",
]


def human_dt_from_ns(value_ns: int) -> str:
    try:
        return datetime.fromtimestamp(value_ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


class SnapshotDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.executescript(DB_SCHEMA)

    def create_snapshot(self, label: str, root_path: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO snapshots(label, root_path, created_at) VALUES (?, ?, ?)",
            (label, root_path, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return cur.lastrowid

    def insert_file_batch(self, rows):
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO files(
                snapshot_id, path, is_dir, size, mtime_ns, ctime_ns, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def insert_error(self, snapshot_id: int, path: str, error: str):
        self.conn.execute(
            "INSERT INTO scan_errors(snapshot_id, path, error, created_at) VALUES (?, ?, ?, ?)",
            (snapshot_id, path, error, datetime.now().isoformat(timespec="seconds")),
        )

    def commit(self):
        self.conn.commit()

    def list_snapshots(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, label, root_path, created_at FROM snapshots ORDER BY id")
        return cur.fetchall()

    def get_snapshot(self, snapshot_id: int):
        cur = self.conn.cursor()
        cur.execute("SELECT id, label, root_path, created_at FROM snapshots WHERE id = ?", (snapshot_id,))
        return cur.fetchone()

    def compare_snapshots(self, before_id: int, after_id: int):
        cur = self.conn.cursor()

        created_sql = """
        SELECT a.path, a.is_dir, a.size, a.mtime_ns, a.ctime_ns, a.mode
        FROM files a
        LEFT JOIN files b
            ON b.snapshot_id = ? AND a.path = b.path
        WHERE a.snapshot_id = ? AND b.path IS NULL
        ORDER BY a.path
        """
        deleted_sql = """
        SELECT b.path, b.is_dir, b.size, b.mtime_ns, b.ctime_ns, b.mode
        FROM files b
        LEFT JOIN files a
            ON a.snapshot_id = ? AND a.path = b.path
        WHERE b.snapshot_id = ? AND a.path IS NULL
        ORDER BY b.path
        """
        modified_sql = """
        SELECT
            a.path,
            b.size AS before_size, a.size AS after_size,
            b.mtime_ns AS before_mtime_ns, a.mtime_ns AS after_mtime_ns,
            b.ctime_ns AS before_ctime_ns, a.ctime_ns AS after_ctime_ns,
            b.mode AS before_mode, a.mode AS after_mode
        FROM files a
        JOIN files b
            ON a.path = b.path
        WHERE a.snapshot_id = ?
          AND b.snapshot_id = ?
          AND (
                a.is_dir != b.is_dir
             OR a.size != b.size
             OR a.mtime_ns != b.mtime_ns
             OR a.ctime_ns != b.ctime_ns
             OR a.mode != b.mode
          )
        ORDER BY a.path
        """

        created = cur.execute(created_sql, (before_id, after_id)).fetchall()
        deleted = cur.execute(deleted_sql, (after_id, before_id)).fetchall()
        modified = cur.execute(modified_sql, (after_id, before_id)).fetchall()
        return created, deleted, modified

    def count_files_for_snapshot(self, snapshot_id: int) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM files WHERE snapshot_id = ?", (snapshot_id,))
        return cur.fetchone()[0]

    def count_errors_for_snapshot(self, snapshot_id: int) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM scan_errors WHERE snapshot_id = ?", (snapshot_id,))
        return cur.fetchone()[0]

    def close(self):
        self.conn.close()


class ScannerWorker(QObject):
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    scan_lines = pyqtSignal(str)
    finished = pyqtSignal(bool, str, int)

    def __init__(self, db_path: str, roots_to_scan: list[str], label: str, excluded_paths: list[str]):
        super().__init__()
        self.db_path = db_path
        self.roots_to_scan = roots_to_scan
        self.label = label
        self.excluded_paths = [self._norm(p) for p in excluded_paths if p.strip()]
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    @staticmethod
    def _norm(path: str) -> str:
        return os.path.normcase(os.path.normpath(path.strip().rstrip("\\/")))

    def _is_excluded(self, path: str) -> bool:
        npath = self._norm(path)
        for excl in self.excluded_paths:
            if not excl:
                continue
            if npath == excl or npath.startswith(excl + os.sep):
                return True
        return False

    def run(self):
        db = None
        try:
            db = SnapshotDatabase(self.db_path)
            root_label = " | ".join(self.roots_to_scan)
            snapshot_id = db.create_snapshot(self.label, root_label)
            self.log.emit(f"Snapshot '{self.label}' creado con ID {snapshot_id}.")

            batch = []
            scanned = 0
            stack = []
            for root in reversed(self.roots_to_scan):
                if root and os.path.exists(root) and not self._is_excluded(root):
                    stack.append(root)

            last_emit = time.time()
            live_lines = []

            while stack:
                if self._cancel_requested:
                    db.commit()
                    self.finished.emit(False, "Escaneo cancelado por el usuario.", snapshot_id)
                    return

                current_dir = stack.pop()
                if self._is_excluded(current_dir):
                    continue

                try:
                    with os.scandir(current_dir) as it:
                        for entry in it:
                            if self._cancel_requested:
                                db.commit()
                                self.finished.emit(False, "Escaneo cancelado por el usuario.", snapshot_id)
                                return

                            entry_path = os.path.normpath(entry.path)
                            if self._is_excluded(entry_path):
                                continue

                            try:
                                stat = entry.stat(follow_symlinks=False)
                                is_dir = 1 if entry.is_dir(follow_symlinks=False) else 0
                                size = stat.st_size if not is_dir else 0
                                row = (
                                    snapshot_id,
                                    entry_path,
                                    is_dir,
                                    size,
                                    int(stat.st_mtime_ns),
                                    int(getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000))),
                                    int(stat.st_mode),
                                )
                                batch.append(row)
                                scanned += 1

                                if is_dir:
                                    stack.append(entry.path)

                                live_lines.append(entry_path)
                                if len(batch) >= 2000:
                                    db.insert_file_batch(batch)
                                    db.commit()
                                    batch.clear()

                                now = time.time()
                                if now - last_emit >= 0.20:
                                    self.progress.emit(0, f"Escaneados: {scanned:,} | Actual: {entry_path}")
                                    if live_lines:
                                        self.scan_lines.emit("\n".join(live_lines))
                                        live_lines.clear()
                                    last_emit = now

                            except Exception as e:
                                db.insert_error(snapshot_id, entry.path, repr(e))
                except Exception as e:
                    db.insert_error(snapshot_id, current_dir, repr(e))

            if live_lines:
                self.scan_lines.emit("\n".join(live_lines))
            if batch:
                db.insert_file_batch(batch)
            db.commit()
            self.finished.emit(True, f"Escaneo completado. Elementos registrados: {scanned:,}", snapshot_id)

        except Exception:
            error_text = traceback.format_exc()
            self.finished.emit(False, error_text, -1)
        finally:
            if db:
                db.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1020, 760)

        self.worker_thread = None
        self.worker = None

        self.root_edit = QLineEdit(r"C:\\")
        self.db_edit = QLineEdit(str(Path.home() / "snapshots.sqlite"))
        self.export_dir_edit = QLineEdit(str(Path.home() / "Desktop"))
        self.before_label_edit = QLineEdit("ANTES")
        self.after_label_edit = QLineEdit("DESPUÉS")
        self.before_id_edit = QLineEdit()
        self.after_id_edit = QLineEdit()

        self.include_paths_edit = QPlainTextEdit()
        self.exclude_paths_edit = QPlainTextEdit()
        self.include_paths_edit.setPlaceholderText("Una carpeta por línea. Si lo dejas vacío, se usa la ruta principal.")
        self.exclude_paths_edit.setPlaceholderText("Una carpeta por línea para excluir del escaneo.")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self.status_label = QLabel("Listo.")
        self.snapshots_label = QLabel("Snapshots: ninguno cargado todavía.")

        self.scan_log_box = QPlainTextEdit()
        self.scan_log_box.setReadOnly(True)
        self.main_log_box = QPlainTextEdit()
        self.main_log_box.setReadOnly(True)

        self.btn_scan_before = QPushButton("1) Crear escaneo inicial")
        self.btn_scan_after = QPushButton("2) Crear escaneo después de instalar")
        self.btn_compare = QPushButton("3) Comparar snapshots")
        self.btn_refresh = QPushButton("Actualizar lista")
        self.btn_cancel = QPushButton("Cancelar escaneo")
        self.btn_cancel.setEnabled(False)
        self.btn_load_recommended = QPushButton("Cargar rutas recomendadas")

        self._build_ui()
        self._connect_signals()
        self._load_default_filters()
        self.refresh_snapshots()

    def _build_ui(self):
        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        layout = QVBoxLayout(root_widget)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: ejecución
        tab_run = QWidget()
        run_layout = QVBoxLayout(tab_run)

        action_group = QGroupBox("Proceso")
        action_layout = QHBoxLayout(action_group)
        action_layout.addWidget(self.btn_scan_before)
        action_layout.addWidget(self.btn_scan_after)
        action_layout.addWidget(self.btn_compare)
        action_layout.addWidget(self.btn_refresh)
        action_layout.addWidget(self.btn_cancel)

        ids_group = QGroupBox("IDs para comparar")
        ids_layout = QGridLayout(ids_group)
        ids_layout.addWidget(QLabel("Snapshot ANTES:"), 0, 0)
        ids_layout.addWidget(self.before_id_edit, 0, 1)
        ids_layout.addWidget(QLabel("Snapshot DESPUÉS:"), 0, 2)
        ids_layout.addWidget(self.after_id_edit, 0, 3)

        run_layout.addWidget(action_group)
        run_layout.addWidget(ids_group)
        run_layout.addWidget(self.progress_bar)
        run_layout.addWidget(self.status_label)
        run_layout.addWidget(QLabel("Escaneos:"))
        run_layout.addWidget(self.scan_log_box, 2)
        run_layout.addWidget(QLabel("Snapshots:"))
        run_layout.addWidget(self.snapshots_label)
        run_layout.addWidget(QLabel("Registro general:"))
        run_layout.addWidget(self.main_log_box, 2)

        # Tab 2: opciones
        tab_options = QWidget()
        opt_layout = QVBoxLayout(tab_options)

        cfg_group = QGroupBox("Opciones")
        cfg_grid = QGridLayout(cfg_group)
        cfg_grid.addWidget(QLabel("Ruta principal a escanear:"), 0, 0)
        cfg_grid.addWidget(self.root_edit, 0, 1)
        btn_root = QPushButton("Elegir...")
        cfg_grid.addWidget(btn_root, 0, 2)

        cfg_grid.addWidget(QLabel("Base de datos SQLite:"), 1, 0)
        cfg_grid.addWidget(self.db_edit, 1, 1)
        btn_db = QPushButton("Guardar como...")
        cfg_grid.addWidget(btn_db, 1, 2)

        cfg_grid.addWidget(QLabel("Carpeta exportación CSV:"), 2, 0)
        cfg_grid.addWidget(self.export_dir_edit, 2, 1)
        btn_export_dir = QPushButton("Elegir...")
        cfg_grid.addWidget(btn_export_dir, 2, 2)

        cfg_grid.addWidget(QLabel("Etiqueta primer snapshot:"), 3, 0)
        cfg_grid.addWidget(self.before_label_edit, 3, 1)
        cfg_grid.addWidget(QLabel("Etiqueta segundo snapshot:"), 4, 0)
        cfg_grid.addWidget(self.after_label_edit, 4, 1)

        opt_layout.addWidget(cfg_group)
        opt_layout.addStretch(1)

        # Tab 3: carpetas y exclusiones
        tab_filters = QWidget()
        filters_layout = QVBoxLayout(tab_filters)

        filters_group = QGroupBox("Carpetas a escanear y exclusiones")
        filters_grid = QGridLayout(filters_group)
        filters_grid.addWidget(QLabel("Carpetas a escanear (una por línea):"), 0, 0)
        filters_grid.addWidget(self.include_paths_edit, 1, 0)
        filters_grid.addWidget(QLabel("Carpetas excluidas (una por línea):"), 0, 1)
        filters_grid.addWidget(self.exclude_paths_edit, 1, 1)
        filters_layout.addWidget(filters_group)
        filters_layout.addWidget(self.btn_load_recommended)
        filters_layout.addStretch(1)

        tabs.addTab(tab_run, "Ejecución")
        tabs.addTab(tab_options, "Opciones")
        tabs.addTab(tab_filters, "Carpetas")

        btn_root.clicked.connect(self.choose_root)
        btn_db.clicked.connect(self.choose_db)
        btn_export_dir.clicked.connect(self.choose_export_dir)

    def _connect_signals(self):
        self.btn_scan_before.clicked.connect(lambda: self.start_scan(self.before_label_edit.text().strip() or "ANTES"))
        self.btn_scan_after.clicked.connect(self.start_after_scan)
        self.btn_compare.clicked.connect(self.compare_snapshots)
        self.btn_refresh.clicked.connect(self.refresh_snapshots)
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_load_recommended.clicked.connect(self._load_default_filters)

    def _load_default_filters(self):
        if not self.include_paths_edit.toPlainText().strip():
            self.include_paths_edit.setPlainText("\n".join(DEFAULT_SCAN_HINTS))
        if not self.exclude_paths_edit.toPlainText().strip():
            self.exclude_paths_edit.setPlainText("\n".join(DEFAULT_EXCLUDES))

    def append_log(self, text: str):
        self.main_log_box.appendPlainText(text)

    def append_scan_lines(self, text: str):
        if not text.strip():
            return
        self.scan_log_box.appendPlainText(text)
        sb = self.scan_log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def choose_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Elegir carpeta a escanear", self.root_edit.text())
        if folder:
            self.root_edit.setText(folder)

    def choose_db(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Elegir base de datos SQLite", self.db_edit.text(), "SQLite DB (*.sqlite *.db)"
        )
        if filename:
            self.db_edit.setText(filename)

    def choose_export_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Elegir carpeta de exportación", self.export_dir_edit.text())
        if folder:
            self.export_dir_edit.setText(folder)

    def _get_paths_from_editor(self, editor: QPlainTextEdit) -> list[str]:
        result = []
        for line in editor.toPlainText().splitlines():
            line = line.strip().strip('"')
            if line:
                result.append(os.path.normpath(line))
        return result

    def _get_effective_scan_roots(self) -> list[str]:
        paths = self._get_paths_from_editor(self.include_paths_edit)
        if paths:
            return paths
        root = self.root_edit.text().strip()
        return [root] if root else []

    def set_busy(self, busy: bool):
        self.progress_bar.setVisible(busy)
        self.btn_scan_before.setEnabled(not busy)
        self.btn_scan_after.setEnabled(not busy)
        self.btn_compare.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def ensure_db_exists(self):
        db_path = self.db_edit.text().strip()
        if not db_path:
            QMessageBox.warning(self, "Falta ruta", "Debes indicar la ruta de la base de datos.")
            return False
        SnapshotDatabase(db_path).close()
        return True

    def start_scan(self, label: str):
        roots = self._get_effective_scan_roots()
        db_path = self.db_edit.text().strip()
        excludes = self._get_paths_from_editor(self.exclude_paths_edit)

        if not roots:
            QMessageBox.warning(self, "Falta ruta", "Debes indicar al menos una ruta a escanear.")
            return

        existing_roots = [r for r in roots if os.path.exists(r)]
        if not existing_roots:
            QMessageBox.warning(self, "Ruta inválida", "Ninguna de las rutas a escanear existe.")
            return
        if not self.ensure_db_exists():
            return

        self.scan_log_box.clear()
        self.set_busy(True)
        self.status_label.setText(f"Iniciando escaneo '{label}'...")
        self.append_log(f"\n=== Iniciando escaneo '{label}' ===")
        for root in existing_roots:
            self.append_log(f"Escaneando raíz: {root}")
        if excludes:
            self.append_log(f"Exclusiones activas: {len(excludes)}")

        self.worker_thread = QThread()
        self.worker = ScannerWorker(db_path, existing_roots, label, excludes)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.log.connect(self.append_log)
        self.worker.scan_lines.connect(self.append_scan_lines)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def start_after_scan(self):
        label = self.after_label_edit.text().strip() or "DESPUÉS"
        reply = QMessageBox.question(
            self,
            "Instalación del programa",
            "Ahora instala el programa que quieres analizar.\n\n"
            "Cuando termines la instalación, pulsa 'Yes' para iniciar el segundo escaneo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.start_scan(label)

    def cancel_scan(self):
        if self.worker:
            self.worker.request_cancel()
            self.append_log("Se solicitó la cancelación del escaneo...")

    def on_scan_progress(self, _value: int, text: str):
        self.status_label.setText(text)

    def on_scan_finished(self, ok: bool, message: str, snapshot_id: int):
        self.set_busy(False)
        self.status_label.setText("Listo." if ok else "Finalizado con incidencias.")
        self.append_log(message)
        self.refresh_snapshots()

        if snapshot_id > 0:
            if self.before_id_edit.text().strip() == "":
                self.before_id_edit.setText(str(snapshot_id))
            else:
                self.after_id_edit.setText(str(snapshot_id))

        if ok:
            QMessageBox.information(self, "Escaneo terminado", message)
        else:
            QMessageBox.warning(self, "Escaneo terminado", message)

    def refresh_snapshots(self):
        db_path = self.db_edit.text().strip()
        if not db_path or not os.path.exists(db_path):
            self.snapshots_label.setText("Snapshots: base de datos aún no creada.")
            return

        db = None
        try:
            db = SnapshotDatabase(db_path)
            rows = db.list_snapshots()
            if not rows:
                self.snapshots_label.setText("Snapshots: todavía no hay escaneos.")
                return

            lines = []
            for sid, label, root_path, created_at in rows:
                file_count = db.count_files_for_snapshot(sid)
                err_count = db.count_errors_for_snapshot(sid)
                lines.append(
                    f"ID {sid}: {label} | {created_at} | {root_path} | archivos={file_count:,} | errores={err_count:,}"
                )
            self.snapshots_label.setText("Snapshots cargados:\n" + "\n".join(lines))
        except Exception as e:
            self.snapshots_label.setText(f"Error al leer snapshots: {e}")
        finally:
            if db:
                db.close()

    def compare_snapshots(self):
        db_path = self.db_edit.text().strip()
        if not os.path.exists(db_path):
            QMessageBox.warning(self, "Base de datos no encontrada", "Primero crea por lo menos dos snapshots.")
            return

        try:
            before_id = int(self.before_id_edit.text().strip())
            after_id = int(self.after_id_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "IDs inválidos", "Debes indicar dos IDs numéricos de snapshots.")
            return

        export_dir = self.export_dir_edit.text().strip()
        if not export_dir:
            export_dir = str(Path.home() / "Desktop")
        os.makedirs(export_dir, exist_ok=True)

        db = SnapshotDatabase(db_path)
        try:
            before = db.get_snapshot(before_id)
            after = db.get_snapshot(after_id)
            if not before or not after:
                QMessageBox.warning(self, "Snapshots no encontrados", "Uno o ambos IDs no existen.")
                return

            self.append_log(f"\n=== Comparando snapshot {before_id} con snapshot {after_id} ===")
            created, deleted, modified = db.compare_snapshots(before_id, after_id)
        finally:
            db.close()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        created_csv = os.path.join(export_dir, f"cambios_creados_{before_id}_{after_id}_{timestamp}.csv")
        deleted_csv = os.path.join(export_dir, f"cambios_eliminados_{before_id}_{after_id}_{timestamp}.csv")
        modified_csv = os.path.join(export_dir, f"cambios_modificados_{before_id}_{after_id}_{timestamp}.csv")
        summary_txt = os.path.join(export_dir, f"resumen_comparacion_{before_id}_{after_id}_{timestamp}.txt")

        with open(created_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "is_dir", "size", "mtime", "ctime", "mode"])
            for row in created:
                writer.writerow([row[0], row[1], row[2], human_dt_from_ns(row[3]), human_dt_from_ns(row[4]), row[5]])

        with open(deleted_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "is_dir", "size", "mtime", "ctime", "mode"])
            for row in deleted:
                writer.writerow([row[0], row[1], row[2], human_dt_from_ns(row[3]), human_dt_from_ns(row[4]), row[5]])

        with open(modified_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "path",
                "before_size", "after_size",
                "before_mtime", "after_mtime",
                "before_ctime", "after_ctime",
                "before_mode", "after_mode"
            ])
            for row in modified:
                writer.writerow([
                    row[0],
                    row[1], row[2],
                    human_dt_from_ns(row[3]), human_dt_from_ns(row[4]),
                    human_dt_from_ns(row[5]), human_dt_from_ns(row[6]),
                    row[7], row[8],
                ])

        with open(summary_txt, "w", encoding="utf-8") as f:
            f.write("Comparación de snapshots\n")
            f.write(f"Antes : ID {before_id} | {before[1]} | {before[3]} | {before[2]}\n")
            f.write(f"Después: ID {after_id} | {after[1]} | {after[3]} | {after[2]}\n")
            f.write("\n")
            f.write(f"Archivos/carpetas creados    : {len(created):,}\n")
            f.write(f"Archivos/carpetas eliminados : {len(deleted):,}\n")
            f.write(f"Archivos/carpetas modificados: {len(modified):,}\n")
            f.write("\n")
            f.write("Archivos generados:\n")
            f.write(f"- {created_csv}\n")
            f.write(f"- {deleted_csv}\n")
            f.write(f"- {modified_csv}\n")
            f.write(f"- {summary_txt}\n")

        msg = (
            "Comparación terminada.\n\n"
            f"Creados: {len(created):,}\n"
            f"Eliminados: {len(deleted):,}\n"
            f"Modificados: {len(modified):,}\n\n"
            f"Se exportó un resumen y 3 archivos CSV en:\n{export_dir}"
        )
        self.append_log(msg)
        QMessageBox.information(self, "Comparación terminada", msg)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
