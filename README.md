<div align="center">

# LocalTranslator · 本地屏幕翻译

由大肥鱼（harness）构建，功能测试正常。

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-3776ab)

</div>

---

<!-- TODO(作者补充): 这里写项目的由来 / 一句话亮点 / 演示 GIF。README 其余部分同样可自由增删 -->

## 功能特性

| 功能 | 说明 |
|---|---|
| **框选翻译** | `Alt+Q` 框选屏幕任意区域 → OCR → 本地模型翻译，结果留在应用内（不会弹窗打断你） |
| **实时翻译** | `Alt+R` 框选一块区域后弹出独立浮窗，内容变化时自动重新翻译；支持暂停 `Alt+P`、退出 `Alt+W` |
| **上一段对照** | 实时浮窗里同时显示「最新译文」与灰色小字的「上一段」，滚动字幕也能接上下文 |
| **文本翻译** | 应用内直接粘贴文字翻译，`Ctrl+Enter` 触发 |
| **六语互译** | 中文 / 英文 / 日语 / 俄语 / 西班牙语 / 法语，任意两种互译，源语种自动识别 |
| **可调外观** | 浮窗字号 12–32、遮罩透明度 25–95%、窗口自由缩放（最小 340×200），全部自动记忆 |

## 系统要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 10（2004+）/ Windows 11，x64 |
| 显卡 | NVIDIA 显卡，显存 **≥ 4GB** 建议 |
| 驱动 | NVIDIA 驱动 ≥ 580（支持 CUDA 13.x） |

## 快速开始

### 方式一：使用打包好的发行版

1. 下载/解压发行包，得到 `LocalTranslator\` 文件夹
2. 双击 `LocalTranslator.exe`
3. 首次启动会自动拉起内置推理服务（约 8–10 秒），右上角状态变为「服务就绪」
4. 按 `Alt+Q` 框选翻译，或 `Alt+R` 开启实时翻译

## 模型准备

**本仓库不包含任何模型权重**
运行前需要在程序目录下自行准备模型，可在huggingface下载：

```
LocalTranslator\
  models\    ← 放置翻译模型 *.gguf（如 mt-1.8b-*-Q5_K_M.gguf）
```

## 项目结构

```
LocalTranslator/
├─ app/                 应用源码
│  ├─ main.py           入口
│  ├─ ui_main.py        Fluent 界面（截图页 / 文本页）
│  ├─ live.py           实时翻译引擎 + 浮窗（含暂停、上一段、缩放）
│  ├─ overlay.py        全屏定格框选层
│  ├─ capture.py        mss 抓屏
│  ├─ ocr.py            RapidOCR 封装（六语 OCR、引擎缓存、预热）
│  ├─ layout.py         碎行 → 段落合并
│  ├─ translate.py      调用本地 llama-server 翻译
│  ├─ langs.py          语种表 / 语种检测 / OCR 模型映射
│  ├─ paths.py          路径解析（源码运行 & 打包运行）
│  ├─ server.py         推理服务生命周期管理
│  ├─ settings.py       设置持久化（settings.json）
│  ├─ selftest.py / uitest.py / livetest.py   自动化测试
├─ scripts/             模型转换 / 对比 / 基准测试等开发脚本
├─ build/               打包脚本与图标
├─ requirements.txt
├─ LICENSE              GPL-3.0
└─ THIRD-PARTY-NOTICES.md
```

## 已知限制

- 只抓主显示器（多屏暂不支持）
- 双栏版面会按行合并，可能串行
- 视频字幕为「白字描边 + 复杂背景」时 OCR 偶尔认不出（浮窗会提示「未识别到文字」）
- 小语种翻译质量不均衡（1.8B 模型的固有能力上限）
- 实时翻译在画面持续快速变化时约有 0.5–1 秒延迟

## 许可证

本项目以 **GNU General Public License v3.0** 发布，全文见 [LICENSE](LICENSE)。

之所以是 GPL-3.0：界面依赖的 `PySide6-Fluent-Widgets` 为 GPLv3，
按 GPL 的传染性，整体作品必须以 GPLv3 发布。

- **个人/内部使用**：无额外义务
- **分发二进制**：需同时提供对应源码（本仓库）并附带 LICENSE
- **闭源商业分发**：需向相关组件作者取得商业授权，或替换为宽松许可的界面方案

第三方组件的完整清单与许可，见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 致谢

- [llama.cpp](https://github.com/ggml-org/llama.cpp) — 本地推理
- [RapidOCR](https://github.com/RapidAI/RapidOCR) / [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — OCR
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) — 界面控件
- Tencent Hunyuan — 翻译模型
