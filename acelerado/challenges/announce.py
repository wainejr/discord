"""Render the monthly challenge announcement message.

Copy is in Portuguese (consistent with the rest of the bot) and adapts
to the spec's primary metric — minimizing time reads differently from
maximizing PSNR. Unknown metrics fall through to a generic
"<direction> <metric>" sentence rather than failing, so a future
challenge with a novel metric still announces cleanly.
"""

from __future__ import annotations

from acelerado.challenges.spec import Spec

# Per-metric copy for the headline. Phrased as a complete sentence so
# the renderer can drop it in without grammar gymnastics.
_METRIC_COPY: dict[tuple[str, str], str] = {
    ("time_ms", "min"): "Minimizar **tempo de execução**.",
    ("time_ms_per_image", "min"): "Minimizar **tempo por imagem**.",
    ("peak_rss_mb", "min"): "Minimizar **pico de memória (RSS)**.",
    ("disk_write_mb", "min"): "Minimizar **escrita em disco**.",
    ("binary_size_bytes", "min"): "Minimizar **tamanho do binário**.",
    ("code_size_bytes", "min"): "Minimizar **tamanho do código-fonte**.",
    ("psnr_mean_db", "max"): "Maximizar **PSNR médio** (qualidade da reconstrução).",
    ("quality", "max"): "Maximizar **qualidade da saída**.",
    ("quality", "min"): "Minimizar **erro da saída**.",
}

_DIRECTION_VERB = {"min": "minimizar", "max": "maximizar"}


def _metric_sentence(spec: Spec) -> str:
    key = (spec.primary_metric, spec.direction)
    if key in _METRIC_COPY:
        return _METRIC_COPY[key]
    verb = _DIRECTION_VERB.get(spec.direction, spec.direction)
    return f"{verb.capitalize()} **`{spec.primary_metric}`**."


# Caps formatter — same idea: known keys get a polished line, unknown
# keys round-trip as ``key: value`` so nothing is silently hidden.
def format_cap(key: str, value: object) -> str:
    if key in {"time_ms", "time_ms_per_image"}:
        suffix = " por imagem" if key == "time_ms_per_image" else ""
        return f"⏱ {value} ms{suffix}"
    if key == "peak_rss_mb":
        return f"💾 {value} MB de RAM"
    if key == "disk_write_mb":
        return f"📝 {value} MB de escrita em disco"
    if key == "binary_size_bytes":
        return f"📦 {value} bytes (binário)"
    if key == "code_size_bytes":
        return f"📜 {value} bytes (código-fonte)"
    return f"{key}: {value}"


def render_announcement(spec: Spec) -> str:
    """Return the message body to post in the announcements channel."""
    lines = [
        f"@everyone 🏁 **Desafio de {spec.month} — {spec.title}**",
        "",
        _metric_sentence(spec),
    ]
    if spec.caps:
        lines.append("")
        lines.append("**Limites:**")
        for cap_key, cap_value in spec.caps.items():
            lines.append(f"• {format_cap(cap_key, cap_value)}")
    lines.append("")
    lines.append(f"📖 Enunciado: {spec.site_url}")
    lines.append(
        "🐳 Submissão via PR no repo "
        "[acelerado-desafios](https://github.com/wainejr/acelerado-desafios)."
    )
    return "\n".join(lines)


def render_short_status(spec: Spec) -> str:
    """One-line summary — used by ``/desafio`` for the active challenge."""
    return f"**{spec.month} — {spec.title}** · {_metric_sentence(spec)}"
