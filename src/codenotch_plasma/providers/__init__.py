from .claude import ClaudeProvider
from .codex import CodexProvider
from .cursor import CursorCorpProvider, CursorPersonalProvider
from .grok import GrokProvider
from .kiro import KiroProvider


def discover_providers(disabled=None):
    disabled = set(disabled or ())
    found = []
    for cls in (
        ClaudeProvider,
        CodexProvider,
        CursorPersonalProvider,
        CursorCorpProvider,
        GrokProvider,
        KiroProvider,
    ):
        provider = cls()
        if provider.id in disabled:
            continue
        if provider.available():
            found.append(provider)
    return found
