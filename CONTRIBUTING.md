# Como contribuir

Obrigado por considerar contribuir com o Acelerado! Esse guia é o caminho rápido.

## Pré-requisitos

- **Python 3.11+**
- [`uv`](https://docs.astral.sh/uv/) — `pip install -U uv`
- Conta no [Discord Developer Portal](https://discord.com/developers/applications) para criar um bot de testes.
- (Opcional) Credenciais OAuth do Google + chave da YouTube Data API v3 — só se for mexer com a parte de YouTube.

## Setup local

```sh
git clone https://github.com/seu-usuario/discord.git
cd discord
uv sync                                 # instala deps + dev deps
cp .example.env .env                    # depois edite com seus valores
cp credentials.example.json credentials.json   # depois cole o JSON da app Google
```

Veja a seção **"Como obter credenciais"** no [`README.md`](./README.md) pra um passo-a-passo de Discord + Google Cloud.

## Workflow de contribuição

1. **Branch**: `feat/<descrição-curta>`, `fix/<bug>`, `docs/<o-que>`.
2. **Antes de commitar**, rode o "CI local":

   ```sh
   uv run ruff check . && \
   uv run ruff format --check . && \
   uv run mypy acelerado && \
   uv run pytest
   ```

   Se algo falhar, ajusta. CI no GitHub Actions roda exatamente isso em PRs/pushes pra `main`.
3. **Commit**: mensagem descritiva, idealmente referenciando a issue (`closes #N` no body fecha automaticamente no merge).
4. **PR**: descrição clara, checklist de smoke tests, espera review.

## Convenções

### Idioma
- **UI / Discord**: PT-BR (mensagens, role names, comandos).
- **Código** (variáveis, funções, comentários, docstrings, mensagens de log): inglês.

### Logging
Cada módulo declara seu logger:
```python
import logging
logger = logging.getLogger(__name__)
```
Não importe um `logger` compartilhado de `acelerado.log` — o handler global é configurado uma vez via `setup_logging()` no callback do typer.

### Testes
Tudo offline. Discord e Google YouTube API são mockados via fixtures de `tests/conftest.py`:
- `fake_bot`, `fake_guild` — stand-ins de `commands.Bot` / `discord.Guild`.
- `make_video_fn`, `make_playlist_item_fn` — builders de payload.
- `_fake_youtube_client()` em `tests/test_youtube.py` — mock encadeável da Google API.

Nunca abra socket, nunca dispara OAuth.

### Contrato fail-proof
Toda corotina dentro de um tick (passos do `event_loop`) **não deve raise** — falhas devem cair em `state.report_error("contexto", exc)`, que loga local e posta no canal de log do Discord (com cooldown de 10 min). O guard externo em `bot.event_loop_task` é a última rede; não confie nele pra lógica.

Veja `CLAUDE.md` ("Fail-proof contract") pra detalhes.

### Slash commands
Vão em `acelerado/slash.py` ou módulos próprios. Pra adicionar um novo:

1. Definir com `@app_commands.command(...)`.
2. `tree.add_command(seu_cmd, guild=guild)` no `register_commands`.
3. Teste de registro em `tests/test_slash.py` (ou módulo afim).
4. Documentar no README.

## Tarefas iniciais

Issues marcadas com **`good first issue`** são bem delimitadas e ótimas pra começar — geralmente self-contained, com critérios de aceite claros e cobertura de teste pequena.

## Contexto profundo

[`CLAUDE.md`](./CLAUDE.md) tem o overview arquitetural — stack, layout, contratos, e gotchas. Vale a leitura antes de mexer em algo grande.

## Reportando bugs

Issue com:
- **O que aconteceu** vs. o que era esperado.
- **Como reproduzir** (passos + comando, se possível).
- **Stack trace** completo. Rodar com `--log-level DEBUG` ajuda muito.
- Versão do Python, do bot (commit hash) e SO.

## Código de conduta

Seja gentil. Aqui é uma comunidade de gente curiosa que gosta de programação de baixo nível e cafezinho.

Obrigado!
