<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado |
| ---------------- | ------ |
| Última missão    | [#1](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/1): esqueleto, uv/ruff/pyright/pytest, CI com `ci-passed` e ruleset (decisões na D7 do [ARCHITECTURE.md](ARCHITECTURE.md)) |
| Próxima missão   | [#2](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/2): schema Pydantic do recibo e do resultado com citação (P0, menor número) |
| PRs abertos      | nenhum após o merge da #1 |
| Portões          | `uv run poe check` (ruff, formatação, pyright estrito) e `uv run pytest`; no CI, `ci-passed` agrega `check`, `test`, `secret-scan` (gitleaks), `workflow-audit` (zizmor) e `dependency-audit` (`uv audit`, também diário) |
| Repositório      | Ruleset "Protect main": PR só com squash, histórico linear, `ci-passed` obrigatório com branch atualizada; squash usa título e corpo do PR; auto-merge e apagar branch ligados; alertas e atualizações de segurança do Dependabot ligados |
| Travas do agente | `.claude/settings.json` nega merge `--admin`, force push, push na `main` e leitura/escrita do `.env`; plugin `mission` com `autoUpdate: false` |

### Armadilhas do ambiente (Windows)

- uv fica em `~/.local/bin`, fora do PATH do Git Bash: `export PATH="$HOME/.local/bin:$PATH"`.
- `astral.sh` não resolve no PowerShell desta máquina: instalar o uv pelo instalador do release no GitHub.
- Git Bash reescreve `gh api /caminho` como caminho de arquivo: usar o endpoint sem a barra inicial.
- Workflow reutilizável do mesmo repositório usa `$/...` (sintaxe self-repository); o zizmor reprova `./...`.

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
