<!-- LTeX: language=pt-BR -->

# doc-intake-pipeline - Regras do projeto

Regras que valem em todo chat e todo agente (o `CLAUDE.md` importa este arquivo). Estado do projeto e versões ficam fora daqui: estado em `docs/PROJECT_SESSION_SUMMARY.md`, arquitetura em `docs/ARCHITECTURE.md`.

## O que é este projeto

Pipeline que lê documentos (PDF e imagem, inclusive escaneados), extrai campos com um LLM e devolve um resultado **validado e com citação da origem** de cada campo. A qualidade é medida por **evals** contra um conjunto-ouro, e o CI barra qualquer piora. É peça de portfólio para clientes: cada decisão precisa ser defensável numa entrevista.

Invariantes (valem em todo PR):

1. **Nada inventado:** campo sem evidência no documento sai `null` com o motivo; nunca um valor plausível.
2. **Toda saída passa pelo schema** (Pydantic). JSON malformado ou inválido tem nova tentativa limitada; esgotadas, o documento sai como falha explícita para revisão humana, nunca parcial em silêncio.
3. **Provedor de LLM atrás de uma interface:** o núcleo não importa SDK de provedor; trocar Claude por OpenAI é configuração.
4. **Testes unitários não chamam rede nem gastam API:** usam um provedor falso. Chamada real só no eval com chave, rodado de propósito.
5. **Dinheiro em `Decimal`, datas em ISO 8601.**
6. **Log sem conteúdo do documento** por padrão: ids, métricas, custo e resultado da validação, não o texto extraído.

## Regra de ouro: todo teste foi visto falhando

1. **Teste antes do código (TDD):** escreva o teste, rode e veja FALHAR pelo motivo esperado; implemente o mínimo (GREEN); refatore com tudo verde.
2. **Mutação:** se o teste nasce verde, altere a expectativa ou o código e veja-o falhar com mensagem útil; desfaça.

Registre no PR como o RED foi visto (comando e erro). Portões (lint, tipos, CI, eval) seguem a mesma regra: prove com uma sonda que reprovam o que devem. **Eval também é teste:** um portão de eval só entra provado por uma piora proposital que ele barra.

## Melhores práticas sempre

- Havendo mais de um caminho, recomende o indicado pelas melhores práticas e cite o princípio (YAGNI, fail fast, test isolation...).
- Em dúvida, **consulte a documentação oficial na versão usada no projeto** antes de sugerir ou perguntar; sem citar de memória. A sugestão traz fontes, recomendação e o que é julgamento próprio.
- Sem atalhos por conveniência (`skip` para silenciar falha, `# noqa`/`# type: ignore` sem motivo, `Any`). Desvio só com justificativa no PR ou na documentação.
- Cada dependência entra na missão que a usa (YAGNI).
- Regra deste arquivo que não siga as melhores práticas é substituída, não contornada.

## Ciclo de missão (uma missão por chat)

Contexto longo degrada a qualidade; cada chat cuida de **uma missão** (uma GitHub Issue) e **o estado mora no repositório, não na conversa**.

**Início de cada chat** (automático, e quando o usuário disser "próxima missão"):

1. Ler `docs/PROJECT_SESSION_SUMMARY.md`.
2. Listar issues e PRs abertos (`gh issue list`, `gh pr list`).
3. Propor a missão de maior prioridade e confirmar com o usuário. Prioridade: bloqueio → segurança → visibilidade → dívida técnica (labels `priority: P0/P1/P2`). No empate, a issue de menor número, porque cada missão se apoia nas anteriores.

**Fechamento** (automático): skill `/mission:close-mission` (plugin `mission`); o registro da missão vai no corpo do PR, e o resumo de sessão guarda só o estado e a próxima missão.

**Contratos** do plugin `mission` ([formato](https://github.com/brunoccalmeida/automation-template/blob/main/plugins/mission/README.md)); a primeira coluna é o nome que as skills procuram. Valores confirmados na missão #1:

| Contrato          | Valor                             |
| ----------------- | --------------------------------- |
| `check`           | `uv run poe check`                |
| `test`            | `uv run pytest`                   |
| `main-branch`     | `main`                            |
| `gate`            | `ci-passed`                       |
| `session-summary` | `docs/PROJECT_SESSION_SUMMARY.md` |

Revisões específicas do projeto ficam em [REVIEW.md](REVIEW.md).

## Gasto de tokens (contexto)

- Filtre saídas na origem (`grep`, `head`, `--jq`, `gh run view --log-failed`, `pytest -q`); nunca despeje log inteiro.
- Subagente só com motivo: trabalho paralelo independente, saída volumosa ou revisor independente.
- Eval com chave real custa dinheiro: rode no menor subconjunto que responde à pergunta e diga o custo antes de rodar o conjunto inteiro.

## Espere o estado ficar pronto antes de agir

- **"Ainda não sei" não é "sim":** pendente, `UNKNOWN` ou resposta vazia significam esperar.
- **Espere por condição, nunca por tempo.**
- **Checks de CI:** logo após um push, os checks verdes ainda são do commit anterior; consulte pelo SHA da head atual, e check ausente é pendente.

## Diagnóstico de erros

Nunca "chute" soluções: **observe** (mensagem completa, stack trace), **contextualize**, **investigue** o mesmo padrão em outros lugares, ache a **causa raiz** (bug do código, do prompt, do dado do gabarito ou do provedor?), **corrija** em todos os locais afetados e **valide** sem regressão (repita se a falha era intermitente).

Ao reportar: **erro observado**, **causa raiz**, **análise**, **solução proposta** com justificativa e **prevenção**.

## Comunicação

- O critério é **quem lê**. Tudo o que se dirige ao usuário sai em **português (Brasil)**: a conversa, os planos, as notas de progresso e as caixas de pergunta (`AskUserQuestion`: pergunta, opções, descrições e prévias), mesmo sendo entrada estruturada de ferramenta. A documentação interna (regras, resumo de sessão, arquitetura) também.
- Em **inglês**, só o que é publicado com o código: código, commits, issues, PRs, README e relatórios de eval.
- O idioma das respostas é fixado também pela configuração `language` no `~/.claude/settings.json` do usuário ([settings](https://code.claude.com/docs/en/settings-reference.md)), porque este arquivo chega como mensagem de usuário, sem garantia de cumprimento ([memory](https://code.claude.com/docs/en/memory.md)), e deixou notas curtas de progresso saírem em inglês (#43, medição na #50). A instrução que ela gera fala em "comments": isso vale para comentários ao usuário, não para comentários de código, que seguem em inglês com o resto do que é publicado.
- Explicar o **porquê**; opiniões fundamentadas, não só concordância.

## Segurança

- Nunca commitar credenciais; chaves de API só em `.env` (fora do Git) ou em secrets do GitHub.
- Configuração vem de variáveis de ambiente validadas na inicialização (`pydantic-settings`); nunca no código.
- Documento de cliente nunca entra no repositório; o conjunto-ouro só usa dados públicos com licença registrada em `docs/DATA.md`.
- Não contorne as travas do agente nem a proteção da `main`.

## Git e Pull Requests

- **Conventional Commits** (`feat`, `fix`, `refactor`, `test`, `docs`, `style`, `perf`, `build`, `ci`, `chore`; escopo opcional), commits atômicos.
- Antes de commitar: `check` verde.
- **Nada vai direto para a `main`:** branch própria e PR.
- **Um PR aberto por vez**; trabalho pronto espera em commit local até a fila esvaziar.
- **Merge só pelo usuário** (skill `/mission:ship-pr`). Nunca `--admin`.
- Ruleset, repositório e demais configurações públicas: confirmar com o usuário antes.

## Princípios

Explícito é melhor que implícito; simples é melhor que complexo; legibilidade conta; erros nunca passam em silêncio; diante da ambiguidade, recuse a tentação de adivinhar.
