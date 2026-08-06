# MaaQQLogin Agent Guide

## Scope

- The active desktop entry point is `tools/qt_workbench.py`; `job-editor.bat` launches it.
- Treat `tools/job_editor.py` and `tools/job_runner_app.py` as legacy Tk code unless a task explicitly targets them.
- Keep `README.md` and `界面功能说明.md` aligned with behavior that exists in the active Qt entry point.

## Safety

- Do not put passwords, tokens, or account secrets in `jobs/**/*.maa_job.json`; `InputText` is stored as plaintext.
- Preserve user-created files under `jobs/` and templates referenced from `assets/resource/image/jobs/` when changing packaging or migration code.
- Preserve `jobs/semantic_map.json`; it contains user-created page and region names.
- Do not delete generated or user data unless the user explicitly approves the exact targets.

## Validation

- Run `python tools/validate_schema.py` after changing `assets/interface.json` or Pipeline resources.
- Run `python -m unittest discover -s tools -p "test_*.py"` after changing job models, the library, the runner, or packaging behavior.
- For UI changes, launch `python tools/qt_workbench.py` and verify recording, playback, and semantic navigation pages. Use an ADB device when the change depends on device behavior.
- Build releases with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version <version>`.
