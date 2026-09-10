"""
Chart Utilities
Generate score charts and comparison graphs as PNG files
"""
import os
import logging
from pathlib import Path
from typing import Optional
import uuid

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _ensure_generated_dir() -> str:
    """Ensure the generated charts directory exists."""
    gen_dir = Path(settings.generated_dir)
    gen_dir.mkdir(parents=True, exist_ok=True)
    return str(gen_dir)


def generate_overall_score_chart(
    candidates: list[dict],  # [{"name": str, "score": float}]
    job_title: str = "",
    filename: Optional[str] = None,
) -> str:
    """
    Generate a horizontal bar chart of candidate overall scores.
    Returns the path to the saved PNG.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        names = [c["name"][:20] for c in candidates]
        scores = [c["score"] for c in candidates]

        # Color by category
        colors = []
        for score in scores:
            if score >= settings.threshold_strong:
                colors.append("#00C851")  # green
            elif score >= settings.threshold_good:
                colors.append("#33B5E5")  # blue
            elif score >= settings.threshold_moderate:
                colors.append("#FFBB33")  # amber
            else:
                colors.append("#FF4444")  # red

        fig, ax = plt.subplots(figsize=(10, max(4, len(candidates) * 0.7 + 2)))

        bars = ax.barh(names, scores, color=colors, edgecolor="white", height=0.6)

        # Add score labels
        for bar, score in zip(bars, scores):
            ax.text(
                min(score + 1, 98), bar.get_y() + bar.get_height() / 2,
                f"{score:.1f}",
                va="center", ha="left", fontweight="bold", fontsize=10
            )

        ax.set_xlim(0, 105)
        ax.set_xlabel("Score (out of 100)", fontsize=11)
        ax.set_title(
            f"Resume Screening Results{' — ' + job_title if job_title else ''}",
            fontsize=13, fontweight="bold", pad=15
        )
        ax.axvline(x=settings.threshold_strong, color="#00C851", linestyle="--", alpha=0.5, linewidth=1)
        ax.axvline(x=settings.threshold_good, color="#33B5E5", linestyle="--", alpha=0.5, linewidth=1)
        ax.axvline(x=settings.threshold_moderate, color="#FFBB33", linestyle="--", alpha=0.5, linewidth=1)

        legend_patches = [
            mpatches.Patch(color="#00C851", label=f"Strong Match (≥{settings.threshold_strong})"),
            mpatches.Patch(color="#33B5E5", label=f"Good Match (≥{settings.threshold_good})"),
            mpatches.Patch(color="#FFBB33", label=f"Moderate Match (≥{settings.threshold_moderate})"),
            mpatches.Patch(color="#FF4444", label="Weak Match"),
        ]
        ax.legend(handles=legend_patches, loc="lower right", fontsize=9)

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", alpha=0.3)
        plt.tight_layout()

        gen_dir = _ensure_generated_dir()
        out_file = filename or os.path.join(gen_dir, f"scores_{uuid.uuid4().hex[:8]}.png")
        plt.savefig(out_file, dpi=120, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.info(f"Score chart saved: {out_file}")
        return out_file

    except Exception as e:
        logger.error(f"Failed to generate score chart: {e}")
        raise


def generate_section_comparison_chart(
    candidates: list[dict],  # [{"name": str, "skills": float, "experience": float, ...}]
    job_title: str = "",
    filename: Optional[str] = None,
) -> str:
    """
    Generate a grouped bar chart comparing section scores across candidates.
    Returns the path to the saved PNG.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        sections = ["Skills", "Experience", "Projects", "Education", "JD Match"]
        section_keys = ["skills", "experience", "projects", "education", "jd_match"]

        n_candidates = len(candidates)
        n_sections = len(sections)
        x = np.arange(n_sections)
        width = 0.8 / n_candidates

        fig, ax = plt.subplots(figsize=(12, 6))

        cmap = plt.cm.get_cmap("tab10")
        for i, candidate in enumerate(candidates):
            values = [candidate.get(k, 0) for k in section_keys]
            offset = (i - n_candidates / 2 + 0.5) * width
            bars = ax.bar(x + offset, values, width, label=candidate["name"][:15],
                         color=cmap(i), alpha=0.85, edgecolor="white")

            for bar, val in zip(bars, values):
                if val > 5:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 1,
                        f"{val:.0f}",
                        ha="center", va="bottom", fontsize=7
                    )

        ax.set_xticks(x)
        ax.set_xticklabels(sections, fontsize=11)
        ax.set_ylim(0, 115)
        ax.set_ylabel("Score (out of 100)", fontsize=11)
        ax.set_title(
            f"Section Score Comparison{' — ' + job_title if job_title else ''}",
            fontsize=13, fontweight="bold", pad=15
        )
        ax.legend(loc="upper right", fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.3)
        ax.axhline(y=85, color="green", linestyle="--", alpha=0.3)
        ax.axhline(y=70, color="blue", linestyle="--", alpha=0.3)
        plt.tight_layout()

        gen_dir = _ensure_generated_dir()
        out_file = filename or os.path.join(gen_dir, f"comparison_{uuid.uuid4().hex[:8]}.png")
        plt.savefig(out_file, dpi=120, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.info(f"Comparison chart saved: {out_file}")
        return out_file

    except Exception as e:
        logger.error(f"Failed to generate comparison chart: {e}")
        raise


def generate_radar_chart(
    candidate_name: str,
    section_scores: dict,  # {"skills": float, "experience": float, ...}
    filename: Optional[str] = None,
) -> str:
    """
    Generate a radar/spider chart for a single candidate's section scores.
    Returns the path to the saved PNG.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        categories = ["Skills", "Experience", "Projects", "Education", "JD Match", "Completeness"]
        keys = ["skills", "experience", "projects", "education", "jd_match", "completeness"]
        values = [section_scores.get(k, 0) for k in keys]
        values += values[:1]  # close the polygon

        angles = [n / float(len(categories)) * 2 * np.pi for n in range(len(categories))]
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

        ax.plot(angles, values, "o-", linewidth=2, color="#33B5E5")
        ax.fill(angles, values, alpha=0.25, color="#33B5E5")

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, size=11)
        ax.set_ylim(0, 100)
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels(["20", "40", "60", "80", "100"], size=8)
        ax.set_title(f"Profile: {candidate_name}", size=13, fontweight="bold", y=1.08)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        gen_dir = _ensure_generated_dir()
        out_file = filename or os.path.join(gen_dir, f"radar_{uuid.uuid4().hex[:8]}.png")
        plt.savefig(out_file, dpi=120, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return out_file

    except Exception as e:
        logger.error(f"Failed to generate radar chart: {e}")
        raise
