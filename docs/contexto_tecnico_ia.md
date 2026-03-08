# Contexto Técnico: Arquitetura e Implementação do GeoRisk

**Copie e cole o texto abaixo na sua ferramenta de IA (Perplexity, ChatGPT, Claude, etc) para dar o contexto técnico do projeto:**

---

**[INÍCIO DO CONTEXTO TÉCNICO]**

Atue como um Engenheiro de Software/Arquiteto de Soluções Sênior. Estou desenvolvendo uma plataforma B2B Inurtech/ClimateTech chamada **GeoRisk**. Preciso que você entenda nossa stack e arquitetura atual para me ajudar com futuras implementações, refatorações ou análises técnicas.

Aqui está o descritivo técnico detalhado do projeto:

### 1. Visão Geral da Arquitetura
O GeoRisk é uma API baseada na arquitetura **Monolito Modular (Modular Monolith)**. Foi escolhida essa abordagem em vez de Microsserviços puros para evitar a complexidade prematura de deploy e rede, enquanto ainda mantemos o isolamento lógico das regras de negócios. 
O código é separado em módulos claros (pastas `routers`, `services`, `providers`, `models`), permitindo que a aplicação rode em um único servidor/contêiner (Monolito), mas que possa ser "quebrada" em microsserviços no futuro se o tráfego escalar. O objetivo primário é entregar análise de risco hidrológico em tempo real cruzando satélites, dados on-ground e IA.

- **Linguagem Backend:** Python 3.9+
- **Framework Web:** FastAPI (alta performance, roteamento assíncrono).
- **Gerenciamento de Dados/Schema:** Pydantic (validação de dados de entrada/saída).
- **Padrão de Projeto:** Baseado em Injeção de Dependências e *Adapter Pattern* para provedores de dados externos.

### 2. Stack de IA e Modelagem de Risco (O "Cérebro")
A inteligência do sistema não é puramente estatística; utilizamos **RAG (Retrieval-Augmented Generation)** para que a IA justifique o risco como um hidrólogo especialista.

- **Framework de LLM:** LangChain.
- **Modelos Integrados:** OpenAI API (GPT-4o para geração de texto, text-embedding-3-small para vetorização).
- **Pipeline RAG Atual:**
    1.  Temos uma base de conhecimento em TXT (`data/flood_risk_brazil.txt`, `data/bart_flood_model.txt`).
    2.  Usamos `RecursiveCharacterTextSplitter` para fatiar o texto.
    3.  Vetorizamos com embeddings da OpenAI e guardamos em memória (arrays NumPy).
    4.  Cruzamos a *query* do usuário (ou atributos do terreno) com o vetor mais próximo (Cosine Similarity) para injetar contexto na *prompt*.
- **Estruturação de Saída:** Usamos `with_structured_output` (do LangChain) para garantir que a resposta da LLM sempre retorne um modelo Pydantic rígido (ex: `RiskAssessment(risk_level="alto", explanation="...")`).

### 3. Integrações de Dados Externa (Adapter Pattern)
Em vez de depender apenas de satélites macro (que ignoram o microclima e a saturação do solo local), injetamos provedores de dados específicos. A arquitetura exige que eles implementem uma classe abstrata `DataProvider` (ex: métodos `get_soil_data()`, `get_water_frequency()`).

- **Integração Nottus (Dados de Solo):** Responsável por buscar dados de umidade, temperatura do solo e permeabilidade em tempo real (atualmente usando *mock data* baseada em paridade de coordenadas, pronto para plugar a API real).
- **Integração MapBiomas (Uso do Solo):** Extrato de dados do Google Earth Engine (Python API) para verificar o tipo de vegetação/urbanização.
- **Integração SAR/InSAR (Em Roadmap):** Planejado uso de imagens C-band (Sentinel-1) via API ESA/Copernicus (ou Google Earth Engine) para detecção de água na superfície e mapas de subsidência do solo (ajuda a descobrir "rios invisíveis" subterrâneos).

### 4. Fluxo de Execução Típico (Endpoint `/ask-ai`)
1. O usuário passa `lat`, `lon` e uma `pergunta` via FastAPI.
2. O serviço de IA instancia o `NottusAdapter`.
3. Busca dados on-ground (solo/água) baseados nas coordenadas.
4. Constrói o contexto RAG buscando a literatura técnica pertinente (ex: modelos hidrológicos BART).
5. Injeta **Dados Locais (Nottus) + Contexto Teórico (RAG)** em um template de Prompt.
6. A LLM avalia a situação e retorna o JSON estruturado do Risco.

### 5. Minha Estratégia Atual ("Zero Hardware")
O GeoRisk atua exclusivamente como a **camada de inteligência (Software/DaaS)**. Não desenvolvemos nem instalamos sensores físicos ou pluviômetros. Em vez disso, compramos ou nos integramos a APIs de quem já tem o hardware no campo (ex: Nottus) ou quem tem constelações de satélites gratuitas/pagas (ESA Sentinel, Planet).

**[FIM DO CONTEXTO TÉCNICO]**
