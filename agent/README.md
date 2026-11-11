# Agent Orchestrator (`agent/`)

This directory coordinates the Goal, Plan, Act, Approve, Log agentic cycle.

## Cycle Stages
1. **Goal**: The student specifies a learning or exam target (e.g., "Exam in 10 days").
2. **Plan**: The language model selects relevant tools.
3. **Act**: Code executes tool functions; runs jury debate if requested.
4. **Approve**: An interactive approval gate pauses execution if an action is marked confirmation-required.
5. **Log**: Every action, tool argument, execution duration, and approval verdict is stored in SQLite.

## Files
- `orchestrator.py`: Implements `run_agent(system_prompt, tools, task, max_iterations, user_context)` with iteration caps, timeout limits, and error handling.
- `dispatcher.py`: Maps tool calls to functions, enforcing human-in-the-loop approvals for sensitive tools.
- `jury.py`: Coordinates the 6-agent jury debate (Round 1 answers, Round 2 blind reviews, weighted synthesis).

## What to Edit
- To adjust the maximum execution iterations or timeout defaults, edit `agent/orchestrator.py`.
- To register new tools or change approval requirements, edit `agent/dispatcher.py`.
