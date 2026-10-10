#!/usr/bin/env python3
"""Rebuild the library part of content/index.json from the files on disk.

Usage:
    python tools/generate_catalog.py <repo path> [--dry-run] [--bump-version]
                                                 [--single-category]

What it does
------------
* Keeps every manually curated lesson (support lessons, science_lab, ...).
* Removes the old generated lessons (ids starting with ``library-``) and
  recreates them from the real files found in each level folder.
* Understands both layouts used in the repository:
    - ``<level>/physique/<category>/<file>``   (1AC, 2AC, 3AC)
    - ``<level>/<category>/<file>``            (1BAC, 2BAC, 2-BAC)
  and merges ``2BAC`` + ``2-BAC`` into the catalog level ``2BACPC``.
* Creates one lesson per category (courses, exercises, homework, ...).
* Ignores temporary/hidden files (``~$x.docx``, ``.DS_Store``, ...) and
  de-duplicates identical files that exist in two folders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration (edit here if the repository layout changes)
# --------------------------------------------------------------------------- #

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".webm", ".mp3", ".wav",
    ".html", ".txt", ".md",
}

# Folder names (in the repo) that hold the files of a catalog level.
# The first entry that exists is not exclusive: all existing folders are merged.
LEVEL_FOLDERS = {
    "1AC": ["1AC"],
    "2AC": ["2AC"],
    "3AC": ["3AC"],
    "TCS": ["TCS"],
    "1BAC": ["1BAC", "1-BAC"],
    "2BACPC": ["2BACPC", "2BAC", "2-BAC"],
}

# A folder directly under a level folder is a *subject* folder when its
# normalised name is here. Any other folder is treated as a *category* folder
# of the default subject.
SUBJECT_FOLDERS = {
    "physique": "physics",
    "physics": "physics",
    "physique chimie": "physics",
    "physique-chimie": "physics",
    "pc": "physics",
}
DEFAULT_SUBJECT_ID = "physics"
DEFAULT_SUBJECT_TITLE = "الفيزياء والكيمياء"

# category key -> (Arabic label shown in the app, sort position)
CATEGORIES = OrderedDict([
    ("lessons", "دروس"),
    ("exercises", "تمارين"),
    ("homework", "فروض"),
    ("self_assessment", "تقويم ذاتي"),
    ("tests", "اختبارات"),
    ("simulations", "محاكاة"),
    ("videos", "فيديوهات"),
    ("other", "ملفات أخرى"),
])

# normalised folder name -> category key
CATEGORY_ALIASES = {
    "cours a ecrit": "lessons", "cours": "lessons", "lecons": "lessons",
    "lecon": "lessons", "دروس": "lessons",
    "exercices": "exercises", "exercice": "exercises", "series": "exercises",
    "تمارين": "exercises",
    "devoirs": "homework", "devoir": "homework", "فروض": "homework",
    "auto evaluation": "self_assessment", "autoevaluation": "self_assessment",
    "تقويم ذاتي": "self_assessment",
    "اختبارات": "tests", "tests": "tests",
    "simulation": "simulations", "simulations": "simulations",
    "محاكاة": "simulations",
    "videos d experiences": "videos", "videos": "videos", "video": "videos",
    "فيديوهات": "videos",
}

LIBRARY_PREFIX = "library-"
SKIP_FILE_PREFIXES = (".", "~$")
SKIP_FILE_NAMES = {"thumbs.db", "desktop.ini"}
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def normalize(name: str) -> str:
    """Lowercase, strip accents and punctuation: 'Leçons' -> 'lecons'."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def natural_key(text: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text.lower())]


def git_blob_sha1(path: Path) -> str:
    """Same value as `git hash-object`; streams the file (videos can be big)."""
    digest = hashlib.sha1()
    digest.update(b"blob " + str(path.stat().st_size).encode("ascii") + b"\0")
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def title_from_path(path: Path) -> str:
    stem = path.stem
    # ".hta.html" style double extensions
    stem = re.sub(r"\.(hta|min)$", "", stem, flags=re.IGNORECASE)
    if stem.lower() == "science_lab":
        return "مختبر تفاعلي • Laboratoire interactif"
    for prefix in ("support_", "diag_", "start_"):
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix):]
            break
    stem = re.sub(r"[_\s]+", " ", stem).strip()
    return stem or path.name


def category_key(folder_name: str | None) -> str:
    if not folder_name:
        return "other"
    return CATEGORY_ALIASES.get(normalize(folder_name), "other")


def is_skipped_file(path: Path) -> bool:
    name = path.name
    return name.startswith(SKIP_FILE_PREFIXES) or name.lower() in SKIP_FILE_NAMES


def bump_version(version: str) -> str:
    today = date.today()
    parts = str(version).split(".")
    if len(parts) == 3 and parts[0] == str(today.year) and parts[1] == str(today.month) \
            and parts[2].isdigit():
        return f"{today.year}.{today.month}.{int(parts[2]) + 1}"
    return f"{today.year}.{today.month}.1"


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #

def iter_files(directory: Path):
    for current, dirs, files in os.walk(directory):
        dirs[:] = sorted(
            (d for d in dirs if d not in SKIP_DIR_NAMES and not d.startswith(".")),
            key=natural_key,
        )
        for name in sorted(files, key=natural_key):
            yield Path(current) / name


def scan_level(root: Path, level_code: str, warnings: list[str], skipped: Counter):
    """Return {subject_id: {category_key: [resource, ...]}} for one level."""
    folders = [root / name for name in LEVEL_FOLDERS.get(level_code, [level_code])]
    folders = [f for f in folders if f.is_dir()]
    result: dict[str, dict[str, list[dict]]] = {}
    seen_paths: set[str] = set()
    seen_content: set[tuple[str, str, str]] = set()

    for level_dir in folders:
        for child in sorted(level_dir.iterdir(), key=lambda p: natural_key(p.name)):
            if child.name in SKIP_DIR_NAMES or child.name.startswith("."):
                continue
            if child.is_file():
                files = [(child, DEFAULT_SUBJECT_ID, "other")]
            else:
                subject_id = SUBJECT_FOLDERS.get(normalize(child.name))
                files = []
                for f in iter_files(child):
                    if subject_id:
                        rel = f.relative_to(child).parts
                        cat = category_key(rel[0] if len(rel) > 1 else None)
                        files.append((f, subject_id, cat))
                    else:
                        rel = f.relative_to(child).parts
                        cat = category_key(child.name)
                        files.append((f, DEFAULT_SUBJECT_ID, cat))

            for file_path, subject_id, cat in files:
                if is_skipped_file(file_path):
                    continue
                if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                    skipped[file_path.suffix.lower() or "(no extension)"] += 1
                    continue
                relative = file_path.relative_to(root).as_posix()
                if relative in seen_paths:
                    continue
                seen_paths.add(relative)

                sha = git_blob_sha1(file_path)
                content_key = (subject_id, cat + "|" + file_path.name.lower(), sha)
                if content_key in seen_content:
                    # same file copied in 2BAC and 2-BAC: keep the first one
                    continue
                seen_content.add(content_key)

                result.setdefault(subject_id, {}).setdefault(cat, []).append({
                    "title": title_from_path(file_path),
                    "path": relative,
                    "category": CATEGORIES[cat],
                    "sha": sha,
                })
    return result, bool(folders)


# --------------------------------------------------------------------------- #
# Catalog update
# --------------------------------------------------------------------------- #

def library_lessons(by_category: dict[str, list[dict]], single_category: bool):
    lessons = []
    if single_category:
        resources = []
        for key in CATEGORIES:
            for res in by_category.get(key, []):
                resources.append({**res, "category": CATEGORIES["lessons"]})
        if resources:
            lessons.append({
                "id": LIBRARY_PREFIX + "index",
                "title": "المكتبة الدراسية • Bibliothèque",
                "objectives": [],
                "resources": resources,
                "test_path": "",
            })
        return lessons

    for key, label in CATEGORIES.items():
        resources = by_category.get(key)
        if not resources:
            continue
        lessons.append({
            "id": LIBRARY_PREFIX + key.replace("_", "-"),
            "title": f"المكتبة الدراسية • {label}",
            "objectives": [],
            "resources": resources,
            "test_path": "",
        })
    return lessons


def update_catalog(root: Path, catalog: dict, single_category: bool):
    warnings: list[str] = []
    skipped: Counter = Counter()
    stats = []

    levels = catalog.get("levels")
    if not isinstance(levels, list):
        raise ValueError("content/index.json has no valid 'levels' list.")

    known_folders = {n.lower() for names in LEVEL_FOLDERS.values() for n in names}
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and re.match(r"^(\d|tcs)", entry.name, re.IGNORECASE) \
                and entry.name.lower() not in known_folders:
            warnings.append(f"Folder '{entry.name}' is not mapped to any level (see LEVEL_FOLDERS).")

    for level in levels:
        code = str(level.get("code", ""))
        if not code:
            continue
        found, any_folder = scan_level(root, code, warnings, skipped)
        if not any_folder:
            continue

        subjects = level.setdefault("subjects", [])
        by_id = {str(s.get("id", "")).lower(): s for s in subjects}

        # remove stale generated lessons from *all* subjects of this level
        for subject in subjects:
            lessons = subject.get("lessons")
            subject["lessons"] = [
                l for l in (lessons if isinstance(lessons, list) else [])
                if not str(l.get("id", "")).startswith(LIBRARY_PREFIX)
            ]

        for subject_id, by_category in found.items():
            subject = by_id.get(subject_id)
            if subject is None:
                title = DEFAULT_SUBJECT_TITLE if subject_id == DEFAULT_SUBJECT_ID else subject_id
                subject = {"id": subject_id, "title": title, "lessons": []}
                subjects.append(subject)
                by_id[subject_id] = subject
            new_lessons = library_lessons(by_category, single_category)
            taken = {l.get("id") for l in subject["lessons"]}
            for lesson in new_lessons:
                if lesson["id"] in taken:
                    warnings.append(f"{code}/{subject_id}: lesson id '{lesson['id']}' already exists.")
                    continue
                subject["lessons"].append(lesson)
            count = sum(len(l["resources"]) for l in new_lessons)
            stats.append((code, subject_id, count, len(new_lessons)))

    catalog["includes_legacy_library"] = False
    return stats, warnings, skipped


def write_json_atomic(path: Path, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".index-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the library part of content/index.json from the folders."
    )
    parser.add_argument("repository", help="Path to the techer-files repository root")
    parser.add_argument("--dry-run", action="store_true", help="Show the result without writing")
    parser.add_argument("--bump-version", action="store_true",
                        help="Increase the catalog 'version' (e.g. 2026.10.1 -> 2026.10.2)")
    parser.add_argument("--single-category", action="store_true",
                        help="Put every file in one 'library-index' lesson, category 'دروس' "
                             "(old behaviour)")
    args = parser.parse_args()

    root = Path(args.repository).resolve()
    catalog_path = root / "content" / "index.json"
    if not catalog_path.is_file():
        print(f"ERROR: missing catalog file: {catalog_path}", file=sys.stderr)
        return 1
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: content/index.json is not valid JSON ({exc}).", file=sys.stderr)
        return 1

    before = json.dumps(catalog, ensure_ascii=False, sort_keys=True)
    try:
        stats, warnings, skipped = update_catalog(root, catalog, args.single_category)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    changed = json.dumps(catalog, ensure_ascii=False, sort_keys=True) != before
    if args.bump_version and changed:
        catalog["version"] = bump_version(catalog.get("version", ""))

    for code, subject_id, count, lessons in stats:
        print(f"  {code:<7} {subject_id:<8} {count:>4} files in {lessons} lesson(s)")
    for message in warnings:
        print(f"WARNING: {message}", file=sys.stderr)
    if skipped:
        listing = ", ".join(f"{ext} x{n}" for ext, n in sorted(skipped.items()))
        print(f"  Ignored (extension not allowed): {listing}")

    total = sum(s[2] for s in stats)
    if args.dry_run:
        print(f"Dry run: {total} library files found, nothing written.")
        return 0
    if not changed and not args.bump_version:
        print(f"Catalog already up to date ({total} library files).")
        return 0

    write_json_atomic(catalog_path, catalog)
    print(f"OK: content/index.json updated ({total} library files, version {catalog.get('version')}).")
    if not args.bump_version:
        print("Tip: use --bump-version if the app only refreshes when 'version' changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
