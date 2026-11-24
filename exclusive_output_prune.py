"""Prompt pruning for an exclusive lazy branch switch."""


def is_link(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def ancestors(prompt, start_id):
    seen = set()
    stack = [str(start_id)]
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in prompt:
            continue
        seen.add(node_id)
        for value in prompt[node_id].get("inputs", {}).values():
            if is_link(value):
                stack.append(str(value[0]))
    return seen


def prune_prompt(prompt, is_output_node, class_type="WildcardExclusiveOutputSwitch"):
    """Detach inactive inputs and remove output roots that would re-run them."""
    gate_ids = [
        str(node_id)
        for node_id, entry in list(prompt.items())
        if entry.get("class_type") == class_type
    ]
    for gate_id in gate_ids:
        gate = prompt.get(gate_id)
        if gate is None:
            continue
        inputs = gate.get("inputs", {})
        switch = inputs.get("switch")
        if type(switch) is not bool:
            continue

        active_name = "on_true" if switch else "on_false"
        inactive_name = "on_false" if switch else "on_true"
        active_link = inputs.get(active_name)
        inactive_link = inputs.get(inactive_name)
        if not is_link(active_link) or not is_link(inactive_link):
            continue

        active_nodes = ancestors(prompt, active_link[0])
        inactive_nodes = ancestors(prompt, inactive_link[0])
        inactive_only = inactive_nodes - active_nodes
        del inputs[inactive_name]

        for node_id, entry in list(prompt.items()):
            if not is_output_node(entry.get("class_type")):
                continue
            dependencies = ancestors(prompt, node_id)
            if gate_id in dependencies:
                continue
            if dependencies & inactive_only:
                del prompt[node_id]

    return prompt
