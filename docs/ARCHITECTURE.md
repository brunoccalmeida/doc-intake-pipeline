<!-- LTeX: language=pt-BR -->

# Arquitetura e decisões

Documento interno (pt-BR). Decisão nova ou revista entra aqui no PR que a implementa, com o porquê.

## Objetivo

Mostrar a um cliente do Upwork que um pipeline de extração com LLM pode ser **confiável e mensurável**: cada campo traz a origem, a saída é validada, a precisão é medida por campo e o CI barra piora. O valor de portfólio está nos evals e na disciplina de testes, não no prompt.

## Fluxo

```text
arquivo (PDF/imagem)
  → ingest: texto por página (camada de texto do PDF; OCR quando não houver)
  → extract: provedor de LLM + schema do pack → JSON
  → validate: Pydantic; inválido → nova tentativa limitada, com o erro de validação no pedido
  → result: campos + citação por campo + status (ok | needs_review | failed)
  → observability: log da execução (tokens, custo, latência, tentativas)
```

## Pastas

| Pasta        | Responsabilidade                                                                                                                         |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `core/`      | Motor genérico: ingest, interface `LLMProvider`, extração com nova tentativa, validação, log e custo. Não conhece tipo de documento.        |
| `packs/`     | Um pack por tipo de documento (recibo/nota fiscal agora; contrato na semana 3): schema, instruções de extração e normalização dos campos. |
| `evals/`     | Conjuntos-ouro por pack, pontuação por campo, relatório em Markdown e a linha de base que o CI compara.                                    |
| `workflows/` | Workflows do n8n exportados (JSON) que chamam o pipeline. Entra quando for usado (YAGNI); a semana 1 não tem n8n.                          |
| `tests/`     | Testes unitários e de integração, sempre com provedor falso.                                                                              |

## Decisões

### D1. Citação da origem em todo campo

Cada campo extraído carrega `page` e `quote` (trecho literal do texto lido). Permite verificar o campo sem abrir o documento e detectar alucinação: citação que não existe no texto de entrada rebaixa o campo para `needs_review`. Coordenadas (bbox) ficam para quando um cliente pedir.

### D2. Provedor trocável por interface

`core` define um `Protocol` `LLMProvider` (pedido com schema → resposta + uso de tokens). Implementações concretas (Claude, OpenAI) ficam em módulos próprios e são escolhidas por configuração. O provedor falso dos testes implementa a mesma interface. Princípio: dependency inversion; o cliente pode exigir um provedor específico.

### D3. Nova tentativa limitada e falha explícita

JSON malformado ou fora do schema gera nova tentativa com o erro de validação no pedido, até um limite configurável (padrão 2). Esgotado, o documento sai `failed` com o último erro. Nunca resultado parcial silencioso (fail loudly). Usar a saída estruturada nativa do provedor quando existir; conferir na doc oficial de cada SDK na versão instalada.

### D4. Eval determinístico no CI (a confirmar na #6)

Recomendação: o CI pontua respostas **gravadas** do provedor (uma por documento, chaveadas pelo hash de prompt + documento + modelo), sem chave e sem custo, e compara com a linha de base commitada. Se a chave mudou (prompt ou modelo novo) e não há gravação, o CI falha pedindo nova gravação local com chave real. Assim todo PR que mexe em prompt traz a nova pontuação junto, e PR de fork roda sem secret. Alternativa descartada por ora: eval ao vivo no CI (custo por push, resultado não determinístico, secret exposto a PR).

### D5. Custo por documento

Tokens de entrada e saída vêm do `usage` da resposta do provedor; o preço por milhão de tokens fica numa tabela versionada com data e fonte (página de preços oficial), porque preço muda. Custo em `Decimal`, em USD.

### D6. Dados do conjunto-ouro

Começar pelo SROIE (recibos com gabarito de empresa, endereço, data e total). Licença e procedência registradas em `docs/DATA.md` antes de commitar qualquer arquivo (ver #5). CORD entra quando o pack de nota fiscal crescer; CUAD (contratos) na semana 3.

### D7. Ferramentas Python (decidida na #1)

| Peça | Escolha | Por quê | Fonte |
| --- | --- | --- | --- |
| Ambiente e lockfile | `uv` 0.13.9, fixado em `[tool.uv] required-version` | Um binário só para Python, venv, lock e auditoria. O `setup-uv` lê a mesma versão do `pyproject.toml`, então local e CI não divergem | [uv: GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/); `action.yml` do `astral-sh/setup-uv` v10.3.3 |
| Python | 3.14 (`.python-version`) | A 3.15 já saiu (3.15.2), mas a #3 traz bibliotecas de PDF/OCR com extensões nativas; a 3.14 tem um ano de wheels publicados. **Julgamento próprio**, rever quando a #3 fixar as dependências (comentário na #3) | [python.org: downloads](https://www.python.org/downloads/); [ciclo de vida das versões](https://devguide.python.org/versions/) |
| Projeto | `package = false` | É aplicação, não biblioteca: nada é construído nem publicado. Os pacotes são importados da raiz (`pythonpath = ["."]` no pytest) | [uv: projetos](https://docs.astral.sh/uv/concepts/projects/config/) |
| Lint e formatação | `ruff` 0.17 | Substitui flake8/isort/black num binário; famílias de regra escolhidas e comentadas no `pyproject.toml` | [ruff: regras](https://docs.astral.sh/ruff/rules/) |
| Tipos | `pyright[nodejs]` 1.1.414, `strict` | O `ty` (Astral) ainda é 0.0.x e não tem modo estrito. O extra `nodejs` é o que o README do pacote recomenda, porque traz o Node como wheel em vez de baixá-lo em tempo de execução | [pyright: instalação](https://github.com/microsoft/pyright/blob/main/docs/installation.md); [pyright-python](https://github.com/RobertCraigie/pyright-python) |
| Testes | `pytest` 9, config nativa `[tool.pytest]` com `strict = true` | `strict` liga `strict_config`, `strict_markers`, `strict_xfail` e `strict_parametrization_ids` (fail fast em config errada) | [pytest: customize](https://docs.pytest.org/en/9.0.x/reference/customize.html); [referência `strict`](https://docs.pytest.org/en/stable/reference/reference.html#confval-strict) |
| Tarefas | `poethepoet`: `uv run poe check` | `check` é uma sequência com `ignore_fail = "return_non_zero"`: roda lint, formatação e tipos mesmo após uma falha e reporta tudo de uma vez, com saída não-zero | [poe: sequence](https://poethepoet.natn.io/tasks/task_types/sequence.html) |
| Auditoria de dependências | `uv audit --locked` | Lê o `uv.lock` direto, consulta o OSV (segunda fonte além do Dependabot). É **experimental** na 0.13.9; risco aceito porque o uv é fixado e só muda num PR que roda o mesmo job | `uv audit --help` (0.13.9) |
| Atualizações | Dependabot, ecossistemas `uv` e `github-actions`, agrupados, `cooldown` de 7 dias | O Dependabot tem suporte nativo ao `uv` e atualiza o `uv.lock` | [GitHub: ecossistemas suportados](https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories) |
| Workflow reutilizável | `uses: $/.github/workflows/security.yml` | Sintaxe self-repository (julho de 2026): mesmo commit do chamador, sem depender do sistema de arquivos em tempo de execução como o `./` | [zizmor: self-repository](https://docs.zizmor.sh/audits/#self-repository); [GitHub changelog](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/) |

O UAT usa Poetry. Aqui o uv ganhou por cobrir Python, lock e auditoria com uma ferramenta só, e por ter suporte nativo no Dependabot e no `setup-uv`.

### D8. Schema e resultado (decidida na #2)

| Regra | Onde | Por quê | Fonte |
| --- | --- | --- | --- |
| Valor exige citação; vazio exige motivo; motivo só com vazio; citação só com valor; texto em branco (`""`) não é valor | `ExtractedField` (`core/result.py`) | A invariante "nada inventado" vira tipo: nenhum produtor (LLM, gabarito, teste) consegue esquecê-la | D1 |
| `failed` não carrega campos; status diferente de `ok` exige `errors`; `ok` não tem `errors` | `ExtractionResult` | Falha nunca sai parcial e nada passa em silêncio | D3 |
| Base `StrictModel`: `frozen=True, extra="forbid"` como **argumentos de classe**, repetidos em cada subclasse | `core/result.py` | Verificador de tipos só lê config passada como argumento de classe e não herda `frozen` (PEP 681); o pyright reprova subclasse que esquecer. Chave extra = produtor fora do schema | [Pydantic 2.14: Configuration](https://pydantic.dev/docs/validation/2.14/concepts/config/); [PEP 681](https://peps.python.org/pep-0681/) |
| `IsoDate` aceita só texto `AAAA-MM-DD` | `core/result.py` | O Pydantic lê timestamp Unix como data (no modo lax e, como texto, até no `strict`): qualquer número do documento viraria data. Observado com sonda no 2.14.3 e travado por teste | sonda + `tests/test_receipt.py` |
| Citação literal (`pattern=r"\S"`, sem `strip`) | `Citation.quote` | A #4 confere a citação contra o texto lido; alterá-la quebraria a conferência | D1 |
| Dinheiro `Decimal` com `ge=0`; JSON número vira `Decimal` pela representação curta (`10.10` → `10.1`, sem `10.0999…`) | `packs/receipt` | Comportamento observado, não documentado (a doc diz só "valor aceito pelo construtor de `Decimal`"): o teste trava contra mudança de versão | [Pydantic 2.14: tipos da stdlib](https://pydantic.dev/docs/validation/2.14/api/pydantic/standard_library_types/) |
| Alias PEP 695 (`type Money = ...`) para tipos com restrição | packs | Gera nomes legíveis no `$defs` do JSON Schema (`ExtractedField[Money]`), que é o que o LLM lê | [Pydantic 2.14: Models (genéricos)](https://pydantic.dev/docs/validation/2.14/concepts/models/) |
| JSON Schema de cada pack commitado com teste de snapshot; `uv run poe export-schemas` regrava | `packs/json_schema.py` | Mudar o schema muda o pedido ao LLM e pode mexer no eval: tem que aparecer no diff. Sem dependência nova (comparação de texto basta) | julgamento próprio (YAGNI) |

Pendente para a #4: o schema atual tem `Money` como `number` **ou** `string` e `citation`/`reason` fora de `required`. Conferir na doc do SDK escolhido o que a saída estruturada nativa aceita antes de ajustar.
