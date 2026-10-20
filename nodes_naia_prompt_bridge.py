"""Stable prompt injection point for NAIA-generated ComfyUI requests."""


class NAIAPromptBridge:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": False}),
                "positive": ("STRING", {"default": "", "multiline": True}),
                "negative": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "original_positive": ("STRING", {"forceInput": True}),
                "original_negative": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("final_positive", "final_negative", "enabled")
    FUNCTION = "emit_prompts"
    CATEGORY = "prompt/string"

    def emit_prompts(
        self,
        enabled,
        positive,
        negative,
        original_positive="",
        original_negative="",
    ):
        if enabled:
            final_positive = positive
            final_negative = negative
        else:
            final_positive = original_positive
            final_negative = original_negative
        return (str(final_positive or ""), str(final_negative or ""), bool(enabled))


NODE_CLASS_MAPPINGS = {"NAIAPromptBridge": NAIAPromptBridge}
NODE_DISPLAY_NAME_MAPPINGS = {"NAIAPromptBridge": "NAIA Prompt Bridge"}
