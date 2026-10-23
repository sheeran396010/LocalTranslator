# -*- coding: utf-8 -*-
"""推理服务管理：需要时自动拉起 llama-server，退出时收拾干净。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import paths
import translate

CREATE_NO_WINDOW = 0x08000000


class ServerHandle:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.owned = False  # True 表示由我们启动，退出时需要关掉

    def stop(self) -> None:
        if self.owned and self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self.proc = None
        self.owned = False


def ensure(base: str, port: int, timeout: float = 90.0, handle: ServerHandle | None = None) -> tuple[bool, str]:
    """确保服务可用。返回 (ok, 说明)。"""
    if translate.health(base, timeout=1.5):
        return True, "已在运行"

    exe = paths.find_server()
    if exe is None:
        return False, "找不到 llama-server.exe（runtime 目录缺失）"
    model = paths.find_model()
    if model is None:
        return False, "找不到 .gguf 模型（models 目录缺失）"

    args = [
        str(exe), "-m", str(model), "-ngl", "99", "-c", "4096",
        "--host", "127.0.0.1", "--port", str(port), "-np", "1",
    ]
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": str(exe.parent),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(args, **kwargs)
    except Exception as e:  # noqa: BLE001
        return False, f"启动失败: {e}"

    if handle is not None:
        handle.proc = proc
        handle.owned = True

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"服务进程提前退出 (code={proc.returncode})"
        if translate.health(base, timeout=1.0):
            return True, f"已启动 ({model.name})"
        time.sleep(0.4)
    return False, "启动超时（90s）"
