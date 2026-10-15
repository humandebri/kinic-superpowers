# Read-only freshness requires manual CLI assembly

First-time agent baseline: 3 rounds, 8 shell commands including documentation reads.

Agent request:

> I wished this read-only command existed:

`python3 scripts/kinic-workflow.py --config CONFIG --cli CLI --allow-non-ii-identity check spec`

> It should compare the remote revision with the baseline and report local dirtiness without modifying the working copy or snapshots.

Scope: add check API/command, keeping status local-only. Specification and task sequence approved by the human on 2026-10-15; exact wiki source revisions recorded in progress. Closed-loop validation uses the same read-only freshness scenario before and after implementation.
