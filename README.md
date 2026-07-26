<h1 align="center">PageWhisper</h1>
<p align="center"><b>PDF 中英对照翻译 · AI 智能体识别正文 / 表格 / 图例</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/Engine-OpenAI%20Compatible%20%2F%20Google-ff69b4.svg" alt="Engine">
  <img src="https://img.shields.io/badge/Desktop-Windows%20.exe-brightgreen.svg" alt="Desktop exe">
</p>

<p align="center">上传英文论文 PDF，AI 智能体自动识别正文、表格、图例，输出<strong>重新排版的中英对照</strong> HTML 与 PDF。</p>

---

## ✨ 特性（Features）

- **中英对照，而非纯中文**：每段原文（灰）+ 中文译文（黑）逐段对照，便于核验。
- **AI 智能体抽取**：`智能抽取` 模式调用 LLM 识别正文 / 表格 / 图例 / 元数据，自适应不同期刊排版，告别"套正则"的脆弱方案。
- **图片原位嵌入**：图表按原文相对位置插入（置于首次引用 `Fig. N` 的段落之前），图文一一对应。
- **图例双语**：Figure Legend 同时输出英文与中文。
- **表格保真**：表格以 `<table>` 重建，保留数据单元格，仅翻译表头与标题。
- **两种翻译模式**：
  - **标准翻译（pipeline）**：抽文 → 分批翻译 → 排版，快、省 Token。
  - **AI Agent 智能翻译（one-shot）**：全文交给 LLM 一次性产出高质量双语 HTML（需 API Key）。
- **零成本预览**：无 Key 时自动回退 Google 翻译，开箱即用。
- **参考文献可开关**：默认保留英文以省 Token，可勾选翻译。
- **一键导出**：浏览器打印为 PDF，或下载 HTML；服务端亦可用 reportlab 生成 PDF。
- **桌面版**：可一键打包为单文件 `PageWhisper.exe`（PyInstaller），绿色免安装、双击即用，亦可在 GitHub Releases 获取预编译版。

---

## 📊 Benchmark（性能实测 / 高亮）

> ### 🚀 用 **DeepSeek v4 flash** 翻译一篇 2025 年发表于 *Science* 的论文，全文耗时约 **4 分 30 秒**，Token 费用约 **¥0.1（官网价）**。
>
> | 项目 | 内容 |
> | --- | --- |
> | 论文 | *Osteoarthritis treatment via the GLP-1–mediated gut-joint axis targets intestinal FXR signaling* |
> | 期刊 / 年份 | **Science**, 2025 |
> | 模式 | 标准翻译（pipeline）+ 智能抽取 |
> | 引擎 | DeepSeek (`deepseek-v4-flash`，OpenAI 兼容端点) |
> | 耗时 | **≈ 4 分 30 秒** |
> | Token 费用 | **≈ ¥0.10**（按 DeepSeek 官网价格估算） |
>
> 结论：一篇顶级期刊长文的全文中英对照翻译，成本可压到**一角钱**级别——几乎可视为"免费"的文献精读助手。

---

## 🏗️ 架构（Architecture）

```
            ┌─────────────── 浏览器 (static/index.html) ───────────────┐
            │   选择 PDF / 模式 / 引擎 / Key → 轮询进度                │
            └───────────────────────┬──────────────────────────────────┘
                                     │  POST /api/translate
                                     ▼
   ┌──────────────────── FastAPI (app.py) ────────────────────┐
   │                                                           │
   │  抽取层         翻译层                排版层              │
   │  pdf_extract    translator            html_builder       │
   │  smart_extract  (Google / LLM)        (HTML + reportlab   │
   │  translate_paper  ▲ one-shot         PDF)                │
   │                  │                                       │
   └──────────────────┼───────────────────────────────────────┘
                      │ OpenAI 兼容 /v1/chat/completions
                      ▼
              DeepSeek / OpenAI / 本地模型 …
```

**模块职责**

| 文件 | 职责 |
| --- | --- |
| `app.py` | FastAPI 服务：接收 PDF、调度任务、轮询进度、产出 HTML/PDF |
| `pdf_extract.py` | 基于 PyMuPDF 抽取文本/图片，过滤页眉页脚，识别图例 |
| `smart_extract.py` | LLM 智能体抽取：识别正文/表格/图例/元数据，适应不同排版 |
| `translate_paper.py` | one-shot 模式：单次 LLM 调用产出完整双语 HTML |
| `translator.py` | 批量翻译（Google 免 Key / OpenAI 兼容 LLM，多线程） |
| `html_builder.py` | 由结构化文档 + 译文构建 HTML，并用 reportlab 生成 PDF |
| `static/` | 前端 UI（原生 HTML/CSS/JS，无框架依赖） |

---

## 🚀 快速开始（Quick Start）

### 方式一：桌面版（预编译 .exe，推荐 ⭐ 零安装）

不想配置环境？直接下载双击即用，最适合大多数用户：

1. 到仓库 [Releases](https://github.com/hydra-hydra/PageWhisper/releases) 下载 `PageWhisper.exe`；
2. **双击运行**，自动打开浏览器至 <http://127.0.0.1:8000>；
3. 关闭窗口即退出；翻译产物临时存放在系统临时目录（`pagewhisper_output`）。

> 单文件、绿色免安装（约 150 MB），无需 Python、无需联网配置。

### 方式二：本地运行（Python 3.11+，适合开发 / 自托管）

**前置条件**：Python 3.11+

```bash
# 1. 克隆仓库
git clone https://github.com/hydra-hydra/PageWhisper.git
cd PageWhisper

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 一键启动（自动打开浏览器）
python run.py
# 或等价地：
# uvicorn app:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。

### 方式三：Docker（推荐服务器 / 干净环境）

```bash
docker compose up --build
# 访问 http://localhost:8000
```

### 方式四：自行打包为桌面软件（PyInstaller）

把整个应用封装成单文件可执行程序（`.exe`），免安装、双击即运行：

```bash
pip install pyinstaller
pyinstaller pagewhisper.spec
# 产物：dist/PageWhisper.exe —— 双击启动本地服务并自动打开浏览器
```

> 💡 **已内置打包配置**：仓库根目录的 `pagewhisper.spec` 已配好 `static` 数据绑定与全部隐藏依赖，
> 直接用上面的命令即可生成 `dist/PageWhisper.exe`（约 150 MB，单文件、绿色免安装）。

> 维护者发布二进制的命令：
> ```bash
> pyinstaller pagewhisper.spec --noconfirm
> gh release upload vX.Y.Z dist/PageWhisper.exe
> ```

---

## 🔧 配置（Configuration）

网页端设置项：

| 设置 | 说明 |
| --- | --- |
| 翻译模式 | 标准翻译（pipeline）/ AI Agent 智能翻译（one-shot） |
| 翻译引擎 | 自动（有 Key 用 LLM，无 Key 用 Google）/ Google / LLM |
| API Key | OpenAI 兼容服务的 Key（Google 模式留空） |
| Base URL | 如 `https://api.deepseek.com`（默认 `https://api.openai.com/v1`） |
| 模型 | 如 `deepseek-v4-flash` |
| 中英对照 | 保留原文逐段对照（默认开启） |
| 智能抽取 | LLM 识别正文/图例/元数据（需 Key，适应不同期刊） |
| 翻译参考文献 | 默认关闭以省 Token |

环境变量（可选，覆盖默认值）：`HOST`、`PORT`。

---

## 📡 API 文档（API）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/translate` | 表单：`file, engine, api_key, base_url, model, translate_refs, keep_original, smart_mode, translate_mode` → `{job_id}` |
| `GET` | `/api/status/{job_id}` | 轮询：`{stage, percent, elapsed, token_info, stats, view_url}` |
| `GET` | `/api/download/{job_id}` | 下载 HTML 结果 |
| `GET`/`POST` | `/api/pdf/{job_id}` | 生成并返回 PDF |

---

## 🧩 工作原理（How it works）

1. **抽取**：PyMuPDF 以 `get_text("dict")` 提取文本块与图片；启发式过滤页眉/页脚/期刊名；字体大小相对正文字号判定标题层级；支持 `.B` / `-Bold` / `Bold` 等多种粗体命名。
2. **智能抽取（可选）**：将段落交给 LLM 分类为 正文 / 标题 / 图例 / 表格 / 元数据，并用图像包围盒过滤图内标签（如 `Gapdh 37`），避免污染译文。
3. **翻译**：
   - pipeline 模式：合并段落为少量批次，多线程并发调用 Google 或 LLM；参考文献默认不译。
   - one-shot 模式：LLM 一次性输出带 `<!-- FIG_N -->` 标记的双语 HTML，服务端替换为 `<figure>`。
4. **排版**：HTML 重建为双语段落、原位插图、双语图例、保真表格；reportlab 进一步生成 PDF。

---

## 📁 项目结构（Project Structure）

```
PageWhisper/
├── app.py                # FastAPI 服务入口
├── pdf_extract.py        # PyMuPDF 抽取（标准模式）
├── smart_extract.py      # LLM 智能体抽取
├── translate_paper.py    # one-shot LLM 双语 HTML
├── translator.py         # 批量翻译（Google / LLM）
├── html_builder.py       # HTML + PDF 排版
├── static/               # 前端 UI（index.html / style.css / app.js）
├── run.py                # 一键启动器（自动开浏览器）
├── pagewhisper.spec      # PyInstaller 打包配置
├── Dockerfile            # 容器镜像
├── docker-compose.yml    # 容器编排
├── requirements.txt      # 依赖
├── LICENSE               # MIT
└── README.md
```

---

## 🗺️ 路线图（Roadmap）

- [ ] 批量 PDF 队列与并发
- [ ] 术语表（glossary）可视化编辑
- [ ] 更多导出格式（Word / EPUB）
- [ ] 插件式抽取后端（arXiv / 出版社 API）

---

## 📄 许可证（License）

[MIT](LICENSE) © 2026 hydra-hydra

---

## 🙏 致谢（Acknowledgements）

- 翻译能力由 [DeepSeek](https://www.deepseek.com/) / OpenAI 兼容端点 / Google 翻译 提供。
- PDF 解析基于 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)。
- PDF 生成基于 [ReportLab](https://www.reportlab.com/)。

---

<p align="center">PageWhisper · 让英文文献阅读成本降到一角钱级别</p>
