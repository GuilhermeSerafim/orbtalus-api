# Handoff local — API original, lote A

Escopo: A-API-001 a A-API-005, base original
`d0c4dafbc583469759267ca067d34571bba1b695`, branch
`ralph/orbtalus-api-original-a-20261101`. O worker entrega arquivos e evidência
offline; o gestor faz aceitação final, stage, commit, integração e publicação.
Nenhum commit novo foi feito ou é alegado pelo worker. Worktree preservado.

## Entrega e achados da revisão

- Configuração e construção de engine/provider tardias; import safety, saúde
  local e CORS exato. Readiness confere `public` e shadowing, com providers
  explicitamente `not_verified`.
- Providers obrigatórios falham com erros tipados seguros, preservando zero real,
  parâmetros científicos, modelos/RAG/prompt e corpora originais. Não há fallback
  Nottus ativo, narrativa de sucesso fabricada ou envelope novo. O fonte histórico
  `providers/nottus_adapter.py` é preservado, sem re-exportação em `providers`
  e fora do COPY/contexto Docker. Somente MapBiomas é entregue como adapter.
- Polygon/Feature, coordenadas assinadas, contrato original, projeção DB e
  transações verificados com dublês. Close após commit confirmado não converte
  sucesso em erro. Cache OSM continua independente da análise.
- Baseline original explícita, contrato descartável e importador transacional;
  Alembic histórico preservado, sem upgrade/stamp automático.
- Dockerfile e contexto preparados por allowlist; UID 10001, porta 8080,
  Uvicorn com exec, código/corpora e scripts explícitos. README e exemplo de
  configuração substituem instruções antigas de fallback/DDL automático.

Os três achados abertos do controller foram tratados em005:

| Achado | Correção e prova offline |
| --- | --- |
| Embeddings bool/text eram convertidos antes da validação | Validação dos elementos originais antes da coerção NumPy; documentos com contagem correta e queries mistas recusadas antes da resposta LLM. Zeros numéricos em vetores não nulos continuam válidos. |
| Libpq podia redirecionar URL válida | Guarda compartilhada recusa PGHOSTADDR/PGSERVICE não vazios antes da engine/sessão; regressões sintéticas exercitam baseline e importador sem conexão ou leitura de arquivos de serviço. |
| Erro de manifesto após DDL confirmada | Escrita/flush/close dentro da transação, antes do commit; falhas injetadas causam saída não zero e rollback. Falha de commit retém manifesto, não anuncia sucesso. Arquivo isolado não prova commit. |

Não há transação distribuída banco/disco nem prova de durabilidade em queda de
processo. A recuperação documentada exige conferir o banco e usar validate-only
quando completo, mantendo artefatos. Nenhum critério ou ID de história foi reduzido.

## Evidência e reprodução

No worktree, `.tools/story005-context-validation.json` registra comandos completos,
exits e caminhos de logs. Execute com o Python local aprovado:

```text
.venv/Scripts/python.exe -X utf8 .tools/story005-context-validate.py
```

O script de evidência é local e não entra na imagem. A reprodução portátil está
no README: `pip check`, `scripts/run_offline_tests.py` e `compileall`. A revisão
local adicional confere pinos instalados, closure de dependências, arquivos
protegidos contra Git e hash pré-sessão, PRD imutável e imports do pacote copiado
em diretório isolado sob guardas offline. COPY seleciona 28 arquivos para a
imagem; essa prova é separada da seleção efetiva do contexto descrita abaixo.
Os fontes da aplicação, testes e locks permanecem iguais à entrega anterior;
as 103 regressões aceitas pelo controller não foram repetidas nesta correção
de empacotamento. Os checks focados e hashes foram executados nesta sessão.

Cada bloco de `.dockerignore` usa `!dir/`, depois `dir/**`, depois as exceções
de arquivos. Sem a segunda regra, o resultado de inclusão do pai libera outros
descendentes. `.tools/story005-context-check.py` verifica a seleção efetiva
pelas duas formas de entrada de `MatchesUsingParentResults` do
[Moby](https://github.com/moby/patternmatcher/blob/main/patternmatcher.go):
resultados por regra herdados do pai e avaliação sem resultados prévios.
O helper aceita somente caminhos POSIX literais, barra final de diretório,
`**`, `dir/**`, negação `!` e comentários de linha inteira. Rejeita outras
sintaxes; **não é um matcher Docker geral, nem prova de arquivo de contexto
gerado ou build**. A [documentação Docker](https://docs.docker.com/build/concepts/context/#dockerignore-files)
orienta a ordem das regras.

O teste falha nas regras antigas (artefato red retido) e passa nas corrigidas:
30 arquivos permitidos, 116 nomes sintéticos excluídos e os seis diretórios
pais acessíveis. Cobre Ralph/logs/CODEX/OBJECTIVE/progress, nomes de secrets e
.env, caches/pyc aninhados, GeoJSON, Nottus/serviços dormentes, testes e
descendentes arbitrários. Remover cada uma das seis regras `dir/**` faz um
caminho proibido voltar a ser incluído. Sete casos de referência e 13 sintaxes
recusadas conferem o helper. Nenhum caminho sintético é aberto e nenhum
snapshot anterior ou diretório protegido é percorrido. O novo review substitui
a antiga asserção textual de que todas as regras após `**` começavam com `!`.

Evidências desta história (locais, retidas, fora da imagem):

- `.tools/worker-probe-fa3d471b522e4146aa067f513b7a8804.txt`: escrita exclusiva e readback.
- `.tools/story005-red.log`, `.tools/story005-ai-red.log`: regressões falhando antes da correção.
- `.tools/story005-green-initial.log`: primeira suíte verde, 102 testes, zero tentativas externas não substituídas.
- `.tools/story005-validation-final-*.log`: verificação final por comando, incluindo suíte com regressão adicional de falha do commit.
- `.tools/story005-followup-validation-final-*.log`: verificação anterior após exclusão do Nottus, preservando as 103 regressões aceitas. Scripts antigos ficam como registro histórico, com as referências de seu ciclo.
- `.tools/worker-probe-e5ac8047cf72491fae5c7b3206b422bb.txt`: escrita exclusiva e readback desta reabertura, retidos.
- `.tools/story005-context-source-hashes.json` e `docs/LOTE-A-SHA256.json`: SHA256 atual da entrega, incluindo locks, fontes, testes e documentos; excluem a si próprios e estado mutável Ralph. Manifests `story005-source-hashes` e `story005-followup-source-hashes` preservam as entregas anteriores.
- `.tools/story005-context-package-review.json`: manifesto atual de COPY, ausência do módulo/export Nottus e imports offline do pacote. Os dois manifests de pacote anteriores permanecem como evidência histórica.
- `.tools/story005-context-red.json`/`.log`, `-green.json`/`.log` e `-before.dockerignore`: reprodução antes/depois, seleções efetivas e mutações das seis exclusões. Nenhum build Docker executado.
- `.tools/story005-context-stability.json`: fontes/locks/testes estáveis, critérios/IDs/count e OBJECTIVE desta rodada preservados; hashes dos helpers e evidências atuais.
- `.tools/worker-probe-fcb5509a2d7f4be181ab2eae16f28396.txt`: escrita exclusiva e readback desta reabertura, retidos.
- `.tools/story005-followup-harness-interfaces.json`: conferência estática das assinaturas locais abaixo; não lê, importa ou executa o harness externo.
- `.tools/story005-protected-before.json` e `.tools/story005-prd-before.json`: referências pré-sessão. Critérios/IDs/count/OBJECTIVE preservados.
- `.tools/story004-current-validation.json`: evidência anterior do schema/importador; manifesto esperado e SQL compilado de004 são artefatos de modelo, não reflexão/DDL real.

`models.py`, calculadora, revisão Alembic histórica e ambos os corpora continuam
iguais à base (comparação de blobs normaliza CRLF; hashes brutos também são
conferidos contra a referência pré-sessão). Nenhuma coluna científica nova.

## Dependências e limites de reprodução

`requirements.txt` contém pinos diretos reconciliados ao código; dotenv é apenas
dependência de teste em `requirements-dev.txt`. `requirements.lock` mantém os
75 pinos candidatos instalados, incluindo utilitários de teste. `pip check` e
comparação com metadata instalada validam Windows/CPython 3.12.10; não validam
disponibilidade futura no índice ou wheels Linux/ARM64. O lock não tem hashes
de distribuições. Instalação Docker exige wheels para falhar explicitamente
quando não disponíveis. Tag base `python:3.12.10-slim-bookworm` ainda sem digest.
O gestor registra resolução, hashes/digests e arquitetura no gate de build.

## Harness externo existente e contrato de integração

Conforme o registro `CONTROLLER REOPEN A-API-005 AFTER RUNNER EXIT` no progresso,
o harness **já existe** em
`C:/Users/Guiler/.codex/agent-manager/agentes/oracle-cloud-2026-10-29/execucao-2026-11-01/infraestrutura/original-a/`.
O controller leu seus `README.md` e `INTEGRATION.md`; este worker não acessou
esse worktree nem copiou, alterou ou executou seus arquivos. A existência e a
descrição do artefato são informações do controller; a conferência desta rodada
se limita às interfaces no fonte da API.

Artefatos existentes informados: `compose.integration.yaml`,
`integration/harness/serve.py`, `integration/harness/doubles.py`,
`integration/harness/egress_guard.py`, `scripts/launch.py` e
`scripts/integration_policy.py`. O overlay usa `/integration` como mount
separado, somente leitura, fora de `/app` e do COPY da imagem de produção.
O produto não contém flag de fixture, seletor de provider simulado ou entrypoint
de harness. A execução futura desse overlay continua proposta e não validada.

Entradas da API disponíveis: `main:create_app` (factory sem argumentos) e
`main:app` (instância criada pela factory). O bootstrap externo deverá instalar
as substituições no processo antes de atender requisições. Os símbolos usados
pelas rotas são os seguintes; substituir apenas a função no módulo de origem
`services.ai_service` não substitui os aliases já importados nas duas rotas.

| Símbolo exato no módulo consumidor | Contrato da substituição externa |
| --- | --- |
| `routers.risk.get_data_provider` | Função sem argumentos. Retorna objeto com `name: str`, `get_soil_data(lat, lon)` retornando `class_id`, `class_name`, `is_permeable`, e `get_water_frequency(lat, lon)` retornando `frequency_years`, `confidence`. Classes e permeabilidade precisam ser coerentes com a tabela MapBiomas original. |
| `routers.risk.get_osm_service` | Função sem argumentos. Retorna objeto com `fetch_and_save_rivers(lat, lon)`; o cenário informado usa no-op. |
| `routers.risk.elevation_m` | Função `(lat, lon)` que retorna número finito, inclusive zero; chamada para o ponto e para o rio. |
| `routers.risk.get_ai_assessment` | Função `(question)` retornando `services.ai_service.RiskAssessment`, com `risk_level` em `baixo/medio/alto` e `explanation` útil, explicitamente identificada como teste. A rota risk consome a explicação; a classificação persistida vem da calculadora. |
| `routers.ai_vertical.get_ai_assessment` | Mesmo contrato de IA; a rota `/ai/ask-ai` serializa o modelo em `resposta`. Este é um segundo alias e exige sua própria substituição. |

No cenário normal informado pelo controller, solo é classe 3/permeável,
água é 0 com confiança 1, elevação é 0 e OSM é no-op; narrativa e `data_source`
devem ser claramente rotulados como dados de teste. O harness não semeia
hidrografia: com DB vazio, risk continua 503 e distance 404. OSM no-op não prova
outage real nem comportamento do cache. Cenários de indisponibilidade de
água/solo/elevação/IA são selecionados apenas no startup externo, sem flag no
produto ou fabricação de respostas pelo browser. As fronteiras indisponíveis
devem produzir os erros tipados existentes (`DATA_UNAVAILABLE` ou
`AI_UNAVAILABLE`), sem permitir cálculo/persistência de sucesso inválido.

Na integração futura, preservar engine, `SessionLocal`, sessões, queries,
geometria, calculadora e construção HTTP reais da aplicação, contra DB
descartável com schema original autorizado separadamente. Nenhuma substituição
de banco ou resposta HTTP é proposta aqui. Os gates externos informados em
`INTEGRATION.md` continuam `authorized=false` e
`final_application_handoff_reviewed=false`; somente o gestor poderá reconciliar
esses gates após revisar a entrega. Compatibilidade operacional do overlay,
egress guard com libpq real, DB semeado, HTTP até persistência, Docker/Linux,
browser e UI permanecem **não executados**. Próximo passo: gestor comparar essas
interfaces com o artefato externo e liberar o ensaio isolado antes de operá-lo.

## Gates independentes ainda não executados

| Gate | Próxima ação concreta do gestor após liberação |
| --- | --- |
| DB novo/PostGIS/DDL/reflexão | Aprovar destino/contrato e versões; conferir identidade e ausência de overrides libpq; criar extensão fora da baseline; ensaiar initialize, manifesto e validate-only; provar recusa de schema não vazio e papel app sem DDL. |
| Importação real e cache | Selecionar/montar GeoJSON aprovado; executar CLI no destino autorizado; conferir transação, quatro colunas originais e duplicação em reimportação; não alterar preview. |
| Restore | Ensaiar em destino separado, conferir manifesto, registros e permissões; nenhum restore executado aqui. |
| Docker/Linux | Executar build preparado no README; registrar digest, wheels/pinos, pip check, UID/GID, corpora, portas e encerramento por sinal. A imagem não inclui dataset de rios nem Alembic histórico. |
| Serviço/browser integrado | Aprovar portas/API/UI e harness separado; verificar sucesso e erros reais, CORS, estado visual e projeção persistida. Nenhum servidor/porta foi operado pelo worker. |
| Providers reais | Aprovar credenciais, custo e egress; verificar EE/datasets, Open-Meteo, OSM e OpenAI/RAG sem alegar que dublês provam disponibilidade. |
| ARM64/hosting/deploy | Resolver/buildar para arquitetura alvo, repetir checks e aprovar infraestrutura/publicação separadamente. |

Gap de escopo previamente registrado: `services/water_service.py` é dormente e
não foi ativado/corrigido; serviços simulados legados ficam fora da imagem e do
fluxo ativo. Novas migrações precisam reconciliar o histórico Alembic. Não há
deduplicação, idempotência, cache vetorial ou ensaio de desempenho/custos.

## Integração pelo gestor

Preservar alterações de histórias anteriores e arquivos de governança. Arquivos
de005: `Dockerfile`, `.dockerignore`, `.env.example`, `.gitignore`, `README.md`,
`requirements.txt`, `requirements-dev.txt`, `providers/__init__.py`, `core/db_target.py`,
`services/ai_service.py`, `scripts/init_original_db.py`,
`tests/test_ai_service.py`, `tests/test_original_schema.py`,
`docs/ORIGINAL-SCHEMA.md`, este handoff e `docs/LOTE-A-SHA256.json`.
Evidências `.tools` e estado Ralph permanecem locais. O worker não fez stage,
commit, push nem publicação. Mensagem proposta ao gestor:
`fix(api): prepare reproducible original API handoff and close review findings`.

Referências usadas na revisão: [variáveis libpq](https://www.postgresql.org/docs/15/libpq-envars.html),
[Dockerfile](https://docs.docker.com/reference/dockerfile/) e
[contexto/.dockerignore](https://docs.docker.com/build/concepts/context/#dockerignore-files).
