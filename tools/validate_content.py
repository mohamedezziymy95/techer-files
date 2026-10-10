#!/usr/bin/env python3
"""Validate deployable tests and the lesson catalog. Run before pushing GitHub content.

Usage:
    python tools/validate_content.py <repo path>

Every problem is reported (not only the first one). Exit code: 0 = OK, 1 = errors.
"""
import argparse
import hashlib
import json
import math
import pathlib
import sys

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, message):
        self.errors.append(f"{where}: {message}")

    def warn(self, where, message):
        self.warnings.append(f"{where}: {message}")


def load_json(path, where, report):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        report.error(where, "file not found")
    except json.JSONDecodeError as exc:
        report.error(where, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except UnicodeDecodeError as exc:
        report.error(where, f"file is not valid UTF-8 ({exc})")
    return None


def safe_relative(value):
    """True if value is a relative POSIX path without '..'."""
    if not isinstance(value, str) or not value.strip():
        return False
    p = pathlib.PurePosixPath(value)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in value


def git_blob_sha1(path):
    digest = hashlib.sha1()
    digest.update(b"blob " + str(path.stat().st_size).encode("ascii") + b"\0")
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_image(value, tests_root, where, report):
    if not isinstance(value, str) or not value.strip():
        return
    if value.startswith("https://"):
        return
    if value.startswith("http://"):
        report.warn(where, f"external image must use HTTPS: {value}")
        return
    if not safe_relative(value):
        report.error(where, f"unsafe image path: {value}")
        return
    image = tests_root / value
    if not image.is_file():
        report.error(where, f"image not found under tests/: {value}")
    elif image.stat().st_size > MAX_IMAGE_BYTES:
        report.warn(where, f"image larger than 5 MB: {value}")


def check_questions(rows, where, tests_root, report):
    if not isinstance(rows, list):
        report.error(where, "'questions' must be a list")
        return
    seen = set()
    for number, q in enumerate(rows, start=1):
        qid = q.get("id") if isinstance(q, dict) else None
        label = f"{where} question #{number}" + (f" ({qid})" if qid else "")
        if not isinstance(q, dict):
            report.error(label, "must be an object")
            continue
        if not qid:
            report.error(label, "missing 'id'")
        elif qid in seen:
            report.error(label, "duplicate question id")
        seen.add(qid)

        if not str(q.get("text", "")).strip():
            report.error(label, "empty 'text'")

        options = q.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= 12:
            report.error(label, "'options' must be a list of 2 to 12 items")
            options = []
        elif any(not str(o).strip() for o in options):
            report.error(label, "an option is empty")

        if "correct_options" in q:
            correct = q["correct_options"]
        elif "correct" in q:
            correct = [q["correct"]]
        else:
            report.error(label, "missing 'correct' (or 'correct_options')")
            correct = []
        if options:
            if not isinstance(correct, list) or not correct:
                report.error(label, "'correct_options' must be a non-empty list")
            else:
                bad = [c for c in correct
                       if isinstance(c, bool) or not isinstance(c, int) or not 0 <= c < len(options)]
                if bad:
                    report.error(label, f"correct index out of range or not an integer: {bad}"
                                        f" (valid: 0..{len(options) - 1})")
                elif len(set(correct)) >= len(options):
                    report.error(label, "all options are marked correct")

        points = q.get("points", 1)
        if isinstance(points, bool) or not isinstance(points, (int, float)) \
                or not math.isfinite(points) or points <= 0:
            report.error(label, f"'points' must be a positive number (got {points!r})")

        if q.get("image"):
            check_image(q["image"], tests_root, label, report)
        for key in ("practice", "support_exercises"):
            if q.get(key):
                check_questions(q[key], f"{label} / {key}", tests_root, report)


def check_tests(root, catalog_levels, report):
    tests_root = root / "tests"
    index = load_json(tests_root / "index.json", "tests/index.json", report)
    if index is None:
        return 0, 0
    tests = index.get("tests")
    if not isinstance(tests, list):
        report.error("tests/index.json", "missing 'tests' list")
        return 0, 0

    ids, paths, total_questions = set(), set(), 0
    for position, entry in enumerate(tests, start=1):
        tid = entry.get("id", f"#{position}") if isinstance(entry, dict) else f"#{position}"
        where = f"tests/index.json [{tid}]"
        if not isinstance(entry, dict):
            report.error(where, "entry must be an object")
            continue
        for key in ("id", "title", "level", "path", "questions_count"):
            if key not in entry:
                report.error(where, f"missing '{key}'")
        if tid in ids:
            report.error(where, "duplicate test id")
        ids.add(tid)

        level = entry.get("level")
        if level == "2BAC":
            report.error(where, "level '2BAC' is not used: write '2BACPC'")
        elif catalog_levels and level not in catalog_levels:
            report.error(where, f"level '{level}' is not a catalog level {sorted(catalog_levels)}")

        path = entry.get("path")
        if not safe_relative(path):
            report.error(where, f"unsafe or missing path: {path!r}")
            continue
        if path in paths:
            report.warn(where, f"path used by several tests: {path}")
        paths.add(path)

        test = load_json(tests_root / path, f"tests/{path}", report)
        if test is None:
            continue
        if test.get("id") != entry.get("id"):
            report.error(where, f"id differs from the test file ({test.get('id')!r})")
        if test.get("level") != level:
            report.error(where, f"level '{level}' differs from the test file ('{test.get('level')}')")
        questions = test.get("questions")
        if isinstance(questions, list):
            if len(questions) != entry.get("questions_count"):
                report.error(where, f"questions_count={entry.get('questions_count')} "
                                    f"but the file has {len(questions)} questions")
            total_questions += len(questions)
        if "duration" in test and test["duration"] != entry.get("duration"):
            report.error(where, f"duration {entry.get('duration')} differs from the "
                                f"test file ({test['duration']})")
        check_questions(questions, f"tests/{path}", tests_root, report)

    # test files that exist but are not listed in the index
    listed = {pathlib.PurePosixPath(p).as_posix() for p in paths}
    for file in sorted(tests_root.rglob("*.json")):
        rel = file.relative_to(tests_root).as_posix()
        if rel in ("index.json",) or file.name.startswith("_"):
            continue
        if rel not in listed:
            report.warn("tests", f"{rel} is not registered in tests/index.json (students will not see it)")
    return len(ids), total_questions


def check_catalog(root, report):
    catalog = load_json(root / "content" / "index.json", "content/index.json", report)
    if catalog is None:
        return set(), {}
    if catalog.get("schema_version") != 1:
        report.error("content/index.json", f"schema_version must be 1 (got {catalog.get('schema_version')!r})")
    levels = catalog.get("levels")
    if not isinstance(levels, list):
        report.error("content/index.json", "missing 'levels' list")
        return set(), {}

    codes = set()
    resource_count = 0
    for level in levels:
        code = level.get("code")
        if code in codes:
            report.error("content/index.json", f"duplicate level code {code}")
        codes.add(code)
        for subject in level.get("subjects", []):
            subject_where = f"content/index.json [{code}/{subject.get('id')}]"
            lesson_ids, resource_paths = set(), set()
            for lesson in subject.get("lessons", []):
                lid = lesson.get("id")
                where = f"{subject_where} lesson '{lid}'"
                if not lid:
                    report.error(subject_where, "lesson without id")
                elif lid in lesson_ids:
                    report.error(where, "duplicate lesson id in this subject")
                lesson_ids.add(lid)
                if not str(lesson.get("title", "")).strip():
                    report.error(where, "empty title")
                for res in lesson.get("resources", []):
                    resource_count += 1
                    rpath = res.get("path")
                    if not safe_relative(rpath):
                        report.error(where, f"unsafe or missing resource path: {rpath!r}")
                        continue
                    target = root / rpath
                    if not target.is_file():
                        report.error(where, f"missing resource {rpath}")
                        continue
                    if rpath in resource_paths:
                        report.warn(where, f"resource listed twice in this subject: {rpath}")
                    resource_paths.add(rpath)
                    if res.get("sha") and res["sha"] != git_blob_sha1(target):
                        report.warn(where, f"sha is out of date for {rpath} "
                                           "(run tools/generate_catalog.py again)")
                test_path = lesson.get("test_path")
                if test_path:
                    if not safe_relative(test_path):
                        report.error(where, f"unsafe test_path: {test_path!r}")
                    elif not (root / "tests" / test_path).is_file():
                        report.error(where, f"test_path not found under tests/: {test_path}")
    return codes, {"resources": resource_count}


def validate(root):
    root = pathlib.Path(root)
    report = Report()
    codes, stats = check_catalog(root, report)
    tests_count, questions_count = check_tests(root, codes, report)
    return report, tests_count, questions_count, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default="app/src/main/assets",
                        help="repository root (default: app/src/main/assets)")
    args = parser.parse_args()

    report, tests_count, questions_count, stats = validate(args.root)
    for message in report.warnings:
        print(f"WARNING: {message}")
    for message in report.errors:
        print(f"ERROR: {message}")
    if report.errors:
        print(f"FAIL: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        return 1
    print(f"PASS: {tests_count} indexed tests, {questions_count} questions; "
          f"{stats.get('resources', 0)} catalog resources valid"
          + (f" ({len(report.warnings)} warning(s))" if report.warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
