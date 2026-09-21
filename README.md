# Codenotch Plasma

Notch de uso de assistentes de código na borda da tela — port para **KDE Plasma no Linux**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Port do excelente [codenotch-gnome](https://github.com/RicardoEGG/codenotch-gnome) (por [Ricardo Egg](https://github.com/RicardoEGG)), que por sua vez é port do [codenotch](https://github.com/vinzdg/codenotch) original de [vinzdg](https://github.com/vinzdg).

> **Disclaimer:** esta versão é **exclusiva para Linux com KDE Plasma** (testado em Plasma 5.27 / Ubuntu 24.04).  
> Não é um plasmoid de painel — é um overlay frameless que replica o visual e a experiência do notch original na borda da tela. GNOME, Windows e macOS **não são suportados**.

## Prévia

| Notch expandido | Card de hover |
|:---:|:---:|
| ![Notch expandido com anéis de uso](docs/screenshots/notch-rings.png) | ![Card de hover com detalhes do Codex](docs/screenshots/notch-card.png) |

| Recolhido na borda | Anel duplo do Codex |
|:---:|:---:|
| ![Notch recolhido na borda](docs/screenshots/notch-folded.png) | ![Close do anel duplo — 5h + semanal](docs/screenshots/codex-dual-ring.png) |

## O que é

Um pill preto colado na borda da tela que desdobra ao passar o mouse, mostrando o uso dos seus assistentes de código em tempo real:

- **Anéis coloridos** por provider — verde (0–49%), amarelo (50–69%), laranja (70–100%)
- **Card de hover** com limites, horários de reset e sessões ativas
- **Anel duplo no Codex** — externo (5h) + interno (semanal)
- **Refresh automático** quando os limites resetam
- **Autostart** no login do KDE

Codenotch **nunca faz login**. Ele só lê credenciais que já existem na sua máquina.

## Instalação rápida

```bash
git clone https://github.com/williamccampos/codenotch-plasma.git
cd codenotch-plasma
./install.sh
```

**Requisitos:** Linux · KDE Plasma · Python 3.10+ · PyQt5

```bash
sudo apt install python3-pyqt5   # Ubuntu / Debian
```

O script instala em `~/.local/bin/codenotch-plasma`, registra autostart e inicia o notch na borda direita.

**Uso:** passe o mouse na borda → notch desdobra. Clique esquerdo abre o dashboard do provider. Clique direito: **Sempre aberto** ou **Sair**.

## Providers suportados

| Provider | Onde lê a credencial |
|----------|----------------------|
| Claude Code | `~/.claude/.credentials.json` |
| Codex | `~/.codex/auth.json` |
| Cursor Personal | sessão do Cursor IDE / agent |
| Cursor Corp | login no browser (Edge) + [`browser-cookie3`](requirements.txt) |
| Grok | `~/.grok/auth.json` |
| Kiro | `~/.local/share/kiro-cli/data.sqlite3` |

Se nenhum provider estiver disponível, anéis de demonstração são exibidos para você avaliar o visual.

### Codex — anel duplo

| Anel | Limite | Comportamento |
|------|--------|---------------|
| Externo (grosso) | 5 horas | Esgotado → laranja |
| Interno (fino) | Semanal | Quota principal → label abaixo do anel |
| Logo | — | Permanece aceso enquanto o limite **semanal** não estiver em 100% |

## Configuração

Arquivo: `~/.config/codenotch-plasma/config.json` — veja [`config.example.json`](config.example.json).

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `edge` | `right` | Borda: `left`, `right`, `top`, `bottom` |
| `position` | `0.5` | Posição na borda (0–1) |
| `alwaysOpen` | `false` | Manter notch desdobrado |
| `hideInFullscreen` | `true` | Esconder em tela cheia |
| `scale` | `1.0` | Escala do notch |
| `textScale` | `1.0` | Escala do texto |
| `openDelay` | `150` | Delay para abrir (ms) |
| `refreshInterval` | `60` | Intervalo de refresh (s) |
| `color` | `#000000` | Cor do corpo |
| `opacity` | `1.0` | Opacidade do corpo |
| `disabledProviders` | `[]` | IDs de providers desabilitados |

**Logs e cache:** `/tmp/codenotch-plasma.log` · `~/.cache/codenotch/readings.json`

## Desinstalar

```bash
./uninstall.sh
```

Config e cache do usuário são preservados.

## Privacidade

Codenotch lê credenciais **apenas localmente** e nunca as envia para servidores de terceiros além das APIs oficiais de cada provider. Nenhum dado é coletado pelo próprio Codenotch.

## Créditos

- Design, geometria, paleta e glyphs: [vinzdg/codenotch](https://github.com/vinzdg/codenotch)
- Port GNOME: [RicardoEGG/codenotch-gnome](https://github.com/RicardoEGG/codenotch-gnome)
- Port KDE Plasma: [williamccampos/codenotch-plasma](https://github.com/williamccampos/codenotch-plasma)

## Licença

[MIT](LICENSE)
