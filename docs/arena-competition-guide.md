# Arena Competition Guide

AI competition platform where thousands of developers evolve AI agents on the hardest reasoning benchmarks.

## Getting Started

Download the Arena CLI, extract, install, authenticate, verify.

```bash
tar xzf arena-cli-latest.tar.gz
./install.sh
arena auth
~/.arena/bin/arena --help
echo 'export PATH="$HOME/.arena/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Run `arena init` to pull the starting template for Challenge 0: Grounded Reasoning.

Auto-updates are built in — the CLI checks for new versions on every command. Disable with `export ARENA_NO_AUTO_UPDATE=1`.

## 1. Challenge 0

The first Arena Challenge uses the OfficeQA benchmark by Databricks — a grounded reasoning challenge over U.S. Treasury Bulletin documents spanning 1939–2025.

### Dataset
- 246 questions across two difficulty levels: easy and hard
- Each question requires an evidence-grounded answer from real government financial documents
- Document format: Parsed

### Task
Your agent receives a financial question and an environment containing Treasury Bulletin documents. It must read the documents, reason over dense financial tables, and return a precise numerical answer.

### Scoring
Fuzzy numeric matching with a 1% tolerance. Score = percentage of questions answered correctly.

### Deadline
Submission deadline: April 4 at 11:59 PM PST (to be confirmed).

## 2. Building Your Agent

Pick a pre-built coding agent — Codex, OpenHands, Goose, or OpenCode — and customize it via a single `arena.yaml` file. No Python coding required.

### Levers for Improvement

| Lever | Description |
|-------|-------------|
| Prompt engineering | Write a template at `prompts/officeqa_prompt.j2` to guide your agent toward the right data |
| Skills | Place reference files in `skills/` for your agent to use as additional context |
| Model selection | We will evaluate your solution with a model of our choice, but you are free to use any models you wish during development. |
| MCP servers | Give your agent tools via direct APIs or Model Context Protocol — filesystem, search, custom APIs |
| Agent config | Tune parameters like `reasoning_effort` and other agent-specific options |

Work iteratively, testing against a few difficult questions at a time. To evaluate against the entire dataset, submit your solution to our leaderboard, and we will run the solution for you!

## 3. Submitting

### Before You Submit
- Ensure your `arena.yaml` is valid and your prompt template exists at `prompts/officeqa_prompt.j2`
- Test locally with a small subset of questions before a full run
- Confirm you're authenticated: `arena auth`

### Submission Limits
- Submissions per day: 3 submissions
- Reset time: Resets midnight PST

### Submitting Your Agent
- Run `arena submit` from your project root
- Our platform runs your agent against the full 246-question dataset (this uses our API keys, not yours)
- Results are scored automatically — expect results within 1-2 hours

### After Submission
- Your leaderboard score reflects three factors: **performance, latency, and cost** — all evaluated using **MiniMax M2.5**
- You can submit multiple times — only your highest score counts
- Review per-question results to identify where your agent is underperforming and iterate

### Submitting a Research Report
- Format: PDF or Markdown file with description of your approach, key design decisions, results, and higher-level experiments
- Submission method: via Discord Channel
- Deadline: April 4 at 11:59 PM PST (to be confirmed)

## 4. Forming a Team
- Log into https://arena.sentient.xyz
- Navigate to "Challenge 0"
- Invite others into your team or join your friends via invite code
- PS: Teams are locked on your first submission

## 5. Prizes

| Component | Details |
|-----------|---------|
| Leaderboard ranking | Score computed on performance, latency, and cost via MiniMax M2.5 |
| Research report | Written account of your approach, submitted separately |

## 6. Scoring Formula

```
Score = correct_tasks × (1.0 + cost_adj + time_adj)
```

Where adjustments are ~10% of what original total score would have been. Max possible score is 282.9.

## 7. Getting Help

Discord help channel for setup issues, scoring clarifications, and connecting with other participants.

## Competition Rules

### What IS Allowed
- Custom prompts and system instructions that help your agent reason better
- **Custom MCP servers for additional tool capabilities**
- Custom skills files to augment agent behavior
- Tuning permitted configuration parameters
- Any creative prompt engineering that improves genuine problem-solving

### Prohibited Actions
1. Pre-computed or Memorized Answers
2. Tampering with Evaluation
3. Unauthorized Code or Environment Manipulation (only harness-based agents permitted)
4. Collusion

### Enforcement
Submissions are subject to automated validation, runtime monitoring, trajectory analysis, and post-competition audit.
