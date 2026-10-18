# PKDiskAudit

![PKDiskAudit icon](icon.png)

[🇫🇷 FR](README.md) · [🇬🇧 EN](README_en.md)

❤️ [Support PK Disk Audit on Ko-fi](https://ko-fi.com/pouark)

**Read-only macOS disk audit.** It measures, classifies and explains where your space went — then lets you decide. No deletions in this version.

Version `2026.10.1` · [Changelog](CHANGELOG.md)

## ✅ Features

- **Real measurements**: allocated bytes (like `du`), sparse files and APFS clones handled, network mounts excluded.
- **Disk map**: treemap of the big consumers, Data volume gauge, home / applications / system split.
- **The payload**: every item classified as `safe` (cache, build, dependencies), `needs review` (models, VMs, apps) or ignored.
- **Per-path detail**: size, age, owning project, proposed action — never executed without review.
- **Applications**: 345 apps measured, last use and launch count from Spotlight, with unknown usage made explicit.
- **AI models**: Hugging Face, Ollama, LM Studio and third-party app `models` folders.
- **Zombies**: OpenCode database free pages, Chrome code-sign clones, caches, build artifacts, VMs.
- **Self-contained HTML report**: exportable, offline, no dependencies.

## 🚀 Usage

```sh
# Full audit + HTML report
PYTHONPATH=engine python3 -m pkdisk run --out ~/Desktop/pkdisk-report

# Fast scan (caches, OpenCode database, clones, VMs, Trash)
PYTHONPATH=engine python3 -m pkdisk run --fast --out ~/Desktop/pkdisk-report

# Also search for large old files (slower)
PYTHONPATH=engine python3 -m pkdisk run --large --out ~/Desktop/pkdisk-report

# Check environment (permissions, tools, disk)
PYTHONPATH=engine python3 -m pkdisk doctor
```

### macOS app

```sh
./packaging/run.sh              # build + run from the repo
./packaging/build_engine.sh     # standalone engine (PyInstaller)
./packaging/build_app.sh        # dist/PKDiskAudit.app
```

The SwiftUI app shows the report in a `WKWebView`, runs the engine, follows live progress and exports the HTML.

## 🧱 Architecture

| Layer | Role | File |
|---|---|---|
| Engine | measurement, classification, JSON | `engine/pkdisk/` |
| Report | self-contained HTML from JSON | `report/style.css` + `engine/pkdisk/report.py` |
| App | native window, progress, export | `src/macos/PKDiskAuditApp.swift` |

The engine never deletes anything. It emits a versioned JSON (`schema: 1`) consumed by the app and the report.

## 🔒 Safety

- Read-only by default; no destructive command is executed.
- Nested roots deduplicated, network mounts and cloud volumes excluded.
- Every scan reports whether it is **complete** or **partial** (`partial_sections`) — an unreadable folder is never counted as empty.
- Proposed actions (delete, VACUUM, uninstall) are described, not performed.

## 📝 Notes

- **`useCount = 0` does not mean "never used"**: Spotlight does not track every app. The report says so explicitly.
- A SQLite `VACUUM` compacts the file without deleting a single session; it only requires OpenCode to be closed.
- Inspired by [Mole](https://github.com/tw93/Mole) (GPL-3.0) and CleanMyMac CLI for the scan → review → confirm model. No code from those projects is reused.

## 📄 License

MIT — see [LICENSE](LICENSE).
