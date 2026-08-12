# Qdd Agent Guide

## Scope

- The active desktop entry point is `tools/qt_workbench.py`; `job-editor.bat` launches it.
- Treat `tools/job_editor.py` and `tools/job_runner_app.py` as legacy Tk code unless a task explicitly targets them.
- Keep `README.md` and `界面功能说明.md` aligned with behavior that exists in the active Qt entry point.

## Safety

- Do not put passwords, tokens, or account secrets in job JSON; `InputText` is stored as plaintext.
- Treat `tools/app_paths.py` as the authority for writable paths. Preserve `jobs_dir`, `template_dir`, and `jobs_dir/semantic_map.json` when changing packaging or migration code.
- Installed Windows data lives under `%LOCALAPPDATA%\Qdd`; portable and source modes keep their documented app/project-relative layouts. Never make active code write beneath installed `assets/`.
- Release ZIPs and installers must start with blank jobs and no recorded templates. Restore local portable data only after all release artifacts are created.
- Do not delete generated or user data unless the user explicitly approves the exact targets.

## Validation

- Run `python tools/validate_schema.py` after changing `assets/interface.json` or Pipeline resources.
- Run `python -m unittest discover -s tools -p "test_*.py"` after changing data paths, job models, the library, the runner, or packaging behavior.
- For UI changes, launch `python tools/qt_workbench.py` and verify recording, playback, and semantic navigation pages. Use an ADB device when the change depends on device behavior.
- Build Windows releases with Inno Setup 6 installed: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version <version>`. The build must produce both the portable ZIP and Setup EXE.
