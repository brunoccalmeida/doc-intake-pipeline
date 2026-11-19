<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado |
| ---------------- | ------ |
| Última missão    | [#5](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/5): conjunto-ouro SROIE fora do Git (sem licença publicada na fonte); `uv run poe fetch-golden` baixa 20 recibos de espelho fixado por commit, confere SHA-256 e converte em `.cache/golden/sroie` ([DATA.md](DATA.md), D6 do [ARCHITECTURE.md](ARCHITECTURE.md)) |
| Próxima missão   | [#6](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/6): eval por campo, relatório e portão no CI (P0). Compara texto sem diferenciar maiúsculas (o SROIE anota tudo em maiúsculas) e precisa de chave real para gravar respostas: há saldo só na Anthropic |
| Pendências       | [#13](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/13): execução manual na OpenAI (sem crédito por ora); [#16](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/16): símbolo de moeda ambíguo (`$`), decidir depois do eval |
| PRs abertos      | nenhum após o merge da #5 |
| Portões          | `uv run poe check` (ruff, formatação, pyright estrito) e `uv run pytest` (exigem antes `uv run poe fetch-tessdata` e `uv run poe fetch-golden`; sem os dados os testes falham, não pulam); no CI, `ci-passed` agrega `check`, `test`, `secret-scan` (gitleaks), `workflow-audit` (zizmor) e `dependency-audit` (`uv audit`, também diário) |
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
