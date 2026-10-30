<div align="center">

# AgenticFinBench

### Benchmarking Financial Agents on Diverse Tasks from Real-World Requests

**NashNova Research**

**230 real-world tasks · 8 categories · 2 languages · 4 complexity levels**

[**Website source**](site/) · [Dataset](data/questions.json) · [Rubrics](data/rubrics.json) · [Quick start](#quick-start) · [中文指南](README.zh-CN.md)

</div>

---

AgenticFinBench evaluates financial agents on diverse, open-ended requests drawn from real-world use. It combines **question-specific rubrics** with **claim-level evidence auditing** to assess how well a response addresses a task and whether its factual claims hold up. Audit evidence informs a final quality score; evidence attribution and factual reliability remain available as separate diagnostics.

This repository releases the frozen 230-task dataset, positive and negative rubrics, and a standalone evaluation pipeline. Supply your agent's answers and optional execution traces to run claim extraction, evidence verification, and rubric-based scoring.

## Why AgenticFinBench?

- **Real financial work.** Tasks cover knowledge Q&A, data and calculation, screening, comparison, investment research, financial analysis, event analysis, and investment planning.
- **Beyond a single reference answer.** Question-specific criteria assess task completion and analytical quality for requests with multiple defensible answers.
- **Evidence-informed scores.** Factual claims are checked against execution traces and, when needed, external sources or calculations. Confirmed errors are assessed for their impact on the response.
- **Reproducible inputs.** Frozen questions and rubrics are bound to file hashes. Runs save manifests, intermediate judgments, evidence, and completion status.

The accompanying manuscript studies 18 agent configurations and examines how factual errors, agent harnesses, and financial tools affect performance. This repository does not yet include the manuscript's complete collection of model responses, execution traces, or per-claim audit judgments.

## What is included

- [`data/questions.json`](data/questions.json): **230 frozen questions**, retaining their original IDs and wording.
- [`data/rubrics.json`](data/rubrics.json): question-specific standards with **5,817 positive criteria** and **1,780 negative criteria**.
- [`data/manifest.json`](data/manifest.json): dataset version, cohort source hash, file hashes, and distribution counts.
- [`data/cohort230.json`](data/cohort230.json): exact question membership, question hashes and complexity levels (10/70/86/64). Language counts are 189 Chinese and 41 English; source batches are 44 seed, 146 expansion and 40 English-batch questions.
- [`benchmark/`](benchmark/), [`fincarat/`](fincarat/), and [`prompts/`](prompts/): evaluation runner, claim extraction, audit instructions, and scoring rules.
- [`examples/one-answer.jsonl`](examples/one-answer.jsonl): a synthetic example for checking the workflow.
- [`site/`](site/): a static leaderboard and question/rubric explorer; see the [website guide](docs/website.md).

**Release scope.** This release matches the current manuscript: **18 configurations × 230 questions = 4,140 frozen responses**. The leaderboard is exported from the paper tables, with source hashes and original figures. The current tree and website downloads contain only the fixed 230-question cohort; the previous source pool and historical leaderboard have been removed. Earlier Git commits remain historical records. The runner does not consume the leaderboard or reproduce historical manual adjudications.

## Evaluation workflow

1. **Submit answers.** Generate responses with your own model or agent. Bind each answer and optional original tool trace to a frozen question ID.
2. **Extract factual claims.** Preserve entities, time periods, units, and context in independently auditable claims.
3. **Audit evidence.** One isolated agent session per question examines the claims, complete answer, and original trace, with external verification when needed.
4. **Score quality.** A judge assesses positive and negative criteria together with audit evidence. Deterministic code computes the quality score and independently checks the arithmetic.

### Interpreting the outputs

**Quality (0–100)** is the primary score. Positive criteria are binary and their weights sum to 100. Explicitly triggered negative criteria and confirmed factual errors can reduce the score. Scoring deduplicates penalties for the same root cause, accounts for points already lost, and applies a cap when an essential calculation or conclusion fails.

**Evidence diagnostics** retain trace support, factual support, contradiction, and unresolved claims. The public v3 runner also reports legacy combined support using an OR rule: support from either axis is sufficient. This is not factual accuracy. An external contradiction is retained even when the trace supports the claim, and the quality judge reviews its effect. Unverified claims are not automatically factual errors.

A legacy *policy pass rate* is reported separately, treating unresolved, unsupported claims as passing. It is not a hallucination-free rate and does not exempt confirmed factual errors from quality scoring. These runner diagnostics should not be substituted for the manuscript's audit-outcome definitions.

## Quick start

**Requirements:** Linux x86_64, Python 3.11+ with `venv`, Node.js 22+, npm, curl, and flock. On macOS or Windows, use a Linux VM or WSL2. The bootstrap installs Python dependencies, the official DSH CLI, and a SHA256-verified PRoot binary. Docker and sudo are not required.

```bash
git clone https://gitlab.cmcf.io/backend/public-benchmark.git
cd public-benchmark
cp .env.example .env
# Set IKUNCODE_DEEPSEEK_API_KEY in .env to your own API key.
./run.sh --answers examples/one-answer.jsonl --out results/demo
```

This example evaluates **one synthetic answer** and makes paid API calls. It is a workflow example, not a model's benchmark result. To evaluate your own answer file:

```bash
./run.sh --answers answers.jsonl --out results/my-agent
```

Start with `--limit 1` or select a question with `--ids prod100-001`. Repeating the same command verifies the inputs and configuration, then reuses successful stages. Use a new output directory when inputs or configuration change.

To validate inputs without evaluation calls:

```bash
./run.sh --answers answers.jsonl --out results/check --check
```

`--check` may still install dependencies, but does not call evaluation models. Setup and evaluation need network access to the configured gateway, npm, and GitHub.

### Answer format

Use JSONL with one answer per line, or a JSON array:

```json
{"id":"prod100-001","answer":"Your agent's complete answer...","trace_file":"traces/prod100-001.json","answer_generated_at":"2026-10-16T10:00:00Z"}
```

- `id` must match a unique ID in `data/questions.json`; duplicates are rejected.
- `answer` is the complete response. If provided, `question` must exactly match the frozen wording.
- `trace_file` is optional and resolves relative to the answer file. Alternatively, provide a `trace` JSON object or array. Include original tool calls and results, rather than the agent's description of its actions.
- Without a trace, external verification still runs and the trace axis records incompleteness.
- `answer_generated_at` supplies context; it does not add an unstated date requirement to a question.

### Configuration and bounded execution

The shipped [`config.json`](config.json) uses `https://api.ikuncode.cc/v1`, `deepseek-v4.1-flash` for extraction and quality judgments, and `deepseek-v4-flash` with high reasoning for v3 audits via `@deepseek-ai/dsh@0.1.5-rc.1`. These are this standalone release's settings, not a claim that every paper experiment used the same configuration.

Each stage defaults to 40 concurrent questions. Extraction and quality judgments allow at most three attempts; extraction permits up to 12 continuation rounds per attempt. Each v3 question uses one session with a 25-minute deadline and stops external evidence collection at minute 19. Failures remain visible and bounded; do not run an unbounded retry loop.

Each audit has a private file view and `/tmp`; the project `.env`, other questions, and host `/proc` are not mounted. PRoot provides tool file isolation, not a security boundary against malicious code. Subagents are disabled.

The [Chinese guide](README.zh-CN.md) documents response-model aliases, recovery of compatible complete extraction responses, and detailed scoring rules.

## Results and reproducibility

Each run writes:

- `scores.csv`: per-question quality scores, claim counts, evidence support, factual contradiction, unresolved counts, and policy pass rates.
- `summary.json`: question results, mean quality score, and completed/failed counts. `final=true` requires every selected question to finish.
- `progress.json`: stage progress and failure reasons.
- `cases/<id>/`: extracted claims, audit and quality judgments, raw responses, and attempt records.
- `manifest.json`: hashes of questions, answers, traces, rubrics, code, prompts, configuration, and dependency versions; no API key.

The quality mean uses completed questions. Evidence and contradiction rates pool their claims. Failed questions are not assigned perfect scores. Subset results must report their selected denominator and must not be described as full 230-question scores.

The original single-question [validation record](docs/canary-validation.json) reports 11 claims, a completed audit, and quality 83.33. Resuming added no model requests. The initial run required recovery from a model-alias mismatch and a second quality-judgment attempt. This validates the workflow, not semantic correctness or completion of all 230 questions.

### Offline development checks

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m benchmark --answers examples/one-answer.jsonl --out results/check --check
python3 scripts/build_site.py
```

The website build produces `public/` locally. GitLab CI validates and packages it; Pages deployment depends on instance configuration. This release is pushed only to GitLab. See the [website guide](docs/website.md).

## Project links

- **GitLab repository:** [backend/public-benchmark](https://gitlab.cmcf.io/backend/public-benchmark)
- **Chinese guide:** [README.zh-CN.md](README.zh-CN.md)

The manuscript is titled **AgenticFinBench: Benchmarking Financial Agents on Diverse Tasks from Real-World Requests**, by **NashNova Research**. A public paper URL and formal citation will be added when available.

`.env`, local runtimes, submitted answers, and evaluation outputs are ignored by Git. Keep credentials and private traces out of commits. Review generated run records before sharing them.

Cost coordinates for fourteen configurations use recorded-token averages on the 230 questions. Kimi, Trae and DuMate retain original run-average costs; WorkBuddy retains its visible-text estimate. No new generation or evaluation was performed for this release.
