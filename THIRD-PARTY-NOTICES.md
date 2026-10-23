# 第三方组件与许可证声明

本项目采用 **GPL-3.0**（见 [LICENSE](LICENSE)）。之所以如此，是因为界面依赖
`PySide6-Fluent-Widgets`，其许可证为 **GPLv3**，构成衍生作品后必须整体以 GPLv3 发布。

以下清单由各组件实际安装的元数据（`importlib.metadata`）核对得出。

## 一、打包进发行版（必须遵守）

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| [PySide6](https://pypi.org/project/PySide6/) | 6.12.0 | LGPL-3.0 / GPL-2.0 / GPL-3.0（三选一） | Qt 的 Python 绑定，界面基础 |
| [PySide6-Fluent-Widgets](https://pypi.org/project/PySide6-Fluent-Widgets/) | 1.11.3 | **GPLv3** | Fluent 风格控件（本项目的许可约束来源） |
| [PySideSix-Frameless-Window](https://pypi.org/project/PySideSix-Frameless-Window/) | 0.8.2 | LGPLv3 | 无边框窗口基类 |
| [onnxruntime](https://pypi.org/project/onnxruntime/) | 1.31.0 | MIT | OCR 推理引擎 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | 3.10.0 | Apache-2.0 | OCR 封装 + PP-OCR 模型 |
| [mss](https://pypi.org/project/mss/) | 10.2.0 | MIT | 屏幕抓取 |
| [keyboard](https://pypi.org/project/keyboard/) | 0.13.5 | MIT | 全局热键（Windows 低级键盘钩子） |
| [pyperclip](https://pypi.org/project/pyperclip/) | 1.11.0 | BSD | 剪贴板 |
| [Pillow](https://pypi.org/project/pillow/) | 13.0.0 | MIT-CMU (HPND) | 图像处理 |
| [numpy](https://pypi.org/project/numpy/) | 2.5.4 | BSD-3-Clause（及 0BSD/MIT/Zlib/CC0 等） | 数值计算 |
| [httpx](https://pypi.org/project/httpx/) | 0.28.1 | BSD-3-Clause | 本地 HTTP 调用 |
| [safetensors](https://pypi.org/project/safetensors/) | 0.8.0 | Apache-2.0 | 模型权重读写（转换脚本用） |
| [darkdetect](https://pypi.org/project/darkdetect/) | 0.8.0 | BSD-3-Clause | 系统深浅色检测 |
| [pywin32](https://pypi.org/project/pywin32/) | 312 | PSF | Windows API（无边框窗口依赖） |

## 二、外部程序（不打包，需自行准备）

| 组件 | 许可证 | 说明 |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp)（`llama-server.exe`） | MIT | 本地推理后端，以独立进程调用，**不随本仓库分发** |
| CUDA 运行库（cudart / cuBLAS） | NVIDIA 许可 | 由 llama.cpp 官方构建包提供，不随本仓库分发 |

## 三、模型权重（不含在本仓库中）

本项目**不包含、也不分发任何模型权重**。使用前请自行获取：

| 模型 | 许可 | 说明 |
|---|---|---|
| 翻译模型（Hunyuan v1 dense 1.8B 系） | **腾讯混元社区许可（Tencent Hunyuan Community License）** | 需遵守原始发布页条款；请勿将权重提交到本仓库 |
| OCR 模型（PP-OCRv6 / PP-OCRv5） | Apache-2.0 | 由 RapidOCR 按需下载 |

> 说明：`models/`、`runtime/`、`*.gguf` 已在 `.gitignore` 中排除，
> 使用者需要按 [README](README.md) 的「模型准备」一节自行放置。

## 四、GPLv3 对你意味着什么

- **自己用 / 内部用**：不受影响。
- **分发本程序的二进制（exe）**：必须同时以 GPLv3 提供完整对应源码（本仓库即为对应源码），
  并向接收者附上 [LICENSE](LICENSE)。
- **想闭源分发**：需要向 `PySide6-Fluent-Widgets` 作者购买商业授权，
  或改用非 GPL 的替代界面方案（如 qt-material / 自绘 QSS）。
