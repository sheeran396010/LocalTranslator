# -*- coding: utf-8 -*-
"""模型 A/B 对照：同一批句子，比较译文一致性、耗时、体积。

    python compare_models.py --models "E:\\Ai\\models\\a.gguf" "E:\\Ai\\models\\b.gguf"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LLAMA = Path(r"E:\Ai\llama.cpp\llama-server.exe")
U = "<\uff5chy_User\uff5c>"
A = "<\uff5chy_Assistant\uff5c>"
EOS_TEXT = "<\uff5chy_place\u2581holder\u2581no\u25812\uff5c>"
PORT = 8099

CASES = [
    ("中文短句", "今天天气很好，我们去公园散步吧。", "英文"),
    ("中文长段", "人工智能的发展速度超出了大多数人的预期。十年前，机器翻译还只能给出勉强可读的结果，而今天，本地运行的小模型已经能在几百毫秒内完成长段落的精准翻译。", "英文"),
    ("英文短句", "The quick brown fox jumps over the lazy dog.", "中文"),
    ("含数字", "该设备于 2026 年 10 月 19 日发布，售价 1299 美元，支持 5G 网络。", "英文"),
    ("技术术语", "我们使用 onnxruntime 的 DirectML 后端进行推理，显存占用约 800 MB。", "英文"),
    ("成语口语", "这事儿八字还没一撇，你先别声张。", "英文"),
    ("中英混排", "请运行 serve.ps1 启动 llama-server，然后按 Alt+Q 框选。", "中文"),
    ("标点保留", "第一，确认环境；第二，启动服务；第三，开始翻译！", "英文"),
]


def build_prompt(text: str, target: str) -> str:
    """与 app/translate.py 完全一致的模板（生产口径）。"""
    return f"{U}把下面这段话翻译成{target}，只输出译文，不要任何解释：\n{text}{A}"


def http(path: str, payload: dict | None = None, timeout: float = 180) -> dict:
    url = f"http://127.0.0.1:{PORT}{path}"
    if payload is None:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def run_model(model: Path) -> dict:
    proc = subprocess.Popen(
        [str(LLAMA), "-m", str(model), "-ngl", "99", "-c", "2048",
         "--host", "127.0.0.1", "--port", str(PORT), "-np", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    out: dict = {"model": model.name, "size_gb": model.stat().st_size / 1024**3, "rows": []}
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                raise SystemExit(f"{model.name} 服务退出 code={proc.returncode}")
            try:
                if http("/health", timeout=1.5).get("status") == "ok":
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        else:
            raise SystemExit(f"{model.name} 启动超时")

        for tag, body, target in CASES:
            t = time.perf_counter()
            r = http("/completion", {
                "prompt": build_prompt(body, target), "n_predict": 256, "temperature": 0.0,
                "top_k": 1, "repeat_penalty": 1.05, "stop": [EOS_TEXT], "stream": False,
            })
            dt = (time.perf_counter() - t) * 1000
            ntok = r.get("tokens_predicted", 0) or 0
            out["rows"].append({
                "tag": tag,
                "content": (r.get("content") or "").strip(),
                "stop": r.get("stop_type"),
                "ms": dt,
                "tok": ntok,
                "tok_s": ntok / (dt / 1000) if dt else 0,
            })
        # 第二次跑一遍取稳态
        for row, (_, body, target) in zip(out["rows"], CASES):
            t = time.perf_counter()
            http("/completion", {
                "prompt": build_prompt(body, target), "n_predict": 256, "temperature": 0.0,
                "top_k": 1, "repeat_penalty": 1.05, "stop": [EOS_TEXT], "stream": False,
            })
            row["ms2"] = (time.perf_counter() - t) * 1000
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--out", default=r"E:\Ai\_downloads\model_ab.txt")
    args = ap.parse_args()

    results = []
    for m in args.models:
        p = Path(m)
        print(f"测试 {p.name} ...", flush=True)
        results.append(run_model(p))

    lines: list[str] = []
    for r in results:
        lines.append(f"### {r['model']}  {r['size_gb']:.2f} GB")
        tot = sum(x["ms2"] for x in r["rows"])
        lines.append(f"    合计(稳态) {tot:.0f} ms / {len(r['rows'])} 句")
        for x in r["rows"]:
            lines.append(f"    [{x['tag']}] {x['ms']:.0f}ms → {x['ms2']:.0f}ms  stop={x['stop']}")
            lines.append(f"        {x['content']}")
        lines.append("")

    if len(results) >= 2:
        a, b = results[0], results[1]
        same = 0
        lines.append(f"### 一致性 {a['model']}  vs  {b['model']}")
        for xa, xb in zip(a["rows"], b["rows"]):
            eq = xa["content"] == xb["content"]
            same += eq
            lines.append(f"    {'一致  ' if eq else '不同  '} [{xa['tag']}]")
            if not eq:
                lines.append(f"        A: {xa['content']}")
                lines.append(f"        B: {xb['content']}")
        lines.append(f"    完全一致 {same}/{len(a['rows'])}")
        ta = sum(x["ms2"] for x in a["rows"])
        tb = sum(x["ms2"] for x in b["rows"])
        lines.append(f"    速度: {a['model']} {ta:.0f} ms  vs  {b['model']} {tb:.0f} ms"
                     f"  ({(tb / ta - 1) * 100:+.0f}%)")
        lines.append(f"    体积: {a['size_gb']:.2f} GB  vs  {b['size_gb']:.2f} GB")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print("written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
