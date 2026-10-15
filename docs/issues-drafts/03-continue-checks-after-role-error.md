# One inaccessible artifact suppresses the rest of a batch check

Independent reviewer:

> A failed role prevents remaining roles from being checked.

The exception handler surrounded the entire role loop. A missing first node
returned exit 1 but produced no result for later roles, contrary to the approved
read-each-role/JSON-per-role contract.

The regression test failed with `[] != [('spec', 'error'), ('plan', 'clean')]`.
Fix: validate role selection before transport; within check, emit an explicit
error row with `remote_checked: false`, continue subsequent roles and preserve
exit 1. Pull/push keep their fail-fast behavior. Unknown roles still fail before
transport. All 30 tests pass after the fix.
