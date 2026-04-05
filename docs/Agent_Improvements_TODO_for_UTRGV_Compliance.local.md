# Agent Improvements TODO (UTRGV Web + Document Accessibility)

Goal: make this agent a reliable, repeatable pipeline for assessing and improving accessibility across UTRGV web properties and posted documents, aligned to the DOJ Title II rule baseline (WCAG 2.1 AA), while still reporting best-practice findings.

## A. Baseline Alignment (Rule-Focused)
- Make WCAG 2.1 AA the default compliance target in outputs.
- Keep optional “best practice” reporting (e.g., WCAG 2.2 AA, Section 508 mapping, EN 301 549 mapping) but clearly separate it from the legal baseline.
- Add rule-aware language to reports:
  - distinguish “automated findings” vs “manual verification required.”
  - explicitly state that automated scanning is not a legal determination.

## B. Crawl UTRGV Web Properties at Scale
- Add first-class multi-site crawling:
  - accept multiple start URLs/domains and treat them as one program-level audit.
  - [x] support allowlist/denylist rules (paths, subdomains, query params).
- Add sitemap and link-discovery support:
  - [x] optional ingestion of `sitemap.xml` and nested sitemaps.
  - [x] optional seed lists for high-value services pages.
- Add crawl governance controls:
  - [x] max pages per site + overall cap.
  - per-host rate limiting and concurrency controls.
  - deduplication (canonicalization rules, ignore tracking params).
  - robust handling of redirects, localization variants, and session-specific URLs.
- Add authentication workflows:
  - pluggable login profiles for common UTRGV auth flows (SSO) where permissible.
  - ability to audit “public only” vs “authenticated” areas with separate reports.
- Add run persistence:
  - store raw results per run (JSON) with timestamps, site identifiers, and crawl configuration.
  - support diffing two runs (regression detection).

## C. Document Coverage (PDF/DOCX/PPTX) at Web Scale
- When crawling web pages, automatically detect and collect linked documents (PDF/DOCX/PPTX) into a document audit queue.
- Track document provenance:
  - source page URL(s), last modified, content type, and hash.
- Apply rule-aware exception flags (not automatic exemptions):
  - mark “preexisting conventional electronic documents” candidates vs “currently used forms/applications” candidates.
  - mark “archived content area” candidates when URL/path matches archive rules.

## D. Expand Accessibility Checks Beyond Axe (Still Automated)
- Add checks commonly missed or under-specified by axe alone:
  - color contrast edge cases, focus visibility heuristics, form error messaging patterns.
  - page titles and headings consistency across templates.
  - language attributes and obvious reading-order problems.
- Add screenshot capture and DOM snapshot bundling for each violation cluster to help remediation teams.

## E. Manual Verification Workflow (Required for Real Compliance)
- Generate a “manual test checklist” per site/template including:
  - keyboard-only navigation pass.
  - screen reader smoke test steps.
  - focus order, skip links, menus/modals/dialogs.
  - forms: labels, instructions, errors, success confirmation.
  - multimedia: captions, transcripts, audio description where needed.
- Add evidence capture hooks:
  - store screenshots/video clips and notes references alongside findings.

## F. Better Remediation Guidance for Teams
- Group findings by:
  - template/component (nav, header, footer, cards, forms).
  - severity/impact and estimated effort.
- Provide role-specific action items:
  - content editors (alt text, headings, link text).
  - frontend developers (ARIA, keyboard, focus management).
  - platform admins (CMS templates, plugins).

## G. Reporting & Export
- Produce exports suitable for campus workflows:
  - CSV/JSON issue exports for tracking systems.
  - “executive summary” view + “technical appendix” view.
- Add deduping and stable IDs for issues so teams can track fixes across runs.

## H. Operationalization
- Add scheduled runs (e.g., nightly/weekly) with saved configurations.
- Add “quality gates” for launch:
  - fail builds/deploys if new critical issues introduced on key templates.
- Add a central configuration file listing UTRGV properties and crawl settings.

## I. Vendor Mobile Apps (Not in Implementation Scope Right Now)
- Track as a compliance dependency (for governance), but exclude from engineering TODO per current request:
  - Pulse (Brightspace)
  - EAB Navigate

## Suggested Implementation Order
1) Multi-site crawl + persistence + diffing.
2) Document link harvesting + doc scan queue.
3) Reporting upgrades (WCAG 2.1 AA baseline + exports + stable issue IDs).
4) Manual verification checklist generator + evidence capture.
5) Additional automated checks and template clustering.
