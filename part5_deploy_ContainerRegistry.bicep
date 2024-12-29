

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2020-11-01-preview' = {
  name: 'ikeacontainerregistry'
  location: resourceGroup().location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
  tags: {
    environment: 'dev'
    deployment: 'bicep'
    version: '1.0.0'
  }
}
