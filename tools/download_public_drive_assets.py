"""Resumable downloader for a public Google Drive asset folder.

Downloads only editor-relevant media and records inaccessible files instead of
aborting the entire import when Drive rate-limits one asset.
"""
from __future__ import annotations

import json
from pathlib import Path

import gdown


FOLDER_ID = "1xmn8FA0zC1ND8WcNxreLqDgOCdfPswYP"
ASSET_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".gif",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg",
    ".wav", ".mp3", ".aif", ".aiff", ".ogg", ".m4a",
    ".ttf", ".otf", ".woff", ".woff2",
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data" / "reference-assets"
    output.mkdir(parents=True, exist_ok=True)
    failures_path = output / "download-failures.json"

    items = gdown.download_folder(id=FOLDER_ID, skip_download=True, quiet=True)
    failures = []
    downloaded = 0
    skipped = 0
    for item in items:
        relative = Path(item.path)
        if relative.suffix.lower() not in ASSET_EXTENSIONS:
            continue
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 1024:
            skipped += 1
            continue
        try:
            result = gdown.download(id=item.id, output=str(target), quiet=True, resume=True)
            if result and target.exists() and target.stat().st_size > 1024:
                downloaded += 1
            else:
                failures.append({"id": item.id, "path": item.path, "reason": "No file returned"})
        except Exception as exc:  # Keep downloading other public assets.
            failures.append({"id": item.id, "path": item.path, "reason": str(exc)[:500]})

    failures_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
    print(json.dumps({"downloaded": downloaded, "skipped": skipped, "failed": len(failures)}))


if __name__ == "__main__":
    main()
