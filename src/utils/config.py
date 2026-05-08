from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.exceptions import ConfigError


def load_config_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file.

    PyYAML is the intended parser. A small fallback keeps simple tests and
    bootstrapping usable before dependencies are installed.
    """

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml
    except ModuleNotFoundError:
        return _parse_simple_yaml(text)

    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"Top-level YAML value must be a mapping: {config_path}")
    return loaded


def load_config_dir(config_dir: str | Path) -> dict[str, dict[str, Any]]:
    directory = Path(config_dir)
    if not directory.exists():
        raise ConfigError(f"Config directory not found: {directory}")
    return {path.stem: load_config_file(path) for path in sorted(directory.glob("*.yaml"))}


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = _yaml_lines(text)
    if not lines:
        return {}

    parsed, next_index = _parse_yaml_block(lines, 0, lines[0][0])
    if next_index != len(lines):
        raise ConfigError("Unable to parse full YAML document without PyYAML.")
    if not isinstance(parsed, dict):
        raise ConfigError("Top-level YAML value must be a mapping.")
    return parsed


def _yaml_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    return lines


def _parse_yaml_block(
    lines: list[tuple[int, str]],
    start_index: int,
    indent: int,
) -> tuple[dict[str, Any] | list[Any], int]:
    if lines[start_index][1].startswith("- "):
        return _parse_yaml_list(lines, start_index, indent)
    return _parse_yaml_mapping(lines, start_index, indent)


def _parse_yaml_mapping(
    lines: list[tuple[int, str]],
    start_index: int,
    indent: int,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    index = start_index

    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ConfigError(f"Unexpected indentation near: {content}")
        if content.startswith("- "):
            break

        key, sep, value = content.partition(":")
        if not sep:
            raise ConfigError(f"Invalid YAML mapping line: {content}")

        value = value.strip()
        index += 1
        if value:
            result[key] = _coerce_scalar(value)
            continue

        if index >= len(lines) or lines[index][0] <= current_indent:
            result[key] = {}
            continue

        child, index = _parse_yaml_block(lines, index, lines[index][0])
        result[key] = child

    return result, index


def _parse_yaml_list(
    lines: list[tuple[int, str]],
    start_index: int,
    indent: int,
) -> tuple[list[Any], int]:
    result: list[Any] = []
    index = start_index

    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ConfigError(f"Unexpected indentation near: {content}")
        if not content.startswith("- "):
            break

        item = content[2:].strip()
        index += 1
        if item:
            result.append(_coerce_scalar(item))
            continue

        if index >= len(lines) or lines[index][0] <= current_indent:
            result.append(None)
            continue

        child, index = _parse_yaml_block(lines, index, lines[index][0])
        result.append(child)

    return result, index


def _coerce_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
