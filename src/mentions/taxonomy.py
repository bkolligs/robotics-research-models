"""Robotics model variants for arXiv mention tracking.

Adapted from the Interconnects arXiv-mentions method
(https://dashboard.interconnects.ai/#arxiv-mentions), with one change the
robotics question needs: each released model is its own row. Family charts
are a rollup of those rows. A paper that says only "pi0.5" counts as pi0.5,
not also as pi0.

Counting rules, matching the public dashboard contract:

- mention unit is paper presence: a paper counts at most once per variant
- co-mentions are independent: one paper may hit several variants
- date basis is the first submission month
- denominator for "rate" is successfully scanned papers that month
- denominator for "rate among model papers" is papers that mention at least
  one tracked variant
- ambiguous ordinary words require a qualified alias
- a more specific variant consumes its span before a shorter sibling, so
  "pi0.5" does not also match "pi0"
"""

from __future__ import annotations

# (variant_id, label, family_id, family_label, country, company, access, year, aliases)
# country is the releasing organization's headquarters country, the same
# basis Interconnects uses for region. company is that organization.
# Aliases are matched on normalized text. Longest alias wins inside a family.

VARIANTS: list[tuple[str, str, str, str, str, str, str, int, tuple[str, ...]]] = [
    # --- Physical Intelligence π series. Each release is its own row. ---
    # Written forms only. Bare "pi0" / "$\\pi_{0}$" is standard policy
    # notation in control papers and is not a model mention. arXiv HTML
    # renders the model as "π0" with no space, which normalizes to "π0".
    ("pi0", "π0", "pi", "π", "usa", "Physical Intelligence", "open_weight", 2024, (
        "π0", "π₀",
    )),
    ("pi0_fast", "π0-FAST", "pi", "π", "usa", "Physical Intelligence", "open_weight", 2025, (
        "π0-fast", "π₀-fast", "pi0-fast",
    )),
    ("pi05", "π0.5", "pi", "π", "usa", "Physical Intelligence", "open_weight", 2025, (
        "π0.5", "π₀.₅", "pi0.5", "pi05",
    )),
    ("pi06", "π0.6", "pi", "π", "usa", "Physical Intelligence", "closed", 2025, (
        "π0.6", "π₀.₆", "pi0.6", "pi06",
    )),
    ("pi06_star", "π*0.6", "pi", "π", "usa", "Physical Intelligence", "closed", 2025, (
        "π*0.6", "pi*0.6", "π⋆0.6",
    )),
    ("pi07", "π0.7", "pi", "π", "usa", "Physical Intelligence", "closed", 2026, (
        "π0.7", "π₀.₇", "pi0.7", "pi07",
    )),

    # --- NVIDIA GR00T. N1 is the base; later N1.x are separate releases. ---
    ("gr00t_n1", "GR00T N1", "gr00t", "GR00T", "usa", "NVIDIA", "open_weight", 2025, (
        "gr00t n1", "gr00t-n1", "groot n1", "gr00t-n1-2b",
    )),
    ("gr00t_n1_5", "GR00T N1.5", "gr00t", "GR00T", "usa", "NVIDIA", "open_weight", 2025, (
        "gr00t n1.5", "gr00t-n1.5", "gr00t n1_5",
    )),
    ("gr00t_n1_6", "GR00T N1.6", "gr00t", "GR00T", "usa", "NVIDIA", "open_weight", 2025, (
        "gr00t n1.6", "gr00t-n1.6", "gr00t n1_6",
    )),
    ("gr00t_n1_7", "GR00T N1.7", "gr00t", "GR00T", "usa", "NVIDIA", "open_weight", 2026, (
        "gr00t n1.7", "gr00t-n1.7", "gr00t n1_7",
    )),
    # Bare "GR00T" names the line but not a release. Its own row, so a
    # paper that does not say N1 / N1.5 / N1.6 / N1.7 is not credited to N1.
    ("gr00t_unspecified", "GR00T (version unspecified)", "gr00t", "GR00T", "usa", "NVIDIA", "open_weight", 2025, (
        "isaac gr00t", "gr00t",
    )),

    # --- Google DeepMind Robotics Transformer line. ---
    ("rt1", "RT-1", "rt", "RT", "usa", "Google DeepMind", "open_weight", 2022, (
        "rt-1", "rt1",
    )),
    ("rt1_x", "RT-1-X", "rt", "RT", "usa", "Google DeepMind", "open_weight", 2023, (
        "rt-1-x", "rt1-x", "rt-1x",
    )),
    ("rt2", "RT-2", "rt", "RT", "usa", "Google DeepMind", "closed", 2023, (
        "rt-2", "rt2",
    )),
    ("rt2_x", "RT-2-X", "rt", "RT", "usa", "Google DeepMind", "closed", 2023, (
        "rt-2-x", "rt2-x", "rt-2x", "rt-x",
    )),
    ("rt_h", "RT-H", "rt", "RT", "usa", "Google DeepMind", "closed", 2024, (
        "rt-h", "rt-hierarchy",
    )),

    # --- OpenVLA line. OFT is a released fine-tuning recipe with its own
    # checkpoints, so it is a variant, not folded into the base model. ---
    ("openvla", "OpenVLA", "openvla", "OpenVLA", "usa", "Stanford / RAIL", "open_weight", 2024, (
        "openvla", "open-vla",
    )),
    ("openvla_oft", "OpenVLA-OFT", "openvla", "OpenVLA", "usa", "Stanford / RAIL", "open_weight", 2025, (
        "openvla-oft", "openvla oft", "openvlaoft",
    )),

    # --- Other generalist policies people actually baseline against. ---
    ("octo", "Octo", "octo", "Octo", "usa", "UC Berkeley", "open_weight", 2024, (
        "octo-base", "octo-small", "octo model", "octo policy",
    )),
    ("smolvla", "SmolVLA", "smolvla", "SmolVLA", "france", "Hugging Face", "open_weight", 2025, (
        "smolvla", "smol-vla",
    )),
    ("rdt_1b", "RDT-1B", "rdt", "RDT", "china", "Tsinghua", "open_weight", 2024, (
        "rdt-1b", "rdt1b",
    )),
    ("rdt2", "RDT2", "rdt", "RDT", "china", "Tsinghua", "open_weight", 2026, (
        "rdt-2", "rdt2",
    )),
    ("diffusion_policy", "Diffusion Policy", "diffusion_policy", "Diffusion Policy", "usa", "Columbia / Toyota Research Institute", "open_weight", 2023, (
        "diffusion policy", "diffusion-policy",
    )),
    ("dp3", "3D Diffusion Policy", "diffusion_policy", "Diffusion Policy", "china", "Shanghai Jiao Tong University", "open_weight", 2024, (
        "3d diffusion policy", "3d-diffusion-policy", "dp3",
    )),
    ("act", "ACT", "act", "ACT", "usa", "Stanford", "open_weight", 2023, (
        "action chunking with transformers",
        "action chunking transformer",
    )),
    ("cogact", "CogACT", "cogact", "CogACT", "china", "Microsoft Research Asia", "open_weight", 2024, (
        "cogact",
    )),
    ("tinyvla", "TinyVLA", "tinyvla", "TinyVLA", "china", "Midea", "open_weight", 2024, (
        "tinyvla", "tiny-vla",
    )),
    ("spatialvla", "SpatialVLA", "spatialvla", "SpatialVLA", "china", "Shanghai AI Lab", "open_weight", 2025, (
        "spatialvla", "spatial-vla",
    )),
    ("xvla", "X-VLA", "xvla", "X-VLA", "china", "Shanghai AI Lab", "open_weight", 2025, (
        "x-vla", "xvla",
    )),
    ("internvla", "InternVLA", "internvla", "InternVLA", "china", "Shanghai AI Lab", "open_weight", 2025, (
        "internvla", "intern-vla",
    )),
    ("lingbot_vla", "LingBot-VLA", "lingbot", "LingBot", "china", "Ant Group", "open_weight", 2026, (
        "lingbot-vla", "lingbot vla",
    )),
    ("lingbot_vla2", "LingBot-VLA 2.0", "lingbot", "LingBot", "china", "Ant Group", "open_weight", 2026, (
        "lingbot-vla 2", "lingbot-vla2", "lingbot vla 2",
    )),
    ("gr3", "GR-3", "gr3", "GR-3", "china", "ByteDance", "open_weight", 2025, (
        "gr-3",
    )),
    ("qwen_vla", "Qwen-VLA", "qwen_vla", "Qwen-VLA", "china", "Alibaba", "open_weight", 2026, (
        "qwen-vla", "qwen vla", "qwenvla",
    )),
    ("xiaomi_robotics", "Xiaomi-Robotics-1", "xiaomi_robotics", "Xiaomi-Robotics", "china", "Xiaomi", "open_weight", 2026, (
        "xiaomi-robotics-1", "xiaomi robotics-1", "xiaomi-robotics",
    )),
    ("molmoact", "MolmoAct", "molmoact", "MolmoAct", "usa", "Allen Institute for AI", "open_weight", 2025, (
        "molmoact",
    )),
    ("molmoact2", "MolmoAct2", "molmoact", "MolmoAct", "usa", "Allen Institute for AI", "open_weight", 2026, (
        "molmoact2", "molmoact 2",
    )),
    ("gemini_robotics", "Gemini Robotics", "gemini_robotics", "Gemini Robotics", "usa", "Google DeepMind", "closed", 2025, (
        "gemini robotics",
    )),
    ("gemini_robotics_15", "Gemini Robotics 1.5", "gemini_robotics", "Gemini Robotics", "usa", "Google DeepMind", "closed", 2025, (
        "gemini robotics 1.5", "gemini robotics-1.5",
    )),
    ("helix", "Helix", "helix", "Helix", "usa", "Figure", "closed", 2025, (
        "helix vla",
    )),
    ("robobrain", "RoboBrain", "robobrain", "RoboBrain", "china", "Beijing Academy of AI", "open_weight", 2025, (
        "robobrain",
    )),
    ("tracevla", "TraceVLA", "tracevla", "TraceVLA", "usa", "Stanford", "open_weight", 2024, (
        "tracevla",
    )),
    ("vla_3d", "3D-VLA", "vla_3d", "3D-VLA", "usa", "UMass / MIT-IBM", "open_weight", 2024, (
        "3d-vla", "3dvla",
    )),
    ("ecot", "ECoT", "ecot", "ECoT", "usa", "UC Berkeley", "open_weight", 2024, (
        "embodied chain-of-thought", "embodied chain of thought", "ecot",
    )),
    ("fast_tokenizer", "FAST", "fast", "FAST", "usa", "Physical Intelligence", "open_weight", 2025, (
        "frequency-space action sequence tokenization",
        "frequency-space action",
        "fast action tokenizer",
    )),
    ("lapa", "LAPA", "lapa", "LAPA", "usa", "KAIST / Microsoft", "open_weight", 2024, (
        "latent action pretraining",
    )),
    ("palm_e", "PaLM-E", "palm_e", "PaLM-E", "usa", "Google", "closed", 2023, (
        "palm-e", "palme",
    )),
    ("saycan", "SayCan", "saycan", "SayCan", "usa", "Google", "closed", 2022, (
        "saycan", "say-can",
    )),
    ("roboflamingo", "RoboFlamingo", "roboflamingo", "RoboFlamingo", "china", "ByteDance Research", "open_weight", 2023, (
        "roboflamingo",
    )),
    ("hpt", "HPT", "hpt", "HPT", "usa", "MIT", "open_weight", 2024, (
        "heterogeneous pre-trained transformers",
        "heterogeneous pretrained transformers",
    )),
    ("peract", "PerAct", "peract", "PerAct", "uk", "Imperial College London", "open_weight", 2022, (
        "peract", "perceiver-actor",
    )),
    ("cliport", "CLIPort", "cliport", "CLIPort", "usa", "University of Washington", "open_weight", 2021, (
        "cliport",
    )),
    ("vc1", "VC-1", "vc1", "VC-1", "usa", "Meta", "open_weight", 2023, (
        "vc-1",
    )),
    ("r3m", "R3M", "r3m", "R3M", "usa", "Meta", "open_weight", 2022, (
        "r3m",
    )),
]


def variant_records() -> list[dict]:
    rows = []
    for vid, label, fid, flabel, country, company, access, year, aliases in VARIANTS:
        rows.append({
            "variant_id": vid,
            "label": label,
            "family_id": fid,
            "family_label": flabel,
            "country": country,
            "company": company,
            "region": country,
            "access_class": access,
            "introduced": year,
            "aliases": list(aliases),
        })
    return rows
