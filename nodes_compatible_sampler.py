"""Route Anima to the installed Spectrum sampler and other models to core."""

import logging


logger = logging.getLogger(__name__)


def _diffusion_model(model):
    getter = getattr(model, "get_model_object", None)
    dit = getter("diffusion_model") if callable(getter) else model.model.diffusion_model
    seen = set()
    while getattr(dit, "_orig_mod", None) is not None and id(dit) not in seen:
        seen.add(id(dit))
        dit = dit._orig_mod
    return dit


def _supports_spectrum(dit):
    return any(cls.__name__ == "Anima" for cls in type(dit).__mro__) and hasattr(dit, "final_layer")


class WildcardCompatibleKSampler:
    @classmethod
    def INPUT_TYPES(cls):
        from nodes import KSampler
        required = dict(KSampler.INPUT_TYPES()["required"])
        required.update({
            "backend": (["auto", "standard", "spectrum"], {
                "default": "auto",
                "tooltip": "auto: Anima uses the installed Spectrum sampler when available. MOSS and other models use core KSampler, without Spectrum acceleration. standard: always core. spectrum: require compatible Anima and Spectrum installation.",
            }),
            "refresh_ratio": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01,
                "tooltip": "Anima Spectrum only. -1: window schedule; 0: SEA auto; >0: explicit refresh ratio. Ignored by standard sampling."}),
        })
        return {"required": required}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("latent", "report")
    FUNCTION = "sample"
    CATEGORY = "Wildcard Image Iterator/sampling"
    DESCRIPTION = "Anima: installed Spectrum acceleration. MOSS and other models: official KSampler. The report identifies the actual backend. No Spectrum hooks are installed on MOSS."

    def sample(self, model, seed, steps, cfg, sampler_name, scheduler, positive, negative,
               latent_image, denoise=1.0, backend="auto", refresh_ratio=0.0):
        import nodes
        if backend not in ("auto", "standard", "spectrum"):
            raise ValueError("Unknown sampler backend.")
        dit = _diffusion_model(model)
        compatible = _supports_spectrum(dit)
        spectrum = nodes.NODE_CLASS_MAPPINGS.get("SpectrumKSampler")
        if backend == "spectrum" and not compatible:
            raise ValueError(f"Spectrum backend does not support {type(dit).__name__}. Use auto or standard for MOSS.")
        if backend == "spectrum" and spectrum is None:
            raise ValueError("SpectrumKSampler is not installed or failed to import. Use auto/standard, or install comfyui-spectrum-ksampler.")
        args = dict(model=model, seed=seed, steps=steps, cfg=cfg, sampler_name=sampler_name,
                    scheduler=scheduler, positive=positive, negative=negative,
                    latent_image=latent_image, denoise=denoise)
        if backend != "standard" and compatible and spectrum is not None:
            report = f"{type(dit).__name__}: Spectrum (Anima acceleration; modulation guidance off)"
            logger.info("[Wildcard Compatible KSampler] %s", report)
            result = spectrum().sample(**args, quality_tags="", mod_w_profile="off", refresh_ratio=refresh_ratio)
        else:
            reason = "requested" if backend == "standard" else (
                "Spectrum is not installed" if compatible else "Spectrum acceleration is not supported for this model")
            report = f"{type(dit).__name__}: standard KSampler ({reason}); no Spectrum acceleration"
            logger.info("[Wildcard Compatible KSampler] %s", report)
            result = nodes.common_ksampler(
                model, seed, steps, cfg, sampler_name, scheduler, positive, negative,
                latent_image, denoise=denoise)
        return (result[0], report)


NODE_CLASS_MAPPINGS = {"WildcardCompatibleKSampler": WildcardCompatibleKSampler}
NODE_DISPLAY_NAME_MAPPINGS = {"WildcardCompatibleKSampler": "Wildcard KSampler (Anima / MOSS)"}
