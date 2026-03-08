# Relatório Técnico: Arquitetura e Motor de Risco do GeoRisk

**Última atualização:** 08/03/2026

---

## 1. Arquitetura Geral

O GeoRisk é uma API backend em **Python/FastAPI** com arquitetura **Monolito Modular**:

```
core/           → Motor de cálculo (RiskCalculator)
routers/        → Endpoints da API (/geo/risk, /geo/distance)
services/       → Lógica de negócio (IA, OSM, elevação)
providers/      → Integrações externas (MapBiomas, Nottus)
models.py       → Modelos SQLAlchemy (WaterBody, RiskAssessment)
```

### Stack de Integração

```
PostGIS (Supabase) ← rios e histórico
       ↕
OpenStreetMap (Overpass API) ← waterways + relations
       ↕
Google Earth Engine ← MapBiomas Collection 8 (solo) + Water Collection 3 (frequência)
       ↕
Open-Elevation API ← SRTM 30m
       ↕
RiskCalculator ← algoritmo ponderado (topo 50% / água 30% / solo 20%)
       ↕
GPT-4 (LangChain RAG) ← laudo técnico enriquecido
       ↕
FastAPI ← endpoint /geo/risk (audit-ready JSON)
```

---

## 2. Fluxo do Endpoint `/geo/risk`

1. Recebe polígono GeoJSON, calcula ponto representativo (Shapely).
2. Busca/cacheia rios próximos via Overpass (OSM) → PostGIS.
3. Consulta PostGIS: corpo d'água mais próximo, distância e ponto de contato.
4. Consulta elevação no ponto do usuário e no ponto do rio (SRTM), gerando queda relativa.
5. Consulta dados ambientais (solo e frequência de água) via MapBiomas/GEE.
6. Executa `RiskCalculator` (motor determinístico ponderado).
7. Gera laudo técnico via IA (GPT-4 + contexto RAG).
8. Persiste histórico em `risk_assessments`.

---

## 3. Fórmula de Risco

### 3.1 Score Total

`total = topografia × 0.50 + água × 0.30 + solo × 0.20`

### 3.2 Topografia (sub-score)

`topografia = distância × 0.60 + elevação × 0.40`

| Distância | Score | Elevação | Score |
|---|---|---|---|
| < 50m | 1.0 | < -2m (abaixo do rio) | 1.0 |
| < 100m | 0.8 | < 0m | 0.9 |
| < 200m | 0.5 | < 2m | 0.7 |
| < 500m | 0.3 | < 5m | 0.4 |
| ≥ 500m | 0.1 | ≥ 5m | 0.1 |

### 3.3 Frequência de Água

**Prioridade 1:** Dados de satélite MapBiomas (30 anos)

| Anos com água | Score |
|---|---|
| ≥ 20 | 1.0 |
| ≥ 10 | 0.8 |
| ≥ 5 | 0.6 |
| ≥ 2 | 0.4 |
| ≥ 1 | 0.2 |

**Prioridade 2 (fallback):** Quando satélite retorna 0 (rios canalizados), usa distância PostGIS:

| Distância | Score inferido |
|---|---|
| < 100m | 0.6 |
| < 300m | 0.4 |
| < 500m | 0.2 |
| < 1000m | 0.1 |

### 3.4 Solo (Permeabilidade)

| Tipo | Score |
|---|---|
| Impermeável (urbano, mineração) | 1.0 |
| Permeável (floresta, pastagem) | 0.0 |

### 3.5 Classificação Final

| Score | Nível |
|---|---|
| ≥ 0.7 | 🔴 Alto |
| ≥ 0.4 | 🟡 Médio |
| < 0.4 | 🟢 Baixo |

---

## 4. Integrações Externas (Adapter Pattern)

### MapBiomas (Implementado)
- **Solo:** Collection 8, banda `classification_2022`, resolução 30m.
- **Água:** Water Collection 3, buffer 1km com `Reducer.max()`, auto-detecção de banda.

### OSM / Overpass (Implementado)
- Query `way["waterway"]` + `relation["waterway"]` com raio de 5km.
- Processamento de relations para capturar nomes de rios grandes.
- Cache em PostGIS (>5 rios no raio = área já mapeada).

### Nottus (Placeholder)
- `NottusAdapter` retorna mock data, pronto para plugar API real.

### SAR/InSAR (Roadmap)
- Sentinel-1 para detecção de água real-time e deformação do solo.

---

## 5. Pontos Fortes

1. **Explicável e auditável:** regras explícitas, pesos fixos, IA justifica.
2. **Arquitetura limpa:** cálculo isolado em `core/`, providers desacoplados.
3. **Degradação controlada:** continua operando com fallback em caso de falha.
4. **Resposta rica:** score total, sub-scores, pesos e laudo em um JSON.

## 6. Limitações Conhecidas

1. **Elevação `0` tratada como `None`** — regiões ao nível do mar perdem dado topográfico.
2. **Solo binário** — não diferencia parque de asfalto dentro de "Área Urbanizada".
3. **SRTM 30m** — micro-topografia urbana pode ter erro de ±10m.
4. **Cobertura OSM** — depende de mapeamento voluntário.
5. **Sem fallback para falha da IA** — se GPT-4 falhar, endpoint retorna erro.

## 7. Recomendações para Produção

### Curto prazo
- Trocar `if elev and ...` por checagem `is not None`
- Fallback textual quando IA falhar
- Versionar modelo de risco (`risk_model_version`)

### Médio prazo
- SAR (Sentinel-1) via GEE para water frequency real-time
- SRTM → LIDAR (resolução 1m)
- ANA (hidrografia oficial) para substituir OSM
- Solo granular (escala contínua 0-1)

### Longo prazo
- InSAR como 4º componente (subsidência/deformação)
- Calibração empírica com dados de sinistro real
- Fine-tuning de modelo IA com histórico de risco
