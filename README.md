# OrbTalus (GeoRisk) — Backend

API FastAPI para análise de risco de inundação a partir de Polygon GeoJSON.
Preserva os pesos de `core/risk_calculator.py` e o formato da resposta.
A hidrografia inclui a origem e as datas de consulta. Configuração, engine, sessões e providers são tardios;
importar a aplicação não conecta, não executa DDL e não inicializa providers.

## Alcance e limites

Protótipo de pesquisa para triagem preliminar de risco ambiental. As saídas são
exploratórias: não são previsões validadas nem avaliação completa de imóvel ou
região. Cobertura de dados, unidades das bandas de água e conversão para anos
exigem validação científica. Scores e `confidence` não são probabilidades
calibradas. Nottus continua sendo um adaptador placeholder, sem comprovação de
observações ambientais; não deve ser apresentado como fonte real.

Esta branch substitui comportamentos antigos documentados na main: configuração
agora é explícita, não há DDL ao importar, e indisponibilidade de dados/IA deve
falhar com erro seguro, sem produzir parecer de sucesso com fallback. O modelo
ponderado continua determinístico; a IA explica a classificação calculada e
uma declaração de classe divergente é recusada. Isso não garante a veracidade
de todas as frases do parecer nem ausência de alucinações.

Esta entrega foi validada **offline no Windows/CPython 3.12**. Docker/Linux,
PostGIS real, providers reais, browser integrado, restore, ARM64 e deploy
permanecem gates separados do gestor. Não execute os comandos operacionais
abaixo sem essa liberação. [Handoff e evidências](docs/HANDOFF-LOTE-A.md).

## Reprodução local sem serviços

Use o Python 3.12 já aprovado para o projeto. No worktree do worker:

```powershell
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -X utf8 scripts/run_offline_tests.py
.venv/Scripts/python.exe -m compileall -q core providers routers services scripts main.py database.py models.py migrate_rivers.py ai_vertical.py test_risk_api.py alembic/env.py
```

Para preparar um ambiente novo, com instalação pública autorizada:

```text
python -m pip install -r requirements.lock -r requirements-dev.txt
python -m pip check
python -X utf8 scripts/run_offline_tests.py
```

`requirements.txt` declara os imports diretos ativos. `requirements-dev.txt`
adiciona clientes de teste e dotenv somente para o bloqueio de leitura implícita
nos testes. `requirements.lock` fixa a closure instalada, incluindo pacotes de
teste; não é lock com hashes de wheels nem prova de resolução Linux/ARM64.
Não atualize pinos como parte de um ensaio operacional sem revisão.

O runner descobre somente `tests/`, limpa configuração da aplicação e instala
bloqueios de sockets/DNS/HTTP/DB antes da coleta. As fronteiras são substituídas
por dublês. A exceção para socketpair interno do asyncio no Windows não permite
HTTP ou conexões arbitrárias. `test_risk_api.py` é um script HTTP manual com
main explícito: não faz HTTP ao importar e não pertence à coleta offline.
Não execute `setup_gee.py` nesta validação.

## Configuração explícita

A aplicação não carrega `.env`. [.env.example](.env.example) contém somente
placeholders; injete valores aprovados no ambiente do processo. Nenhuma chave,
DSN real ou arquivo de credenciais deve entrar em Git ou na imagem.

| Variável | Uso |
| --- | --- |
| `DATABASE_URL` | URL SQLAlchemy PostgreSQL explícita para API/CLI; sem default. Papel app sem DDL; owner separado para baseline/importação. |
| `OPENAI_API_KEY` | Obrigatória quando IA é usada; não é necessária para importar ou `/ping`. |
| `GEE_PROJECT` | Projeto explícito, obrigatório ao inicializar Earth Engine. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho de credencial montada somente em runtime. Tem prioridade sobre JSON inline. |
| `GEE_SERVICE_ACCOUNT_JSON` | Alternativa JSON inline; sem ambas, EE usa autenticação padrão/ADC disponível no runtime. |
| `CORS_ORIGINS` | Origens HTTP(S) exatas separadas por vírgula, sem path, credenciais ou `*`; vazio não permite origem. Exemplo proposto: `http://127.0.0.1:3310`. |
| `PORT` | Porta do container, default `8080`. |

CORS permite POST/OPTIONS e Content-Type, sem credentials. Origem é comparada
exatamente, incluindo esquema e porta. Configuração ausente gera erro seguro
quando o recurso é solicitado; não ativa provider alternativo.

## Contrato HTTP

| Rota | Resultado |
| --- | --- |
| `GET /` e `GET /ping` | Processo vivo; não declaram banco ou providers conectados. |
| `GET /ready` | Valida PostGIS, as tabelas públicas da versão atual e o índice único dos trechos por fonte. Retorna `scope=local_dependencies` e `providers=not_verified`. |
| `GET /debug-db` | Conectividade e contagem de rios; erro seguro em falha de DB. |
| `POST /geo/distance` | Consulta local até 5 km. Usa as observações OSM da cobertura vigente. Na ausência dessa cobertura, consulta apenas o inventário legado sem origem identificada. Retorna 404 se não encontrar um corpo d’água elegível. |
| `POST /geo/hydrology` | Testa a mesma busca de rio de `/geo/risk`: reaproveita a cobertura vigente ou consulta o Overpass e atualiza o PostGIS. Retorna a origem da consulta, sua data e o rio elegível mais próximo em até 5 km. |
| `POST /geo/risk` | Exige consulta OSM bem-sucedida e vigente para a área e corpo d’água observado a até 5 km. Se faltar um deles, retorna 503 antes de consultar elevação, MapBiomas ou IA e de gravar uma análise. |
| `POST /ai/ask-ai` | `{ "pergunta": "..." }` retorna `{ "resposta": { "risk_level": "baixo|medio|alto", "explanation": "..." } }`. |

Risk/distance aceitam `{polygon: Polygon}` ou `{polygon: Feature<Polygon>}`,
coordenadas `[longitude, latitude]`. Geometria vazia, inválida, fora dos limites,
anéis abertos/degenerados e valores não numéricos/não finitos retornam 422
antes de criar sessão ou provider. Não há reparação silenciosa da geometria.

### Testar somente a hidrografia

Na raiz desta versão do backend, execute `docker compose -f compose.hydrology.yaml up -d --build`.
Abra [o Swagger local da hidrografia](http://127.0.0.1:8001/docs), escolha **POST /geo/hydrology**
e clique em **Try it out**. A porta 8001 usa PostGIS próprio e a consulta real ao OpenStreetMap via
Overpass. O cache fica no volume deste projeto e é reutilizado após reiniciar. A cota da demo se
aplica no Render. Para acompanhar a busca, use `docker compose -f compose.hydrology.yaml logs -f api`.
Para encerrar e manter o cache, use `docker compose -f compose.hydrology.yaml down`.
Exemplo em PowerShell, com uma pequena área próxima à Marginal Pinheiros em São Paulo:

```powershell
$body = '{"polygon":{"type":"Polygon","coordinates":[[[-46.6962,-23.5861],[-46.6960,-23.5861],[-46.6960,-23.5859],[-46.6962,-23.5859],[-46.6962,-23.5861]]]}}'
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8001/geo/hydrology' -ContentType 'application/json' -Body $body
```

`consulta` indica se esta chamada consultou o Overpass (`overpass`) ou reaproveitou uma busca anterior (`cache`). `consultado_em` é a data dessa busca. O campo `rio` contém nome, tipo, distância em metros, origem, ID e data de edição na fonte, quando disponível. Em chamadas concorrentes, a escolha do rio usa a cobertura vigente no banco no instante da seleção. Uma resposta 200 com `rio: null` indica que a busca foi válida e não identificou um rio elegível no raio de 5 km. Uma falha ao obter a cobertura retorna 503 com `HYDROLOGY_LOOKUP_FAILED`.

A rota atualiza apenas os dados hidrográficos e, no Render, os contadores próprios da demo. Usa os limites por IP e global configurados em um contador separado do de `/geo/risk`. O teste não consulta elevação, Earth Engine ou IA e não grava uma análise.

### Contrato da análise de risco

Exemplo de request, somente ilustrativo:

```json
{"polygon":{"type":"Polygon","coordinates":[[[-46.2,-23.2],[-46,-23.2],[-46,-23],[-46.2,-23],[-46.2,-23.2]]]}}
```

Exemplo de formato HTTP 200, ilustrativo, **não resultado de provider real**:

```json
{
  "distancia_rio_m": 120.1,
  "queda_relativa_m": -8.0,
  "rio_mais_proximo": "Rio Original",
  "tipo_hidrografia": "river",
  "resposta_ia": "Parecer técnico ilustrativo.",
  "risk_level": "Médio",
  "risk_calculation": {
    "confidence": 1.0,
    "total_score": 0.47,
    "component_scores": {"topography": 0.7, "water_frequency": 0.4, "soil_permeability": 0.0},
    "weights_applied": {"topography": 0.5, "water_frequency": 0.3, "soil_permeability": 0.2}
  },
  "environmental_data": {
    "soil": {"class_id": 3, "class_name": "Formação Florestal", "is_permeable": true},
    "water_frequency": {"years": 0, "confidence": 1.0},
    "data_source": "MapBiomas (GEE)",
    "provider_status": "OK"
  },
  "debug_coords": {"rio_lat": -23.0, "rio_lon": -46.0}
}
```

Sem envelope novo, ID persistido ou colunas de proveniência. Zero real de água
ou elevação é válido; elevações `(0,8)` produzem queda `-8`, e `(0,0)` produzem
`0`. O tipo original da queda permanece number|null, mas o fluxo não calcula
sucesso com elevação obrigatória ausente. A classificação vem da calculadora
original, e o parecer da IA é obrigatório; não há narrativa substituta.

Erros conhecidos usam mensagens fixas, sem eco do input, DSN, token ou traceback:

| Status | `detail.code` | `detail.message` |
| --- | --- | --- |
| 422 | `INPUT_INVALID` | Área de análise inválida. Revise a seleção. |
| 503 | `CONFIG_UNAVAILABLE` | Serviço de análise indisponível. Tente novamente mais tarde. |
| 503 | `DATA_UNAVAILABLE` | Dados necessários à análise estão indisponíveis. Tente novamente mais tarde. |
| 503 | `HYDROLOGY_UNAVAILABLE` | Hidrografia local insuficiente para classificar o risco nesta área. |
| 503 | `DATABASE_UNAVAILABLE` | Não foi possível concluir a análise. Tente novamente mais tarde. |
| 503 | `AI_UNAVAILABLE` | Parecer técnico indisponível. Tente novamente mais tarde. |

```json
{"detail":{"code":"DATA_UNAVAILABLE","message":"Dados necessários à análise estão indisponíveis. Tente novamente mais tarde."}}
```

Bugs inesperados continuam 500 com resposta genérica. A exceção 404 de distance
preserva seu contrato legado; não recebe novo envelope de indisponibilidade.

## Persistência, cache e IA

`WaterBody` guarda geometria, nome e tipo. Para os dados do OpenStreetMap,
guarda também a fonte (`osm`), o identificador do trecho (por exemplo
`way/123`), a data da última edição do trecho informada pelo OSM, quando
disponível, e a data da consulta. A edição de um trecho no OSM pode ocorrer
em data diferente da alteração física do rio. Registros legados preservam os
valores desconhecidos como nulos.
`RiskAssessment` mantém as doze colunas originais. Cada sucesso grava:

| Origem | Coluna persistida |
| --- | --- |
| Ponto representativo do polígono | `lat`, `lon` |
| Calculadora original | `risk_level` |
| Parecer obrigatório | `explanation` |
| Rio escolhido | `river_name`, `distance_m` (valor bruto; HTTP arredonda a uma casa) |
| Dados ambientais | `water_frequency_30y`, `soil_type`, `soil_class_id`, `is_permeable` |
| ORM/banco | `created_at` (default Python), `id` (serial) |

Não persiste o payload inteiro, scores ou debug_coords. Falhas conhecidas de
sessão/commit causam rollback/close e 503; erros de cleanup preservam o resultado
principal. Close falhando depois de commit confirmado não converte sucesso em
503. Não há idempotência ou deduplicação de requests.

O PostGIS registra o centro, o raio e o instante de cada consulta completa
ao Overpass, inclusive das consultas válidas que retornam zero trechos.
A política inicial reutiliza essa consulta por até 30 dias, somente quando
o disco consultado contém todo o disco de análise. Uma busca de 6 km permite
reaproveitar um resultado a até 1 km do centro para a análise de 5 km.
A contagem de rios cadastrados não determina a cobertura.

Uma nova consulta atualiza os trechos pelo identificador da fonte. A gravação
dos trechos e da área consultada ocorre na mesma transação, que também remove
os registros de cobertura expirados. Uma falha não renova a validade.
O cálculo seleciona os trechos observados a partir da
consulta vigente mais recente que cobre a área. Assim, um trecho ausente na
renovação dessa área deixa de participar da nota, e um trecho presente em
duas consultas mantém sua identidade no banco. O prazo é uma política do
cache. A atualidade do dado em campo depende do levantamento de origem.

Para testar esse fluxo em PostGIS local descartável, com a imagem
`postgis/postgis:15-3.3` já instalada, execute
`python scripts/test_hydrography_postgis.py`. Os testes simulam o Overpass
e exercitam as rotas, o cache e respostas concorrentes em sessões reais do banco.

MapBiomas usa classes e parâmetros originais; falhas EE/solo/água/banda não
reconhecida não fabricam insumos. O fonte histórico `providers/nottus_adapter.py`
permanece no repositório, sem re-exportação pelo pacote `providers` e excluído
do COPY e do contexto Docker. O runtime entrega somente MapBiomas como adapter.
Serviços simulados legados
`soil_service.py`/`mapbiomas_service.py` e o serviço dormente `water_service.py`
não participam do fluxo ativo nem da imagem. O gap dormente de water_service
permanece para planejamento do gestor, fora deste PRD.

RAG usa os dois corpora originais relativos ao módulo, splitter 1000/200, top 3,
`text-embedding-3-small` e `gpt-4o-mini` com temperatura 0.1. Embeddings são
recalculados por chamada; não há cache vetorial persistente. Booleanos, textos,
vetores nulos/incompatíveis/não finitos são recusados antes da resposta da IA.
Credenciais, custos, qualidade e acesso real aos datasets/modelos não foram
validados nesta entrega.

## Baseline e importação — somente após gate operacional

Leia [ORIGINAL-SCHEMA.md](docs/ORIGINAL-SCHEMA.md) para contrato descartável,
guardas de destino/PostGIS/schema vazio, manifesto e recuperação de falhas.
Não há DDL no startup. A baseline completa é independente da revisão histórica
Alembic; **não executar upgrade/stamp automaticamente**. A revisão histórica
não inicializa banco vazio e não deve ser aplicada sobre a baseline completa.

```text
python scripts/init_original_db.py --initialize --target-contract target.json --manifest-out original-manifest.json
python scripts/init_original_db.py --validate-only --target-contract target.json --manifest original-manifest.json
python migrate_rivers.py --target-contract target.json --input /caminho/aprovado/rios.geojson
```

O importador valida o arquivo inteiro antes da sessão e usa commit único. Sem
`--input`, o caminho é `data/exportCurtibaTypeAllRivers.geojson` relativo ao
módulo. O dataset **não é incluído na imagem**: monte o arquivo aprovado e use
`--input`. Contrato e manifesto também são montados fora do código da imagem;
a saída precisa ser gravável pelo UID 10001. PGHOSTADDR/PGSERVICE não vazios
são recusados antes da engine/sessão, sem leitura de arquivos de serviço.

### Migração do cache hidrográfico

Para um banco novo, inicialize e valide a baseline v1 com os comandos acima.
Para um banco existente, faça backup e execute a migração como proprietário
antes de publicar a API que usa o cache v2. A aplicação anterior exige a
lista exata de colunas v1 em `/ready`. Planeje uma janela entre migração e
publicação ou publique primeiro uma versão de transição de `/ready` que
aceite ambos os esquemas.

Prepare um contrato JSON com `host`, `port`, `database`, `schema: "public"`
e `purpose: "hydrography-cache-upgrade"`. Use `DATABASE_URL` com o mesmo
host, porta explícita e banco do contrato. Exemplo para a role da demo:

```sh
python scripts/upgrade_hydrography.py --target-contract hydro-target.json --runtime-role orbtalus_runtime
```

A transação valida o destino e o esquema, preserva os rios e análises
existentes, cria a tabela de consultas e o índice único da fonte, e aplica
as permissões adicionais à role informada. A role precisa das permissões
usuais de leitura e inserção em `water_bodies`. Reexecutar o comando em v2
valida o esquema e reaplica os grants pedidos. O importador v1 continua
gravando apenas a geometria, o nome e o tipo fornecidos pelo arquivo.

## Container e execução — comandos preparados, não executados

Dockerfile define Python 3.12.10 slim-bookworm, UID/GID 10001, PORT 8080 e
`exec` Uvicorn. COPY seleciona os arquivos de runtime e migração para a imagem. No contexto, cada
diretório liberado por `!dir/` é seguido por `dir/**` antes das exceções para
arquivos individuais; isso impede que a liberação do diretório inclua seus
outros descendentes. `.dockerignore` permite esses arquivos mais Dockerfile
e o próprio `.dockerignore`.
Inclui API, providers, baseline/importador e os dois corpora. Exclui segredos,
.env, testes, Ralph, .tools, logs, fixtures e dados de rios. Não há DDL ou
inicialização de providers no entrypoint.

A prova histórica de seleção da baseline v1 está em `.tools/story005-context-green.json`: compara
30 inclusões e 116 exclusões sintéticas usando a semântica de resultados dos
diretórios pais do Moby, restrita aos padrões usados aqui. O teste reproduz o
defeito das regras anteriores e recusa sintaxe fora desse subconjunto. Nenhum
arquivo de segredo é aberto pelo teste. COPY/imports do pacote e seleção do
contexto têm evidências separadas; o contexto real e o build Docker continuam
pendentes. Comandos e limites constam no [handoff](docs/HANDOFF-LOTE-A.md).

Comandos para a futura janela do gestor, após configurar destino e credenciais:

```text
docker build --pull -t orbtalus-api:original-a .
docker run --rm --env-file /caminho/aprovado/runtime.env -p 18090:8080 orbtalus-api:original-a
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

A imagem usa pinos candidatos e exige wheels; uma plataforma sem wheel falha
em vez de introduzir toolchain implicitamente. O tag base não é pinado por
digest. O gate Docker deve registrar digest base/imagem, resolução Linux,
`pip check`, usuário efetivo, corpora presentes e comportamento do processo.
O `--env-file` acima é lido pelo Docker, não pela aplicação. Não há build,
container, porta publicada ou deploy comprovado nesta rodada.

O harness de integração existente é um artefato externo, com overlay e mount
somente leitura em `/integration`, separado de `/app` e da imagem. Seus cinco
pontos de substituição e gates estão no [handoff](docs/HANDOFF-LOTE-A.md#harness-externo-existente-e-contrato-de-integração).
Não há modo de fixture ou flag de harness no produto; a compatibilidade
operacional desse artefato ainda depende da liberação e validação do gestor.
