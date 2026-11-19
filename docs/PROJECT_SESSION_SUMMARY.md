<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado |
| ---------------- | ------ |
| Última missão    | [#6](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/6): eval por campo com replay de respostas gravadas e portão de tolerância zero no CI (D4 do [ARCHITECTURE.md](ARCHITECTURE.md)). Linha de base (Opus 5.5): company 15, address 9, date 17, total 18, currency 17, em 20 |
| Próxima missão   | [#7](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/7): log por execução e custo por documento (P1, menor número entre as P1 desbloqueadas). Reaproveita `core/pricing.py` e `core.llm.Metered` |
| Pendências       | P1: [#18](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/18) perguntas ao usuário em português no `AGENTS.md`; [#19](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/19) OCR vazio em 2 recibos desbotados; [#20](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/20) valor copiando erro do OCR; [#13](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/13) execução na OpenAI (sem crédito). P2: [#16](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/16) moeda `$`, agora com números do eval |
| PRs abertos      | nenhum após o merge da #6 |
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
- O Docker Desktop fica desligado: abrir antes de comparar algo com o Linux (`python:3.14-slim` + binário do `uv` copiado de `ghcr.io/astral-sh/uv:0.13.9`).
- Chave de API vai no `.env` (criado com `Copy-Item .env.example .env`), nunca no `.env.example`, que é versionado. O agente não lê nem grava o `.env`; `uv run poe extract <arquivo>` falha nomeando a variável que falta, sem gastar nada.

## Plano da semana 1 (~16 h)

| Issue | Missão                                                                          | Horas |
| ----- | ------------------------------------------------------------------------------- | ----- |
| #1    | Esqueleto: `core/`, `packs/`, `workflows/`, `evals/`, ambiente Python, lint e testes no CI | ~2    |
| #2    | Schema Pydantic do recibo/nota fiscal e do resultado, com citação da origem      | ~1,5  |
| #3    | Leitura de PDF e imagem, com OCR para documento escaneado                       | ~3    |
| #4    | Extrator com LLM, provedor trocável, saída validada e nova tentativa             | ~3    |
| #5    | Conjunto-ouro: 20 recibos do SROIE com gabarito convertido para o schema         | ~2    |
| #6    | Eval: precisão por campo, relatório Markdown e CI barrando piora                 | ~3    |
| #7    | Log por execução e custo por documento                                           | ~1,5  |

No fim da semana: conferir horas reais contra a estimativa e o que entra no vídeo de demonstração.
