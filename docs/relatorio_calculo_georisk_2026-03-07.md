# Relatório Técnico: Cálculo de Risco no GeoRisk

**Data:** 07/03/2026  
**Escopo:** avaliar como o cálculo de risco é feito hoje no endpoint `/geo/risk` e se a abordagem atual é a melhor forma para produção.

## 1. Resumo executivo

O GeoRisk usa hoje uma **matriz de decisão ponderada e explicável** (determinística), com boa legibilidade para MVP e auditoria.  
Não é a melhor forma final para produção em escala, mas é uma boa base inicial.

**Veredito:**  
- **Boa para MVP e explicabilidade:** sim.  
- **Melhor forma para acurácia/robustez de produção:** ainda não.

---

## 2. Como o cálculo funciona hoje

Fluxo observado no endpoint de risco:

1. Recebe um polígono e calcula um ponto representativo (Shapely).  
   Referência: `routers/risk.py:48-50`.
2. Atualiza/cacheia rios próximos via Overpass (OSM) e salva no banco.  
   Referência: `routers/risk.py:52`, `services/osm_service.py:11-68`.
3. Busca no PostGIS o corpo d'água mais próximo, a distância e o ponto mais próximo no rio.  
   Referência: `routers/risk.py:54-68`.
4. Consulta elevação no ponto do usuário e no ponto do rio (Open-Meteo), gerando queda relativa.  
   Referência: `routers/risk.py:84-87`, `services/elevation_service.py:3-7`.
5. Consulta dados ambientais (solo e frequência de água) via provider (MapBiomas/GEE).  
   Referência: `routers/risk.py:89-97`, `providers/mapbiomas_adapter.py:103-235`.
6. Executa o motor de cálculo (`RiskCalculator`).  
   Referência: `routers/risk.py:99-105`, `core/risk_calculator.py:99-169`.
7. Gera explicação textual por IA e persiste histórico.  
   Referência: `routers/risk.py:107-139`, `services/ai_service.py:22-70`, `models.py:17-31`.

---

## 3. Fórmula e regras atuais

### 3.1 Componentes e pesos globais

O score total é:

`total = topo*0.50 + agua*0.30 + solo*0.20`  
Referência: `core/risk_calculator.py:26-28`, `127-131`.

### 3.2 Topografia

Topografia combina distância e diferença de elevação:

`topo = dist*0.60 + elev*0.40`  
Referência: `core/risk_calculator.py:42-68`.

Faixas atuais:
- Distância `<50m=1.0`, `<100=0.8`, `<200=0.5`, `<500=0.3`, `>=500=0.1`.
- Elevação `None=0.5`, `<-2m=1.0`, `<0=0.9`, `<2=0.7`, `<5=0.4`, `>=5=0.1`.

### 3.3 Frequência de água (MapBiomas)

- `>=20 anos=1.0`, `>=10=0.8`, `>=5=0.6`, `>=2=0.4`, `>=1=0.2`, `0=0.0`.  
Referência: `core/risk_calculator.py:71-88`.

### 3.4 Solo/permeabilidade

- Permeável => `0.0`, impermeável => `1.0`.  
Referência: `core/risk_calculator.py:91-97`.

### 3.5 Classificação final

- `>=0.7`: Alto  
- `>=0.4 e <0.7`: Médio  
- `<0.4`: Baixo  
Referência: `core/risk_calculator.py:133-139`.

### 3.6 Confiança

Base 1.0 com penalidade por ausência:
- sem elevação: `x0.8`
- sem soil_class_id: `x0.9`  
Referência: `core/risk_calculator.py:141-146`.

---

## 4. Pontos fortes da abordagem atual

1. **Explicável e auditável:** regras explícitas e pesos fixos facilitam defesa técnica.  
2. **Arquitetura limpa para evolução:** cálculo isolado em `core/` e fontes de dados desacopladas via adapter.  
3. **Degradação controlada:** sistema continua operando mesmo com falha de provider externo.  
4. **Resposta rica para inspeção:** retorna score total, sub-scores e pesos aplicados.

---

## 5. Limitações e riscos técnicos

1. **Queda relativa pode virar `None` quando elevação for `0`**  
   Em `routers/risk.py:86`, a condição usa truthy (`if elev_ponto and elev_rio`), então `0` é tratado como ausência.  
   Impacto: perda indevida de informação topográfica em regiões próximas do nível do mar.

2. **Fallback tende a reduzir risco com confiança alta demais**  
   Quando provider falha, solo vira permeável e frequência vira 0 (`routers/risk.py:95-96`, `mapbiomas_adapter.py:114-123`, `190-194`).  
   Como `soil_class_id=0` (não `None`), a confiança pode permanecer alta (`risk_calculator.py:145-146`).  
   Impacto: falso senso de segurança.

3. **Conversão de frequência de água simplificada para 30 anos**  
   A banda citada cobre 1985-2023 (39 anos), mas a conversão usa `*30` (`mapbiomas_adapter.py:207`, `224`).  
   Impacto: possível subestimação/superestimação em certos cenários.

4. **Modelo de solo é binário (permeável vs impermeável)**  
   Não considera gradiente hidrológico real (ex.: grau de compactação, textura, drenagem urbana).

5. **Topografia usa faixas discretas fixas**  
   Simples e robusto, porém pode perder nuance local (microdrenagem, canalização, declividade real, bacias urbanas).

6. **Endpoint de risco depende de IA para completar resposta**  
   Se IA falhar, hoje não há fallback claro no endpoint (`routers/risk.py:122`).  
   Impacto: disponibilidade operacional menor que o necessário para serviço crítico.

---

## 6. É a melhor forma?

**Resposta direta:** não é a melhor forma final, mas é uma **boa forma inicial**.

Avaliação:
- **MVP / prova de conceito:** 8/10 (boa clareza e valor rápido).  
- **Produção regulada / escala nacional:** 5.5/10 (precisa fortalecer qualidade de dados, calibração e fallback).  
- **Explicabilidade para auditoria:** 8.5/10.

---

## 7. Recomendações priorizadas

### 7.1 Correções rápidas (alto impacto, baixo esforço)

1. Trocar `if elev_ponto and elev_rio` por checagem `is not None`.
2. Incorporar `water_data["confidence"]` no cálculo final de confiança.
3. Penalizar confiança quando usar fallback (`class_id == 0` ou frequência default).
4. Tratar falha da IA com fallback textual simples, sem derrubar o endpoint.

### 7.2 Evolução de modelo (médio prazo)

1. Calibrar pesos e thresholds com dados históricos de sinistro/alagamento.
2. Trocar score de solo binário por escala contínua (0-1) com classes intermediárias.
3. Revisar normalização da frequência de água para janela temporal real da coleção.
4. Adicionar variáveis de chuva antecedente, declividade e drenagem urbana.

### 7.3 Governança técnica (produção)

1. Versionar o modelo de risco (`risk_model_version`) em resposta e banco.
2. Criar suíte de testes unitários para o `RiskCalculator` cobrindo bordas.
3. Monitorar drift: distribuição de score por região e incidência de fallback.

---

## 8. Conclusão

O cálculo atual do GeoRisk está bem estruturado para explicar decisões e evoluir de forma incremental.  
Para ser a melhor abordagem em produção, precisa principalmente: **calibração empírica, melhoria de confiança em modo degradado, e tratamento robusto de falhas externas**.

