# AGENTS.md — Antigravity & Gemini Agent Architecture

This file configures guidelines, skills, and model behavior for **Gemini models** operating in **Google Antigravity IDE**.

---

## 🚀 Gemini Model Behavior Overlays

When using Gemini models (e.g. Gemini 3.7 Flash, Gemini 2.5 Pro):
1. **Bias Toward Action**: Execute actions and commands directly using available tools (`run_command`, `replace_file_content`, `view_file`, `browser_subagent`) rather than narrating what will be done.
2. **Structured & High-Density Outputs**: Use tables, diffs, concise bullet points, and code blocks. Avoid conversational filler or redundant preamble.
3. **Exploit Large Context**: Process full test runs, large HTML dumps, and multiple scraper outputs in a single pass.
4. **Tool Mapping**:
   - Shell commands: Use Antigravity `run_command` (PowerShell on Windows).
   - Code Inspection & Editing: Use `view_file`, `replace_file_content`, and `multi_replace_file_content`.
   - Browser & Scraper verification: Use Antigravity `browser_subagent` or Scrapling Python fetchers.
   - User Input: Use `ask_question` tool.

---

## 🛠️ gstack Workflow Integration

The agent recognizes and executes all standard **gstack** slash commands and engineering workflows:

### 1. Product & Architecture
- **/office-hours**: YC-style office hours interrogation. Asks 6 forcing questions (demand reality, status quo, desperate specificity, narrowest wedge, observation, future-fit) to refine features before writing code.
- **/plan-ceo-review**: Challenges scope, cuts complexity, and validates customer value.
- **/plan-eng-review**: Rigorous architectural review, locking schemas, edge cases, failure modes, and performance bottlenecks.
- **/autoplan**: End-to-end plan generation, task breakdown, and execution.

### 2. Code Quality & Security
- **/review**: Pre-landing code review analyzing diffs for regressions, trust boundaries, SQL injection risks, and side effects.
- **/cso**: Chief Security Officer audit covering OWASP Top 10, STRIDE threat models, secret leak checks, and credential handling.
- **/devex-review**: Checks ergonomics, CLI clarity, error messages, and documentation quality.

### 3. Browser & QA Testing
- **/qa**: Autonomous end-to-end user flow testing in the browser.
- **/browse**: Headless browser automation, DOM inspection, and state verification.
- **/scrape**: Fast data extraction from target URLs using Scrapling / HTTP / browser engines.

### 4. Shipping
- **/ship**: Prepares changes, runs test suites, verifies diffs, and creates pull requests / git commits.

---

## 🕷️ Web Scraping Architecture (Scrapling)

For web scraping and price tracking across Amazon, Flipkart, Myntra, and Ajio:
- Prefer **Scrapling** (`scrapling.fetchers.Fetcher`, `StealthyFetcher`, `DynamicFetcher`).
- Use **Browser Impersonation** (`impersonate="chrome"`) on `Fetcher` to bypass TLS fingerprinting.
- Use **`StealthyFetcher`** for JS-rendered or bot-protected sites (Cloudflare Turnstile, Kasada).
- Use **Adaptive Selectors** (`adaptive=True`, `auto_save=True`) so selector changes do not break the scraper.
