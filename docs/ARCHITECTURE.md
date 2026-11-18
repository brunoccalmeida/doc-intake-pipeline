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

### D7. Ferramentas Python (a confirmar na #1)

Recomendação: `uv` (ambiente, Python fixado e lockfile), `ruff` (lint e formatação), `pyright` (tipos, modo estrito), `pytest`, `poethepoet` para o `check`. O UAT usa Poetry; a escolha aqui é registrada na #1 com a fonte que a sustenta (inclusive suporte do Dependabot ao lockfile escolhido).
