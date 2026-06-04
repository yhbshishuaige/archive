#!/usr/bin/env python3
"""A small local archive manager driven by .MY_README.md files."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


README_NAME = ".MY_README.md"
META_NAME = "meta.json"
CONFIG_FILE = Path.home() / ".archive"
LEGACY_CONFIG_FILE = Path.home() / ".config" / "local_archive" / "config.json"
NAME_PATTERN = re.compile(r"^\s*[-*]?\s*文件夹名称[:：]\s*(.+?)\s*$")
INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
README_TEMPLATE = """# 归档说明

- 文件夹名称：
- 类型：
- 关键词：
- 状态：
- 简述：

## 详细记录

"""
FLAG_SHORT_OPTIONS = set("hzrfgc")
VALUE_SHORT_OPTIONS = set("pbsWuwF")


class ArchiveError(Exception):
    """User-facing archive error."""


def info(message: str) -> None:
    print(f"[INFO] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def configured_path(explicit_value: str | None, config: dict, key: str, missing_message: str) -> Path:
    value = explicit_value or config.get(key)
    if not value:
        raise ArchiveError(missing_message)
    return expand_path(value)


def configured_workspace_value(config: dict) -> str | None:
    return config.get("default_workspace") or config.get("default_workbase")


def configured_workspace_path(explicit_value: str | None, config: dict) -> Path:
    value = explicit_value or configured_workspace_value(config)
    if not value:
        raise ArchiveError("未指定 workspace，请使用 --workspace 或先使用 --set_workspace 设置默认值")
    return expand_path(value)


def load_config() -> dict:
    config_path = CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ArchiveError(f"配置文件损坏：{config_path} ({exc})") from exc


def save_config(config: dict) -> None:
    with CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write("\n")


def update_recent_bases(config: dict, base: Path) -> None:
    recent = [item for item in config.get("recent_bases", []) if item != str(base)]
    recent.insert(0, str(base))
    config["recent_bases"] = recent[:10]


def remember_archive(config: dict, archive_dir: Path, name: str, base: Path) -> None:
    archive_path = str(archive_dir)
    try:
        rel_path = archive_dir.relative_to(base).as_posix()
    except ValueError:
        rel_path = archive_dir.name
    archives = []
    for item in config.get("archives", []):
        if isinstance(item, dict) and item.get("path") != archive_path:
            archives.append(item)
    archives.insert(
        0,
        {
            "name": name,
            "base_path": str(base),
            "rel_path": rel_path,
            "path": archive_path,
            "readme": str(archive_dir / README_NAME),
            "created_at": now_iso(),
        },
    )
    config["archives"] = archives


def configured_archive_units(config: dict) -> list[Path]:
    units: list[Path] = []
    seen: set[Path] = set()
    for item in config.get("archives", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        archive_dir = expand_path(item["path"])
        if archive_dir in seen:
            continue
        if (archive_dir / README_NAME).is_file():
            seen.add(archive_dir)
            units.append(archive_dir)
    return units


def is_archive_unit(path: Path) -> bool:
    return path.is_dir() and (path / README_NAME).is_file()


def archive_record_rel_path(item: dict) -> str | None:
    rel_path = item.get("rel_path")
    if rel_path:
        return str(rel_path)
    path = item.get("path")
    if path:
        return Path(path).name
    name = item.get("name")
    if name:
        return sanitize_name(str(name))
    return None


def find_repair_candidate(item: dict, default_base: Path | None) -> Path | None:
    path = item.get("path")
    if path:
        current = expand_path(path)
        if is_archive_unit(current):
            return current

    rel_path = archive_record_rel_path(item)
    candidates: list[Path] = []
    if default_base and rel_path:
        candidates.append(default_base / rel_path)
    base_path = item.get("base_path")
    if base_path and rel_path:
        candidates.append(expand_path(base_path) / rel_path)

    for candidate in candidates:
        if is_archive_unit(candidate):
            return candidate

    if default_base and rel_path and default_base.is_dir():
        wanted_name = Path(rel_path).name
        for readme in default_base.rglob(README_NAME):
            archive_dir = readme.parent
            if archive_dir.name == wanted_name and is_archive_unit(archive_dir):
                return archive_dir
    return None


def repair_archives(config: dict) -> int:
    default_base_value = config.get("default_base")
    default_base = expand_path(default_base_value) if default_base_value else None
    archives = config.get("archives", [])
    if not archives:
        print("没有需要修复的归档记录")
        return 0

    repaired = 0
    valid = 0
    missing = 0
    updated_archives = []
    for item in archives:
        if not isinstance(item, dict):
            continue
        old_path = item.get("path")
        candidate = find_repair_candidate(item, default_base)
        updated = dict(item)
        if candidate:
            valid += 1
            updated["path"] = str(candidate)
            updated["readme"] = str(candidate / README_NAME)
            updated["name"] = updated.get("name") or candidate.name
            if default_base and is_relative_to(candidate, default_base):
                updated["base_path"] = str(default_base)
                updated["rel_path"] = candidate.relative_to(default_base).as_posix()
            else:
                updated["rel_path"] = updated.get("rel_path") or candidate.name
            updated.pop("missing", None)
            if old_path != str(candidate):
                repaired += 1
                info(f"修复归档路径：{old_path} -> {candidate}")
        else:
            missing += 1
            updated["missing"] = True
            warn(f"未能修复归档路径：{old_path or updated.get('name', '未知记录')}")
        updated_archives.append(updated)

    config["archives"] = updated_archives
    save_config(config)
    print(f"repair 完成：有效 {valid} 条，修复 {repaired} 条，仍失效 {missing} 条")
    return 0 if missing == 0 else 1


def sanitize_name(raw_name: str) -> str:
    name = raw_name.strip().replace(" ", "_")
    name = INVALID_NAME_CHARS.sub("_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("._-")
    if not name or name in {".", ".."}:
        return ""
    return name[:80]


def extract_name_from_readme(readme_path: Path) -> str | None:
    for line in readme_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = NAME_PATTERN.match(line)
        if match:
            name = sanitize_name(match.group(1))
            return name or None
    return None


def auto_name(readme_path: Path) -> str:
    text = readme_path.read_text(encoding="utf-8", errors="replace")
    first_words = ""
    for line in text.splitlines():
        cleaned = sanitize_name(line)
        if cleaned:
            first_words = cleaned[:24]
            break
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"auto_{timestamp}_{first_words}" if first_words else f"auto_{timestamp}"


def unique_archive_dir(base: Path, wanted_name: str) -> tuple[str, Path]:
    name = sanitize_name(wanted_name) or f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    candidate = base / name
    if not candidate.exists():
        return name, candidate
    index = 1
    while True:
        candidate_name = f"{name}_{index}"
        candidate = base / candidate_name
        if not candidate.exists():
            return candidate_name, candidate
        index += 1


def archive_dir_for_name(base: Path, wanted_name: str, force: bool) -> tuple[str, Path]:
    if not force:
        return unique_archive_dir(base, wanted_name)
    name = sanitize_name(wanted_name) or f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return name, base / name


def require_readme(source: Path) -> Path:
    readme = source / README_NAME
    if not readme.is_file():
        raise ArchiveError(f"归档目录中必须包含 {README_NAME}：{source}")
    return readme


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def source_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for item in source.rglob("*"):
        if item.is_file() or item.is_symlink():
            files.append(item)
    return files


def write_zip(source: Path, zip_path: Path) -> None:
    files = source_files(source)
    expected = {item.relative_to(source).as_posix() for item in files}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in sorted((item for item in source.rglob("*") if item.is_dir()), key=str):
            rel = directory.relative_to(source).as_posix()
            if rel:
                archive.write(directory, f"{rel}/")
        for item in sorted(files, key=str):
            archive.write(item, item.relative_to(source).as_posix())

    if not zip_path.exists() or zip_path.stat().st_size <= 0:
        raise ArchiveError("zip 文件不存在或大小为 0")

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ArchiveError(f"zip 校验失败，损坏条目：{bad_file}")
        actual = {name for name in archive.namelist() if not name.endswith("/")}

    missing = expected - actual
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        raise ArchiveError(f"zip 内容不完整，缺少：{sample}")


def safe_extract_zip(zip_path: Path, target: Path) -> None:
    target = target.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            destination = (target / member.filename).resolve()
            if not is_relative_to(destination, target):
                raise ArchiveError(f"zip 中存在非法路径，拒绝解压：{member.filename}")
        archive.extractall(target)


def copy_source(source: Path, target: Path) -> None:
    shutil.copytree(source, target, symlinks=True)


def remove_source_contents(source: Path) -> None:
    if source == Path(source.anchor):
        raise ArchiveError(f"拒绝清空根目录：{source}")
    for item in source.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_meta(
    staging: Path,
    *,
    name: str,
    source: Path,
    final_dir: Path,
    base: Path,
    content_kind: str,
    content_name: str,
    zip_error: str | None = None,
) -> None:
    meta = {
        "name": name,
        "source_path": str(source),
        "archive_path": str(final_dir),
        "base_path": str(base),
        "created_at": now_iso(),
        "readme_name": README_NAME,
        "content_kind": content_kind,
        "content_name": content_name,
        "zip_verified": content_kind == "zip",
    }
    if zip_error:
        meta["zip_error"] = zip_error
    with (staging / META_NAME).open("w", encoding="utf-8") as file:
        json.dump(meta, file, ensure_ascii=False, indent=2)
        file.write("\n")


def archive_folder(args: argparse.Namespace, config: dict) -> int:
    source = expand_path(args.packed_folder)
    if not source.is_dir():
        raise ArchiveError(f"--packed_folder 不是有效目录：{source}")

    readme = require_readme(source)
    base = configured_path(
        args.tmp_base,
        config,
        "default_base",
        "未指定归档 base，请使用 --tmp_base 或先使用 --set_base 设置默认值",
    )
    base.mkdir(parents=True, exist_ok=True)

    if is_relative_to(base, source):
        raise ArchiveError("归档 base 不能位于 packed_folder 内部，否则可能把归档结果一起打进去")

    wanted_name = extract_name_from_readme(readme) or auto_name(readme)
    final_name, final_dir = archive_dir_for_name(base, wanted_name, args.force)
    staging = Path(tempfile.mkdtemp(prefix=f".{final_name}.", dir=base))

    info(f"归档源目录：{source}")
    info(f"归档目标：{final_dir}")

    content_kind = "files"
    content_name = "files"
    zip_error: str | None = None
    zip_succeeded = False

    try:
        shutil.copy2(readme, staging / README_NAME)
        if args.zip:
            zip_path = staging / "content.zip"
            try:
                write_zip(source, zip_path)
                content_kind = "zip"
                content_name = "content.zip"
                zip_succeeded = True
                info("zip 打包和校验成功")
            except Exception as exc:  # noqa: BLE001 - show any zip failure to the user
                zip_error = str(exc)
                warn(f"zip 打包失败，改为复制原目录内容：{zip_error}")
                if zip_path.exists():
                    zip_path.unlink()
                copy_source(source, staging / "files")
        else:
            copy_source(source, staging / "files")

        write_meta(
            staging,
            name=final_name,
            source=source,
            final_dir=final_dir,
            base=base,
            content_kind=content_kind,
            content_name=content_name,
            zip_error=zip_error,
        )
        if args.force and final_dir.exists():
            warn(f"归档目标已存在，按 --force 覆盖：{final_dir}")
            if final_dir.is_dir() and not final_dir.is_symlink():
                shutil.rmtree(final_dir)
            else:
                final_dir.unlink()
        staging.rename(final_dir)

        update_recent_bases(config, base)
        remember_archive(config, final_dir, final_name, base)
        save_config(config)
        info(f"归档完成：{final_dir}")

        if args.remove_source:
            if args.zip and not zip_succeeded:
                warn("本次请求了 --zip 但 zip 失败并回退为复制，因此不会删除源目录内容")
            else:
                remove_source_contents(source)
                info(f"已清空源目录内容：{source}")
        return 0
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def iter_archive_units(base: Path) -> Iterable[Path]:
    if not base.is_dir():
        return []
    units: list[Path] = []
    seen: set[Path] = set()
    for readme in base.rglob(README_NAME):
        archive_dir = readme.parent
        try:
            relative_parts = archive_dir.relative_to(base).parts
        except ValueError:
            continue
        if "files" in relative_parts:
            continue
        if archive_dir in seen:
            continue
        seen.add(archive_dir)
        units.append(archive_dir)
    return sorted(units)


def search_readmes(args: argparse.Namespace, config: dict) -> int:
    keywords = [keyword for keyword in args.search if keyword]
    if not keywords:
        raise ArchiveError("--search 至少需要一个关键词")

    lowered_keywords = [keyword.lower() for keyword in keywords]
    results: list[tuple[Path, list[tuple[int, str]]]] = []
    archive_units = configured_archive_units(config)
    if not archive_units:
        if config.get("archives"):
            raise ArchiveError(f"{CONFIG_FILE} 中记录的归档路径都已失效，请运行 archive --repair")
        raise ArchiveError(f"{CONFIG_FILE} 中还没有 archive 生成过的归档目录记录")

    for archive_dir in archive_units:
        readme = archive_dir / README_NAME
        matches: list[tuple[int, str]] = []
        lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_number, line in enumerate(lines, start=1):
            lowered_line = line.lower()
            if any(keyword in lowered_line for keyword in lowered_keywords):
                matches.append((line_number, line))
        if matches:
            results.append((archive_dir, matches))

    if not results:
        print(f"没有找到匹配内容：{' '.join(keywords)}")
        return 1

    for index, (archive_dir, matches) in enumerate(results, start=1):
        print(f"[{index}] {archive_dir}")
        for line_number, line in matches:
            print(f"    line {line_number}: {line}")
        print()
    return 0


def read_meta(archive_dir: Path) -> dict:
    meta_path = archive_dir / META_NAME
    if not meta_path.is_file():
        return {}
    with meta_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_archive_unit(query: str, base: Path, config: dict) -> Path:
    direct = expand_path(query)
    if direct.is_dir() and (direct / README_NAME).is_file():
        return direct

    exact = base / query
    if exact.is_dir() and (exact / README_NAME).is_file():
        return exact

    configured_candidates = [item for item in configured_archive_units(config) if item.name == query]
    if len(configured_candidates) == 1:
        return configured_candidates[0]

    candidates = [item for item in configured_archive_units(config) if query in item.name]
    if not candidates:
        candidates = [item for item in iter_archive_units(base) if query in item.name]
    if not candidates:
        raise ArchiveError(f"没有找到归档：{query}")
    if len(candidates) > 1:
        print("匹配到多个归档，请使用更精确的名称或完整路径：")
        for item in candidates:
            print(f"  {item}")
        raise ArchiveError(f"归档名称不唯一：{query}")
    return candidates[0]


def unpack_archive(args: argparse.Namespace, config: dict) -> int:
    base = configured_path(
        args.tmp_base,
        config,
        "default_base",
        "未指定归档 base，请使用 --tmp_base 或先使用 --set_base 设置默认值",
    )

    workbase = configured_workspace_path(args.workbase, config)
    workbase.mkdir(parents=True, exist_ok=True)

    archive_dir = resolve_archive_unit(args.unpack, base, config)
    meta = read_meta(archive_dir)
    name = sanitize_name(meta.get("name") or archive_dir.name) or archive_dir.name
    target = workbase / name

    if target.exists():
        warn(f"目标目录已存在，按默认 overwrite 逻辑覆盖：{target}")
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.mkdir(parents=True, exist_ok=True)

    shutil.copy2(archive_dir / README_NAME, target / README_NAME)
    content_kind = meta.get("content_kind")
    content_name = meta.get("content_name")

    if content_kind == "zip" or (archive_dir / "content.zip").is_file():
        zip_path = archive_dir / (content_name or "content.zip")
        if not zip_path.is_file():
            raise ArchiveError(f"meta.json 指向的 zip 不存在：{zip_path}")
        safe_extract_zip(zip_path, target)
        info(f"已解压 zip 到：{target}")
    else:
        files_dir = archive_dir / (content_name or "files")
        if not files_dir.is_dir():
            raise ArchiveError(f"归档内容不存在：{files_dir}")
        for item in files_dir.iterdir():
            destination = target / item.name
            if item.is_dir() and not item.is_symlink():
                shutil.copytree(item, destination, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)
        info(f"已复制归档内容到：{target}")

    return 0


def set_default_base(args: argparse.Namespace, config: dict) -> int:
    base = expand_path(args.set_base)
    base.mkdir(parents=True, exist_ok=True)
    config["default_base"] = str(base)
    update_recent_bases(config, base)
    save_config(config)
    info(f"默认归档 base 已设置为：{base}")
    return 0


def set_default_workspace(args: argparse.Namespace, config: dict) -> int:
    workbase = expand_path(args.set_workspace)
    workbase.mkdir(parents=True, exist_ok=True)
    config["default_workspace"] = str(workbase)
    config.pop("default_workbase", None)
    save_config(config)
    info(f"默认 workspace 已设置为：{workbase}")
    return 0


def get_readme_template(force: bool) -> int:
    target = Path.cwd() / README_NAME
    if target.exists() and not force:
        raise ArchiveError(f"当前目录已存在 {README_NAME}，不会覆盖：{target}")
    if target.exists() and force:
        warn(f"当前目录已存在 {README_NAME}，按 --force 覆盖：{target}")
    target.write_text(README_TEMPLATE, encoding="utf-8")
    info(f"已生成 README 模板：{target}")
    return 0


def show_config(config: dict) -> int:
    print(f"当前配置文件：{CONFIG_FILE}")
    print(f"  默认归档 base：{config.get('default_base', '未设置')}")
    print(f"  默认 workspace：{configured_workspace_value(config) or '未设置'}")
    recent = config.get("recent_bases", [])
    if recent:
        print("  最近使用的 base：")
        for item in recent:
            print(f"    {item}")
    archives = config.get("archives", [])
    if archives:
        print("  已记录的归档目录：")
        for item in archives:
            if isinstance(item, dict):
                print(f"    {item.get('path', '')}")
    return 0


def show_base(config: dict) -> int:
    print(config.get("default_base", "未设置"))
    return 0


def show_workspace(config: dict) -> int:
    print(configured_workspace_value(config) or "未设置")
    return 0


def config_file_for_uninstall() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            import pwd

            return Path(pwd.getpwnam(sudo_user).pw_dir) / ".archive"
        except Exception:
            return CONFIG_FILE
    return CONFIG_FILE


def uninstall_archive(args: argparse.Namespace) -> int:
    if not args.force:
        raise ArchiveError("卸载会删除可执行文件和 ~/.archive；请加 -f/--force 确认")

    target = expand_path(args.uninstall_target or "/usr/bin/archive")
    config_file = config_file_for_uninstall()

    try:
        if target.exists():
            if target.is_dir() and not target.is_symlink():
                raise ArchiveError(f"拒绝删除目录：{target}")
            target.unlink()
            info(f"已删除可执行文件：{target}")
        else:
            warn(f"可执行文件不存在，跳过：{target}")

        if config_file.exists():
            config_file.unlink()
            info(f"已删除配置文件：{config_file}")
        else:
            warn(f"配置文件不存在，跳过：{config_file}")
    except PermissionError as exc:
        raise ArchiveError(f"删除失败，权限不足；删除 /usr/bin/archive 通常需要 sudo：{exc}") from exc

    return 0


def normalize_short_options(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    for token in argv:
        if not token.startswith("-") or token.startswith("--") or len(token) <= 2:
            normalized.append(token)
            continue

        chars = token[1:]
        known_chars = FLAG_SHORT_OPTIONS | VALUE_SHORT_OPTIONS
        if any(char not in known_chars for char in chars):
            normalized.append(token)
            continue

        value_options = [char for char in chars if char in VALUE_SHORT_OPTIONS]
        if not value_options:
            normalized.extend(f"-{char}" for char in chars)
            continue

        if len(value_options) == 1:
            value_option = value_options[0]
            normalized.extend(f"-{char}" for char in chars if char in FLAG_SHORT_OPTIONS)
            normalized.append(f"-{value_option}")
            continue

        normalized.append(token)
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive",
        description="本地文件归档管理系统：根据 .MY_README.md 归档、搜索和解包临时项目。",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示这份中文帮助并退出")
    parser.add_argument(
        "-p",
        "--packed_folder",
        "--packed-folder",
        "--packer_folder",
        "--packer-folder",
        help="要归档的目录，目录中必须包含 .MY_README.md",
    )
    parser.add_argument("-b", "--tmp_base", "--tmp-base", help="本次使用的归档目标 base；不提供时使用默认 base")
    parser.add_argument("-s", "--set_base", "--set-base", help="设置默认归档 base，例如 --set_base=~/archive")
    parser.add_argument("-W", "--set_workspace", "--set-workspace", dest="set_workspace", help="设置默认 workspace，例如 --set_workspace=~/workspace")
    parser.add_argument("--set_workbase", "--set-workbase", dest="set_workspace", help=argparse.SUPPRESS)
    parser.add_argument("-z", "--zip", dest="zip", action="store_true", default=True, help="默认行为：将 packed_folder 内容压缩为 base/归档名/content.zip")
    parser.add_argument("--no-zip", dest="zip", action="store_false", help="不压缩，改为复制 packed_folder 内容到 base/归档名/files")
    parser.add_argument("-r", "--remove-source", "--remove_source", action="store_true", help="归档成功后清空 packed_folder 内部内容；默认不删除")
    parser.add_argument("-u", "--unpack", help="解包某个归档，可传归档名、名称片段或完整路径")
    parser.add_argument("-w", "--workspace", dest="workbase", metavar="WORKSPACE", help="解包目标 workspace；不提供时使用默认 workspace")
    parser.add_argument("--workbase", dest="workbase", help=argparse.SUPPRESS)
    parser.add_argument("-F", "--search", nargs="+", help="搜索关键词；只在 ~/.archive 记录过的归档目录中寻找 .MY_README.md")
    parser.add_argument("-f", "--force", action="store_true", help="强制覆盖：归档时覆盖同名归档，生成 README 模板时覆盖已有文件")
    parser.add_argument("-g", "--get_readme", "--get-readme", action="store_true", help="在当前目录生成空白 .MY_README.md 模板")
    parser.add_argument("-c", "--show_config", "--show-config", action="store_true", help="显示当前默认 base、workspace、最近 base 和归档记录")
    parser.add_argument("--show_base", "--show-base", action="store_true", help="显示默认知识库路径")
    parser.add_argument("--show_workspace", "--show-workspace", action="store_true", help="显示默认 workspace")
    parser.add_argument("--repair", action="store_true", help="修复 ~/.archive 中因 base 改名而失效的归档路径")
    parser.add_argument("--uninstall", action="store_true", help="卸载 archive：删除 /usr/bin/archive 和 ~/.archive，需要配合 -f")
    parser.add_argument("--uninstall_target", "--uninstall-target", help=argparse.SUPPRESS)
    parser._optionals.title = "选项"
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = normalize_short_options(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(normalized_argv)

    try:
        if args.uninstall:
            return uninstall_archive(args)

        config = load_config()

        performed = False
        exit_code = 0

        def record(code: int) -> None:
            nonlocal performed, exit_code
            performed = True
            exit_code = max(exit_code, code)

        if args.set_base:
            record(set_default_base(args, config))
        if args.set_workspace:
            record(set_default_workspace(args, config))
        if args.get_readme:
            record(get_readme_template(args.force))
        if args.repair:
            record(repair_archives(config))
        if args.packed_folder:
            record(archive_folder(args, config))
        if args.search:
            record(search_readmes(args, config))
        if args.unpack:
            record(unpack_archive(args, config))
        if args.show_config:
            record(show_config(config))
        if args.show_base or args.show_workspace:
            if args.show_base:
                show_base(config)
            if args.show_workspace:
                show_workspace(config)
            record(0)

        if not performed:
            parser.print_help()
        return exit_code
    except ArchiveError as exc:
        error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
