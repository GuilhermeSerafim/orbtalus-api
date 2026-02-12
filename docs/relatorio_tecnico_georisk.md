# Relatório Técnico: Varredura GeoRisk e Futuras Implementações

## 1. Estado Atual do Projeto (Varredura)

### 1.1. Arquitetura Geral
O projeto **GeoRisk** é uma aplicação backend desenvolvida em **Python** utilizando o framework **FastAPI**. A estrutura é modular e organizada, seguindo boas práticas de "Vertical Slice" ou arquitetura em camadas:

- **`core/`**: Configurações e utilitários básicos.
- **`routers/`**: Definição dos endpoints da API.
- **`services/`**: Lógica de negócio (ex: `ai_service.py`, `water_service.py`).
- **`providers/`**: Integrações com fontes de dados externas (Adapters).
- **`data/`**: Armazenamento de arquivos estáticos/texto para contexto da IA.

### 1.2. Inteligência Artificial (Atual)
A implementação atual de IA (`ai_vertical.py` e `services/ai_service.py`) utiliza o padrão **RAG (Retrieval-Augmented Generation)**:
- **Framework**: LangChain.
- **Modelo**: OpenAI (`gpt-4o`).
- **Contexto**: A IA responde perguntas baseada exclusivamente em dois arquivos de texto estáticos:
    - `flood_risk_brazil.txt`
    - `bart_flood_model.txt` (Artigo científico sobre modelo BART para inundações).
- **Embeddings**: `text-embedding-3-small` da OpenAI.
- **Funcionamento**: O sistema busca trechos relevantes nos textos acima e os envia ao GPT-4o para gerar uma resposta ou avaliação de risco (`RiskAssessment`).

### 1.3. Integrações de Dados (Providers)
- **MapBiomas**: Implementado (`mapbiomas_adapter.py`), parece funcional para obter dados de uso do solo.
- **Nottus**: Existe um arquivo `nottus_adapter.py`, mas atualmente opera em modo **PLACEHOLDER (Mock)**. Ele retorna dados fictícios baseados nas coordenadas geográficas (paridade de latitude/longitude).

---

## 2. Futuras Implementações

Conforme solicitado, segue a análise situacional e plano para **SAR**, **InSAR** e **Melhoria da IA com Nottus**.

### 2.1. SAR (Synthetic Aperture Radar)
**Estado Atual**:
- A única menção a SAR no projeto está no arquivo `bart_flood_model.txt`, referenciando o uso de dados "PALSAR" para gerar Modelos Digitais de Elevação (DEM). Não há código de processamento de radar implementado.

**Plano de Implementação**:
O SAR é essencial para monitoramento de inundações (pois "vê" através de nuvens) e umidade do solo.
1.  **Aquisição de Dados**: Integrar com Sentinel-1 (ESA) via API (ex: `sentinelsat` ou `asf_search`).
2.  **Processamento**: Implementar pipeline de pré-processamento (Calibração Radiométrica, Filtro de Speckle, Correção de Terreno).
3.  **Aplicação**:
    - **Detecção de Água**: Thresholding em imagens VH/VV para identificar corpos d'água em tempo real.
    - **Umidade do Solo**: Estimativa baseada na retroespalhamento (backscatter).

### 2.2. InSAR (Interferometria SAR)
**Estado Atual**:
- Não há menções ou implementações no código atual.

**Plano de Implementação**:
O InSAR é utilizado para detectar deformações milimétricas no solo (ex: deslizamentos, subsidência).
1.  **Complexidade**: O processamento bruto de InSAR (geração de interferogramas a partir de pares de imagens SLC) é computacionalmente intensivo e complexo para ser feito "on-the-fly" em uma API Python simples.
2.  **Estratégia Recomendada**: Consumir produtos já processados (Nível 3) de serviços como o **EGMS (European Ground Motion Service)** ou processar offline usando ferramentas como **SNAP** ou **ISCE2** e servir apenas os resultados (mapas de velocidade de deformação) via API GeoRisk.

### 2.3. Melhoria da IA com Dados da Nottus
**Objetivo**: Tornar a avaliação de risco da IA mais precisa usando dados reais da Nottus (ao invés de apenas textos genéricos).

**Estratégia de Implementação**:
1.  **Integração Real (Adapter)**:
    - Substituir o `NottusAdapter` mockado por chamadas reais à API da Nottus.
    - Capturar dados estruturados: *Tipo de Solo*, *Permeabilidade*, *Histórico de Inundações*, *Pluviometria*.
2.  **Enriquecimento de Contexto (Context Injection/RAG Avançado)**:
    - Atualmente, o prompt da IA recebe apenas trechos de texto (`{context}`).
    - **Novo Fluxo**:
        - O usuário envia coordenadas (Lat/Lon).
        - O sistema consulta o `NottusAdapter` e obtém os dados locais.
        - O prompt é montado dinamicamente:
          ```text
          Contexto Local (Dados Nottus):
          - Solo: Argiloso (Permeabilidade Baixa)
          - Histórico: 2 inundações nos últimos 5 anos
          - Chuva Recente: 50mm

          Contexto Teórico (RAG):
          [Trechos do bart_flood_model.txt...]

          Pergunta: Qual o risco de alagamento hoje?
          ```
    - Isso permite que a IA combine o *conhecimento teórico* (dos textos) com a *realidade local* (da Nottus).
3.  **Fine-Tuning (Longo Prazo)**:
    - Se houver um dataset histórico de "Dados Nottus" + "Ocorrência Real de Sinistro", podemos fazer o fine-tuning de um modelo (ex: GPT-4o-mini) para se especializar nessa correlação.

---

## 3. Próximos Passos Sugeridos

1.  **Imediato**: Implementar a conexão real com a API da Nottus (assim que chaves/docs estiverem disponíveis).
2.  **Curto Prazo**: Alterar o `ai_service.py` para injetar os dados estruturados do Adapter no prompt da IA.
3.  **Médio Prazo**: Criar um módulo `services/sar_service.py` para baixar e processar imagens Sentinel-1 para áreas críticas.
