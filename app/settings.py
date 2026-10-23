# -*- coding: utf-8 -*-
"""设置持久化：JSON 存在应用目录（便携），目录不可写时退回 LOCALAPPDATA。

保存项：目标语言、遮罩透明度、实时开关、当前页、窗口位置尺寸。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

import paths

DEFAULTS = {
    "target": "auto",      # "auto" 或语种 code
    "opacity": 60,         # 实时浮窗遮罩透明度 25-95（%）
    "font_size": 17,       # 实时浮窗译文字号 12-32（px）
    "page": 0,             # 当前页签
    "window": None,        # [x, y, w, h]
    "live_size": None,     # 实时浮窗 [w, h]
}


def _settings_path() -> Path:
    for base in (paths.app_dir(), Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LocalTranslator"):
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write_test"
            probe.write_text("x", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return base / "settings.json"
        except Exception:  # noqa: BLE001
            continue
    return Path.home() / "LocalTranslator-settings.json"


class Settings(QObject):
    """带变更信号的轻量设置对象。"""

    changed = Signal(str, object)

    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = Path(path) if path else _settings_path()
        self._data: dict = dict(DEFAULTS)
        self._load()

    # ---------- 读写 ----------
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        if not isinstance(raw, dict):
            return
        for key, default in DEFAULTS.items():
            if key not in raw:
                continue
            value = raw[key]
            if key == "opacity":
                try:
                    value = max(25, min(95, int(value)))
                except Exception:  # noqa: BLE001
                    value = default
            elif key == "font_size":
                try:
                    value = max(12, min(32, int(value)))
                except Exception:  # noqa: BLE001
                    value = default
            elif key == "target":
                if value != "auto" and value not in dict(paths_langs()):
                    value = default
            elif key == "window":
                if not (isinstance(value, list) and len(value) == 4
                        and all(isinstance(v, int) for v in value)):
                    value = None
            elif key == "live_size":
                if not (isinstance(value, list) and len(value) == 2
                        and all(isinstance(v, int) and v > 0 for v in value)):
                    value = None
            elif key == "page":
                value = value if value in (0, 1) else default
            self._data[key] = value

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 访问 ----------
    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value, save: bool = True) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if save:
            self.save()
        self.changed.emit(key, value)


def paths_langs() -> list[tuple[str, str]]:
    """避免顶层 import langs（settings 可能被无 Qt 环境导入）。"""
    try:
        import langs

        return langs.LANGS
    except Exception:  # noqa: BLE001
        return []
