<!-- LTeX: language=pt-BR -->

# Produto e modelo de entrega

Documento interno (pt-BR). Diz **o que o cliente compra e como recebe**, para orientar a escolha e o desenho das missões. Decisões técnicas continuam em [ARCHITECTURE.md](ARCHITECTURE.md); este arquivo dá o porquê comercial delas. Atualizado em 2026-11-21.

## O que o cliente compra

O cliente paga pelo trabalho de construir e integrar um pipeline de extração para os documentos dele. Ele não compra uma licença nem assina um serviço.

- **Roda nas contas do cliente**, ou nos servidores dele: nuvem, chave de API do LLM e repositório em nome dele. O autor não hospeda o sistema nem guarda documentos de cliente.
- **O cliente paga o LLM direto ao fornecedor**, na própria fatura. O custo por documento é medido e informado (D5).
- **Contrato em etapas:** primeiro um piloto, com acurácia por campo medida em documentos reais do cliente; depois a construção; depois a entrega com documentação e um período de correção de bugs; por fim, manutenção por hora quando algo mudar.
- **Fora do produto:** SaaS hospedado pelo autor; serviço recorrente em que o autor processa os documentos do cliente.

## Três camadas de código

| Camada | O que contém | Onde fica | Licença |
| --- | --- | --- | --- |
| Núcleo | Leitura (OCR), extração com LLM, schema com citação da origem, campo vazio com motivo, revisão humana do duvidoso, eval contra conjunto-ouro no CI, custo por documento | Este repositório (público, portfólio) | MIT |
| Kit de entrega | Conectores de entrada e saída para os sistemas do cliente, gerador do relatório do piloto, modelos de documentação de entrega, forma de publicar na conta do cliente | Repositório privado do autor (ainda não criado; consome o núcleo por dependência git, D18) | Não exclusiva, combinada a cada contrato |
| Específico do cliente | Campos, regras, ligações com os sistemas dele, conjunto-ouro com os documentos dele, configuração | Repositório do cliente | Do cliente |

### Regra de fronteira para as missões

- **O núcleo é genérico:** não conhece cliente, não depende de conector de sistema de cliente (Gmail, Drive, QuickBooks, NetSuite etc.) e continua testável só com provedor falso. Isso estende o que a tabela de pastas já diz de `core/` e o invariante 3 do AGENTS.md.
- **O que só acelera entregas** (conector, relatório do piloto, modelo de documentação) **é do kit**, não deste repositório.
- **Exceção: o que mostra ao cliente como a entrega funciona pode ser público,** desde que genérico e sem dado de cliente. Na demo de ponta a ponta, a entrada por pasta, a execução agendada e a planilha com fila de revisão são públicas; conectores por API são do kit ([D18](ARCHITECTURE.md#d18-fronteira-entre-núcleo-kit-de-entrega-e-código-do-cliente-decidida-na-52)).
- **O kit e o cliente consomem o núcleo como dependência git fixada em tag;** as peças do kit são copiadas para o repositório do cliente na entrega (D18).
- **Os invariantes do AGENTS.md valem também para o kit** e para o código entregue (lista na D18).
- **Documento de cliente nunca entra em nenhum repositório do autor** que não seja o do próprio cliente (Segurança, AGENTS.md).

## O que o mercado pediu

Base: 15 vagas de extração de documentos no Upwork, com pagamento verificado, publicadas entre 07 e 21/11/2026. É uma amostra de duas semanas, não uma pesquisa completa; serve para priorizar, não para prometer.

| Necessidade | O que as vagas pediam | Situação no núcleo |
| --- | --- | --- |
| Entrada | Caixa de e-mail compartilhada; pasta do Google Drive ou Dropbox; upload; foto tirada no celular | Pasta de entrada lida por execução agendada (exemplo de timer do systemd), servindo também pasta sincronizada pelo Drive ou Dropbox; arquivo ainda sendo gravado espera a próxima execução ([#53](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/53)). E-mail e upload: kit |
| Saída | Planilha; sistemas como QuickBooks, NetSuite, Exact, ADP | Planilha CSV por execução, uma linha por campo, pronta para Excel e Sheets (#53); JSON por documento no `extract`. Sistemas de negócio: kit |
| Tipos de documento | Faturas, pedidos de compra, confirmações de pedido, romaneios, tickets de campo, timesheets, cheques | Dois packs: recibo (eval em 20 recibos escaneados reais) e fatura (cabeçalho e totais, eval em 20 faturas geradas por template do FATURA, D24); os dois passam pela execução diária por pasta, pela calibração e pelo relatório de erro (`--pack invoice`), cada um com a sua pasta e a sua política. Pedidos de compra, romaneios, tickets de campo e timesheets: sem conjunto público rotulado, calibração com os documentos revisados do cliente |
| Volume | Até 150 a 300 documentos por dia, em dezenas de formatos | Medido em 20 recibos escaneados e 20 faturas geradas por template |
| Revisão humana | Fila para campos de baixa confiança, com acesso ao original e jeito de corrigir | Fila na planilha: filtro `field_status = needs_review`, com valor, citação, motivo e o original movido para a mesma pasta da execução (#53). Sem tela de revisão; correção feita na planilha não volta ao pipeline |
| Prova de qualidade | Acurácia por campo medida em documentos reais, piloto com 10 a 20 documentos antes do projeto | Eval por campo com gate no CI (D4, D16); nos documentos do cliente, relatório de erro por campo a partir das revisões, com limite superior de 95% (D21, #64) |
| Entrega | Código na hospedagem ou no repositório do cliente, documentação, instruções de configuração, 30 dias de correção de bugs | Fora do núcleo (kit) |

## Limites que valem para demos e dados fictícios

- Sem bancos, pagamentos, cartões, fintech, crédito, investimentos, corretora, cripto, seguros ou apostas em exemplos, dados fictícios ou demos.
- Nada de scraping de sites, treino ou fine-tuning de modelo próprio, nem plataformas de extração prontas (AWS Textract, Azure Document Intelligence, Google Document AI) como base do produto.

## Como usar este arquivo ao escolher missões

- Ao propor ou desenhar uma missão, confira a camada (núcleo, kit ou cliente) e a necessidade da tabela acima que ela atende.
- Missão que mexe em entrada, saída, revisão ou tipo de documento cita aqui a linha que muda; ao fechar, atualize a coluna "Situação no núcleo".
- Mudança no modelo de entrega ou na fronteira entre camadas é decisão do usuário: atualize este arquivo no PR que a aplica.
