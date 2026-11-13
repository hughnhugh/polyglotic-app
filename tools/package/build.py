"""Build the app testers install: PyInstaller, one folder (decision 0016).

    uv sync --locked --group package
    uv run --no-sync python -m tools.dictionaries.build      # once: the dictionaries
    uv run --no-sync python -m tools.package.build v0.1.0    # -> dist/Polyglotic/

From the locked environment, in order:
1. the release stamp from the tag (`stamp.py`, decision 0015), and Windows'
   file properties and an icon for `Polyglotic.exe`;
2. PyInstaller with `polyglotic.spec`: the app's code from `src/` (never
   `tests/`), the speech-detection model, the icon masters, heading
   faces and the interface's translations, compiled first (`ui/assets`;
   `tools.i18n`, decision 0034), the stamp, and the libraries the code imports,
   trimmed of what it never loads;
3. beside `Polyglotic.exe`, as separate, unlocked files: the dictionaries
   and their `CREDITS.md` (decision 0009), `THIRD_PARTY_NOTICES.md`, and
   `licenses/` - every bundled package's licence files, Python's and the
   heading faces' OFL texts;
4. checks: no tests, `.env` files or device tokens anywhere in the folder
   or its code archive; the parts the app needs are there;
5. `--check-install` run on the packed app (it opens no window, captures
   nothing, connects nowhere), timed: its whole run (`wall_seconds`), the
   main window's first paint from the process's launch (`launch_seconds`,
   Python's start and the imports included - over
   `perf.budgets.START_PACKED` is a problem) and from the check's start
   (`window_seconds`);
6. a summary: size on disk, files, a zip's size (the download), start
   time - printed, and written to `build/package/summary.json`.

Velopack packs the folder afterwards (the release workflow).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator, Sequence
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.requirements import Requirement

from tools.i18n import __main__ as i18n
from tools.package import stamp

if TYPE_CHECKING:
    from PySide6.QtGui import QImage

REPO = Path(__file__).resolve().parents[2]
SPEC = Path(__file__).with_name("polyglotic.spec")
WORK = REPO / "build" / "package"
NAME = "Polyglotic"
DICTIONARY_FILES = ("cedict.sqlite", "ecdict.sqlite", "CREDITS.md")
ASSETS = REPO / "src" / "polyglotic_desktop" / "ui" / "assets"
QT_LANGUAGES = tuple(
    language
    for language in i18n.LANGUAGES
    if (i18n.LRELEASE.parent / "translations" / f"qtbase_{language}.qm").exists()
    and language != "en"
)
"""The interface languages Qt has its own words for (OK, Cancel, Copy -
not Thai, Vietnamese, Indonesian, Malay, Hindi or Filipino): their
`qtbase_<language>.qm` is kept in the packed app (decision 0034; the spec's
DROP, told by POLYGLOTIC_QT_LANGUAGES)."""
NEEDED = (  # inside the packed folder: what the app can't start without
    f"{NAME}.exe",
    "_internal/polyglotic_desktop/release.json",
    "_internal/polyglotic_desktop/platform/data/silero_vad_16k_op15.onnx",
    "_internal/polyglotic_desktop/platform/data/samples/zh.flac",
    "_internal/polyglotic_desktop/platform/data/samples/en.flac",
    "_internal/polyglotic_desktop/platform/data/samples/CREDITS.md",
    "_internal/PySide6/plugins/platforms/qwindows.dll",
    "_internal/PySide6/Qt6Svg.dll",  # the icons are drawn from SVG masters
    # Qt's own words (OK, Cancel, Copy) in each interface language (0034)
    *(f"_internal/PySide6/translations/qtbase_{q}.qm" for q in QT_LANGUAGES),
    *(
        f"_internal/polyglotic_desktop/ui/assets/{p.relative_to(ASSETS).as_posix()}"
        for p in sorted(ASSETS.rglob("*"))
        if p.is_file() and p.suffix != ".qm"
    ),
    # the interface's translations, compiled by the build (not committed: 0034)
    *(
        f"_internal/polyglotic_desktop/ui/assets/translations/{i18n.qm_path(language).name}"
        for language in i18n.LANGUAGES
    ),
    "_internal/_soundfile_data/libsndfile_x64.dll",
    "THIRD_PARTY_NOTICES.md",
    *(f"dictionaries/{file}" for file in DICTIONARY_FILES),
)
TOKEN = re.compile(rb"pgd_[A-Za-z0-9_-]{43}")  # a device token (protocol.md)
LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)
OUR_LICENCE_TEXTS = Path(__file__).with_name("licenses")
QT = ("LGPL-3.0.txt", "GPL-3.0.txt")
"""Qt and PySide6 are used under the LGPL-3.0, which comes with the GPL-3.0;
their wheels carry neither text, so we do (from gnu.org, 2026-11-05)."""
IN_PACKAGE = {  # licence files kept in a package's folder, not its dist-info
    "onnxruntime": ("LICENSE", "ThirdPartyNotices.txt"),
    "_soundfile_data": ("COPYING",),  # libsndfile's LGPL-2.1
}


# -- 1. the stamp, file properties and icon ---------------------------------------


def version_info(version: str) -> str:
    """PyInstaller's version resource: Windows shows it in the file's
    properties."""
    numbers = tuple(int(n) for n in version.split(".")) + (0,)
    strings = {
        "FileDescription": NAME,
        "FileVersion": version,
        "InternalName": NAME,
        "OriginalFilename": f"{NAME}.exe",
        "ProductName": NAME,
        "ProductVersion": version,
    }
    table = ", ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers},"
        " mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,"
        " date=(0, 0)),\n"
        f"  kids=[StringFileInfo([StringTable('040904B0', [{table}])]),\n"
        "        VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ")\n"
    )


def write_icon(path: Path) -> None:
    """The app's icon (`ui.icons`, from its SVG masters) as a Windows .ico
    at 16, 20, 24, 32, 48 and 256 pixels, for the exe and the installer
    (Velopack's `--icon`)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from polyglotic_desktop.ui.icons import ICO_SIZES, app_image

    _app = QGuiApplication.instance() or QGuiApplication([])
    path.write_bytes(ico([app_image(size) for size in ICO_SIZES]))


def ico(images: Sequence[QImage]) -> bytes:
    """Square images as one .ico file: 256 px as PNG, the rest as 32-bit
    bitmaps with their mask - what every Windows reader takes."""
    entries = [_ico_png(image) if image.width() >= 256 else _ico_bitmap(image)
               for image in images]  # fmt: skip
    data = struct.pack("<HHH", 0, 1, len(images))  # reserved, icon, count
    offset = len(data) + 16 * len(images)
    for image, entry in zip(images, entries, strict=True):
        side = image.width() % 256  # 0 means 256
        data += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(entry), offset)
        offset += len(entry)
    return data + b"".join(entries)


def _ico_png(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImageWriter

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not QImageWriter(buffer, b"png").write(image):
        raise RuntimeError("couldn't write the icon's PNG")
    return bytes(buffer.data().data())


def _ico_bitmap(image: QImage) -> bytes:
    """A 32-bit BGRA bitmap, bottom row first, at twice its height (the
    colours, then the 1-bit mask: set where the pixel is clear)."""
    from PySide6.QtGui import QImage

    image = image.convertToFormat(QImage.Format.Format_ARGB32)  # BGRA in memory
    side = image.width()
    pixels, line = bytes(image.constBits()), image.bytesPerLine()
    rows = [pixels[y * line : y * line + side * 4] for y in range(side)]
    mask_row = (side + 31) // 32 * 4
    mask = b""
    for row in rows:
        bits = bytearray(mask_row)
        for x in range(side):
            if row[x * 4 + 3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask = bytes(bits) + mask  # bottom row first, as the colours
    colours = b"".join(reversed(rows))
    header = struct.pack("<IiiHHIIiiII", 40, side, side * 2, 1, 32, 0,
                         len(colours) + len(mask), 0, 0, 0, 0)  # fmt: skip
    return header + colours + mask


# -- 3. notices and licences --------------------------------------------------------


def runtime_distributions(
    root: str = "polyglotic-desktop",
) -> list[metadata.Distribution]:
    """The app's runtime dependencies, all the way down, for this platform
    (no dev or package groups: those are never bundled)."""
    seen: dict[str, metadata.Distribution] = {}
    queue = [root]
    while queue:
        name = queue.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        dist = metadata.distribution(name)
        seen[key] = dist
        for line in dist.requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                queue.append(requirement.name)
    seen.pop(re.sub(r"[-_.]+", "-", root).lower())
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def licence_files(dist: metadata.Distribution) -> Iterator[tuple[Path, Path]]:
    """Each licence file in the package's dist-info, with its path there
    (numpy keeps one per vendored library, several with the same name), and
    any software bill of materials (velopack lists the Rust crates it
    links)."""
    for file in dist.files or []:
        parts = file.parts
        in_dist_info = parts and parts[0].endswith(".dist-info")
        listed = "licenses" in parts or "sboms" in parts
        if in_dist_info and (LICENSE_NAME.search(file.name) or listed):
            yield Path(str(dist.locate_file(file))), Path(*parts[1:])


def top_level_names(dist: metadata.Distribution) -> set[str]:
    """The importable names a distribution installs (`numpy`,
    `_soundfile_data`, `typing_extensions`...)."""
    names = set()
    for file in dist.files or []:
        first = file.parts[0]
        if first.endswith((".dist-info", ".data")) or first in ("..", "__pycache__"):
            continue
        names.add(first.split(".")[0])
    return names


def is_bundled(dist: metadata.Distribution, folder: Path, modules: set[str]) -> bool:
    """Whether PyInstaller put any of the distribution in the packed app:
    in its code archive, or as files under `_internal`."""
    internal = folder / "_internal"
    return any(
        name in modules
        or (internal / name).exists()
        or any(internal.glob(f"{name}.*"))  # an extension: _cffi_backend.cp312-...pyd
        for name in top_level_names(dist)
    )


def copy_licences(folder: Path) -> list[dict[str, object]]:
    """Every bundled package's licence files, and Python's, under
    `licenses/`; returns what was copied, for the summary."""
    out = folder / "licenses"
    copied: list[dict[str, object]] = []
    modules = {m.split(".")[0] for m in archive_modules(folder / f"{NAME}.exe")}
    for dist in runtime_distributions():
        if not is_bundled(dist, folder, modules):
            continue  # a dependency the app's code never imports
        name, version = dist.metadata["Name"], dist.version
        target = out / f"{name}-{version}"
        files = list(licence_files(dist))
        for file, relative in files:
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target / relative)
        licence = dist.metadata.get("License-Expression") or dist.metadata.get(
            "License"
        )
        copied.append(
            {
                "name": name,
                "version": version,
                "licence": (licence or "").splitlines()[0][:80] if licence else None,
                "files": len(files),
            }
        )
    qt = out / "Qt-and-PySide6"
    qt.mkdir(parents=True, exist_ok=True)
    for text in QT:
        shutil.copy2(OUR_LICENCE_TEXTS / text, qt / text)
    # velopack's wheel names MIT but carries no text (its SBOM lists the
    # Rust crates it links); the installer's Setup.exe and Update.exe are
    # Velopack's too
    (out / "Velopack").mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUR_LICENCE_TEXTS / "Velopack-MIT.txt", out / "Velopack" / "LICENSE")
    for package, names in IN_PACKAGE.items():
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            continue
        where = Path(spec.submodule_search_locations[0])
        for name in names:
            if (where / name).is_file():
                (out / package).mkdir(parents=True, exist_ok=True)
                shutil.copy2(where / name, out / package / name)
    # the heading faces' SIL Open Font Licence texts (they ship beside the
    # fonts too, in _internal/polyglotic_desktop/ui/assets/fonts)
    (out / "Fonts").mkdir(parents=True, exist_ok=True)
    for ofl in sorted((ASSETS / "fonts").glob("*-OFL.txt")):
        shutil.copy2(ofl, out / "Fonts" / ofl.name)
    python = Path(sys.base_prefix) / "LICENSE.txt"
    if python.is_file():
        (out / "Python").mkdir(parents=True, exist_ok=True)
        shutil.copy2(python, out / "Python" / "LICENSE.txt")
    copied.append({"name": "Python", "version": sys.version.split()[0],
                   "licence": "PSF-2.0", "files": int(python.is_file())})  # fmt: skip
    return copied


# -- 4. checks ----------------------------------------------------------------------


def archive_modules(exe: Path) -> list[str]:
    """The module names in the packed app's code archive (PYZ)."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    pyz = next(name for name, entry in archive.toc.items() if entry[-1] == "z")
    return sorted(archive.open_embedded_archive(pyz).toc)


def problems(folder: Path) -> list[str]:
    """What mustn't be in the packed app, or must be and isn't."""
    found = [f"missing: {need}" for need in NEEDED if not (folder / need).is_file()]
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        if path.name.startswith(".env") or path.suffix == ".env":
            found.append(f"an environment file: {relative}")
        if TOKEN.search(path.read_bytes()):
            found.append(f"something shaped like a device token: {relative}")
    for module in archive_modules(folder / f"{NAME}.exe"):
        top = module.split(".")[0]
        if top in ("tests", "tools", "conftest") or (
            top == "polyglotic_desktop" and "test" in module
        ):
            found.append(f"a test or tool in the code: {module}")
    return found


# -- 5., 6. the self-check and the summary ------------------------------------------


def check_install(folder: Path) -> dict[str, object]:
    """`Polyglotic.exe --check-install`, timed from start to exit, with a
    data folder of its own, emptied first - never the account's own
    (`%APPDATA%\\Polyglotic`). The check opens the learning stores in its
    data folder, and the build runs on the user's PC as the user (the
    self-hosted runner, decision 0025): their own learning data is no
    build's business, and a build mustn't pass or fail by what's in it
    (polyglotic-hq 242)."""
    report = WORK / "check-install.json"
    report.unlink(missing_ok=True)
    data = WORK / "check-install-data"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True)
    started = time.perf_counter()
    result = subprocess.run(
        [
            str(folder / f"{NAME}.exe"),
            "--check-install",
            str(report),
            "--data",
            str(data),
        ],
        timeout=120,
        check=False,
    )
    seconds = round(time.perf_counter() - started, 3)
    found = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    found.update(exit_code=result.returncode, wall_seconds=seconds)
    return found


def over_start_budget(check: dict[str, object]) -> list[str]:
    """The packed app's main window later than its budget (or not timed).

    Judged on `launch_seconds` - from the process's launch, Python's start
    and the imports included, which is the wait a person has (polyglotic-hq
    243; 136 added the field) - falling back to `window_seconds` (from the
    check's start) when a build couldn't read its process time."""
    from polyglotic_desktop.perf.budgets import START_PACKED

    seconds = check.get("launch_seconds")
    measured = "from launch"
    if not isinstance(seconds, int | float):
        seconds = check.get("window_seconds")
        measured = "from the check's start (launch time unread)"
    if not isinstance(seconds, int | float):
        return ["--check-install didn't time the main window"]
    if seconds > START_PACKED.ms / 1000:
        return [
            f"the main window took {seconds} s {measured}, over {START_PACKED.ms:.0f} ms"
        ]
    return []


def zipped_size(folder: Path) -> int:
    """The folder as a zip (Velopack's packages are zips): about the
    download."""
    path = WORK / f"{NAME}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                z.write(file, file.relative_to(folder))
    size = path.stat().st_size
    path.unlink()
    return size


def biggest(folder: Path, n: int = 12) -> list[tuple[str, float]]:
    files = [p for p in folder.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    return [(p.relative_to(folder).as_posix(), mb(p.stat().st_size)) for p in files[:n]]


def mb(size: int) -> float:
    return round(size / 1_000_000, 1)


# -- the build ----------------------------------------------------------------------


def build(tag: str, channel: str, dictionaries: Path, out: Path) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    release = stamp.stamp(stamp.version_from_tag(tag), channel)
    version = json.loads(release)["version"]
    (WORK / "release.json").write_text(release, encoding="utf-8")
    (WORK / "version_info.txt").write_text(version_info(version), encoding="utf-8")
    write_icon(WORK / f"{NAME}.ico")
    i18n.build()  # the interface's .qm files, packed with the other assets
    missing = [f for f in DICTIONARY_FILES if not (dictionaries / f).is_file()]
    if missing:
        print(f"No dictionaries in {dictionaries}: run tools.dictionaries.build first")
        return 1

    env = dict(
        os.environ,
        POLYGLOTIC_STAMP=str(WORK / "release.json"),
        POLYGLOTIC_VERSION_FILE=str(WORK / "version_info.txt"),
        POLYGLOTIC_ICON=str(WORK / f"{NAME}.ico"),
        POLYGLOTIC_QT_LANGUAGES=" ".join(QT_LANGUAGES),
    )
    pyinstaller = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
                   "--clean", "--log-level", "WARN", "--distpath", str(out),
                   "--workpath", str(WORK / "work")]  # fmt: skip
    started = time.perf_counter()
    subprocess.run(pyinstaller, env=env, check=True, cwd=REPO)
    build_seconds = round(time.perf_counter() - started, 1)

    folder = out / NAME
    shutil.copytree(dictionaries, folder / "dictionaries", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*-wal", "*-shm", "*.tmp"))  # fmt: skip
    shutil.copy2(REPO / "THIRD_PARTY_NOTICES.md", folder / "THIRD_PARTY_NOTICES.md")
    licences = copy_licences(folder)

    found = problems(folder)
    check = check_install(folder)
    if check.get("exit_code") != 0 or check.get("version") != version:
        found.append(f"--check-install failed: {check}")
    found += over_start_budget(check)
    files = [p for p in folder.rglob("*") if p.is_file()]
    summary = {
        "version": version,
        "channel": channel,
        "build_seconds": build_seconds,
        "files": len(files),
        "size_mb": mb(sum(p.stat().st_size for p in files)),
        "zipped_mb": mb(zipped_size(folder)),
        "check_install": check,
        "biggest_mb": biggest(folder),
        "licences": licences,
        "problems": found,
    }
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "licences"}, indent=2))
    if found:
        print("\nThe packed app isn't right:\n- " + "\n- ".join(found))
        return 1
    print(f"\nPacked {NAME} {version} ({channel}) in {folder}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.package.build")
    parser.add_argument("tag", help="the release's git tag, e.g. v0.1.0")
    parser.add_argument("--channel", default="win-x64-alpha")
    parser.add_argument(
        "--dictionaries", type=Path, default=REPO / "build" / "dictionaries"
    )
    parser.add_argument("--out", type=Path, default=REPO / "dist")
    args = parser.parse_args(argv)
    try:
        return build(args.tag, args.channel, args.dictionaries, args.out)
    except ValueError as e:
        print(f"Not a release: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
