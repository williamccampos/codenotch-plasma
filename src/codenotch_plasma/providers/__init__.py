from ..provider_order import arrange
from .antigravity import AntigravityProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .cursor import CursorCorpProvider, CursorPersonalProvider
from .grok import GrokProvider
from .kiro import KiroProvider


# Display order matches codenotch-gnome prefs, then Plasma-only providers.
TOOL_SPECS = (
    (ClaudeProvider, "Claude Code"),
    (CodexProvider, "Codex"),
    (AntigravityProvider, "Antigravity (agy)"),
    (GrokProvider, "Grok"),
    (CursorPersonalProvider, "Cursor Personal"),
    (CursorCorpProvider, "Cursor Corp"),
    (KiroProvider, "Kiro"),
)


def all_provider_classes():
    return [cls for cls, _title in TOOL_SPECS]


def tool_catalog():
    catalog = []
    for cls, title in TOOL_SPECS:
        provider = cls()
        catalog.append({
            "id": provider.id,
            "title": title,
            "display_name": provider.display_name,
            "installed": provider.available(),
            "provider": provider,
        })
    return catalog


def discover_providers(disabled=None, order=None):
    disabled = set(disabled or ())
    found = []
    for cls, _title in TOOL_SPECS:
        provider = cls()
        if provider.id in disabled:
            continue
        if provider.available():
            found.append(provider)
    return arrange(found, order)
