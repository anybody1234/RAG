"""Tải các văn bản trong data/manifest.json về data/raw/.

Chạy từ thư mục gốc của repo:
    python scripts/download_data.py           # bỏ qua file đã có và đúng sha256
    python scripts/download_data.py --force   # tải lại toàn bộ

File nào chưa có sha256 trong manifest thì script in ra hash để điền vào.
"""

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
RAW_DIR = ROOT / "data" / "raw"
# Một số máy chủ (asean.org, investdanang.gov.vn) trả 403 nếu không có User-Agent trình duyệt.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, tmp.open("wb") as f:
        shutil.copyfileobj(response, f)
    with tmp.open("rb") as f:
        is_pdf = f.read(5) == b"%PDF-"
    if not is_pdf:
        tmp.unlink()
        raise ValueError("nội dung tải về không phải PDF (có thể bị chặn hoặc link đã đổi)")
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="tải lại cả file đã có")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures = []

    for doc in manifest["documents"]:
        for file in doc["files"]:
            dest = RAW_DIR / file["filename"]
            expected = file.get("sha256")
            up_to_date = dest.exists() and (expected is None or sha256_of(dest) == expected)
            if up_to_date and not args.force:
                print(f"[có sẵn] {file['filename']}")
                continue
            try:
                download(file["url"], dest)
            except Exception as exc:  # noqa: BLE001 - báo lỗi từng file rồi chạy tiếp
                failures.append(file["filename"])
                print(f"[LỖI]    {file['filename']}: {exc}")
                continue
            actual = sha256_of(dest)
            if expected is None:
                print(f"[đã tải] {file['filename']} (chưa có sha256 trong manifest: {actual})")
            elif actual != expected:
                failures.append(file["filename"])
                print(f"[LỖI]    {file['filename']}: sha256 {actual} khác manifest {expected}")
            else:
                print(f"[đã tải] {file['filename']}")

    if failures:
        print(f"\n{len(failures)} file lỗi: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
