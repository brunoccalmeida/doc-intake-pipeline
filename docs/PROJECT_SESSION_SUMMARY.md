<!-- LTeX: language=pt-BR -->

# Resumo das sessões

Estado do projeto entre chats. Guarda **só o estado e a próxima missão**; o registro de cada missão vai no corpo do PR (squash com a descrição do PR).

## Estado atual

| Item             | Estado                                                                                                                       |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Missão atual     | Nenhuma: repositório com regras, README e issues da semana 1                                                                 |
| Próxima missão   | #1 (esqueleto do repositório, ambiente Python, `check`, CI com `ci-passed` e ruleset)                                        |
| PRs abertos      | nenhum                                                                                                                       |
| Portões          | ainda não existem (nascem na #1)                                                                                             |
| Travas do agente | `.claude/settings.json` nega merge `--admin`, force push, push na `main` e leitura/escrita do `.env`; plugin `mission` com `autoUpdate: false` |

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
