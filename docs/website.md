# AgenticFinBench research website

This GitLab release contains the current 18-configuration, 230-question website source. The separately hosted GitHub site is not updated by a GitLab-only push.

The static HTML/CSS/JavaScript site in `site/` includes the manuscript leaderboard, dataset distribution, construction process, evaluation framework, five findings with original paper figures, and a searchable question/rubric explorer. It has no model calls, backend, tracking, or API-key requirements.

## Build and preview

```bash
python3 scripts/build_site.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory public
```

The build validates frozen dataset hashes, all 230 question/rubric bindings, the 18-configuration paper leaderboard against saved manuscript rows, figure hashes, and static HTML asset links. Output is `public/`, ignored by Git. Rubrics load per question rather than downloading the entire rubric file on first visit. Paths are relative so the site works below `/AgenticFinBench/`.

## Evidence and content

- `site/paper-results.json`: the October 30, 2026 manuscript snapshot, 18 configurations and 230 common questions; quality Q, confidence intervals, baseline B, differences, and claim/response hallucination diagnostics. Values preserve the precision of the paper tables.
- `docs/paper-snapshot/`: the source table rows for quality, auditing, dataset statistics, and category counts.
- `site/paper-sources.json`: SHA256 records for the source rows and the original figure PDFs.
- `site/assets/figures/`: original manuscript PDFs and high-resolution PNG renders. The Evaluation Framework section uses the current manuscript evaluation overview. Click a figure to enlarge it or open the PDF for full resolution.
- `data/`: frozen question and rubric exports. Question wording and rubric items are preserved; complexity levels come from the frozen cohort manifest.

Language counts are 189 Chinese / 41 English. Batch composition is 44 seed / 146 expansion / 40 English-batch questions. Complexity counts are 10 / 70 / 86 / 64. These are distinct classifications. The release includes 5,817 positive and 1,780 negative rubric items.

The public runner and manuscript diagnostics have protocol differences described in the README. The website reports manuscript results, without claiming a new public-runner rerun or including the unpublished complete answer/trace corpus. No paid evaluations were started during publication.

## GitLab publication

Push to the GitLab default branch after offline validation. `site-build` creates the static artifact; GitLab Pages deployment remains conditional on instance setup and `PUBLISH_GITLAB_PAGES=true`. A source push alone does not establish a live Pages deployment. The GitHub remote and its live site are outside this release.

The build replaces its generated `public/` directory before exporting, so removed questions cannot remain accessible through stale per-question rubric files. Only 230 questions and their matching rubrics are packaged. The old source pool and historical results JSON are absent from the current tree; earlier Git commits are not rewritten.

## Design and verification

The research-page progression is inspired by [FinSearchComp](https://randomtutu.github.io/FinSearchComp/), with independently written code and text and original AgenticFinBench figures. Warm neutral surfaces and muted purple follow NashNova's branding.

Verify desktop and mobile navigation, three leaderboard sorts, image dialog and Escape close, task search and empty state, source-batch filtering, positive/negative rubric tabs, downloads, and the absence of horizontal page overflow. Model results and figures must be updated together with their source hashes; do not substitute the legacy leaderboard or silently mix denominators.
