# Schema original, baseline e importação

Este documento prepara comandos para uma janela operacional autorizada separadamente.
Nesta entrega, **não foram executados banco, DDL, PostGIS, importação real ou Docker**.
Os testes usam dublês e bloqueiam rede. O manifesto esperado em memória descreve o
modelo; somente um ensaio autorizado poderá produzir um manifesto refletido de um
banco real e provar compatibilidade com a versão escolhida de PostgreSQL/PostGIS.

## Contrato e guardas

`models.py` continua o original. A baseline não cria extensão, banco, usuário,
privilégios, colunas novas ou `alembic_version`. A extensão PostGIS deve existir
em `public`. A URL deve ser fornecida como `DATABASE_URL` no ambiente do processo;
nenhum comando carrega `.env`. Não coloque senha no contrato nem em argumentos.

Exemplo **ilustrativo**, sem autorização para conectar:

```json
{
  "host": "db.example.invalid",
  "port": 55442,
  "database": "disposable_test",
  "schema": "public",
  "purpose": "disposable-original-baseline"
}
```

O contrato aceita exatamente esses cinco campos. Exige host, porta e database
idênticos aos da URL PostgreSQL, porta explícita, schema `public`, finalidade
descartável e nenhum parâmetro de query na URL (evita overrides de conexão).
Recusa `PGHOSTADDR` ou `PGSERVICE` não vazios antes de construir engine/sessão,
pois defaults libpq podem redirecionar a conexão mesmo com host explícito.
Não lê arquivos de serviço nem imprime valores do ambiente. `PGSERVICEFILE`
sozinho não seleciona serviço. O gestor deve fornecer um ambiente sem esses
overrides; o comando não altera o ambiente para contornar a recusa.
Após conectar, confere `current_database()`, `current_schema()`, schemas efetivos
explícitos iguais a `[public]` e a extensão. Não é uma prova da identidade física
do servidor: DNS, redirecionamentos e destino operacional pertencem ao contrato
que o gestor deve conferir antes da janela. Use conexão nova e banco descartável,
sem escritores concorrentes, com papel owner somente para baseline/importação.

Antes de DDL, a baseline inventaria objetos dependentes do namespace `public`.
Objetos pertencentes ao PostGIS e suas dependências internas são excluídos; qualquer
outro objeto (inclusive função, tipo, tabela ou sequência) impede inicialização.
Não há limpeza automática. Após criar o metadata original em uma transação,
reflete e compara colunas, nulabilidade, defaults SQL, PKs, índices e sequências
com o modelo. Falha aborta a transação. A API não chama esse inicializador.

Comandos para o gestor executar **somente depois da liberação operacional**:

```text
python scripts/init_original_db.py --initialize --target-contract target.json --manifest-out original-manifest.json
python scripts/init_original_db.py --validate-only --target-contract target.json --manifest original-manifest.json
python migrate_rivers.py --target-contract target.json --input /caminho/rios.geojson
```

`--initialize` exige um arquivo de saída novo: reserva-o com criação exclusiva
antes da conexão e nunca sobrescreve um manifesto anterior. Um erro pode deixar
esse arquivo vazio ou parcial. A escrita, o flush e o fechamento ocorrem dentro
da transação, antes do commit: falha em qualquer uma dessas etapas provoca
rollback da DDL. O artefato é sempre retido, nunca apagado automaticamente.
Isso não cria transação distribuída entre banco e disco: falha de commit,
conexão interrompida ou queda do processo pode deixar um manifesto completo
sem confirmação do resultado no banco. Um arquivo existente não prova commit.
Em qualquer falha, preserve o artefato; o gestor deve conferir o estado durante
a janela autorizada. Se o schema estiver completo, use `--validate-only` com
manifesto completo; se estiver vazio, uma nova inicialização exige outro nome
exclusivo de saída. Schema parcial/divergente exige investigação, sem limpeza
ou nova DDL automática. Os comandos mostram erro fixo, sem DSN ou traceback.

`--validate-only` exige manifesto coincidente com o modelo, abre transação
**READ ONLY**, rejeita objetos desconhecidos e compara a reflexão atual.
Não chama `create_all`, não instala extensão, não grava manifesto nem outro
arquivo. Repetir inicialização em schema não vazio é sempre recusado. Os testes
de guardas e transação não demonstram execução real de PostgreSQL.

## Manifesto original

O formato `orbtalus-original-v1` inclui schema, tabelas, colunas em ordem, tipos,
defaults SQL, nulabilidade, PKs, índices (método, colunas, unicidade, inclusão e
predicado), constraints e sequências (tipo, início, limites, incremento, cache,
ciclo e coluna proprietária). Não exporta credenciais ou valores de registros.
`python_defaults` identifica separadamente defaults do ORM; não os apresenta
como defaults instalados no servidor.

| Tabela | Colunas originais |
| --- | --- |
| `water_bodies` | `id`, `name`, `type`, `geom` |
| `risk_assessments` | `id`, `lat`, `lon`, `risk_level`, `explanation`, `river_name`, `distance_m`, `water_frequency_30y`, `soil_type`, `soil_class_id`, `is_permeable`, `created_at` |

As PKs são inteiros SERIAL com sequências próprias. Além dos índices de PK,
o metadata declara `ix_water_bodies_id`, `ix_risk_assessments_id` e o GiST
`idx_water_bodies_geom`. `geom` aceita geometria WGS84/SRID4326; não se adiciona
filtro por metadados de origem. `created_at` é obrigatório e tem **default Python
`datetime.utcnow`, sem default SQL**. Inserts SQL diretos precisam fornecer seu
valor. `soil_class_id` já integra a baseline completa.

## Política Alembic

A revisão histórica `add_soil_class_id_v2`, no arquivo
`alembic/versions/add_soil_class_id_manual.py`, é um patch de tabela existente.
Não cria a baseline e tentaria adicionar uma coluna que ela já contém.
O arquivo histórico permanece intocado. Não executar `alembic upgrade head`
nem `alembic stamp` como inicialização ou após esta baseline.

`alembic/env.py` exige `DATABASE_URL` explícita, recusa ausência antes de criar
engine e não usa dotenv ou URL de `alembic.ini` como fallback. Isso não autoriza
usar a revisão histórica na baseline. Uma migração futura exige reconciliação
do histórico por decisão própria do gestor. Não inventamos histórico aplicado.

## Importador e OSM

O importador aceita GeoJSON local `FeatureCollection`, sem override de CRS,
com coordenadas bidimensionais finitas nos limites de longitude/latitude.
Valida todas as features antes de criar a sessão ou adicionar linhas; geometria
inválida, bool/NaN/Infinity, nome/tipo inválido ou arquivo ausente interrompem.
O default é `data/exportCurtibaTypeAllRivers.geojson` relativo ao módulo, mesmo
em outro cwd. `--input` seleciona arquivo explícito. Não há download de dados.
Todos os rios são gravados em uma transação com commit único e rollback/close
em falha. Não há DDL em import ou carga. `migrate(path=None)` também é chamável
por código confiável; o CLI exige `--target-contract` e verifica o destino.
Com contrato, confere também a URL da engine efetivamente vinculada à sessão
antes de conectar, recusando uma engine em cache que aponte para outro destino.

Nome e tipo preservam os defaults herdados (`Sem nome`, `river` quando ausentes),
com remoção de controles de texto inválidos. A projeção permanece `name/type/geom`;
o banco gera `id`. **Não há deduplicação**: reimportar pode duplicar rios.

O enriquecimento OSM mantém consulta ways/relations, raio padrão 5km e regra
herdada de cache (mais de cinco rios na área evita consulta). Usa sessão e
transação próprias; falhas de criação, provider, commit, rollback ou close são
best effort e registram mensagens fixas. Relações continuam fornecendo nome/tipo
a ways sem essas tags. O cache pode ter confirmado alterações mesmo que a
análise de risco falhe depois. Isso não autoriza gravar um `risk_assessments`
de análise malsucedida. Falha de enriquecimento não desqualifica rios herdados.
Sem rio utilizável, risk responde503 e distance404, conforme o contrato da API.

## Evidências e próximos gates

Testes: `test_original_schema`, `test_river_import`, `test_osm_service`,
`test_legacy_rivers`, import safety e a suíte offline completa. O manifesto de
teste, a compilação SQL local e os mocks não comprovam DDL ou durabilidade real.
O gestor ainda deve autorizar/provar baseline em DB novo com PostGIS, reflexão
do manifesto, carga do arquivo aprovado, permissões do app sem DDL e restore.
Docker/build, browser integrado, providers reais, ARM64/hosting e publicação
continuam gates separados. Somente o gestor faz commits e integração.

Referências da revisão de catálogo: [funções de identidade de objetos do PostgreSQL](https://www.postgresql.org/docs/current/functions-info.html#FUNCTIONS-INFO-OBJECT-TABLE)
e [tipos de dependência em pg_depend](https://www.postgresql.org/docs/current/catalog-pg-depend.html).
