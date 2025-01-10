import os
import pyodbc
import sqlalchemy
from dotenv import load_dotenv
import pandas as pd
from pandasai import SmartDataframe
from pandasai.responses.response_parser import ResponseParser
from langchain_openai import AzureChatOpenAI
import streamlit as st

#dotenv.load_dotenv()

load_dotenv()

## Alternative 1 - Read from your local file as a CSV using Pandas
# imports the CSV file from ./data/garmin_data.csv
# data = pd.read_csv("garminactivities.csv")

## Alternative 2 - Read data from your remote Azure SQL Database
## SQL Database Credentials Option 1 - hard Code into the python (not recommended)
# db_host="YourServerName"
# db_name="YourDataBaseName"
# db_user="YourUserAdminLogin"
# db_password="YourUswerAdminPsw"
# driver = '{ODBC Driver 18 for SQL Server}'
## SQL Database Credentials Option 2 - hard Code into environment variable (also not recommended)
db_host_name=os.getenv('SQL_SERVER_NAME')
db_name=os.getenv('SQL_DB_NAME')
db_user=os.getenv('SQL_SERVER_USERNAME')
db_password=os.getenv('SQL_SERVER_PASSWORD')
odbc_driver='{ODBC Driver 18 for SQL Server}'

if not all([db_host_name, db_name, db_user, db_password]):
    raise ValueError("One or more environment variables are not set. Please check your .env file.")

# SQL Database Connection
#cnxn = pyodbc.connect(f'DRIVER='+driver+';SERVER=tcp:'+db_host+'.database.windows.net;PORT=1433;DATABASE='+db_name+';UID='+db_user+';Pwd='+ db_password+';Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;')
# cnxn = pyodbc.connect(f'DRIVER='+odbc_driver+';SERVER=tcp:'+db_host_name+'.database.windows.net;PORT=1433;DATABASE='+db_name+';UID='+db_user+';Pwd='+ db_password+';Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;')
# cursor = cnxn.cursor()

# Create connection string
connection_string = {
    'drivername': 'mssql+pyodbc',
    'username': db_user,
    'password': db_password,
    'host': f"{db_host_name}.database.windows.net",
    'port': 1433,
    'database': db_name,
    'query': {'driver': 'ODBC Driver 18 for SQL Server'}
}
db_url = sqlalchemy.engine.url.URL(**connection_string)

# Connect to the database using SQLAlchemy
engine = sqlalchemy.create_engine(db_url)
connection = engine.connect()

# SQL Query to import all data from the garminactivities table, for Small table only - not for scale.
query = "SELECT * FROM [dbo].[garminactivities]"

data_df = pd.read_sql(query, connection)

connection.close()

llm = AzureChatOpenAI(
        model=os.getenv("OPENAI_CHAT_MODEL"),
        deployment_name=os.getenv("OPENAI_CHAT_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0
)

class StreamlitResponse(ResponseParser):
    def __init__(self, context) -> None:
        super().__init__(context)

    def format_dataframe(self, result):
        st.dataframe(result["value"])
        return

    def format_plot(self, result):
        st.image(result["value"])
        return

    def format_other(self, result):
        st.write(result["value"])
        return

query_engine = SmartDataframe(
        data_df,
        config={
            "llm": llm,
            #"response_parser": StreamlitResponse(ResponseParser context={})
            "response_parser": StreamlitResponse
        }
)

st.write("# Chat with your Garmin Activity data")

st.write("Connected to the following data source in Azure: ")
st.write("SQL database: **" + db_name + "** on server: **" + db_host_name +"**")

summary = "Describle what is the data about. Provide a description or each column based on the header and sample from the data records."
overview = query_engine.chat(summary)
st.write(overview)

st.image("./images/solution_diagram_overview.jpg", caption="Solution Diagram Overview", use_container_width=True)

with st.expander('Here is a short description of your data:'):
    st.write(data_df.head())

query = st.text_area("Chat with your data using PandasAI")

st.write(query)

if query:
    answer = query_engine.chat(query)
    st.write(answer)
else:
    st.write("Ask a question to get started")
    
