``` mermaid
graph TD
    A[Users] -->|HTTP Requests| B[Azure App Service]
    B -->|NLP Requests| C[Azure OpenAI Service]
    B -->|Search Queries| D[Azure AI Search]
    D -->|Fetch Data| E[Azure SQL Database]
    C -->|Fetch Data| E
    E -->|Return Data| D
    D -->|Return Search Results| B
    C -->|Return NLP Results| B
    B -->|HTTP Responses| A

    subgraph Azure Cloud
        B
        C
        D
        E
    end