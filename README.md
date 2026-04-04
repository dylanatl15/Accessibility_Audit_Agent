# Accessibility Audit Agent

An OmniAgents-based assistant for auditing and improving accessibility across websites and local documents.

This agent is designed for higher-ed compliance workflows and is aligned to the DOJ ADA Title II web/mobile app rule baseline (WCAG 2.1 AA), while still supporting best-practice guidance.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install Node dependencies for the browser scanner
npm install

# Install Playwright browser
npx playwright install chromium

# Configure your environment
cp .env.example .env
# Edit .env and add your API key
```

Python 3.10–3.12 is recommended for browser automation tooling.

## Run

```bash
# Web UI (opens browser)
omniagents run -c agent.yml

# Terminal UI
omniagents run -c agent.yml --mode ink

# API server (for programmatic access)
omniagents run -c agent.yml --mode server --port 9494
```

## What It Can Do

- Crawl and scan websites with Playwright + axe-core (`run_accessibility_audit`).
- Crawl and scan multiple sites and write a combined JSON report (`run_multisite_accessibility_audit`).
- Scan local documents for accessibility issues (`scan_documents_accessibility`).
- Propose and apply certain automated document fixes (`propose_document_fixes`, `apply_document_fixes`).
- Extract images from DOCX/PPTX and generate alt text with vision (`extract_document_images`, `read_image`, `apply_document_alt_text`).

## Compliance Reference

- DOJ Title II web/mobile rule summary: `docs/ADA_Title_II_Web_and_Mobile_App_Rule_Requirements.md`
- WCAG 2.1 AA requirements checklist: `docs/WCAG_2_1_AA_Requirements.md`
- Project improvement plan: `docs/Agent_Improvements_TODO_for_UTRGV_Compliance.md`

## Project Structure

```
Accessibility_Audit_Agent/
├── agent.yml
├── instructions.md
├── tools/
│   ├── accessibility_audit.py
│   ├── document_accessibility.py
│   ├── image_alt_text.py
│   └── ...
├── docs/
│   ├── ADA_Title_II_Web_and_Mobile_App_Rule_Requirements.md
│   └── Agent_Improvements_TODO_for_UTRGV_Compliance.md
├── .env.example
├── requirements.txt
└── package.json
```
