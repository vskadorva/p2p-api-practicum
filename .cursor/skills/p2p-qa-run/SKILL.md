---
name: p2p-qa-run
description: Runs the P2P QA agent — the explorer, then the adversary, then the judge — and shows the report. Use when the user asks to run the QA agent, test the P2P API on its own, run the challenge, or check the business rules end to end against a running API.
---

# P2P QA run

Orchestrates the three challenge subagents in order. **Fix nothing, write no tests, file no bugs** — those are separate steps a human starts.

## Base URL

Default `http://localhost:8000`. If the user names another host/port or `PORT` is set in the environment, use that base URL for health, reset, and in every subagent prompt.

## Steps

1. **GET `<base URL>/health`**, and if it's down tell the user to run `npm start` and **stop**.
2. **Empty `qa-run/`** (it holds run output only) — remove contents, keep the directory.
3. **POST `/admin/reset`** on the base URL (log success or failure; continue only if reset succeeds or docs allow proceeding).
4. Run the **p2p-explorer** subagent with the base URL and **wait** for it to finish.
5. Run the **p2p-adversary** subagent and **wait**.
6. Run the **p2p-judge** subagent.
7. **Show** the happy path status, the rule table, and the path to `qa-run/report.json`.

## Subagent prompts

Pass the base URL explicitly in each Task prompt, e.g. `Base URL: http://localhost:8000`. Do not run explorer and adversary in parallel — adversary may reset data; order is fixed.

| Step | Subagent | Deliverables |
| --- | --- | --- |
| 4 | `p2p-explorer` | `qa-run/steps.jsonl` |
| 5 | `p2p-adversary` | `qa-run/attack-plan.md`, `qa-run/attacks.jsonl` |
| 6 | `p2p-judge` | `qa-run/report.json` |

If a subagent stops early (API down, missing logs), still run the judge so `report.json` explains what is missing; then report the failure to the user.

## Present results

After the judge finishes:

1. Read `qa-run/report.json`.
2. State **`happy_path.status`** (`PASS` or `FAIL`); if `FAIL`, name the failing step(s) from `happy_path.steps`.
3. Reproduce the judge’s markdown table — one row per `adversarial` entry: **rule**, **status** (`HELD` / `BREACHED`), **evidence** (one line: status + key field or amount).
4. Give the full path to **`qa-run/report.json`** and paste or summarize **`summary`** when the user needs narrative (money at risk, open questions, not confirmed breaches).

## Out of scope

- Do not read or change `src/`, tests, or docs.
- Do not fix API defects, add Playwright tests, or open issues unless the user asks in a **separate** request.

## Reference

- Challenge shape and goals: `CHALLENGE.md`
- Subagent behavior: `.cursor/agents/p2p-explorer.md`, `p2p-adversary.md`, `p2p-judge.md`
