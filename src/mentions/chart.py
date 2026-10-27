"""Draw the mention chart from output/summary.json.

Two panels, matching the dashboard's two rates:

- left: share of PDF-scanned papers that name each variant
- right: share of papers that name any tracked variant

Variants are drawn separately. A family is not collapsed.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mentions.paths import output_dir

COUNTRY_COLORS = {
    "usa": "#2258C3",
    "china": "#E83030",
    "uk": "#70B8DB",
    "france": "#E88532",
    "south korea": "#7A5195",
}

# Stable colors for the variants that usually lead. Others get the cycle.
COLORS = {
    "pi0": "#2258C3",
    "pi0_fast": "#7BA3E0",
    "pi05": "#0B3A86",
    "pi06": "#163E75",
    "pi06_star": "#081E40",
    "openvla": "#E83030",
    "openvla_oft": "#A11E1E",
    "diffusion_policy": "#E88532",
    "dp3": "#A85A12",
    "act": "#70B8DB",
    "octo": "#105257",
    "gr00t_n1": "#81B135",
    "gr00t_n1_5": "#5E8A20",
    "gr00t_n1_6": "#3E6010",
    "gr00t_n1_7": "#243C08",
    "gr00t_unspecified": "#B7D48A",
    "rt1": "#999999",
    "rt2": "#666666",
    "rt2_x": "#333333",
    "smolvla": "#C96442",
    "rdt_1b": "#7A5195",
    "cogact": "#D7A800",
}


def main() -> None:
    summary_path = output_dir() / "summary.json"
    summary = json.loads(summary_path.read_text())
    months = summary["months"]
    monthly = summary["monthly"]
    # Rank variants by total papers and keep the ones with a visible share.
    ranked = [row for row in summary["variants"] if row["papers"] >= 5]
    ranked = ranked[:12]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2), sharex=True)
    for ax, mode, title in (
        (axes[0], "scanned", "Share of scanned cs.RO papers"),
        (axes[1], "model", "Share of papers that name a tracked model"),
    ):
        for row in ranked:
            vid = row["variant_id"]
            ys = []
            for month in months:
                block = monthly[month]
                count = block["variants"].get(vid, 0)
                if mode == "scanned":
                    denom = block["papers_scanned"] or None
                else:
                    denom = block["any_model_papers"] or None
                ys.append(100 * count / denom if denom else None)
            ax.plot(
                months, ys,
                label=row["label"],
                color=COLORS.get(vid),
                linewidth=1.8,
            )
        ax.set_title(title)
        ax.set_ylabel("percent")
        ax.set_ylim(bottom=0)
        ax.tick_params(axis="x", labelrotation=60, labelsize=7)
        # show every 3rd month tick
        ax.set_xticks(months[::3])
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(fontsize=8, frameon=False, loc="upper left")

    scanned = summary["papers_scanned"]
    failed = summary.get("papers_failed", 0)
    any_n = summary["papers_mentioning_any_tracked_variant"]
    fig.suptitle(
        "Which robotics models cs.RO papers name\n"
        f"{scanned:,} papers with bulk-PDF text · {failed:,} failed · "
        f"{any_n:,} name a tracked model",
        fontsize=12,
    )
    fig.tight_layout()
    out = output_dir() / "mentions.png"
    fig.savefig(out, dpi=140)
    print(f"wrote {out}")
    write_origin(summary)


def write_origin(summary: dict) -> None:
    """Share of model-papers naming a model from each country and company."""
    months = summary["months"]
    monthly = summary["monthly"]
    countries = [row["country"] for row in summary.get("by_country", [])]
    companies = [row["company"] for row in summary.get("by_company", [])][:8]
    if not countries:
        return
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2), sharex=True)
    for ax, keys, field, title in (
        (axes[0], countries, "countries", "Share of model-papers by country"),
        (axes[1], companies, "companies", "Share of model-papers by company"),
    ):
        for key in keys:
            ys = []
            for month in months:
                block = monthly[month]
                count = block.get(field, {}).get(key, 0)
                denom = block["any_model_papers"] or None
                ys.append(100 * count / denom if denom else None)
            ax.plot(months, ys, label=key, color=COUNTRY_COLORS.get(key), linewidth=1.8)
        ax.set_title(title)
        ax.set_ylabel("percent of papers naming a tracked model")
        ax.set_ylim(0, 100)
        ax.set_xticks(months[::3])
        ax.tick_params(axis="x", labelrotation=60, labelsize=7)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.suptitle(
        "Where the named robotics models come from\n"
        "A paper counts once per country and once per company",
        fontsize=12,
    )
    fig.tight_layout()
    origin = output_dir() / "origin.png"
    fig.savefig(origin, dpi=140)
    print(f"wrote {origin}")


if __name__ == "__main__":
    main()
