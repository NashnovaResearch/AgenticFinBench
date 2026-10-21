# AgenticFinBench：一键质量与事实核验评测

[展示网站 ↗](https://nashnovaresearch.github.io/AgenticFinBench/) · [English](README.md) · [GitHub](https://github.com/NashnovaResearch/AgenticFinBench)

AgenticFinBench 是论文 **AgenticFinBench: Benchmarking Financial Agents on Diverse Tasks from Real-World Requests** 的题集与评测代码发布仓库，由 **NashNova Research** 维护。论文覆盖500道真实金融任务、8类任务、2种语言及4个复杂度层级，以逐题 rubric 与事实主张核验共同形成质量评分。

本仓此前使用 Finance 500 名称；冻结数据的版本标识和哈希保持原样。展示网站使用 `site/paper-results.json` 中从当前论文表格导出的11组配置、共同500题结果，并附原始论文图表和来源哈希。`site/results.json` 保留2026年10月16日的12组历史配置快照，不用于新版网站榜单。本仓尚未包含论文全部模型回答、执行 Trace 和逐原子判决。

展示页源码位于 [`site/`](site/)，提供模型榜单、500 题搜索和正负项 rubric 浏览。构建与 GitLab Pages 发布方法见 [展示页文档](docs/website.md)。网站发布需要实例启用 Pages；仓库地址本身不是展示页地址。

500道金融题、逐题正负项 rubric，以及原子抽取 → v3 证据核验 → 质量评分的完整流水线。提供模型的回答文件，配置一个 key，执行一个命令即可看到逐题分数与平均分。不依赖内部网站、历史评测目录或 Codex 账号。

## 快速开始

运行环境：**Linux x86_64、Python 3.11+（含 venv）、Node.js 22+、npm、curl、flock**。macOS/Windows 请在 Linux VM/WSL2 中运行。首次命令自动安装 Python 依赖、官方 DSH CLI 与校验过 SHA256 的 PRoot；无需 Docker 或 sudo。需可访问 npm、GitHub 与模型网关。

```bash
cp .env.example .env
# 编辑 .env，填入 IKUNCODE_DEEPSEEK_API_KEY=你自己的key
./run.sh --answers examples/one-answer.jsonl --out results/demo
```

上面只评1题，包含真实模型调用，会产生 API 费用。示例回答为人工编写的流程样例，无原始 Trace，并非某个模型的历史成绩。自己的500题回答：

```bash
./run.sh --answers answers.jsonl --out results/my-model
```

再次执行同一命令会校验输入与版本，并复用成功阶段。逐题完成抽取后立即进入 v3，v3完成后立即评分，不等待整批结束。默认各阶段40题并发；修改 `config.json` 可分别调整。第一次运行建议 `--limit 1`，或用 `--ids prod100-001` 指定一题。输入或配置变动请使用新输出目录。

只校验、不调用模型：

```bash
./run.sh --answers answers.jsonl --out results/check --check
```

`--check` 仍会安装运行依赖，但不会产生评测调用。失败有界保留，不会无限计费。抽取/质量各最多3个 attempt；抽取每 attempt 最多12轮续抽，截断正文不会算成功。v3每题一次会话，最多25分钟，第19分钟停止外部取证。达到上限时退出码为1；检查输出里的失败原因和已有原始响应，勿盲目循环命令。若抽取已返回完整正文，只是传输/校验适配失败，可在新目录用 `--recover-from results/旧跑次` 离线恢复兼容的完整抽取响应，再进入后续阶段；输入、模型、网关和抽取 prompt 不一致会拒绝恢复。

## 回答文件

JSONL每行一题，也接受 JSON 数组。`id` 必须来自 `data/questions.json`，不能重复；`answer` 为完整回答。可选 `question` 如提供必须与冻结题面完全一致。

```json
{"id":"prod100-001","answer":"模型的完整回答……","trace_file":"traces/prod100-001.json","answer_generated_at":"2026-10-16T10:00:00Z"}
```

`trace_file` 相对回答文件目录解析，也可直接使用 `trace` JSON 对象/数组。应提供完整原始工具调用及返回，不要只放模型自述。未提供 Trace 时仍做外部事实核验，Trace轴为 incomplete，不伪造工具证据；报告会保留这一局限。时间字段只用于解释回答背景，不向原题添加隐藏时点要求。回答生成由参评模型或 Agent 自行完成，本包评测提交的回答，不替用户选择或运行答题产品。

## 输出

终端逐题显示质量分；每30秒显示完成数和实际活跃并发。输出目录包含：

- `scores.csv`：逐题质量分、原子数、证据支持率、事实反驳率、未核实数和政策通过率。
- `summary.json`：逐题结果与质量算术平均分，附完成分母、失败数；仅全部选定题完成时 `final=true`。不足500题明确标注选定数量，不能称为500题最终成绩。
- `progress.json`：每阶段完成与活跃数、逐题状态和失败原因。
- `cases/<id>/extract.json`、`audit.json`、`quality.json`：原子、两轴判定、正负项逐项判定/证据/确定性计分。
- `cases/<id>/<stage>/attempt-*`：完整模型流、请求、失败、DSH会话和证据。成功阶段写入哈希回执，防止输入变更后错误复用。
- `manifest.json`：题面/回答/Trace、rubric、代码、prompt、参数和依赖版本绑定，不保存 key。

平均质量分为已完成题的逐题平均；证据/反驳比例采用已完成题的原子总数加权。没有事实原子时该题比例为 null。失败题不假装成功、不补质量满分，也不会纳入完成均分。

## 评分含义

**质量（0–100）**：全部冻结正向项满足/不满足，权重总和100；负向项明确触发才扣分。同根因取最大罚分，已因同一错误丢失的正向分抵扣重复罚分，再应用封顶。程序计分，并用独立 Decimal 计算复核。

抽取和质量请求显式使用 `thinking.type=disabled` 并流式保存正文与用量；空正文/截断不会误判成功。ikuncode 当前可能把 DS4.1 的响应模型名写作通用别名 `deepseek/deepseek-flash`，`config.json` 显式记录可接受别名，原始请求模型与响应别名均留档；别名不是对网关实际底层模型的独立验证。

质量评委为 `deepseek-v4.1-flash`，一次请求读取完整题目、回答、全套正负项、v3已有证据，直接返回结构化判定，不逐项调用，也不需要人工 Codex 修正。输出格式/完整性失败才有界修复。评委判断有波动，不能把结构验证视为语义正确性保证。

通用事实影响规则与全部题共用，见 `prompts/quality.txt`：

1. **Trace支持不能跳过事实反驳**：全部事实轴 contradicted 都要检查抽取对齐、反驳证据和答案语境。未核实不等于错误。
2. **错误影响依赖链**：先匹配原负向项，未覆盖的独立事实错误按旁支3分、实质12分、核心25分处理；核心必要计算/结论失效封顶60。按独立纠正单元去重，保留未受影响的分析。
3. **完整条件与严重度约束**：检查答案内部矛盾、替代满足路径；只有实际使用的决策阈值才做反事实，必须绑定源文、数值与分类翻转，不能编造门槛升档。相关主题本身不足以升级严重度。

**v3证据轴**：官方 `@deepseek-ai/dsh@0.1.5-rc.1`，默认 `deepseek-v4-flash` + high；每题一个 Agent 会话读取全部冻结原子、回答与 Trace，必要时搜索正文或计算。禁用 subagent；每题私有文件视图和 `/tmp`，不挂载项目 `.env`、其他题或宿主 `/proc`。PRoot用于工具文件隔离，不是针对恶意代码的安全容器。

保留两个底层标签：Trace支持与事实支持/反驳/未决。综合证据支持采用 OR（任一supported即supported），所以“证据支持率”不叫“事实正确率”。另外单独输出事实反驳率，即使Trace支持也计入事实反驳。保留历史政策通过率：综合未支持但事实未决按通过计分；这个数不代表无幻觉。质量评分不会用该默认通过政策豁免明确事实错误。这里没有把质量与证据随意加权成第三个“总分”。

## 数据与版本

`data/questions.json` 为当前500题（380道原有题、120道英文题），保留原题号与题面；`data/rubrics.json` 为对应冻结正负项，共12,786正向项、3,856负向项。题型不同，项数不同，不重新生成标准。导出移除了内部 Trace 地址等溯源字段。

`data/manifest.json` 保存来源 CSV SHA256、导出文件哈希及题面哈希异常清单。源 CSV 的 `prod386-260` 自带哈希与正文不符，导出按原文复算并记录，不修改题面。运行前严格检查全部500题唯一ID、题面/rubric一致性、权重和链接。

本发布版本 `public-full-pipeline-v1` 使用冻结题库与通用评分规则，提供独立可运行评测；评测运行器不读取历史逐模型人工复核、历史分数或离线修正结果，也不承诺逐分复现榜单。展示页的 `site/results.json` 仅用于展示已冻结成绩，与运行器输入分离。

## 单题验收

已用 `examples/one-answer.jsonl` 完成真实调用验证：11条原子、v3完成、质量83.33分；同命令续跑未新增模型请求。初次发现网关模型返回别名差异后，恢复了已有抽取正文；质量结构校验在第2次判定通过。详见 [验收记录](docs/canary-validation.json)。这是流程验证，不代表500题完成或评分语义已经无误。

## 开发验证

```bash
.venv/bin/python -m unittest discover -s tests -v
```

`.env`、`.runtime`、`.venv`、回答文件与 `results/` 默认忽略。不要提交 key、真实用户 Trace 或运行日志。模型请求/回复完整保存在本机结果目录，发布结果前自行审阅其中的业务数据。
