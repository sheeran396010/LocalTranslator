# -*- coding: utf-8 -*-
"""修正 HF 目录里的 tokenizer_config.json：
   - eos/bos/pad 指向真实的混元特殊 token（原来的 placeholder 映射是坏的）
   - 补上 chat_template（原文件缺失，导致 GGUF 没有模板）
   - tokenizer_class 改成 transformers 能识别的类名
"""
import json
from pathlib import Path

D = Path(r"E:\Ai\models\mt-1.8b-hf")
p = D / "tokenizer_config.json"

cfg = json.loads(p.read_text(encoding="utf-8"))
print("修正前:", {k: cfg.get(k) for k in ("bos_token", "eos_token", "pad_token", "tokenizer_class")})

cfg["bos_token"] = "<\uff5chy_begin\u2581of\u2581sentence\uff5c>"
cfg["eos_token"] = "<\uff5chy_end\u2581of\u2581sentence\uff5c>"
cfg["pad_token"] = "<\uff5chy_\u2581pad\u2581\uff5c>"
cfg["unk_token"] = None if "unk_token" not in cfg else cfg["unk_token"]
cfg["tokenizer_class"] = "PreTrainedTokenizerFast"
cfg["clean_up_tokenization_spaces"] = False
cfg["model_max_length"] = 262144
cfg.pop("backend", None)
cfg.pop("is_local", None)
cfg.pop("local_files_only", None)

# 混元对话模板：User/Assistant 包裹，助手回合以 <|hy_EOT|> 结束
cfg["chat_template"] = (
    "{% for message in messages %}"
    "{% if message['role'] == 'user' %}"
    "{{ '<\uff5chy_User\uff5c>' + message['content'] }}"
    "{% elif message['role'] == 'assistant' %}"
    "{{ '<\uff5chy_Assistant\uff5c>' + message['content'] + '<\uff5chy_EOT\uff5c>' }}"
    "{% elif message['role'] == 'system' %}"
    "{{ '' }}"
    "{% endif %}"
    "{% endfor %}"
    "{% if add_generation_prompt %}{{ '<\uff5chy_Assistant\uff5c>' }}{% endif %}"
)

p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("修正后:", {k: cfg.get(k) for k in ("bos_token", "eos_token", "pad_token", "tokenizer_class")})
print("chat_template 长度:", len(cfg["chat_template"]))
