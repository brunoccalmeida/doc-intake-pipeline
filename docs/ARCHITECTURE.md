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
| `providers/` | Implementações de `LLMProvider` (Claude, OpenAI) e a fábrica `make_provider`. Único lugar que importa SDK de provedor (D10).             |
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
| Python | 3.14 (`.python-version`) | A 3.15 já saiu (3.15.2), mas a #3 traz bibliotecas de PDF/OCR com extensões nativas; a 3.14 tem um ano de wheels publicados. **Julgamento próprio**; revisto na #3 (D9): falta wheel cp315 do PyYAML, troca na [#11](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/11) | [python.org: downloads](https://www.python.org/downloads/); [ciclo de vida das versões](https://devguide.python.org/versions/) |
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

Revisto na #4: `citation` e `reason` passaram a ser **obrigatórios, mesmo nulos** (sem default). O modo estrito da OpenAI exige toda propriedade em `required`, e no Claude a decodificação restrita passa a obrigar a chave; os dois provedores recebem o mesmo contrato e todo produtor (LLM, gabarito, teste) declara a evidência ou a ausência dela. `Money` continua `number` ou `string`: os dois provedores aceitam `anyOf`. Detalhes na D10.

### D9. Leitura de PDF e imagem (decidida na #3)

`core/ingest.py`: `ingest(path, *, tessdata_dir) -> Document` com `pages: tuple[PageText, ...]` (número a partir de 1, texto e `source: text_layer | ocr`). A decisão entre camada de texto e OCR é **por página**, então um PDF que mistura páginas digitadas e escaneadas funciona.

| Peça | Escolha | Por quê | Fonte |
| --- | --- | --- | --- |
| PDF (texto e renderização) | `pypdfium2` 5.15 (BSD-3/Apache-2.0) | Uma dependência só lê a camada de texto e renderiza a página escaneada para o OCR, com wheels para todas as plataformas (sem poppler). O `pypdf` lê texto mas não renderiza, e o `pdfplumber` já depende do `pypdfium2`. O PyMuPDF foi descartado pela licença AGPL, que não serve para entregar a cliente | metadados do PyPI; docstrings da versão instalada |
| OCR | `tesserocr` 2.13 (MIT), Tesseract 5.5.4 embutido | Os wheels (Linux, macOS e Windows, cp314) **embutem o Tesseract**: o CI não precisa de `apt-get` e o Windows não precisa de instalador. O `pytesseract` exigiria o binário no sistema. RapidOCR/EasyOCR trazem onnxruntime/torch e não foram medidos (**julgamento próprio**: Tesseract é o padrão conhecido; revisitar se a precisão do eval na #6 apontar o OCR como gargalo) | [tesserocr no PyPI](https://pypi.org/project/tesserocr/) |
| Modelo de idioma | `eng.traineddata` do `tessdata_fast` (Apache-2.0), fixado por commit e SHA-256 em `scripts/fetch_tessdata.py`; `uv run poe fetch-tessdata` grava em `DOC_INTAKE_TESSDATA_DIR` (padrão `.cache/tessdata`, fora do Git) | "Most users will want tessdata_fast and that is what will be shipped as part of Linux distributions". O checksum garante que um arquivo trocado não muda o OCR (e o eval) em silêncio; o mesmo padrão do gitleaks no CI | [tessdoc: Data Files](https://tesseract-ocr.github.io/tessdoc/Data-Files.html) |
| Resolução do OCR em PDF | 300 DPI (`scale = 300 / 72`) | "Tesseract works best on images which have a DPI of at least 300 dpi" | [tessdoc: Improving the quality](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html) |
| Texto literal | só `\r\n` → `\n` | O PDFium termina linhas com `\r\n` (observado no 5.15 e travado por teste); a citação (D1) compara com este texto, então nada mais é alterado | sonda + `tests/test_ingest.py` |
| Tipos | stubs mínimos em `typings/` (`stubPath`) | O `pypdfium2` não publica tipos e o stub do `tesserocr` anota a imagem como o módulo `PIL.Image`: o pyright estrito reprova 8 pontos sem eles (sonda). O stub cobre só a API usada, e os testes exercitam cada chamada | [pyright: import resolution](https://github.com/microsoft/pyright/blob/main/docs/import-resolution.md) |
| Erros | `IngestError` → `UnsupportedFileTypeError`, `UnreadableDocumentError` (ausente ou corrompido), `EmptyDocumentError`, `OcrDataMissingError` | Uma hierarquia: o pipeline marca o documento como `failed` com o motivo, sem pular nada. A mensagem cita o nome do arquivo, nunca o conteúdo (invariante 6) | AGENTS.md |

### D10. Extrator com LLM (decidida na #4)

`core/extract.py`: `extract(document, pack, provider, *, max_retries=2) -> ExtractionResult`. `core/llm.py` define `LLMRequest` (instruções, prompt, nome e modelo Pydantic do schema), `LLMResponse` (texto cru, tokens, modelo que respondeu) e o `Protocol` `LLMProvider`. Um `Pack` é nome + schema + instruções.

| Regra | Onde | Por quê | Fonte |
| --- | --- | --- | --- |
| SDK de provedor só em `providers/`; o ruff (`TID251`, banned-api) barra `anthropic`/`openai` em qualquer outro lugar | `pyproject.toml` | A D2 vira portão: um import errado reprova no lint, não na revisão. Provado com sonda em `core/` e `packs/` | [ruff: banned-api](https://docs.astral.sh/ruff/settings/#lint_flake8-tidy-imports_banned-api) |
| O pedido carrega o **modelo Pydantic**, não o JSON Schema; cada provedor converte com o helper do próprio SDK (`anthropic.transform_schema`, `to_strict_json_schema` da OpenAI) | `providers/` | Cada API aceita um dialeto: o Claude rejeita `minimum`/`pattern` (o helper move para a descrição); a OpenAI estrita exige tudo em `required` e `$ref` sem chaves irmãs. Testes conferem as duas regras sem rede | [Anthropic: Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs); [OpenAI: Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) |
| `to_strict_json_schema` vem de `openai.lib._pydantic` (módulo com `_`) | `providers/gpt.py` | É a conversão que o próprio `responses.parse` usa; o `parse` não serve porque valida dentro da chamada (`model_parse_json`): um `ValidationError` perde o texto cru, que a nova tentativa reenvia, e os tokens gastos. Risco de mudança no SDK coberto pelo teste do schema | código do SDK 3.55 (`lib/_parsing/_responses.py`) |
| Descrições dos campos também nas instruções | `core/extract.py` | O `transform_schema` da Anthropic descarta a `description` ao lado de um `$ref` (observado com sonda no SDK 2.10) | sonda |
| `max_retries` = novas tentativas **depois** da primeira (padrão 2, logo até 3 chamadas); a nova tentativa reenvia o documento com a resposta rejeitada e os erros | `core/extract.py`, `DOC_INTAKE_MAX_RETRIES` | Pedido autocontido, sem histórico de conversa: neutro entre provedores e sem replay de blocos de raciocínio | julgamento próprio |
| Erros do resultado sem o valor de entrada (`include_input=False`) | `core/extract.py` | Os erros vão para o log; o valor rejeitado é conteúdo do documento (invariante 6). Teste de mutação com `str(error)` reprova | AGENTS.md |
| Erro de transporte (rede, autenticação, limite após as tentativas do SDK) **propaga**, não vira `failed` | `core/extract.py` | Não é falha de validação; quem chama decide e reporta o documento, sem pular | D3 (fail loudly) |
| Citação conferida contra a página citada, ignorando só o layout de espaços (`" ".join(s.split())`); página inexistente ou trecho ausente → `needs_review` com os campos mantidos | `core/extract.py` | O modelo costuma juntar linhas com espaço; caixa, pontuação e erro de OCR têm de bater, então paráfrase é pega | D1 |
| Claude: `claude-opus-5-5`, `effort: medium` explícito, `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`); OpenAI: `gpt-6.2-astra`, Responses API com `store=False` | `providers/`, `core/config.py` | Modelo recomendado de cada fornecedor como padrão; o eval (#6) é quem deve mudá-lo. Recusa de segurança é reexecutada pelo servidor em outro modelo, registrado em `LLMResponse.model`. `store=False`: documento de cliente não fica guardado na OpenAI | [Anthropic: models](https://platform.claude.com/docs/en/about-claude/models/overview); [OpenAI: models](https://developers.openai.com/api/docs/models) |
| Chaves `DOC_INTAKE_ANTHROPIC_API_KEY`/`DOC_INTAKE_OPENAI_API_KEY` como `SecretStr`, opcionais no `Settings`; `make_provider` falha nomeando a variável | `core/config.py`, `providers/__init__.py` | Ingest e testes rodam sem chave; quem extrai falha antes da primeira chamada. `SecretStr` não aparece em `repr` nem em traceback | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) |

Python 3.15 (revisão pedida pela D7): as bibliotecas da #3 e o `pydantic-core` já publicam wheels cp315 (ou `py3`), mas o PyYAML 6.0.3 (dev) não, e seria compilado do código-fonte. Fica no 3.14; a troca está na [#11](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/11).
