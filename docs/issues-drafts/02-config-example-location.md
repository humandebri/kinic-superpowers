# Configuration example location is ambiguous

Fresh agent after the check-command addition:

> cat: /Volumes/KINGSTON/KINIC/kinic-superpowers/docs/kinic/kinic-workflow.example.json: No such file or directory

> I inferred the example lived beside the README, then successfully read it from the repository root.

Fix: link the example from docs/kinic/README.md with the explicit relative path
`../../kinic-workflow.example.json`. The file already exists at that target.
