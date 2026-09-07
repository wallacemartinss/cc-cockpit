"""Translation catalogue and locale-aware formatting.

One catalogue feeds all three surfaces (tray, CLI and dashboard), so a string
is written once. The language follows the OS by default and can be pinned in
the config file.
"""
from __future__ import annotations

import os

SUPPORTED = ("en", "pt", "es")
DEFAULT = "en"

# region kept when the OS provides one, so numbers format the local way
_TAGS = {"en": "en-US", "pt": "pt-BR", "es": "es-ES"}

CATALOG: dict[str, dict[str, str]] = {
    "en": {
        # tray + cli
        "block_of": "Block of {h}h",
        "no_activity": "no activity in the current window",
        "resets_in": "resets in {d}",
        "pace": "{v}/h",
        "projection": "projection {v}",
        "ceiling_eta": "at this pace, ceiling in {d}",
        "days7": "Last 7 days",
        "today": "Today",
        "month": "This month",
        "cache_hit_7d": "cache hit {p}% over the last 7 days",
        "tokens_requests": "{tok} tokens · {n} requests",
        "no_sessions": "No session open",
        "sessions_open": "{n} session(s) open",
        "projects_today": "Today's projects",
        "working": "working",
        "idle_for": "idle for {d}",
        "open_for": "open for {d}",
        "requests_tokens": "{n} requests · {tok} tokens",
        "pid_line": "pid {pid} · {mb} MB · v{version}",
        "open_dashboard": "Open dashboard",
        "refresh_now": "Refresh now",
        "quit": "Quit",
        "read_error": "could not read the history",
        # cli only
        "cli_sessions": "open sessions",
        "cli_none": "(none)",
        "cli_projects": "projects · all time",
        "cli_models": "models",
        "cli_requests_short": "req",
        "cli_footer": "local history: {n} requests · {tok} tokens · {usd} API-equivalent",
        "cli_new_events": "{new} new event(s) · {total} in the history",
        # dashboard
        "month_equivalent": "API-equivalent this month",
        "plan_roi": "plan {name} · returned {roi}× this month",
        "updated": "updated {time}",
        "reference_ceiling": "reference ceiling {v}",
        "requests": "requests",
        "sessions": "sessions",
        "kpi_pace": "pace in the current block",
        "kpi_projection": "projected to the end of the block",
        "kpi_eta": "until the reference ceiling",
        "kpi_cache": "cache hit over 7 days",
        "card_daily": "Spend per day · API-equivalent",
        "card_hourly": "Last 24 hours",
        "card_sessions": "Sessions open right now",
        "card_projects": "Projects · all time",
        "card_blocks": "Recent {h}h blocks",
        "card_models": "Models",
        "card_tokenmix": "Token mix · 7 days",
        "card_effort": "Effort & subagents",
        "th_project": "project",
        "th_tokens": "tokens",
        "th_model": "model",
        "th_req": "req",
        "no_data": "no data",
        "subagents": "subagents: {usd} across {n} requests",
        "footer": "local history: {n} requests · {tok} tokens · {usd} API-equivalent",
        "settings": "Settings",
        "panel_shows": "Panel shows",
        "bar_style": "Bar style",
        "language_label": "Language",
        "auto": "Automatic",
        "metric_none": "Nothing",
        "show_cost": "Show the amount",
        "open_config": "Open the config file",
        "open_data": "Open the data folder",
        "style_blocks": "Blocks",
        "style_dots": "Dots",
        "style_emoji": "Colour squares",
        "src_official": "from the official panel",
        "week_window": "Weekly window",
        "sync_cleared": "anchors and calibration samples dropped",
        "sync_state": "{window}: {pct}% · {used} · resets in {reset} · window {source} · ceiling {v} ({n} sample(s))",
        "src_local": "estimated locally",
        "src_anchored": "anchored to the panel",
        "src_rolling": "rolling 7 days",
        "cal_cleared": "calibration samples for '{window}' dropped",
        "cal_state": "{window}: {n} sample(s) · implied ceiling {v}",
        "cal_no_usage": "no usage recorded in this window yet",
        "cal_recorded": "{pct}% of the {window} window = {used} → implied ceiling {v}",
        "src_manual": "set by you",
        "src_calibrated": "calibrated",
        "src_peak": "your historical peak",
    },
    "pt": {
        "block_of": "Bloco de {h}h",
        "no_activity": "sem atividade na janela atual",
        "resets_in": "reseta em {d}",
        "pace": "{v}/h",
        "projection": "projeção {v}",
        "ceiling_eta": "no ritmo atual, teto em {d}",
        "days7": "Últimos 7 dias",
        "today": "Hoje",
        "month": "No mês",
        "cache_hit_7d": "cache hit {p}% nos últimos 7 dias",
        "tokens_requests": "{tok} tokens · {n} requests",
        "no_sessions": "Nenhuma sessão aberta",
        "sessions_open": "{n} sessão(ões) aberta(s)",
        "projects_today": "Projetos de hoje",
        "working": "trabalhando",
        "idle_for": "ociosa há {d}",
        "open_for": "aberta há {d}",
        "requests_tokens": "{n} requests · {tok} tokens",
        "pid_line": "pid {pid} · {mb} MB · v{version}",
        "open_dashboard": "Abrir dashboard",
        "refresh_now": "Atualizar agora",
        "quit": "Sair",
        "read_error": "não consegui ler o histórico",
        "cli_sessions": "sessões abertas",
        "cli_none": "(nenhuma)",
        "cli_projects": "projetos · histórico",
        "cli_models": "modelos",
        "cli_requests_short": "req",
        "cli_footer": "histórico local: {n} requests · {tok} tokens · {usd} equivalente API",
        "cli_new_events": "{new} evento(s) novo(s) · {total} no histórico",
        "month_equivalent": "equivalente API no mês",
        "plan_roi": "plano {name} · rendeu {roi}× este mês",
        "updated": "atualizado {time}",
        "reference_ceiling": "teto de referência {v}",
        "requests": "requests",
        "sessions": "sessões",
        "kpi_pace": "ritmo no bloco atual",
        "kpi_projection": "projeção até o fim do bloco",
        "kpi_eta": "até o teto de referência",
        "kpi_cache": "cache hit em 7 dias",
        "card_daily": "Consumo por dia · equivalente API",
        "card_hourly": "Últimas 24 horas",
        "card_sessions": "Sessões abertas agora",
        "card_projects": "Projetos · todo o histórico",
        "card_blocks": "Blocos de {h}h recentes",
        "card_models": "Modelos",
        "card_tokenmix": "Composição de tokens · 7 dias",
        "card_effort": "Effort e subagentes",
        "th_project": "projeto",
        "th_tokens": "tokens",
        "th_model": "modelo",
        "th_req": "req",
        "no_data": "sem dados",
        "subagents": "subagentes: {usd} em {n} requests",
        "footer": "histórico local: {n} requests · {tok} tokens · {usd} equivalente API",
        "settings": "Configurações",
        "panel_shows": "No painel",
        "bar_style": "Estilo da barra",
        "language_label": "Idioma",
        "auto": "Automático",
        "metric_none": "Nada",
        "show_cost": "Mostrar o valor",
        "open_config": "Abrir o arquivo de configuração",
        "open_data": "Abrir a pasta de dados",
        "style_blocks": "Blocos",
        "style_dots": "Pontos",
        "style_emoji": "Quadrados coloridos",
        "src_official": "do painel oficial",
        "week_window": "Janela semanal",
        "sync_cleared": "âncoras e amostras de calibração apagadas",
        "sync_state": "{window}: {pct}% · {used} · reseta em {reset} · janela {source} · teto {v} ({n} amostra(s))",
        "src_local": "estimada localmente",
        "src_anchored": "ancorada no painel",
        "src_rolling": "7 dias corridos",
        "cal_cleared": "amostras de calibração de '{window}' apagadas",
        "cal_state": "{window}: {n} amostra(s) · teto implícito {v}",
        "cal_no_usage": "ainda não há consumo registrado nesta janela",
        "cal_recorded": "{pct}% da janela {window} = {used} → teto implícito {v}",
        "src_manual": "definido por você",
        "src_calibrated": "calibrado",
        "src_peak": "seu pico histórico",
    },
    "es": {
        "block_of": "Bloque de {h}h",
        "no_activity": "sin actividad en la ventana actual",
        "resets_in": "se reinicia en {d}",
        "pace": "{v}/h",
        "projection": "proyección {v}",
        "ceiling_eta": "a este ritmo, techo en {d}",
        "days7": "Últimos 7 días",
        "today": "Hoy",
        "month": "Este mes",
        "cache_hit_7d": "cache hit {p}% en los últimos 7 días",
        "tokens_requests": "{tok} tokens · {n} requests",
        "no_sessions": "Ninguna sesión abierta",
        "sessions_open": "{n} sesión(es) abierta(s)",
        "projects_today": "Proyectos de hoy",
        "working": "trabajando",
        "idle_for": "inactiva hace {d}",
        "open_for": "abierta hace {d}",
        "requests_tokens": "{n} requests · {tok} tokens",
        "pid_line": "pid {pid} · {mb} MB · v{version}",
        "open_dashboard": "Abrir panel",
        "refresh_now": "Actualizar ahora",
        "quit": "Salir",
        "read_error": "no pude leer el historial",
        "cli_sessions": "sesiones abiertas",
        "cli_none": "(ninguna)",
        "cli_projects": "proyectos · historial",
        "cli_models": "modelos",
        "cli_requests_short": "req",
        "cli_footer": "historial local: {n} requests · {tok} tokens · {usd} equivalente API",
        "cli_new_events": "{new} evento(s) nuevo(s) · {total} en el historial",
        "month_equivalent": "equivalente API en el mes",
        "plan_roi": "plan {name} · rindió {roi}× este mes",
        "updated": "actualizado {time}",
        "reference_ceiling": "techo de referencia {v}",
        "requests": "requests",
        "sessions": "sesiones",
        "kpi_pace": "ritmo en el bloque actual",
        "kpi_projection": "proyección hasta el fin del bloque",
        "kpi_eta": "hasta el techo de referencia",
        "kpi_cache": "cache hit en 7 días",
        "card_daily": "Consumo por día · equivalente API",
        "card_hourly": "Últimas 24 horas",
        "card_sessions": "Sesiones abiertas ahora",
        "card_projects": "Proyectos · todo el historial",
        "card_blocks": "Bloques de {h}h recientes",
        "card_models": "Modelos",
        "card_tokenmix": "Composición de tokens · 7 días",
        "card_effort": "Effort y subagentes",
        "th_project": "proyecto",
        "th_tokens": "tokens",
        "th_model": "modelo",
        "th_req": "req",
        "no_data": "sin datos",
        "subagents": "subagentes: {usd} en {n} requests",
        "footer": "historial local: {n} requests · {tok} tokens · {usd} equivalente API",
        "settings": "Configuración",
        "panel_shows": "En el panel",
        "bar_style": "Estilo de la barra",
        "language_label": "Idioma",
        "auto": "Automático",
        "metric_none": "Nada",
        "show_cost": "Mostrar el valor",
        "open_config": "Abrir el archivo de configuración",
        "open_data": "Abrir la carpeta de datos",
        "style_blocks": "Bloques",
        "style_dots": "Puntos",
        "style_emoji": "Cuadrados de color",
        "src_official": "del panel oficial",
        "week_window": "Ventana semanal",
        "sync_cleared": "anclas y muestras de calibración borradas",
        "sync_state": "{window}: {pct}% · {used} · se reinicia en {reset} · ventana {source} · techo {v} ({n} muestra(s))",
        "src_local": "estimada localmente",
        "src_anchored": "anclada al panel",
        "src_rolling": "7 días corridos",
        "cal_cleared": "muestras de calibración de '{window}' borradas",
        "cal_state": "{window}: {n} muestra(s) · techo implícito {v}",
        "cal_no_usage": "todavía no hay consumo registrado en esta ventana",
        "cal_recorded": "{pct}% de la ventana {window} = {used} → techo implícito {v}",
        "src_manual": "definido por ti",
        "src_calibrated": "calibrado",
        "src_peak": "tu pico histórico",
    },
}

_lang = DEFAULT
_tag = _TAGS[DEFAULT]


def detect() -> tuple[str, str]:
    """Reads the OS locale. Returns (language, BCP-47 tag)."""
    raw = ""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            raw = value.split(":")[0]
            break
    code = raw.split(".")[0].replace("_", "-")
    lang = code.split("-")[0].lower()
    if lang not in SUPPORTED:
        return DEFAULT, _TAGS[DEFAULT]
    tag = code if "-" in code else _TAGS[lang]
    return lang, tag


def use(language: str | None = None) -> str:
    """Pins the language. 'auto' or None follows the OS."""
    global _lang, _tag
    if language and language != "auto" and language in SUPPORTED:
        _lang, _tag = language, _TAGS[language]
    else:
        _lang, _tag = detect()
    return _lang


def language() -> str:
    return _lang


def tag() -> str:
    return _tag


def t(key: str, **kwargs) -> str:
    text = CATALOG.get(_lang, CATALOG[DEFAULT]).get(key) or CATALOG[DEFAULT].get(key, key)
    return text.format(**kwargs) if kwargs else text


def catalog() -> dict[str, str]:
    """Full catalogue for the current language, for the dashboard."""
    merged = dict(CATALOG[DEFAULT])
    merged.update(CATALOG.get(_lang, {}))
    return merged


# ---------- locale-aware formatting ----------

def _group(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    if _lang == "en":
        return text
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def money(value: float) -> str:
    """Always USD - it is the API-equivalent value, not a local charge."""
    prefix = "$" if _lang == "en" else "US$ "
    return f"{prefix}{_group(value, 2)}"


def number(value: float, decimals: int = 0) -> str:
    return _group(value, decimals)


def tokens(n: int) -> str:
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return _group(n / div, 0 if div == 1e3 else 1) + suffix
    return str(n)


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, h, m = seconds // 86400, seconds % 86400 // 3600, seconds % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h{m:02d}"
    return f"{m}min"
