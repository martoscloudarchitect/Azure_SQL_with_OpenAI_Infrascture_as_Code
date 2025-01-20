/// Deploys an Azure OpenAI Service to an existing resoruce group and on the same location as the resource group.

/// defines the resourc group as a parameter from the AzResourceDeployment command
// part1_createaoai.bicep
param location string = resourceGroup().location
/// Creates a new Azure OpenAI Service in the specified location using Resource Group Name and Identity
param openaiServiceName string = 'aoaiservice${uniqueString(resourceGroup().id, 1, 10)}'
param openaiServiceSku string = 'S0'
param openaiServiceKind string = 'OpenAI'
param openaiModelSku string = 'GlobalStandard' /// GlobalStandard, Standard

resource openaiService 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openaiServiceName
  location: location
  kind: openaiServiceKind
  sku: {
    name: openaiServiceSku
  }
  properties: {
    publicNetworkAccess: 'Enabled'    
  }
  tags: {
    environment: 'dev'
    deployment: 'bicep'
    version: '1.0.0'
  }
}

output openaiServiceName string = openaiService.name

resource GPT4oModel 'Microsoft.CognitiveServices/accounts/deployments@2024-06-01-preview'= {
  name: 'gpt-4o'
  parent: openaiService
  sku: {
    capacity: 8
    name: openaiModelSku
  }
  properties: {
    model : {
      format: 'OpenAI'
      name:'gpt-4o'
      version: '2024-08-06' 
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    currentCapacity: 10
    raiPolicyName: ''
  }
}
