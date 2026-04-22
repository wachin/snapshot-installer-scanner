# Snapshot Installer Scanner

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-success)
![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6)
![License](https://img.shields.io/badge/License-MIT-yellow)

A PyQt6 desktop tool for Windows that captures two filesystem snapshots and compares them to identify what changed after installing a program.

## What it does

- Scans a filesystem root such as `C:\`
- Saves each snapshot into SQLite
- Compares the **before** and **after** snapshots
- Exports CSV reports for:
  - created items
  - deleted items
  - modified items
- Detects **new top-level created folders** and summarizes each one with:
  - folder name
  - number of new files inside it
  - number of new subfolders inside it
  - total size of new files inside it
  - folder date
  - full folder path
- Orders the folder summary from **largest to smallest**

## Why this is useful

When an installer runs, it often creates a main folder and then several nested subfolders and files under it. This tool helps you see the **main new folder roots** instead of only listing individual files.

Example summary output:

```text
Folder 1: "AppData", 5 Files, 4 Folders, 3.06 MB (3214363 bytes), 2026-04-22 08:30:41, "C:\AppData"
Folder 2: "duck", 1 Files, 1 Folders, 7 bytes (7 bytes), 2026-04-22 08:33:56, "C:\duck"
```

## Important note about the reports folder

Some users expect files to appear on the visible Windows Desktop, but that is not always what a code path means.

For example, a path based on the user's home folder may point to something like:

```text
C:\Users\YourName\snapshot_reports
```

That is **not necessarily the same thing as the Desktop** shown by Windows Explorer.

Because of that, this application shows the **exact full reports path** in the interface. Always verify the full path there before looking for the exported files.

## Requirements

- Windows 10 or 11
- Python 3.10+
- PyQt6

Install dependencies:

```bash
pip install PyQt6
```

## Run

```bash
python snapshot_installer_scanner.py
```

## Basic workflow

1. Choose the scan root, usually `C:\`
2. Choose the SQLite database path
3. Choose the reports folder
4. Click **Create initial snapshot**
5. Install the program you want to analyze
6. Click **Create post-install snapshot**
7. Click **Compare snapshots**
8. Review the table and the exported CSV/TXT reports

## Output files

The compare step exports:

- `created_items.csv`
- `deleted_items.csv`
- `modified_items.csv`
- `created_root_folders_summary.csv`
- `created_root_folders_summary.txt`

## Internationalization

This repository includes Qt Linguist translation source files:

- `i18n/snapshot_installer_scanner_en.ts`
- `i18n/snapshot_installer_scanner_es.ts`

This helps other developers add more languages later.

## Notes

- A full `C:\` scan can take a long time.
- Running the app as Administrator is recommended for broader filesystem access.
- The current comparison is metadata-based and does not hash file contents.

## License

MIT
