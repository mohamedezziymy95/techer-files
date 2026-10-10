#!/usr/bin/env python3
"""Scan a local techer-files clone and rebuild the library catalog from files on disk.

The script preserves manually curated lessons, removes any stale generated
`library-index` entries, and recreates them from the actual files found under each
subject directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".html",
    ".txt",
    ".md",
}


def sha1_for_file(path: Path) -> str:
    data = path.read_bytes()
    header = b"blob " + str(len(data)).encode("utf-8") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def normalize_subject_id(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def human_title_from_path(path: Path) -> str:
    stem = path.stem
    lower = stem.lower()

    if lower == "science_lab":
        return "مختبر تفاعلي • Laboratoire interactif"
    if lower.startswith("support_"):
        stem = stem[len("support_") :]
    if lower.startswith("diag_"):
        stem = stem[len("diag_") :]
    if lower.startswith("start_"):
        stem = stem[len("start_") :]

    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return path.name
    return stem


def ensure_catalog_path(root: Path) -> Path:
    catalog_path = root / "content" / "index.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"Missing catalog file: {catalog_path}")
    return catalog_path


def find_level_directory(root: Path, level_code: str) -> Path | None:
    directory = root / level_code
    if directory.exists():
        return directory
    if level_code == "2BACPC" and (root / "2BAC").exists():
        return root / "2BAC"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate the techer-files library catalog from the content folders."
    )
    parser.add_argument("repository", help="Path to the techer-files repository root")
    args = parser.parse_args()

    root = Path(args.repository).resolve()
    catalog_path = ensure_catalog_path(root)

    with catalog_path.open("r", encoding="utf-8") as fh:
        catalog = json.load(fh)

    levels = catalog.get("levels", [])
    if not isinstance(levels, list):
        raise ValueError("content/index.json has no valid 'levels' list.")

    total_resources = 0
    total_subjects = 0

    for level in levels:
        level_code = level.get("code")
        if not level_code:
            continue

        directory = find_level_directory(root, str(level_code))
        if directory is None or not directory.exists():
            continue

        subjects_map = {str(subject.get("id", "")).lower(): subject for subject in level.get("subjects", [])}

        for subject_dir in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not subject_dir.is_dir():
                continue
            if any(part.startswith(".") for part in subject_dir.parts):
                continue

            subject_id = normalize_subject_id(subject_dir.name)
            subject = subjects_map.get(subject_id)
            if subject is None:
                subject = {"id": subject_id, "title": subject_dir.name, "lessons": []}
                level.setdefault("subjects", []).append(subject)
                total_subjects += 1

            subject["title"] = subject.get("title") or subject_dir.name
            subject["id"] = subject_id

            lessons = subject.get("lessons", [])
            if not isinstance(lessons, list):
                lessons = []
                subject["lessons"] = lessons

            subject["lessons"] = [lesson for lesson in lessons if lesson.get("id") != "library-index"]

            seen_paths = set()
            resources = []
            for file_path in sorted(subject_dir.rglob("*"), key=lambda p: p.relative_to(root).as_posix().lower()):
                if not file_path.is_file():
                    continue
                if file_path.name.startswith("."):
                    continue
                if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue

                relative_path = file_path.relative_to(root).as_posix()
                if relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)

                sha = sha1_for_file(file_path)
                resources.append(
                    {
                        "title": human_title_from_path(file_path),
                        "path": relative_path,
                        "category": "دروس",
                        "sha": sha,
                    }
                )

            total_resources += len(resources)
            if resources:
                subject["lessons"].append(
                    {
                        "id": "library-index",
                        "title": "المكتبة الدراسية • Bibliothèque",
                        "objectives": [],
                        "resources": resources,
                        "test_path": "",
                    }
                )

    catalog["includes_legacy_library"] = False

    with catalog_path.open("w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    message = f"✓ Catalog updated successfully.\n  Added {total_resources} resources across {total_subjects} new subjects."
    print(message, file=sys.stdout)


if __name__ == "__main__":
    main()
