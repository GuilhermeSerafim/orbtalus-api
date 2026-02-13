# Curso Introdutório: SAR e InSAR para Desenvolvedores Python

**Objetivo:** Entender como usar dados de satélite gratuitos (Sentinel-1) para detectar água e deformações no solo, sem precisar de hardware físico.

---

## Módulo 1: O Conceito Básico (SAR)

### 1.1 O que é SAR (Synthetic Aperture Radar)?
Diferente de satélites ópticos (como o Google Earth, que tiram "fotos"), o SAR é um **radar**.
- **Como funciona:** O satélite emite um pulso de micro-ondas para a Terra e mede o que volta (eco/backscatter).
- **Vantagem matadora:** O radar atravessa nuvens, fumaça e funciona à noite. Para inundações (que ocorrem em tempestades), isso é essencial.

### 1.2 Detectando Água ("Rios Invisíveis" de Superfície)
A água é fácil de ver no radar:
- **Superfície Rugosa (Solo/Vegetação):** O sinal bate e volta espalhado = Imagem Brilhante/Cinza.
- **Superfície Lisa (Água Calma):** O sinal bate e reflete para longe (igual espelho) = **Imagem Preta**.
- **Lógica no Código:** Se um pixel era "cinza" (solo) e virou "preto" (água) durante uma chuva, ali é um ponto de inundação.

### 1.3 Implementação em Python
Existe uma biblioteca oficial da ESA e ferramentas Python:
- **Acesso aos Dados:** API `sentinelsat` ou `asf_search` (NASA).
- **Processamento:** Bibliotecas `snappy` (SNAP ESA) ou `rioxarray`.

---

## Módulo 2: O Conceito Avançado (InSAR)

### 2.1 O que é InSAR (Interferometria SAR)?
InSAR é a técnica de comparar **duas imagens SAR** do mesmo lugar, tiradas em dias diferentes.
- Ele mede a **diferença de fase** da onda.
- **Precisão:** Consegue detectar movimentos no solo de **milímetros**.

### 2.2 Aplicação: Mapeando "Rios Invisíveis" Subterrâneos
- **Subsidência (Afundamento):** Quando um lençol freático seca ou um canal subterrâneo colapsa/move, o solo em cima afunda levemente.
- O InSAR gera um "mapa de calor" de onde o chão está se movendo.
- **Risco:** Áreas que afundam (subsidência) viram bacias naturais para acumular água.
- **Como a gente vende isso:** "Detectamos onde o solo está cedendo antes de visualmente aparecer um buraco ou uma poça."

---

## Módulo 3: Pipeline de Implementação (Roadmap)

Se você não vai usar hardware, seu "sensor" é o Satélite Sentinel-1 (Gratuito/ESA).

### Passo 1: Aquisição de Dados (Python)
Script que roda todo dia às 18h:
1. Conecta na API da ESA (Copernicus).
2. Baixa a imagem Sentinel-1 mais recente da área de interesse (ex: São Paulo).

### Passo 2: Processamento (Water Detection)
1. **Calibração:** Converter o sinal bruto em dB (decibéis).
2. **Thresholding (Limiar):** Tudo abaixo de -20dB é considerado água.
3. **Comparação:** Comparar com um "mapa base" de seca.
   - `Água Atual` - `Água Normal` = **Inundação**.

### Passo 3: Ingestão na Nottus/IA
- O script gera um GeoJSON: `{"type": "Feature", "properties": {"risk": "high", "cause": "water_detected"}}`
- A sua IA (RAG) lê isso: *"O satélite detectou acúmulo de água na região X, confirmando a saturação do solo prevista."*

---

## Ferramentas Recomendadas
1.  **SNAP (Sentinel Application Platform):** Software desktop para testar e visualizar. Open Source.
2.  **Google Earth Engine (GEE):** A forma mais fácil de começar sem baixar terabytes de dados. Tem API Python (`import ee`).
    - *Recomendação:* Comece pelo GEE. Você processa tudo na nuvem do Google e só baixa o resultado leve (JSON/CSV).
