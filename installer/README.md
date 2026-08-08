<div align="center">

# Windows installer

**Packages the Flutter desktop client into a single `PersonalERP-Setup.exe`.**

![Inno Setup](https://img.shields.io/badge/Inno_Setup-6.3_or_newer-2D6099?style=flat-square)
![Architecture](https://img.shields.io/badge/x64-only-6E7681?style=flat-square)
![Scope](https://img.shields.io/badge/install-per--user_by_default-4C8BF5?style=flat-square)

[Desktop client](../app_frontend/README.md) · [Root README](../README.md)

</div>

---

## Prerequisites

**1. Inno Setup 6.3 or newer** - <https://jrsoftware.org/isdl.php>

When installing Inno Setup, **leave "Install Inno Setup Preprocessor" checked**. It is
on by default, and it is the one option that matters: [`personal-erp.iss`](personal-erp.iss)
uses `#define` and `#if`, and without the preprocessor it will not compile.

6.3 is the floor because the script uses `ArchitecturesAllowed=x64compatible`. On an
older 6.x, change that line and the one below it to `x64`.

**2. A release build of the app**

```powershell
cd app_frontend
flutter build windows --release
```

The script refuses to compile if that output is missing, rather than producing an empty
installer that only fails on the machine you were installing it on.

---

## Building the installer

Either open [`personal-erp.iss`](personal-erp.iss) in the Inno Setup Compiler and press
**F9** (Build → Compile), or from the repository root:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\personal-erp.iss
```

The result lands in `installer\dist\`. There are no options to answer while compiling -
every decision is in the script, so two builds of the same commit are identical.

---

## What the script already decides

| | |
| --- | --- |
| **Install scope** | Per-user by default (`%LocalAppData%\Programs\Personal ERP`), no UAC prompt. The wizard offers "for all users" for anyone who wants Program Files. The app writes nothing to its own folder, so it does not need admin. |
| **Architecture** | x64 only, matching what Flutter builds. A 32-bit or ARM machine is refused up front rather than installing something that cannot start. |
| **Payload** | The entire `Release` folder: the `.exe`, `flutter_windows.dll`, plugin DLLs, and `data\`. All of it is required - without `data\` the app exits silently. |
| **Upgrades** | Installing a newer version replaces the current one in place, and a running copy is closed first rather than failing the copy. |
| **Shortcuts** | Start menu always; desktop shortcut offered **unchecked**. |
| **Uninstall** | Standard entry in Add/Remove Programs. User preferences in `%AppData%` are deliberately left behind, so reinstalling does not lose settings. |

---

## What the person running the installer sees

Four screens: install-for-me-or-everyone, destination folder, the desktop-icon
checkbox, then install. Nothing needs to be typed.

---

## Two things worth doing before you hand this to anyone

**1. Code signing.** An unsigned installer triggers a SmartScreen "Windows protected
your PC" warning, and most people stop there. If you have a certificate:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 installer\dist\PersonalERP-Setup.exe
```

Sign `personalerp_desktop.exe` before compiling as well, so the warning does not simply
reappear on first launch.

**2. Decide about the Visual C++ runtime.** The build links against the MSVC 2015-2022
runtime. Almost every Windows 10/11 machine already has it, and on a machine that does
not, the app **exits silently on launch** - the worst kind of bug report to receive. To
remove the risk entirely, download `vc_redist.x64.exe` into this folder and uncomment
the two marked lines in the script; it will be installed only when the registry says it
is absent.

---

## The API URL is baked in

`app_frontend/.env` is bundled as a Flutter **asset**, so whatever it contains at build
time is compiled into the installer:

```
API_BASE_URL=https://erp.yourdomain.com
```

Check that before building a release, because it is not a runtime setting - pointing an
installed copy somewhere else means editing
`data\flutter_assets\.env` inside the installation directory, which is a plain text file
but hardly a supported workflow. If you need per-customer endpoints, build one installer
per endpoint.

---

## Versioning

The version appears in three places and they should agree:

| Where | Value |
| --- | --- |
| `app_frontend/pubspec.yaml` | `version: 1.0.0+1` |
| `installer/personal-erp.iss` | `#define AppVersion "1.0.0"` |
| The installed app | reports `AppVersion` in Add/Remove Programs and in the file's Properties |

The output filename is deliberately **not** versioned - it is always
`PersonalERP-Setup.exe`, so a download link never needs updating. Each build therefore
replaces the previous one; archive it first if you need to keep a specific release.

`AppId` must **never** change between versions - it is the identity Windows tracks the
installation under, and changing it makes the next release install alongside this one
instead of upgrading it.
