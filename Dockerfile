FROM python:3.11.0

EXPOSE 8501
RUN mkdir -p /app
WORKDIR /app

# Copies the requirements file to the container
COPY requirements.txt ./requirements.txt
COPY README.md ./README.md
COPY ./images ./images
COPY .env .env
COPY application.py ./application.py

# Defines Variables
ENV OPENAI_API_TYPE=azure
ENV AZURE_OPENAI_ENDPOINT=https://<YOUR-AZURE-OPENAI-SERVICE>.api.cognitive.microsoft.com/
ENV OPENAI_API_BASE=https://<YOUR-AZURE-OPENAI-SERVICE>.api.cognitive.microsoft.com/
ENV OPENAI_API_KEY=<YOUR-AZURE-OPENAI-SERVICE-KEY>
ENV OPENAI_API_VERSION=2024-10-01-preview
ENV OPENAI_CHAT_MODEL=gpt-4o
ENV SQL_SERVER_ENDPOINT=<YOUR-AZURE-SQL-SERVER-NAME>.database.windows.net
ENV SQL_SERVER_NAME=<YOUR-AZURE-SQL-SERVER-NAME>
ENV SQL_SERVER_PORT=1433
ENV SQL_SERVER_USERNAME=<YOUR-AZURE-SQL-SERVER-USERNAME>
ENV SQL_SERVER_PASSWORD=<YOUR-AZURE-SQL-SERVER-PSWD>
ENV SQL_DB_NAME=<YOUR-AZURE-SQL-DATABASE-NAME>

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    unixodbc-dev \
    curl \
    gnupg2 \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Installs python packages
RUN pip3 install --no-cache-dir -r requirements.txt

# Intializing the streammlit python app
ENTRYPOINT ["streamlit", "run"]
CMD ["application.py"]