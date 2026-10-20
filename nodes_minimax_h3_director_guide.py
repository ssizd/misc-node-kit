"""Thin Director adapter for ComfyUI's native MiniMax H3 nodes."""

from .helper_minimax_h3_director import normalize_guide


def _native_node(name):
    """Resolve at execution so installed ComfyUI updates are used automatically."""
    try:
        from comfy_extras import nodes_minimax_h3
        return getattr(nodes_minimax_h3, name)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"MiniMax H3 Director requires ComfyUI's native {name} node. "
            "Update ComfyUI to a version that includes MiniMax H3 support."
        ) from exc

class MiniMaxH3DirectorGuide:
    """Turn one Director guide socket into the exact native MiniMax H3 call."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "guide": ("MINIMAX_H3_DIRECTOR_GUIDE",),
            },
            "optional": {"audio_vae": ("VAE",)},
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "latent")
    FUNCTION = "apply"
    CATEGORY = "image/animation/MiniMax H3"

    def apply(self, clip, vae, guide, audio_vae=None):
        state = normalize_guide(guide)
        if state.mode in {"T2VA", "I2VA", "FL2VA", "L2VA"}:
            native = _native_node("MiniMaxH3ImageToVideo")
            positive, latent = native.execute(
                clip, vae, state.resolved_prompt, state.width, state.height, state.length,
                state.first_frame, state.last_frame,
            )
            return positive, latent

        if audio_vae is None:
            raise ValueError("audio_vae is required for REF2VA")
        native = _native_node("MiniMaxH3ReferenceToVideo")
        positive, latent = native.execute(
            clip, vae, audio_vae, state.resolved_prompt, state.width, state.height, state.length,
            state.ref_image_size, state.ref_images, state.ref_videos,
            state.ref_video_audios, state.ref_audios,
        )
        return positive, latent


NODE_CLASS_MAPPINGS = {"WildcardMiniMaxH3DirectorGuide": MiniMaxH3DirectorGuide}
NODE_DISPLAY_NAME_MAPPINGS = {"WildcardMiniMaxH3DirectorGuide": "Wildcard MiniMax H3 Director Guide"}
