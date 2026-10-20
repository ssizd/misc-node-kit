# Wildcard Image Iterator Engineering Rules

These rules apply to every change in this custom node.

## Definition of Done

- Do not report a fix as complete from code inspection alone.
- Reproduce the reported workflow before changing behavior whenever the current
  files and runtime make reproduction possible.
- Inspect the installed ComfyUI frontend/backend implementation for behavior
  that depends on serialization, cloning, widgets, execution, or validation.
- Run `powershell -ExecutionPolicy Bypass -File .\tests\verify.ps1` from this
  directory after every code change.
- Add or update a regression test for every fixed bug when it can be automated.
- If the live ComfyUI server is available, verify the actual user interaction.
  If it is unavailable, state that live UI verification was not performed.

## Stateful Frontend Nodes

For nodes that store profiles, rules, dynamic widgets, or other UI state, test
all relevant lifecycle paths before reporting completion:

1. Edit a value and serialize the workflow immediately.
2. Duplicate the node using ComfyUI's clone path.
3. Copy and paste the node using ComfyUI's clipboard path.
4. Save and reload the workflow.
5. Reload the browser frontend.

Clipboard and duplicate tests must follow the installed ComfyUI implementation,
not an assumed LiteGraph lifecycle. Serialized workflow/node payloads are the
authoritative state. Local storage is only a recovery fallback and must never
override an explicit configure or clipboard payload.

## Compatibility

- Preserve existing input/output order, widget order, names, and serialized
  formats unless the requested change requires a migration.
- When adding or moving a widget, include migration handling for existing
  workflows.
- Do not remove or rename existing nodes used by saved workflows unless the user
  explicitly requests it.

