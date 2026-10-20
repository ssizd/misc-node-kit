from .helper_action_character_sets import build_action_character_sets, build_combiner_inputs


class ActionCharacterWildcardSets:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action_list": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "character_list": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "CHARACTER_SET_LISTS")
    RETURN_NAMES = ("marked_action_list", "character_sets")
    FUNCTION = "build"
    CATEGORY = "prompt/wildcard"

    def build(self, action_list, character_list="", **kwargs):
        entries = build_action_character_sets(action_list, character_list)
        marked_action_list, slot_lists = build_combiner_inputs(action_list, character_list)
        character_sets = {
            "slot_lists": slot_lists,
            "max_girls": entries[0]["max_girls"],
        }
        return (marked_action_list, character_sets)


NODE_CLASS_MAPPINGS = {"ActionCharacterWildcardSets": ActionCharacterWildcardSets}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ActionCharacterWildcardSets": "Action + Character Wildcard Sets"
}
