# -*- coding: utf-8 -*-
"""翻译层：调用本地 llama-server 的 /completion 接口。

关键约束（实测得出，别改）：
  1. 必须用 <｜hy_User｜>...<｜hy_Assistant｜> 包裹，裸文本会被模型判为无需回答
  2. EOS 已是 120020，服务端会自己停；仍额外传 stop 做双保险
  3. 逐段翻译，保持段落顺序一对一
  4. 提示词必须用"严格模板"（这段话 + 只输出译文 + 换行）：
     实测模型对宽松写法（"把这句话翻译成…："）鲁棒性差，会原样返回原文
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import langs

U = "<\uff5chy_User\uff5c>"
A = "<\uff5chy_Assistant\uff5c>"
EOS_TEXT = "<\uff5chy_place\u2581holder\u2581no\u25812\uff5c>"
EOT_TEXT = "<\uff5chy_EOT\uff5c>"


class TranslateError(RuntimeError):
    pass


def _post(base: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/completion",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def health(base: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def translate(
    text: str,
    target: str = "en",
    base: str = "http://127.0.0.1:8080",
    timeout: float = 180.0,
) -> str:
    """target 用语种 code（zh/en/ja/ru/es/fr）。"""
    text = text.strip()
    if not text:
        return ""

    target = langs.normalize_target(target) or "en"
    n_predict = min(512, max(64, int(len(text) * 2.2) + 48))
    payload = {
        "prompt": f"{U}把下面这段话翻译成{langs.label(target)}，只输出译文，不要任何解释：\n{text}{A}",
        "n_predict": n_predict,
        "temperature": 0.0,
        "top_k": 1,
        "repeat_penalty": 1.05,
        "stop": [EOS_TEXT, EOT_TEXT],
        "stream": False,
    }
    try:
        out = _post(base, payload, timeout)
    except urllib.error.URLError as e:
        raise TranslateError(
            f"连不上本地推理服务 {base}。请确认 runtime 目录存在或先运行 serve.ps1（{e.reason}）"
        ) from e
    except Exception as e:  # noqa: BLE001
        raise TranslateError(f"翻译请求失败: {e}") from e

    content = (out.get("content") or "").strip()
    for marker in (EOS_TEXT, EOT_TEXT):
        if marker in content:
            content = content.split(marker)[0].strip()
    return content


def translate_paragraphs(
    paragraphs: list[str],
    target: str | None = None,
    base: str = "http://127.0.0.1:8080",
    timeout: float = 180.0,
) -> list[dict]:
    """返回 [{src, dst, src_lang, tgt_lang}]，段落顺序一一对应。"""
    if not paragraphs:
        return []
    if not health(base):
        raise TranslateError(
            f"本地推理服务 {base} 未响应。请先启动：E:\\Sheeran\\scripts\\serve.ps1"
        )
    fixed_target = langs.normalize_target(target)
    results: list[dict] = []
    for para in paragraphs:
        src_lang = langs.detect(para)
        tgt = fixed_target or langs.choose_target(src_lang)
        results.append(
            {
                "src": para,
                "dst": translate(para, tgt, base, timeout=timeout),
                "src_lang": src_lang,
                "tgt_lang": tgt,
            }
        )
    return results
