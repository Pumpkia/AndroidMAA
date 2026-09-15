# NnMaa Agent Guide

## Scope

- The single entry point is the packaged `NnMaa.exe` (PyInstaller entry script `tools/qt_workbench.py`). No arguments opens the workbench; `--run [task]`, `--serial`, `--help` and `--version` drive the headless pipeline in `tools/pipeline_cli.py`. Do not reintroduce bat or python launcher shims.
- Treat `tools/job_editor.py` and `tools/job_runner_app.py` as legacy Tk code unless a task explicitly targets them.
- Keep `README.md` and `界面功能说明.md` aligned with behavior that exists in the active Qt entry point.
- The asset workspace is `tools/asset_page.py` with catalog logic in `tools/asset_model.py`.
- Stage recognition and chapter-list navigation live in `tools/stage_model.py` and `tools/stage_navigator.py`.
- Workbench taps go through `tools/scrcpy_input.py` (scrcpy overlay click, falling back to `adb input tap`); tests set `NNMAA_USE_SCRCPY=0`. Do not pass `--mouse=uhid` or `--keyboard=uhid` (they can kill the game).

## Safety

- Do not put passwords, tokens, or account secrets in job JSON; `InputText` is stored as plaintext.
- Treat `tools/app_paths.py` as the authority for writable paths. Preserve `jobs_dir`, `template_dir`, `game_asset_dir`, `jobs_dir/semantic_map.json`, and `jobs_dir/clothing_memory.json` when changing packaging or migration code.
- Scripts must not read Excel. The only clothing ledger is `jobs/clothing_memory.json` (`clothing_memory.py`). `have` changes only via inventory edits or job success callbacks.
- Installed Windows data lives under `%LOCALAPPDATA%\NnMaa`; portable and source modes keep their documented app/project-relative layouts. Never make active code write beneath installed `assets/`.
- Release ZIPs and installers must start with blank jobs and no recorded templates. Restore local portable data only after all release artifacts are created.
- Do not delete generated or user data unless the user explicitly approves the exact targets.

## Validation

- Run `python tools/validate_schema.py` after changing `assets/interface.json` or Pipeline resources.
- Run `python -m unittest discover -s tools -p "test_*.py"` after changing data paths, job models, the library, the runner, or packaging behavior.
- For UI changes, launch `python tools/qt_workbench.py` and verify recording, playback, and asset pages. Use an ADB device when the change depends on device behavior.
- Build Windows releases with Inno Setup 6 installed: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version <version>`. The build must produce both the portable ZIP and Setup EXE.
