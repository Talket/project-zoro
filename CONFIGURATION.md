# PROJECT ZORO — Configuration Reference

ZORO utilizes **Pydantic v2 `BaseSettings`** with support for environment variables, `.env` files, and dynamic settings.

---

## 1. Environment Variables & Defaults

All settings can be overridden by environment variables prefixed with `ZORO_`.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `ZORO_APP_ENV` | `str` | `production` | Environment mode (`development`, `testing`, `production`). |
| `ZORO_LOG_LEVEL` | `str` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `ZORO_INSTANCE_ID` | `str` | `zoro-primary` | Identifier for the running instance. |
| `ZORO_DATA_DIR` | `str` | `%APPDATA%\Zoro` | Path to persistent user data and state. |
| `ZORO_DB_PATH` | `str` | `%APPDATA%\Zoro\zoro.db` | Absolute path to the SQLite database. |
| `ZORO_MAX_VRAM_MB` | `int` | `3600` | VRAM safety ceiling before governor throttles work. |
| `ZORO_MAX_RAM_MB` | `int` | `13800` | System RAM ceiling before garbage collection/alerts. |
| `ZORO_MODEL_IDLE_TIMEOUT_SEC` | `int` | `600` | Inactivity seconds before model is evicted from VRAM. |
| `ZORO_PIPE_NAME` | `str` | `\\.\pipe\zoro-ipc-main` | Windows Named Pipe endpoint for IPC. |
| `ZORO_IPC_MAX_PAYLOAD_MB` | `int` | `16` | Maximum payload size for JSON-RPC messages. |
| `ZORO_UI_THEME` | `str` | `dark_obsidian` | Desktop UI theme name. |
| `ZORO_UI_START_MINIMIZED` | `bool` | `true` | Launch minimized to system tray by default. |

---

## 2. Directory Resolution Hierarchy

ZORO dynamically resolves paths via `zoro.config.paths.AppPaths`:
- **Workspace Root**: The active repository root (`D:\downloads\PROJECTS\ZORO`).
- **User Data Root**: `%APPDATA%\Zoro` (created automatically with restricted permissions).
- **Security Root**: `%PROGRAMDATA%\Zoro\Security` (for halt lockfile and supervisor tokens).
- **Database File**: `%APPDATA%\Zoro\zoro.db`.
- **Logs Directory**: `%APPDATA%\Zoro\logs`.
