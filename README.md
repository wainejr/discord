# Discord Bot — Acelerado

Projeto aberto para toda a comunidade do canal [Waine — Dev do Desempenho](https://www.youtube.com/@waine_jr).

## Descrição

O **Acelerado** é um bot de Discord que:

- anuncia novos vídeos e lives do YouTube no canal da comunidade;
- sincroniza membros do YouTube com o cargo `Registradores` no Discord;
- avisa quando o token OAuth do YouTube está prestes a expirar;
- oferece uma CLI (`typer`) com subcomandos utilitários e uma TUI (`textual`) para monitoramento ao vivo.

Construído com `discord.py` 2.x, `google-api-python-client`, `pydantic-settings`, `typer`, `textual` e `rich`.

## Pré-requisitos

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) para gerenciamento de dependências
- Uma aplicação de Bot no [Discord Developer Portal](https://discord.com/developers/applications) (com o intent de **Server Members** ligado)
- Credenciais OAuth 2.0 do Google Cloud com a **YouTube Data API v3** habilitada

## Instalação

```sh
pip install -U uv
uv sync
```

## Configuração

1. **Variáveis de ambiente** — copie o exemplo e preencha:

   ```sh
   cp .example.env .env
   ```

   Variáveis obrigatórias (validadas por `pydantic-settings`):

   | Variável                        | Descrição                                      |
   |---------------------------------|------------------------------------------------|
   | `DISCORD_TOKEN`                 | Token do bot no Discord                        |
   | `DISCORD_GUILD_ID`              | ID do servidor (guild)                         |
   | `DISCORD_ANNOUNCE_CHANNEL_ID`   | Canal onde novos vídeos serão anunciados       |
   | `DISCORD_LOG_CHANNEL_ID`        | Canal para avisos internos (ex: token expira)  |
   | `YOUTUBE_CHANNEL_ID`            | ID do canal do YouTube a monitorar             |
   | `YOUTUBE_API_KEY`               | Chave de API do YouTube (fallback sem OAuth)   |
   | `ACELERADO_TICK_SECONDS`        | (opcional) Período do loop, default `300`      |
   | `ACELERADO_LOG_LEVEL`           | (opcional) `DEBUG`/`INFO`/`WARNING`/…           |
   | `ACELERADO_AUTO_THREAD`         | (opcional) Auto-cria thread no anúncio de vídeo, default `true` |
   | `DISCORD_WELCOME_CHANNEL_ID`    | (opcional) Canal pra mensagem de boas-vindas. Se `0`/vazio, tenta DM. |
   | `DISCORD_MODS_CHANNEL_ID`       | (opcional) Canal privado de mods. Recebe `/report` e logs de bloqueios anti-spam. |
   | `ACELERADO_INVITE_WHITELIST`    | (opcional) Lista de guild IDs (separados por vírgula) cujos convites NÃO são bloqueados. |

2. **Credenciais OAuth do Google** — copie o exemplo e substitua pelos valores da sua app:

   ```sh
   cp credentials.example.json credentials.json
   ```

   Na primeira execução que precisar da API do YouTube (por ex. `acelerado run` ou `acelerado refresh-token`), o navegador abrirá para consentimento e o token será salvo em `token.pickle`.

## Slash commands no Discord

| Comando | Descrição |
|---------|-----------|
| `/links` | Lista os canais/redes oficiais (resposta ephemeral, só você vê). |
| `/sync` | (admin) Força a sincronização de cargos `Registradores` na hora — útil quando alguém acabou de virar membro pago no YouTube e não quer esperar o tick. |
| `/update` | (admin) Faz `git pull` + `uv sync` e reinicia o bot via wrapper (exit code 75). Veja "Restart automático" abaixo. |
| `/report` | Reportar uma mensagem aos mods. Recebe link da mensagem (Copy Message Link) + motivo. Rate-limit de 3 reports / 10min por usuário. |

Todos os slash commands são **guild-scoped** — registrados no servidor configurado em `DISCORD_GUILD_ID`, propagam instantaneamente. Para adicionar um novo, ver `acelerado/slash.py`.

## Uso — CLI

Toda a funcionalidade administrativa é exposta por um único entrypoint `acelerado`, montado com `typer`:

```sh
uv run acelerado --help
```

| Subcomando                    | O que faz                                                               |
|-------------------------------|-------------------------------------------------------------------------|
| `acelerado run`               | Inicia o bot (processo longo; é o comando do systemd).                  |
| `acelerado status`            | Mostra expiração do token e contagem de vídeos já anunciados.           |
| `acelerado monitor`           | Abre a TUI (`textual`) com contagem regressiva do token ao vivo e lista de anúncios recentes. |
| `acelerado audit-members`     | Lista membros com o cargo `Registradores` que perderam o cargo do YouTube (tabela `rich`). |
| `acelerado refresh-token`     | Faz backup de `token.pickle` e refaz o fluxo OAuth.                     |
| `acelerado update`            | Faz `git pull --ff-only` + `uv sync --frozen`. Sai com exit 75 se atualizou; o wrapper externo deve restartar. |
| `acelerado healthcheck [--max-age N]` | Lê `last_tick.txt` e retorna exit 0 (ok) ou 1 (stale/missing). Default `--max-age` = 2× tick interval. Útil em cron. |

### Logs

O logger padrão é `INFO`. Pra aumentar verbosidade:

```sh
uv run acelerado --log-level DEBUG run
# ou via env var
ACELERADO_LOG_LEVEL=DEBUG uv run acelerado run
```

Em `DEBUG` os logs do `discord.py`, `googleapiclient` e `urllib3` também são liberados; em níveis superiores ficam silenciados em `WARNING` pra reduzir ruído.

### TUI (monitor)

```sh
uv run acelerado monitor
```

Teclas: `q` pra sair, `r` pra recarregar manualmente. A tela é atualizada a cada 1s, mostrando a expiração do token e os últimos 15 vídeos em `published.txt`.

## Deploy

O bot é "à prova de falhas": cada passo do tick é isolado em try/except, falhas são logadas localmente E reportadas no canal de log do Discord (com cooldown de 10 min pra não spammar). Loops com erro são reiniciados automaticamente. Em caso de crash do processo, basta restartar.

Recomendação: rode dentro de um `tmux` (ou `screen`) — assim sobrevive ao logout e dá pra reanexar a sessão.

```sh
tmux new -s acelerado
uv run acelerado run
# Ctrl+B, D pra desanexar
# tmux attach -t acelerado pra reanexar depois
```

### Restart automático — `scripts/run.sh`

Pra reiniciar automaticamente em caso de crash **ou** após `acelerado update` / `/update`, use o supervisor incluso:

```sh
bash scripts/run.sh
```

Ou, recomendado, dentro de tmux:

```sh
tmux new -s acelerado 'bash scripts/run.sh'
# Ctrl+B, D pra desanexar / tmux attach -t acelerado pra reanexar
```

O script:

- Restarta o bot quando ele sai com exit **75** (`EX_TEMPFAIL` — `acelerado update` ou `/update` pediu restart).
- Restarta com **backoff exponencial** (2s → 4s → … → cap 60s) em caso de crash (exit ≠ 0/130/143). Evita loop tight de restart se o bot tiver bug fatal.
- **Encerra o loop** com exit 0 (shutdown limpo via Ctrl+C → 130) ou em SIGTERM (143).
- Loga cada evento com timestamp.

Se quiser inspecionar o que o script faz, é tudo bash puro em `scripts/run.sh` (~30 linhas).

Pra copiar um `token.pickle` renovado pra uma máquina remota (ex.: Raspberry Pi), há o utilitário `scripts/send_token.sh` (ajuste o host `home_rasp` pro seu `~/.ssh/config`).

## Testes

A suíte roda totalmente **offline** — nenhum request ao Discord ou ao YouTube é feito. O cliente do Google é substituído por um `MagicMock` encadeável e o Discord é representado por `MagicMock`/`AsyncMock` nos pontos que `AceleradoState` consome.

```sh
uv run pytest             # roda tudo (58 testes)
uv run pytest -q          # saída concisa
uv run pytest tests/test_state.py -k announce   # filtro por nome
```

Cobertura atual inclui:

- **`test_youtube.py`** — helpers puros (`is_*`, `get_video_*`) e chamadas mockadas da API.
- **`test_state.py`** — `AceleradoState`: filtros de anúncio, `published.txt`, mensagens (`@everyone`, livestream, membros), rate-limit de aviso de expiração, sync de cargos (incluindo o caso especial de ignorar o user `eniaw`).
- **`test_env.py`** — carregamento e validação de `pydantic-settings`.
- **`test_log.py`** — idempotência de `setup_logging` e gating de níveis.
- **`test_cli.py`** — smoke tests com `typer.testing.CliRunner`.

Fixtures em `tests/conftest.py` isolam cada teste em `tmp_path` e limpam os caches `@lru_cache` entre runs.

## Qualidade de código

```sh
uv run ruff check .                    # lint
uv run ruff format .                   # formatação
uv run mypy acelerado                  # type check
uv run pytest --cov                    # com coverage
```

A pipeline de CI (`.github/workflows/ci.yml`) roda `ruff check`, `ruff format --check`, `mypy` e `pytest --cov` em pushes/PRs pra `main`. Quebrou alguma checagem? O CI te avisa antes do merge.

Configuração em `pyproject.toml`:
- Ruff: linha 100, target `py311`, regras `E,F,I,UP,B`, exclui `examples/`.
- Mypy: pragma — `ignore_missing_imports`, `check_untyped_defs`, `warn_unused_ignores`, plugin `pydantic.mypy`.
- Coverage: branch coverage habilitada, `__main__.py` excluído.

## Estrutura do projeto

```
acelerado/
  __main__.py     # wrapper fino: python -m acelerado -> cli.app
  cli.py          # typer app + callback global (--log-level)
  bot.py          # AceleradoBot (commands.Bot) + setup_hook + tasks.loop
  state.py        # AceleradoState — orquestra cada tick de 5 min
  youtube.py      # OAuth + YouTube Data API (clientes com @lru_cache)
  tui.py          # MonitorApp em textual
  env.py          # configuração via pydantic-settings
  log.py          # setup_logging() com RichHandler
tests/            # suíte offline com pytest + pytest-asyncio
scripts/
  send_token.sh             # envia token.pickle pra host remoto (SCP)
.github/workflows/
  ci.yml                    # ruff + mypy + pytest em PRs/pushes
examples/         # payloads de exemplo da API do YouTube
published.txt     # IDs de vídeos já anunciados (não apagar em produção!)
credentials.json  # segredos OAuth do Google (gitignored)
token.pickle      # token OAuth em cache (gitignored)
.env              # configuração (ver .example.env)
```

## Como contribuir

1. Faça um fork deste repositório.
2. Clone o seu fork:

   ```sh
   git clone https://github.com/seu-usuario/discord.git
   ```

3. Crie uma branch:

   ```sh
   git checkout -b minha-feature
   ```

4. Faça mudanças, rode lint + testes:

   ```sh
   uv run ruff check . && uv run ruff format . && uv run pytest
   ```

5. Commit e push:

   ```sh
   git commit -am "Minha nova feature"
   git push origin minha-feature
   ```

6. Abra um Pull Request no repositório original.

Consulte a [documentação do discord.py](https://discordpy.readthedocs.io/en/stable/) e do [typer](https://typer.tiangolo.com/) quando for mexer em comandos novos. Para novos testes, siga o padrão em `tests/conftest.py` — nada de chamadas reais à rede.

## Relatar problemas

Se encontrar algum bug, abra uma issue detalhando o erro (stack trace, passos pra reproduzir, nível de log). Rodar com `--log-level DEBUG` ajuda bastante no diagnóstico.

## Links importantes

- [Canal do YouTube](https://www.youtube.com/@waine_jr)
- [Servidor do Discord](https://discord.gg/RHuhFcfzyV)
- [@waine_jr no Instagram](https://instagram.com/waine_jr)

## Licença

Projeto licenciado sob a [MIT License](./LICENSE).

## Contato

Pra dúvidas ou mais informações, fale no servidor do Discord ou comente no canal do YouTube.

Obrigado por fazer parte da comunidade!
