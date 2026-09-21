# Install DDRCV on Windows

For installation followed by source setup, integrations, and a first rehearsal,
use the [operator walkthrough](operator_walkthrough.md). This page covers the
installer and environment options in detail.

## First-time setup

1. Download and extract the repository ZIP, or clone it. Put it in a writable
   folder such as `C:\Games\ddrcv`, outside `Program Files`.
2. Double-click **setup_desktop.bat** and choose **1** to install local Python,
   **2** to select a detected installation, or **3** to enter your own path.
   On a fresh install, pressing Enter chooses local Python. Leave the console
   open until it reports success. First setup needs internet and can take several minutes.
3. Double-click **launch_desktop.vbs** to open the tournament app.

For browser-based rehearsal, use **setup_workbench.bat** and
**launch_workbench.bat** instead. You can install both in the same checkout.
Setup only installs software and checks readiness; it does not start capture.

No preinstalled Python, Python launcher, uv, or administrator terminal is
required. Setup uses the versioned official uv installer and keeps uv, its
cache, and managed Python inside `.tools`. The application environment lives in
`.venv`. It does not change your global Python or PATH. Keep `.tools/python`
alongside `.venv`: the environment depends on that interpreter.

Setup supports **Windows x64 and CPython 3.12**. This deliberately matches the
validated native dependency versions. Windows ARM Python, 32-bit Python, and
other Python minors are rejected. The desktop setup checks WebView2 and, if
missing, downloads Microsoft's signed Evergreen bootstrapper and runs its
per-user installation. Company device policies may require IT assistance.

Both setup paths download the OCR model when necessary and require actual
recognition of the bundled test crops. Optional OBS and the sibling
`ddr_score_render` checkout are not prerequisites for recognition. If that
checkout is present, setup registers it in the environment without installing
its dependencies, preserving the previous renderer integration behavior.

## Use your own Python

The desktop setup menu checks common per-user, Program Files, drive-root,
Scoop, uv, Windows registry, and PATH locations. Only existing, runnable x64
CPython 3.12 installations appear in the list. Manual entry accepts a quoted
path to `python.exe` or its folder, including paths with spaces and Windows
environment variables such as `%LOCALAPPDATA%`. Invalid paths return you to the
menu; **Q** cancels before installation starts.

If `.venv` exists, **4** (also the Enter default) reuses it after validation.
Choosing local Python while that environment uses system Python explains how
to rename the old environment as a backup. Setup never replaces it implicitly.

To bypass the menu, supply the interpreter directly.
From Command Prompt or PowerShell in the repository folder:

```bat
.\setup_desktop.bat -Python "C:\Program Files\Python312\python.exe"
.\setup_workbench.bat -Python "D:\Python312\python.exe"
```

The supplied interpreter must be x64 CPython 3.12 with Tkinter. Setup uses that
interpreter to create the venv and disables Python downloads on this path. The
path is passed as one argument, including when it contains spaces.

With `-NonInteractive` and no `-Python`, setup reuses a compatible `.venv`; when
no environment exists, it installs/uses a checkout-local managed Python.
Workbench setup retains this automatic behavior by default. With `-Python`, an existing
environment must also use the same base interpreter. Setup refuses to overwrite
an incompatible, broken, or non-venv directory. Close DDRCV, rename `.venv` to a
backup name, and rerun setup to switch interpreters. Application settings and
Results records are stored separately and are not removed by setup.

For a separate environment, use `-Venv "C:\path\to\ddrcv-env"`. The standard
launchers always use `.venv`; launch a custom environment explicitly:

```bat
"C:\path\to\ddrcv-env\Scripts\python.exe" -B -m ddrcv.desktop
```

For unattended desktop invocation, pass `-NonInteractive` (or `-Python`) to skip
the menu, and set `DDRCV_SETUP_NO_PAUSE=1` to skip the batch file's final pause:

```bat
set DDRCV_SETUP_NO_PAUSE=1
setup_desktop.bat -NonInteractive
```

These options also work when calling `tools\setup.ps1` directly with PowerShell.
Redirected input requires `-NonInteractive` or `-Python`; it cannot accidentally
accept a menu default. Setup returns a nonzero exit code on failure.

## Package and manual installation

`pyproject.toml` is the source of package metadata and direct dependencies.
Extras are `ocr`, `tournament`, `workbench`, and `desktop`; each application
includes the tournament and OCR requirements. The desktop extra also includes
workbench support. `uv.lock` records the transitive resolution and artifact
hashes. The supported setup runs `uv sync --locked --inexact`: it refuses a
stale lockfile and retains unrelated installed packages unless they conflict
with required dependencies.

Experienced users can create an environment with their own Python and pip:

```bat
"C:\path\to\Python312\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.venv\Scripts\python.exe -B -m ddrcv.ocr.check --provision
.venv\Scripts\python.exe -B -m ddrcv.desktop --check
```

Pip uses the declared direct pins but resolves transitive versions afresh.
Use the setup scripts for the checked-in lockfile, Python provisioning, and
WebView2 installation. For a smaller manual install, select `.[ocr]`,
`.[tournament]`, or `.[workbench]` in place of `.[desktop]`; run these commands
from the repository root. Application dependencies are maintained only in
`pyproject.toml` and `uv.lock`.

Historical EasyOCR/Torch/jacket experiments use `requirements-legacy.txt`,
outside the supported application lock, in a separate environment. The
requirements files under `apps/obs` and `apps/state_simulator` belong to those
standalone legacy tools; the desktop installer does not use them.

Wheel and source distributions use the standard build interface, without
`setup.py`. To build and refresh the lock with an installed uv:

```bat
uv lock
uv build
```

Commit `pyproject.toml` and the refreshed `uv.lock` together when changing
dependencies. Run setup and the OCR/application checks after updating the lock.
The lock pins application packages; the managed Python 3.12 patch release,
seeded pip, and isolated build backend can update within their declared ranges.

## Update and troubleshoot

Close the desktop/tray app, workbench, and any running CLI driver before
updating. Pull/extract the new source, then rerun the same setup script.
Compatible environments are reused, and existing settings are preserved.
An interrupted download/install can be retried with the same command.

If a download fails, check internet/proxy access to Astral, GitHub, PyPI,
Microsoft (desktop only), and the OCR model host shown in the error. Runtime OCR
works offline after provisioning. Initial offline installation is not supported
by the double-click installer. For a missing WebView2 runtime that cannot be
installed automatically, install it from Microsoft's download page, then rerun
setup. If managed Python is deleted or the checkout moves, recreate `.venv`.

References: [uv Python management](https://docs.astral.sh/uv/guides/install-python/),
[uv installer options](https://docs.astral.sh/uv/reference/installer/),
[uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/), and
[Microsoft WebView2 deployment](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).
