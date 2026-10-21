# AgenticFinBench research website

Live site: https://nashnovaresearch.github.io/AgenticFinBench/

The static HTML/CSS/JavaScript site in `site/` includes the manuscript leaderboard, dataset distribution, construction process, evaluation framework, five findings with original paper figures, and a searchable question/rubric explorer. It has no model calls, backend, tracking, or API-key requirements.

## Build and preview

```bash
python3 scripts/build_site.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory public
```

The build validates frozen dataset hashes, all 500 question/rubric bindings, the 11-configuration paper leaderboard against saved manuscript rows, figure hashes, and static HTML asset links. Output is `public/`, ignored by Git. Rubrics load per question rather than downloading the entire rubric file on first visit. Paths are relative so the site works below `/AgenticFinBench/`.

## Evidence and content

- `site/paper-results.json`: the October 21, 2026 manuscript snapshot, 11 configurations and 500 common questions; quality Q, confidence intervals, baseline R, differences, and claim/response hallucination diagnostics. Values preserve the precision of the paper tables.
- `docs/paper-snapshot/`: the source table rows for quality, auditing, dataset statistics, and category counts.
- `site/paper-sources.json`: SHA256 records for the source rows and the original figure PDFs.
- `site/assets/figures/`: original manuscript PDFs and 2,200-pixel PNG renders. Click a figure to enlarge it or open the PDF for full resolution.
- `site/results.json`: the earlier October 16 snapshot of 12 configurations and 5,998 scores. Retained for provenance; **not used by the current leaderboard**.
- `data/`: frozen question and rubric exports. No relabeling or edits to these inputs were made for the website.

Language counts are 374 Chinese / 126 English. Batch composition is 83 seed / 297 expansion / 120 English-batch questions. These are different classifications. Category and complexity labels await expert validation; the site preserves the manuscript's caveat.

The public runner and manuscript diagnostics have protocol differences described in the README. The website reports manuscript results, without claiming a new public-runner rerun or including the unpublished complete answer/trace corpus. No paid evaluations were started during publication.

## GitHub Pages deployment

`.github/workflows/pages.yml` builds on pull requests and `main` pushes. The deploy job runs only for `main`, using GitHub Pages artifacts and the `github-pages` environment. Repository Pages settings use **GitHub Actions** as the publishing source. Only the deploy job has `pages: write` and `id-token: write`; repository contents are read-only to the workflow.

To publish a change, merge reviewed changes into `main`. Check the Actions run and live website. Manual redeployment is available through `workflow_dispatch`. The repository About website and the README both link to the live Pages URL.

GitLab remains a development mirror. Its existing offline validation, SAST, secret detection, and static build are retained. GitLab Pages deployment stays conditional on instance setup and `PUBLISH_GITLAB_PAGES=true`; the public website is hosted on GitHub Pages.

## Design and verification

The research-page progression is inspired by [FinSearchComp](https://randomtutu.github.io/FinSearchComp/), with independently written code and text and original AgenticFinBench figures. Warm neutral surfaces and muted purple follow NashNova's branding.

Verify desktop and mobile navigation, three leaderboard sorts, image dialog and Escape close, task search and empty state, source-batch filtering, positive/negative rubric tabs, downloads, and the absence of horizontal page overflow. Model results and figures must be updated together with their source hashes; do not substitute the legacy leaderboard or silently mix denominators.
