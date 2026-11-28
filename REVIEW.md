<!-- LTeX: language=pt-BR -->

# Instruções de revisão

Verificações específicas deste projeto para o revisor (`mission:reviewer` e o Code Review da Anthropic, que lê este arquivo na raiz), somadas à lista genérica dele. As regras gerais estão em [AGENTS.md](AGENTS.md); a arquitetura, em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Sempre verificar

- **Invariantes do AGENTS.md:** campo sem evidência sai `null` com motivo; toda saída passa pelo schema; o núcleo (`doc_intake.core`) não importa SDK de provedor; dinheiro em `Decimal`.
- **Citação real:** a citação de cada campo aponta para texto que existe no documento lido (página e trecho); teste que afirma a citação compara com a entrada, não com outra saída do LLM.
- **Testes sem rede:** nenhum teste unitário ou de integração chama provedor real nem depende de chave. Chamada real só no eval, rodado de propósito.
- **Eval honesto:** o gabarito não foi ajustado para a saída do modelo; mudança no conjunto-ouro vem com o motivo (erro no gabarito original, com evidência) e nunca no mesmo PR que muda prompt ou modelo.
- **Prova para cliente:** o que o PR acrescenta aparece num número verificável (precisão por campo, custo por documento) ou num artefato do CI; afirmação no README tem link de evidência.
- **Regras só duráveis:** o que o PR acrescenta ao `AGENTS.md` ou ao `CLAUDE.md` vale em toda sessão e para todo agente; estado, datas, relato de missão ou instrução de uma área só vão para o resumo de sessão, o `docs/ARCHITECTURE.md` ou o documento da área (D26).
- **Custo e privacidade nos logs:** o log registra tokens, custo e resultado da validação, sem o conteúdo do documento.

## Não reportar

- O que `ruff`, `pyright` e os testes já impõem (estilo, formatação, imports, tipos).
