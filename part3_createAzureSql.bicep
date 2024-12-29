@description('Location for all resources.')
param location string = resourceGroup().location

/// Creates a unique name for the SQL logical server using resource group name and id
@description('The name of the SQL logical server.')
var fullSqlServerName = '${resourceGroup().name}${uniqueString(resourceGroup().id)}'
var sqlServerName = take(fullSqlServerName, 19)

@description('The name of the SQL Database.')
param sqlDatabaseName string = 'aoaidb'

@description('The administrator username of the SQL logical server.')
param sqlServerAdminLogin string = 'sqlAdmin'

@description('The administrator password of the SQL logical server.')
@secure()
param administratorLoginPassword string

resource sqlServer 'Microsoft.Sql/servers@2022-05-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    administratorLogin: sqlServerAdminLogin
    administratorLoginPassword: administratorLoginPassword
  }
}

resource sqlDB 'Microsoft.Sql/servers/databases@2022-05-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
}

output sqlServerName string = sqlServer.name
output sqlServerAdminLogin string = sqlServer.properties.administratorLogin
output sqlDatabaseName string = sqlDB.name
