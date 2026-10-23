#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mlx_dequant.py -- 把 MLX 4bit affine 量化的 safetensors 还原成 HF bf16 权重

为什么需要这一步:
    llama.cpp 的 convert_hf_to_gguf.py 只认标准 HF/transformers 权重。
    而 MLX 的量化的权重长这样（同一个线性层被拆成 3 个张量）:
        model.layers.0.mlp.gate_proj.weight   uint32 [6144, 256]   <-- 每 u32 打包 8 个 4bit
        model.layers.0.mlp.gate_proj.scales   bf16   [6144,  32]
        model.layers.0.mlp.gate_proj.biases   bf16   [6144,  32]
    反量化公式:  w = q * scale + bias      （bias 已经等于 -scale * zero_point）

用法:
    python mlx_dequant.py --src "E:\\Ai\\models\\mt-1.8b-src" --dst "E:\\Ai\\models\\mt-1.8b-hf"

输出:
    <dst>/model.safetensors   bf16，张量名与 HF 一致，可直接喂 convert_hf_to_gguf.py
    <dst>/config.json         已剔除 quantization 段落
    <dst>/tokenizer*.json 等  原样复制
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

BITS = 4
PACK = 32 // BITS          # 每个 uint32 打包 8 个 4bit 值
GROUP_SIZE = 64            # 与 config.json 的 quantization.group_size 一致
ROW_CHUNK = 8192           # 分块反量化，控制峰值内存

SHIFT_MASK_NIBBLES = torch.arange(0, 32, BITS, dtype=torch.int64)


def dequant_tensor(w_q: torch.Tensor, scales: torch.Tensor, biases: torch.Tensor) -> torch.Tensor:
    """uint32[out, in/8] + bf16[out, in/64] -> bf16[out, in]"""
    out_features, packed_cols = w_q.shape
    in_features = packed_cols * PACK
    n_groups = scales.shape[1]

    if in_features != n_groups * GROUP_SIZE:
        raise ValueError(
            f"形状不自洽: in={in_features} groups={n_groups} group_size={GROUP_SIZE}"
        )

    result = torch.empty((out_features, in_features), dtype=torch.bfloat16)

    for start in range(0, out_features, ROW_CHUNK):
        end = min(start + ROW_CHUNK, out_features)

        # uint32 -> int64 再做位运算，避免 uint 位移的类型陷阱
        u = w_q[start:end].to(torch.int64)                       # [rows, packed_cols]
        nib = (u.unsqueeze(-1) >> SHIFT_MASK_NIBBLES) & 0xF       # [rows, packed_cols, 8]
        q = nib.reshape(end - start, in_features).to(torch.float32)

        s = scales[start:end].to(torch.float32).repeat_interleave(GROUP_SIZE, dim=1)
        b = biases[start:end].to(torch.float32).repeat_interleave(GROUP_SIZE, dim=1)

        result[start:end] = (q * s + b).to(torch.bfloat16)

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="含 MLX model.safetensors 的目录")
    ap.add_argument("--dst", required=True, help="输出 HF 目录")
    ap.add_argument("--check-only", action="store_true", help="只做形状/统计检查，不写文件")
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    st_file = src / "model.safetensors"
    if not st_file.is_file():
        print(f"[X] 找不到 {st_file}", file=sys.stderr)
        return 1

    t0 = time.time()
    print(f"[1/4] 载入 {st_file.name} ({st_file.stat().st_size / 1024**3:.2f} GB) ...")
    raw = load_file(str(st_file))
    print(f"      张量总数 = {len(raw)}   ({time.time() - t0:.1f}s)")

    out_state: dict[str, torch.Tensor] = {}
    quantized, plain = 0, 0

    for name in sorted(raw.keys()):
        if name.endswith(".scales") or name.endswith(".biases"):
            continue                                          # 由 .weight 分支消费
        if not name.endswith(".weight"):
            print(f"      [跳过] 非 weight 张量: {name} {tuple(raw[name].shape)}")
            continue

        base = name[: -len(".weight")]
        q_key, s_key, b_key = base + ".weight", base + ".scales", base + ".biases"

        if s_key in raw and b_key in raw:
            t = dequant_tensor(raw[q_key], raw[s_key], raw[b_key])
            quantized += 1
            if quantized <= 3 or "embed_tokens" in name:
                print(f"      [反量化] {name:52s} {tuple(raw[q_key].shape)} -> {tuple(t.shape)}")
        else:
            t = raw[q_key].to(torch.bfloat16)
            plain += 1

        if not torch.isfinite(t).all():
            print(f"[X] {name} 含 NaN/Inf，反量化结果不可信", file=sys.stderr)
            return 2
        out_state[name] = t

    print(f"[2/4] 完成: 反量化 {quantized} 个线性层, 直通 {plain} 个归一化层  ({time.time() - t0:.1f}s)")

    # --- 统计体检（不写文件也能判断是否明显跑偏）---
    probe = "model.norm.weight"
    if probe in out_state:
        p = out_state[probe].float()
        print(f"      {probe}: mean={p.mean():.4f} std={p.std():.4f} (RMSNorm 权重应≈1)")
    for key in ("model.layers.0.self_attn.q_proj.weight", "model.layers.0.mlp.gate_proj.weight"):
        if key in out_state:
            t = out_state[key].float()
            print(f"      {key}: std={t.std():.5f} min={t.min():.4f} max={t.max():.4f}")

    if args.check_only:
        print("[check-only] 不写文件，退出。")
        return 0

    dst.mkdir(parents=True, exist_ok=True)

    # --- 辅助文件 ---
    print("[3/4] 复制 config / tokenizer ...")
    for fn in ("config.json", "tokenizer.json", "tokenizer_config.json",
               "generation_config.json", "special_tokens_map.json", "chat_template.jinja"):
        s = src / fn
        if s.is_file():
            shutil.copy2(s, dst / fn)
            print(f"      copied {fn}")

    # 剔除量化段落，避免下游误判
    cfg_path = dst / "config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for k in ("quantization", "quantization_config"):
            if cfg.pop(k, None) is not None:
                print(f"      config.json: 已移除 '{k}'")
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- 写权重 ---
    print(f"[4/4] 写出 bf16 safetensors ({len(out_state)} 个张量) ...")
    out_file = dst / "model.safetensors"
    save_file(out_state, str(out_file), metadata={"format": "pt"})
    print(f"      完成: {out_file}  ({out_file.stat().st_size / 1024**3:.2f} GB)")
    print(f"总计 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
