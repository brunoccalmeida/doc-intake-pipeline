<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado |
| ---------------- | ------ |
| Última missão    | [#38](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/38): carga de revisão medida e portão de valor errado aceito ([D16](ARCHITECTURE.md)). O resultado nomeia em `review` os campos a conferir; o eval conta, por campo, aceitos, enviados à revisão e vazios, e barra o aumento de `wrong_accepted`. Medido: 70 de 100 aceitos (0 errados), 25 em revisão (3 errados), 5 vazios. Sem gravação nova nem gasto |
| Próxima missão   | [#39](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/39) vídeo de 60 s com legenda para clientes (P1, menor número; cita o número da #38). Depois, [#40](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/40) README para clientes, que embute o vídeo |
| Pendências       | P1: [#39](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/39) vídeo para clientes; [#40](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/40) README para clientes. P2: [#11](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/11) Python 3.15 (espera wheels); [#35](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/35) calibrar aceite automático com conjunto maior (licença do CORD v2 a conferir) |
| PRs abertos      | nenhum após o merge da #38 |
| Gravações do eval | Repositório privado `brunoccalmeida/doc-intake-recordings`, clonado em `.cache/recordings`; commit fixado em `evals/recordings.json`; CI lê com deploy key somente leitura (secret `RECORDINGS_DEPLOY_KEY` no Actions e no Dependabot). Regravar: `uv run poe eval --record` (pago), push lá, atualizar pino e linha de base no mesmo PR ([DATA.md](DATA.md)). Desde a #23 o clone também guarda as 20 respostas ao prompt piorado da cena 4 do demo (não são órfãs); a cena 2 grava em `demo/recordings` (público). Mudança de prompt, schema, OCR ou modelo também regrava o demo (`demo/README.md`) |
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
- O `Settings` lê o `.env` da raiz, onde está a chave real: nos testes, o fixture autouse `no_real_credentials` deixa vazias as chaves e o perfil do `ant`. Nunca remova essas variáveis num teste que roda na raiz (já gerou uma chamada paga na #6).
- `ant` (CLI da Anthropic) fica em `~/.local/bin/ant.exe`, instalado pelo zip do release com SHA-256 conferido; perfil em `%APPDATA%\Anthropic`. O `ant auth login` com redirecionamento não gravou o perfil nesta máquina; usar `ant auth login --no-browser` (no navegador: entrar no Console, escolher organização e workspace, copiar o código e colar no terminal). Conferir com `ant auth status`. Token de acesso dura 8 h; o SDK renova sozinho.
- Rodar uma extração pelo perfil sem mexer no `.env`: `DOC_INTAKE_ANTHROPIC_API_KEY= DOC_INTAKE_ANTHROPIC_PROFILE=default uv run poe extract <arquivo>` (variável vazia vence o `.env` e conta como não definida). `extract` sai com 1 em todo status diferente de `ok`, inclusive `needs_review`.
- Rodar na OpenAI só com a chave no `.env`: `DOC_INTAKE_PROVIDER=openai DOC_INTAKE_OPENAI_MODEL=gpt-6-luna uv run poe extract <arquivo>` (~US$ 0,0005 por recibo; o padrão, `gpt-6.2-astra`, ~US$ 0,037). Recibo sintético: gerar com Pillow no scratchpad (fonte `consola.ttf`), nunca no repositório. O `/tmp` do Git Bash não existe para o Python do Windows: arquivo temporário vai no scratchpad.
- O agente não faz push na `main` de nenhum repositório (trava), inclusive no de gravações: o push de lá é do usuário. Para provar o RED do eval, corromper uma gravação numa branch do repositório privado e disparar o CI com `gh workflow run ci.yml --ref <branch>`.
- Nunca encadear o commit depois de `check | tail` com `&&`: o pipe devolve o status do `tail`, e o commit entra com o `check` vermelho (aconteceu na #26). Rodar `uv run poe check >/dev/null; echo $?` sozinho antes.
- Gravação paga: revisor **antes** de gravar (achado de revisão muda prompt ou schema e invalida as chaves) e piloto com `uv run poe eval --record --ids ...` nos recibos que respondem à pergunta; o `RecordingProvider` reaproveita o piloto na rodada completa, sem custo extra.
- Desde a #26, o pedido leva a imagem da página: mudar o ingest (bytes ou rótulo da imagem) também muda as chaves.
- Toda mudança em `core/ingest.py` muda o texto do OCR e, com ele, a chave das gravações (o hash inclui o texto): é regravação paga. Antes do `--record`, comparar as candidatas offline (citação do gabarito presente no texto do OCR, por campo, nos 20 recibos) e conferir quais gravações seguem válidas; na #19, gravar antes custou uma rodada à toa. Depois, apagar as órfãs, para o repositório de gravações guardar só o que o eval lê.
- Logging é estado global do processo: o `main()` dos scripts configura o logger `core.runlog` sem propagação, e o fixture autouse `restore_run_logger` (`tests/conftest.py`) o restaura a cada teste. Sem ele, testes com `caplog` passam ou falham conforme a ordem.
- Script de análise no scratchpad (fora do repositório) não acha `core`: rodar com `PYTHONPATH=. uv run python <script>` a partir da raiz. Valores do SROIE ficam só na saída local; doc, issue e PR descrevem o caso sem citá-los (D6).
- O Docker Desktop fica desligado: abrir antes de comparar algo com o Linux (`python:3.14-slim` + binário do `uv` copiado de `ghcr.io/astral-sh/uv:0.13.9`).
- VHS (demo): o `Wait` compara a linha sem o espaço final (prompt `$ ` chega como `$`): esperar `/\$$/`. Todo `Wait` nomeia o estado exato (código de saída, veredito); um padrão frouxo filma a falha como sucesso.
- Mutação que mexe em `--record` grava no diretório padrão `.cache/recordings` (o clone privado), porque o `no_doc_intake_env` apaga a variável do diretório: fazer a mutação apontando para `tmp_path`, e conferir `git status` do clone depois.
- `grep ... | head && rm` apaga mesmo quando o `grep` não casa (o `head` devolve 0): conferir o conteúdo num passo e apagar em outro.
- As citações do conjunto-ouro vêm da imagem (`source: "image"`): uma resposta montada a partir do gabarito vai inteira para revisão. Teste que precisa de valor **aceito** cita uma palavra do texto do OCR (`wrong_total_from_page_text` em `tests/test_eval_script.py`).
- Chave de API vai no `.env` (criado com `Copy-Item .env.example .env`), nunca no `.env.example`, que é versionado. O agente não lê nem grava o `.env`; `uv run poe extract <arquivo>` falha nomeando a variável que falta, sem gastar nada.

## Medida de esforço

Semana 1 (#1 a #7) fechada: ~1,6 h de atenção do usuário e ≥ 2,2 h de agente, contra ~16 h estimadas; tabela por missão e método no PR da #18. Horas humanas não medem projeto conduzido por agente: medir **atenção do usuário** e **trabalho do agente**, reconstruídos das transcrições locais (`~/.claude/projects/<projeto>/*.jsonl`). A métrica oficial equivalente, `claude_code.active_time.total` com `type=user`/`cli` ([Monitoring usage](https://code.claude.com/docs/en/monitoring-usage)), exige telemetria ligada; não ligada (YAGNI).
