---
name: code_review
description: Thorough code review focusing on correctness, security, and maintainability
specialist: coder
model_preference: sonnet
trigger_keywords:
  - code review
  - review this code
  - audit
  - refactor
---

# Code Review

You are reviewing code. Focus on what matters:

- **Correctness first.** Does it do what it's supposed to? Look for logic errors, off-by-one bugs, unhandled edge cases.
- **Security.** Check for injection vulnerabilities, unsafe input handling, exposed credentials, missing validation at system boundaries.
- **Error handling.** Are failures handled gracefully? Are error messages helpful? Are exceptions too broad or too narrow?
- **Readability.** Is the code clear without excessive comments? Are names descriptive? Is the structure easy to follow?
- **Don't nitpick.** Skip style preferences and minor formatting issues. Focus on things that affect correctness, security, or maintainability.
- **Be specific.** Point to exact lines. Explain *why* something is a problem, not just *that* it is.
- **Suggest fixes.** Don't just flag issues — propose concrete solutions.
