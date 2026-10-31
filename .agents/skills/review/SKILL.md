---
name: review
description: Pre-landing code review to analyze diffs for regressions, security, performance, and style.
triggers:
  - review
  - code review
  - review this pr
  - check my diff
---

# Code Review Skill

When invoked, analyze git changes or proposed changes systematically:

1. **Bug & Regression Check**: Inspect logic paths, null/None handling, async/sync boundary mismatches, and race conditions.
2. **Security & Data Safety**: Check for SQL injections, unsafe string interpolations, exposed secrets, and unhandled network errors.
3. **Performance & Rate Limiting**: Check delays, connection pooling, resource cleanups (e.g. closing browser contexts/sessions), and memory efficiency.
4. **Output Format**:
   - Provide a concise summary table with: Severity (High / Medium / Low), File/Location, Issue Description, and Recommended Fix.
