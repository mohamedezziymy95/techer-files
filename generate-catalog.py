#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================
منصتي التعليمية - generate-catalog.py
مولّد catalog.json التلقائي
================================================================
الاستخدام:
  python generate-catalog.py --folder ./techer-files --output ./catalog.json

يقرأ هيكل المجلدات ويولّد catalog.json جاهز للرفع على GitHub
================================================================
"""

import os
import json
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 1. تعريف المواد الدراسية (الاسم، الأيقونة، اللون)
# ─────────────────────────────────────────────────────────────
SUBJECTS_META = {
    "math": {
        "subject": "الرياضيات",
        "icon":    "calculate",
        "color":   "#FF6584",
        "shadow":  "rgba(255,101,132,0.35)"
    },
    "physics": {
        "subject": "الفيزياء والكيمياء",
        "icon":    "science",
        "color":   "#6C63FF",
        "shadow":  "rgba(108,99,255,0.35)"
    },
    "biology": {
        "subject": "علوم الحياة والأرض",
        "icon":    "biotech",
        "color":   "#26de81",
        "shadow":  "rgba(38,222,129,0.35)"
    },
    "arabic": {
        "subject": "اللغة العربية",
        "icon":    "auto_stories",
        "color":   "#43C6AC",
        "shadow":  "rgba(67,198,172,0.35)"
    },
    "french": {
        "subject": "اللغة الفرنسية",
        "icon":    "language",
        "color":   "#FF4757",
        "shadow":  "rgba(255,71,87,0.35)"
    },
    "english": {
        "subject": "اللغة الإنجليزية",
        "icon":    "record_voice_over",
        "color":   "#3742FA",
        "shadow":  "rgba(55,66,250,0.35)"
    },
    "islamic": {
        "subject": "التربية الإسلامية",
        "icon":    "mosque",
        "color":   "#2ED573",
        "shadow":  "rgba(46,213,115,0.35)"
    },
    "philosophy": {
        "subject": "الفلسفة",
        "icon":    "psychology",
        "color":   "#A55EEA",
        "shadow":  "rgba(165,94,234,0.35)"
    },
    "history": {
        "subject": "التاريخ والجغرافيا",
        "icon":    "public",
        "color":   "#F7971E",
        "shadow":  "rgba(247,151,30,0.35)"
    }
}

# ─────────────────────────────────────────────────────────────
# 2. تعريف المجلدات (ترتيب ظهورها + أيقوناتها)
# ─────────────────────────────────────────────────────────────
FOLDER_META = {
    "lessons":   {"name": "دروس",      "icon": "menu_book"},
    "exercises": {"name": "تمارين",    "icon": "edit_note"},
    "homework":  {"name": "فروض",      "icon": "assignment"},
    "exams":     {"name": "امتحانات",  "icon": "fact_check"},
    "videos":    {"name": "فيديوهات",  "icon": "play_circle"},
    "images":    {"name": "صور",       "icon": "image"},
    "other":     {"name": "أخرى",      "icon": "folder"}
}

FOLDER_ORDER = [
    "lessons", "exercises", "homework", "exams",
    "videos", "images", "other"
]

# ─────────────────────────────────────────────────────────────
# 3. امتدادات الملفات المدعومة
# ─────────────────────────────────────────────────────────────
FILE_TYPES = {
    ".pdf":  "pdf",
    ".mp4":  "video",
    ".webm": "video",
    ".ogg":  "video",
    ".mov":  "video",
    ".jpg":  "image",
    ".jpeg": "image",
    ".png":  "image",
    ".gif":  "image",
    ".webp": "image",
    ".doc":  "word",
    ".docx": "word",
    ".ppt":  "ppt",
    ".pptx": "ppt"
}

# ─────────────────────────────────────────────────────────────
# 4. دوال مساعدة
# ─────────────────────────────────────────────────────────────

def get_file_type(filename):
    """استخراج نوع الملف من امتداده"""
    ext = Path(filename).suffix.lower()
    return FILE_TYPES.get(ext, "other")

def generate_file_id(path_str):
    """توليد ID فريد من مسار الملف"""
    hash_val = hashlib.md5(path_str.encode('utf-8')).hexdigest()[:10]
    # تنظيف اسم المجلد
    parts    = Path(path_str).parts
    subject  = parts[0] if parts else "file"
    return f"{subject}_{hash_val}"

def clean_title(filename):
    """تنظيف اسم الملف ليصبح عنواناً"""
    name = Path(filename).stem
    # استبدال الشرطات السفلية بمسافات
    name = name.replace('_', ' ').replace('-', ' ')
    return name.strip()

def get_file_mtime(filepath):
    """الحصول على تاريخ تعديل الملف"""
    try:
        mtime = os.path.getmtime(filepath)
        dt    = datetime.fromtimestamp(mtime, tz=timezone.utc)
        return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    except Exception:
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

def get_file_size(filepath):
    """الحصول على حجم الملف بالبايت"""
    try:
        return os.path.getsize(filepath)
    except Exception:
        return 0

def sort_folders(folder_names):
    """ترتيب المجلدات حسب FOLDER_ORDER"""
    def order_key(name):
        try:
            return FOLDER_ORDER.index(name.lower())
        except ValueError:
            return len(FOLDER_ORDER)
    return sorted(folder_names, key=order_key)

# ─────────────────────────────────────────────────────────────
# 5. الدالة الرئيسية لمسح المجلدات
# ─────────────────────────────────────────────────────────────

def scan_repo(base_folder):
    """
    مسح مجلد المستودع وبناء هيكل catalog.json
    
    الهيكل المتوقع:
    base_folder/
      math/
        lessons/   ← ملفات PDF
        exercises/ ← ملفات PDF
        ...
      physics/
        ...
    """
    subjects = []
    base_path = Path(base_folder)

    if not base_path.exists():
        print(f"❌ المجلد غير موجود: {base_folder}")
        return subjects

    print(f"\n📂 مسح المجلد: {base_path.resolve()}")
    print("=" * 50)

    # ── المرور على كل مجلد مادة ──
    subject_dirs = sorted([
        d for d in base_path.iterdir()
        if d.is_dir() and not d.name.startswith('.')
           and not d.name.startswith('_')
    ])

    for subject_dir in subject_dirs:
        subject_id = subject_dir.name.lower()

        # تجاهل المجلدات غير المعروفة
        if subject_id not in SUBJECTS_META:
            print(f"  ⚠️  تجاهل مجلد غير معروف: {subject_id}")
            print(f"      أضفه إلى SUBJECTS_META إذا أردت تضمينه")
            continue

        meta = SUBJECTS_META[subject_id]
        print(f"\n  📚 {meta['subject']} ({subject_id})")

        folders = []

        # ── المرور على مجلدات الفئات ──
        folder_dirs = [
            d for d in subject_dir.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        ]
        folder_dirs = sorted(folder_dirs,
                             key=lambda d: sort_folders(
                                 [d.name]).index(d.name)
                             if d.name in sort_folders([d.name]) else 99)

        # ترتيب المجلدات
        folder_names  = [d.name for d in folder_dirs]
        sorted_names  = sort_folders(folder_names)
        sorted_dirs   = sorted(folder_dirs,
                               key=lambda d: sorted_names.index(d.name)
                               if d.name in sorted_names else 99)

        for folder_dir in sorted_dirs:
            folder_key  = folder_dir.name.lower()
            folder_info = FOLDER_META.get(folder_key, {
                "name": folder_dir.name,
                "icon": "folder"
            })

            # ── المرور على الملفات ──
            files = []
            file_paths = sorted([
                f for f in folder_dir.iterdir()
                if f.is_file()
                   and not f.name.startswith('.')
                   and f.suffix.lower() in FILE_TYPES
            ])

            for file_path in file_paths:
                # المسار النسبي (من جذر المستودع)
                rel_path   = file_path.relative_to(base_path)
                path_str   = str(rel_path).replace('\\', '/')
                file_type  = get_file_type(file_path.name)
                file_id    = generate_file_id(path_str)
                file_title = clean_title(file_path.name)
                file_size  = get_file_size(file_path)
                file_mtime = get_file_mtime(file_path)

                file_entry = {
                    "id":      file_id,
                    "title":   file_title,
                    "path":    path_str,
                    "type":    file_type,
                    "size":    file_size,
                    "addedAt": file_mtime
                }

                files.append(file_entry)
                print(f"    ✅ {file_path.name} [{file_type}]")

            if files:
                folders.append({
                    "name":  folder_info["name"],
                    "icon":  folder_info["icon"],
                    "key":   folder_key,
                    "files": files
                })
            else:
                print(f"    📭 {folder_dir.name}/ — فارغ")

        if folders:
            subjects.append({
                "id":      subject_id,
                "subject": meta["subject"],
                "icon":    meta["icon"],
                "color":   meta["color"],
                "shadow":  meta["shadow"],
                "folders": folders
            })

    return subjects

# ─────────────────────────────────────────────────────────────
# 6. بناء الكتالوج النهائي
# ─────────────────────────────────────────────────────────────

def build_catalog(base_folder, repo_name, branch="main"):
    """بناء كتالوج JSON كامل"""
    subjects  = scan_repo(base_folder)
    now       = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    # حساب الإحصائيات
    total_files   = sum(
        len(f["files"])
        for s in subjects
        for f in s["folders"]
    )
    total_folders = sum(len(s["folders"]) for s in subjects)

    catalog = {
        "_version":     "1.0.0",
        "_generated":   now,
        "_repo":        repo_name,
        "_branch":      branch,
        "_description": "كتالوج ملفات منصتي التعليمية",
        "_stats": {
            "subjects": len(subjects),
            "folders":  total_folders,
            "files":    total_files
        },
        "subjects": subjects
    }

    return catalog

# ─────────────────────────────────────────────────────────────
# 7. نقطة التشغيل
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='مولّد catalog.json لمنصتي التعليمية'
    )
    parser.add_argument(
        '--folder', '-f',
        default='.',
        help='مسار مجلد المستودع (افتراضي: المجلد الحالي)'
    )
    parser.add_argument(
        '--output', '-o',
        default='catalog.json',
        help='مسار ملف الإخراج (افتراضي: catalog.json)'
    )
    parser.add_argument(
        '--repo', '-r',
        default='mohamedezziymy95/techer-files',
        help='اسم المستودع على GitHub'
    )
    parser.add_argument(
        '--branch', '-b',
        default='main',
        help='اسم الفرع (افتراضي: main)'
    )
    parser.add_argument(
        '--indent', '-i',
        type=int, default=2,
        help='مسافة التنسيق في JSON (افتراضي: 2)'
    )

    args    = parser.parse_args()
    catalog = build_catalog(args.folder, args.repo, args.branch)

    # حفظ الملف
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f,
                  ensure_ascii=False,
                  indent=args.indent)

    # ── طباعة الملخص ──
    stats = catalog["_stats"]
    print("\n" + "=" * 50)
    print("✅ تم توليد catalog.json بنجاح!")
    print(f"   📚 المواد:   {stats['subjects']}")
    print(f"   📁 المجلدات: {stats['folders']}")
    print(f"   📄 الملفات:  {stats['files']}")
    print(f"   💾 الإخراج:  {output_path.resolve()}")
    print("=" * 50)
    print("\n📌 الخطوة التالية:")
    print("   ارفع catalog.json على GitHub:")
    print(f"   git add {args.output}")
    print(f"   git commit -m '📋 تحديث كتالوج v{catalog[\"_version\"]}'")
    print(f"   git push origin {args.branch}")
    print()

if __name__ == '__main__':
    main()