# Freshness v2: one read-only command answers the question

Same selected clean-state spec/config and three-round budget as v1. A fresh
agent was forbidden implementation source and earlier attempt reports.

## Result

The agent correctly identified `state: clean`, exit 0 and matching remote/baseline
etags. It used two inspection shell commands and one workflow invocation, plus a
process-output poll. The baseline used eight shell commands including inspection
and tool invocations; the counts are reported separately rather than treating
polling or batched shell calls as equivalent work.

## What worked

> The documented `check spec` command otherwise answered freshness directly without additional inspection.

## Remaining friction and fix

> I inferred the example lived beside the README, then successfully read it from the repository root.

Fixed by linking the actual configuration example explicitly from the setup
guide. A separate live probe tests remote_changed/conflict; this clean-state
usability run alone does not prove those states or automatic plugin startup.

## Deferred

Initial provisioning still requires five wiki nodes and configuration. CLI path
and identity selection remain explicit. Approval validity, evidence durability
and task ownership are still agent responsibilities rather than enforced state
transitions. Those limitations are visible in the protocol and setup guide.
