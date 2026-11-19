<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado |
| ---------------- | ------ |
| Última missão    | [#20](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/20): valor de texto continua igual à citação, mesmo com erro do OCR ([ARCHITECTURE.md](ARCHITECTURE.md) D11); sem regravação, linha de base inalterada (company 16, address 10, date 17, total 18, currency 19) |
| Próxima missão   | [#26](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/26): mandar a imagem da página junto com o OCR (P1 desbloqueada; a #13 espera crédito na OpenAI). 17 dos 20 campos errados não têm o valor certo no texto do OCR, só na imagem |
| Pendências       | P1: [#13](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/13) execução na OpenAI (sem crédito; vai precisar do preço do modelo em `core/pricing.py`, senão o script para antes da chamada). P2: [#16](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/16) moeda `$`; [#23](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/23) vídeo de demonstração |
| PRs abertos      | nenhum após o merge da #20 |
| Gravações do eval | Repositório privado `brunoccalmeida/doc-intake-recordings`, clonado em `.cache/recordings`; commit fixado em `evals/recordings.json`; CI lê com deploy key somente leitura (secret `RECORDINGS_DEPLOY_KEY` no Actions e no Dependabot). Regravar: `uv run poe eval --record` (pago), push lá, atualizar pino e linha de base no mesmo PR ([DATA.md](DATA.md)) |
| Portões          | `uv run poe check` (ruff, formatação, pyright estrito) e `uv run pytest` (exigem antes `uv run poe fetch-tessdata` e `uv run poe fetch-golden`; sem os dados os testes falham, não pulam); `uv run poe eval` (replay, sem custo); no CI, `ci-passed` agrega `check`, `test`, `eval`, `secret-scan` (gitleaks), `workflow-audit` (zizmor) e `dependency-audit` (`uv audit`, também diário) |
| Repositório      | Ruleset "Protect main": PR só com squash, histórico linear, `ci-passed` obrigatório com branch atualizada; squash usa título e corpo do PR; auto-merge e apagar branch ligados; alertas e atualizações de segurança do Dependabot ligados |
| Travas do agente | `.claude/settings.json` nega merge `--admin`, force push, push na `main` e leitura/escrita do `.env`; plugin `mission` com `autoUpdate: false` |

### Armadilhas do ambiente (Windows)

- uv fica em `~/.local/bin`, fora do PATH do Git Bash: `export PATH="$HOME/.local/bin:$PATH"`.
- `astral.sh` não resolve no PowerShell desta máquina: instalar o uv pelo instalador do release no GitHub.
- Git Bash reescreve `gh api /caminho` como caminho de arquivo: usar o endpoint sem a barra inicial.
- `python` no Git Bash pode travar esperando entrada (stub do Windows): rodar Python sempre por `uv run python`.
- Script Python via heredoc (ou sed) no Git Bash erra escapes com barra invertida, como o do CRLF: casa nada ou grava quebra real. Para mutação ou edição pontual, usar o Edit.
- `Path.write_text` no Windows grava CRLF; o `.gitattributes` normaliza no commit (o aviso do Git é esperado).
- Workflow reutilizável do mesmo repositório usa `$/...` (sintaxe self-repository); o zizmor reprova `./...`.
- O WebFetch reprova o certificado de `rrc.cvc.uab.es` (portal do SROIE); o `curl` do Git Bash lê a página normalmente.
- O `Settings` lê o `.env` da raiz, onde está a chave real: nos testes, o fixture autouse `no_real_api_key` a deixa vazia. Nunca remova as variáveis de chave num teste que roda na raiz (já gerou uma chamada paga na #6).
- O agente não faz push na `main` de nenhum repositório (trava), inclusive no de gravações: o push de lá é do usuário. Para provar o RED do eval, corromper uma gravação numa branch do repositório privado e disparar o CI com `gh workflow run ci.yml --ref <branch>`.
- Toda mudança em `core/ingest.py` muda o texto do OCR e, com ele, a chave das gravações (o hash inclui o texto): é regravação paga. Antes do `--record`, comparar as candidatas offline (citação do gabarito presente no texto do OCR, por campo, nos 20 recibos) e conferir quais gravações seguem válidas; na #19, gravar antes custou uma rodada à toa. Depois, apagar as órfãs, para o repositório de gravações guardar só o que o eval lê.
- Logging é estado global do processo: o `main()` dos scripts configura o logger `core.runlog` sem propagação, e o fixture autouse `restore_run_logger` (`tests/conftest.py`) o restaura a cada teste. Sem ele, testes com `caplog` passam ou falham conforme a ordem.
- Script de análise no scratchpad (fora do repositório) não acha `core`: rodar com `PYTHONPATH=. uv run python <script>` a partir da raiz. Valores do SROIE ficam só na saída local; doc, issue e PR descrevem o caso sem citá-los (D6).
- O Docker Desktop fica desligado: abrir antes de comparar algo com o Linux (`python:3.14-slim` + binário do `uv` copiado de `ghcr.io/astral-sh/uv:0.13.9`).
- Chave de API vai no `.env` (criado com `Copy-Item .env.example .env`), nunca no `.env.example`, que é versionado. O agente não lê nem grava o `.env`; `uv run poe extract <arquivo>` falha nomeando a variável que falta, sem gastar nada.

## Medida de esforço

Semana 1 (#1 a #7) fechada: ~1,6 h de atenção do usuário e ≥ 2,2 h de agente, contra ~16 h estimadas; tabela por missão e método no PR da #18. Horas humanas não medem projeto conduzido por agente: medir **atenção do usuário** e **trabalho do agente**, reconstruídos das transcrições locais (`~/.claude/projects/<projeto>/*.jsonl`). A métrica oficial equivalente, `claude_code.active_time.total` com `type=user`/`cli` ([Monitoring usage](https://code.claude.com/docs/en/monitoring-usage)), exige telemetria ligada; não ligada (YAGNI).
