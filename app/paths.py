# -*- coding: utf-8 -*-
r"""路径解析：同时支持"源码运行"和"打包后的 exe"两种形态。

打包布局（PyInstaller onedir）：
    LocalTranslator\
      LocalTranslator.exe
      _internal\            <- PyInstaller 运行时
      runtime\              <- llama-server.exe + CUDA dll
      models\               <- *.gguf（可随时替换）

源码布局：
    E:\Sheeran\app\*.py
    E:\Ai\llama.cpp\llama-server.exe
    E:\Ai\models\*.gguf
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "本地截图翻译"
APP_VERSION = "1.5.0"
DEFAULT_PORT = 8080


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """exe 所在目录（打包后）或 app 源码目录（开发时）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _first_file(cands: list[Path]) -> Path | None:
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def find_server() -> Path | None:
    """定位 llama-server.exe。环境变量 LT_SERVER 优先。"""
    env = os.environ.get("LT_SERVER")
    root = app_dir()
    cands = [
        Path(env) if env else None,
        root / "runtime" / "llama-server.exe",
        root.parent / "llama.cpp" / "llama-server.exe",
        Path(r"E:\Ai\llama.cpp\llama-server.exe"),
    ]
    return _first_file([c for c in cands if c is not None])


def find_model() -> Path | None:
    """定位 .gguf 模型：有多个时取"最新修改"的那个。环境变量 LT_MODEL 优先。"""
    env = os.environ.get("LT_MODEL")
    if env and Path(env).is_file():
        return Path(env)

    for d in (app_dir() / "models", app_dir().parent / "models", Path(r"E:\Ai\models")):
        if not d.is_dir():
            continue
        ggufs = [g for g in d.glob("*.gguf") if g.is_file()]
        if not ggufs:
            continue
        # 按修改时间取最新：用户把新模型丢进目录即生效，无需改名
        return max(ggufs, key=lambda g: g.stat().st_mtime)
    return None


def describe() -> str:
    srv = find_server()
    mdl = find_model()
    return (
        f"frozen={is_frozen()}\n"
        f"app_dir={app_dir()}\n"
        f"server={srv or '<未找到>'}\n"
        f"model={mdl or '<未找到>'}"
    )








