# -*- coding: utf-8 -*-
"""一条命令完成「HF 权重 -> GGUF -> 验证 -> 可选部署」。

    python build_model.py --src E:\\Ai\\models\\mt-1.8b-hf --quant q8_0
    python build_model.py --src <fp16目录> --quant q5_k_m --deploy

做的事：
  1. 校验 HF 目录必需文件
  2. 修正 EOS（写 config.json 的 eod_token_id）与 tokenizer_config 的 eos/chat_template
     —— 这是之前踩过的坑：转换器最后会用 eod_token_id 覆盖 eos，缺省值 3 会让模型永不停机
  3. 调 convert_hf_to_gguf.py；非 q8_0 目标先出 bf16 再 llama-quantize
  4. 起一个临时 llama-server 真跑一句翻译，确认 stop_type == "eos" 且译文非空
  5. --deploy 时备份旧模型并替换到 E:\\Ai\\models 与 dist\\models
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PY = r"E:\Ai\venv312\Scripts\python.exe"
CONVERTER_DIR = Path(r"E:\Ai\tools\llama.cpp-b11734")
LLAMA = Path(r"E:\Ai\llama.cpp")
MODELS = Path(r"E:\Ai\models")
DIST_MODELS = Path(r"E:\Sheeran\dist\LocalTranslator\models")

REQUIRED = ["config.json", "tokenizer.json"]
OPTIONAL = ["tokenizer_config.json", "generation_config.json", "special_tokens_map.json"]

CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "{% if message['role'] == 'user' %}"
    "{{ '<\uff5chy_User\uff5c>' + message['content'] }}"
    "{% elif message['role'] == 'assistant' %}"
    "{{ '<\uff5chy_Assistant\uff5c>' + message['content'] + '<\uff5chy_EOT\uff5c>' }}"
    "{% endif %}"
    "{% endfor %}"
    "{% if add_generation_prompt %}{{ '<\uff5chy_Assistant\uff5c>' }}{% endif %}"
)

U = "<\uff5chy_User\uff5c>"
A = "<\uff5chy_Assistant\uff5c>"
EOS_TEXT = "<\uff5chy_place\u2581holder\u2581no\u25812\uff5c>"


def log(msg: str) -> None:
    print(msg, flush=True)


def step(n: int, total: int, title: str) -> None:
    log(f"\n=== [{n}/{total}] {title} ===")


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------- 1. 校验 ----------------
def check_src(src: Path) -> None:
    missing = [f for f in REQUIRED if not (src / f).is_file()]
    if missing:
        raise SystemExit(f"缺少必需文件: {missing}")
    if not list(src.glob("*.safetensors")):
        raise SystemExit("目录里没有 *.safetensors")
    weights = sum(f.stat().st_size for f in src.glob("*.safetensors"))
    log(f"  src      : {src}")
    log(f"  权重     : {len(list(src.glob('*.safetensors')))} 个文件, {weights / 1024**3:.2f} GB")
    for f in OPTIONAL:
        log(f"  {f:26s}: {'有' if (src / f).is_file() else '缺（会用默认值）'}")


# ---------------- 2. 修正 EOS / 模板 ----------------
def fix_config(src: Path) -> tuple[int, str]:
    cfg_p = src / "config.json"
    cfg = load_json(cfg_p)

    # eos 的权威来源：generation_config > config.json
    eos_id = None
    gen_p = src / "generation_config.json"
    if gen_p.is_file():
        gen = load_json(gen_p)
        v = gen.get("eos_token_id")
        eos_id = v[0] if isinstance(v, list) else v
    if eos_id is None:
        eos_id = cfg.get("eos_token_id")
    if eos_id is None:
        raise SystemExit("拿不到 eos_token_id，无法确定停止 token")
    eos_id = int(eos_id)

    # 用 tokenizer.json 的 added_tokens 反查这个 id 对应的字符串
    tok = load_json(src / "tokenizer.json")
    id2s = {t["id"]: t["content"] for t in tok.get("added_tokens", []) if "id" in t}
    eos_str = id2s.get(eos_id, EOS_TEXT)

    changed = []
    if cfg.get("eod_token_id") != eos_id:
        cfg["eod_token_id"] = eos_id
        save_json(cfg_p, cfg)
        changed.append("config.json: eod_token_id")
    # 去掉量化段落，避免下游误判
    for k in ("quantization", "quantization_config"):
        if k in cfg:
            cfg.pop(k)
            changed.append(f"config.json: 移除 {k}")
    if changed:
        save_json(cfg_p, cfg)

    tc_p = src / "tokenizer_config.json"
    if tc_p.is_file():
        tc = load_json(tc_p)
        if tc.get("eos_token") != eos_str:
            tc["eos_token"] = eos_str
            changed.append("tokenizer_config.json: eos_token")
        if not tc.get("chat_template"):
            tc["chat_template"] = CHAT_TEMPLATE
            changed.append("tokenizer_config.json: chat_template")
        if tc.get("tokenizer_class") in (None, "TokenizersBackend"):
            tc["tokenizer_class"] = "PreTrainedTokenizerFast"
            changed.append("tokenizer_config.json: tokenizer_class")
        save_json(tc_p, tc)

    log(f"  eos_id   : {eos_id}  ({eos_str})")
    log(f"  改动     : {', '.join(changed) if changed else '无（已就绪）'}")
    return eos_id, eos_str


# ---------------- 3. 转换 ----------------
def run(cmd: list[str], cwd: Path | None = None) -> None:
    log("  $ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    t = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    dt = time.perf_counter() - t
    if proc.returncode != 0:
        log(proc.stdout[-2000:])
        log(proc.stderr[-2000:])
        raise SystemExit(f"命令失败 (code={proc.returncode})")
    for line in (proc.stdout or "").splitlines():
        if any(k in line for k in ("Setting special token", "tokenizer", "architecture", "n_tensors", "successfully")):
            log("  | " + line.strip()[:150])
    log(f"  完成 {dt:.1f}s")


def convert(src: Path, gguf: Path, quant: str) -> None:
    if quant in ("q8_0", "f16"):
        run([PY, "convert_hf_to_gguf.py", str(src), "--outtype", quant, "--outfile", str(gguf)],
            cwd=CONVERTER_DIR)
        return
    # 其余量化类型：先转 bf16 GGUF，再用 llama-quantize 压
    run([PY, "convert_hf_to_gguf.py", str(src), "--outtype", "bf16", "--outfile", str(gguf)],
        cwd=CONVERTER_DIR)
    bf16 = gguf.with_name(gguf.stem + "-bf16.gguf")
    shutil.move(str(gguf), str(bf16))
    run([str(LLAMA / "llama-quantize.exe"), str(bf16), str(gguf), quant.upper()])
    bf16.unlink(missing_ok=True)


# ---------------- 4. 验证 ----------------
def http(port: int, path: str, payload: dict | None = None, timeout: float = 30) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    if payload is None:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def verify(gguf: Path, port: int = 8099) -> dict:
    proc = subprocess.Popen(
        [str(LLAMA / "llama-server.exe"), "-m", str(gguf), "-ngl", "99", "-c", "2048",
         "--host", "127.0.0.1", "--port", str(port), "-np", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                raise SystemExit(f"服务提前退出 (code={proc.returncode})")
            try:
                if http(port, "/health", timeout=1.5).get("status") == "ok":
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        else:
            raise SystemExit("服务启动超时")

        cases = [
            ("中→英", "把下面这句话翻译成英文：今天天气很好，我们去公园散步吧。"),
            ("英→中", "把下面这句话翻译成中文：The quick brown fox jumps over the lazy dog."),
        ]
        results = []
        for tag, body in cases:
            t = time.perf_counter()
            out = http(port, "/completion", {
                "prompt": f"{U}{body}{A}", "n_predict": 128, "temperature": 0.0,
                "top_k": 1, "repeat_penalty": 1.05, "stream": False,
            }, timeout=180)
            dt = (time.perf_counter() - t) * 1000
            results.append((tag, out.get("content", "").strip(), out.get("stop_type"), dt,
                            out.get("tokens_predicted", 0)))
        return {"cases": results}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


# ---------------- 5. 部署 ----------------
def deploy(gguf: Path) -> None:
    for target_dir in (MODELS, DIST_MODELS):
        if not target_dir.is_dir():
            log(f"  跳过（不存在）: {target_dir}")
            continue
        dst = target_dir / gguf.name
        if dst.exists():
            bak = dst.with_suffix(".gguf.bak")
            if not bak.exists():
                shutil.copy2(dst, bak)
        shutil.copy2(gguf, dst)
        log(f"  已部署 -> {dst}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="HF 权重目录")
    ap.add_argument("--quant", default="q8_0", choices=["q8_0", "q5_k_m", "q4_k_m", "f16"])
    ap.add_argument("--out", default=None, help="输出 gguf 路径（默认按 src 目录名生成）")
    ap.add_argument("--deploy", action="store_true", help="验证通过后替换 models 目录里的模型")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        raise SystemExit(f"目录不存在: {src}")
    gguf = Path(args.out) if args.out else MODELS / f"{src.name}-{args.quant.upper()}.gguf"
    total = 5

    step(1, total, "校验源目录")
    check_src(src)

    step(2, total, "修正 EOS / chat_template")
    fix_config(src)

    step(3, total, f"转换为 GGUF ({args.quant})")
    t = time.perf_counter()
    convert(src, gguf, args.quant)
    size = gguf.stat().st_size / 1024**3
    log(f"  产物: {gguf}  {size:.2f} GB  ({(time.perf_counter() - t):.1f}s)")

    step(4, total, "启动服务实测")
    ok = True
    if args.skip_verify:
        log("  已跳过")
    else:
        try:
            res = verify(gguf)
            for tag, content, stop, dt, ntok in res["cases"]:
                log(f"  [{tag}] stop={stop} {dt:.0f}ms {ntok}tok")
                log(f"        {content}")
                if stop != "eos" or not content:
                    ok = False
        except SystemExit as e:
            log(f"  验证失败: {e}")
            ok = False

    step(5, total, "部署" if args.deploy else "完成")
    if args.deploy and ok:
        deploy(gguf)
    elif args.deploy:
        log("  验证未通过，不部署")

    log("")
    log(f"结果: {'PASS' if ok else 'FAIL'}   {gguf}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
