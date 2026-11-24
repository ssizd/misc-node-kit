"""A lazy switch that also suppresses output nodes on the inactive branch."""

import nodes as comfy_nodes
from comfy_api.latest import io
from server import PromptServer

from .exclusive_output_prune import prune_prompt


MISSING = object()
NODE_ID = "WildcardExclusiveOutputSwitch"


def _is_output_node(class_type):
    node_class = comfy_nodes.NODE_CLASS_MAPPINGS.get(class_type)
    if node_class is None:
        return False
    if getattr(node_class, "OUTPUT_NODE", False) or getattr(node_class, "_OUTPUT_NODE", False):
        return True
    get_schema = getattr(node_class, "GET_SCHEMA", None)
    return bool(get_schema and get_schema().is_output_node)


def _on_prompt(json_data):
    prompt = json_data.get("prompt")
    if isinstance(prompt, dict):
        prune_prompt(prompt, _is_output_node, NODE_ID)
    return json_data


class ExclusiveOutputSwitch(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        template = io.MatchType.Template("exclusive_switch")
        return io.Schema(
            node_id=NODE_ID,
            display_name="Exclusive Output Switch (한쪽만 실행)",
            category="Wildcard Image Iterator/logic",
            description=(
                "선택하지 않은 분기의 Save, Preview, Sampler 같은 Output 노드를 큐에서 제외합니다. "
                "각 분기의 마지막 결과를 연결하고, 최종 Save는 이 노드의 output에 연결하세요."
            ),
            search_aliases=["exclusive switch", "output switch", "one branch", "한쪽만 실행"],
            inputs=[
                io.Boolean.Input(
                    "switch",
                    default=False,
                    tooltip="False: on_false만 실행, True: on_true만 실행. 이 위젯에서 직접 선택하세요.",
                ),
                io.MatchType.Input("on_false", template=template, lazy=True, optional=True),
                io.MatchType.Input("on_true", template=template, lazy=True, optional=True),
            ],
            outputs=[io.MatchType.Output(template=template, display_name="output")],
        )

    @classmethod
    def check_lazy_status(cls, switch, on_false=MISSING, on_true=MISSING):
        if switch and on_true is None:
            return ["on_true"]
        if not switch and on_false is None:
            return ["on_false"]

    @classmethod
    def validate_inputs(cls, switch, on_false=MISSING, on_true=MISSING):
        selected = on_true if switch else on_false
        if selected is MISSING:
            return "선택한 분기가 연결되지 않았습니다."
        return True

    @classmethod
    def execute(cls, switch, on_false=MISSING, on_true=MISSING):
        selected = on_true if switch else on_false
        return io.NodeOutput(None if selected is MISSING else selected)


server = PromptServer.instance
if not getattr(server, "_wildcard_exclusive_output_switch", False):
    server.add_on_prompt_handler(_on_prompt)
    server._wildcard_exclusive_output_switch = True


NODE_CLASS_MAPPINGS = {NODE_ID: ExclusiveOutputSwitch}
NODE_DISPLAY_NAME_MAPPINGS = {NODE_ID: "Exclusive Output Switch (한쪽만 실행)"}
