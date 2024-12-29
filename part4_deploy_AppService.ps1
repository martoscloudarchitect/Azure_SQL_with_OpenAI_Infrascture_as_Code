
# Sets the Bicep file path to be used for deployment using the New-AzResourceGroupDeployment cmdlet below
$BicepFile = ".\part4_deploy_AppService.bicep"

function Load-DotEnv {
    param (
        [string]$Path
    )
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            if ($_ -match "^\s*([^#][^=]*)\s*=\s*(.*)\s*$") {
                $name = $matches[1]
                $value = $matches[2]
                [System.Environment]::SetEnvironmentVariable($name, $value)
            }
        }
    } else {
        Write-Error "The .env file was not found at path: $Path"
        exit 1
    }
}

# Load environment variables from .env file
$envFilePath = ".env"
Load-DotEnv -Path $envFilePath

# Retrieve Environment Variables
$AzureTenantID = $env:AZURE_TENANT_ID
$AzureSubscriptionID = $env:AZURE_SUBSCRIPTION_ID
$AzureSubscriptionName = $env:AZURE_SUBSCRIPTION_NAME
$AzureResourceGroupName = $env:AZURE_RESOURCE_GROUP_NAME
$AzureRegion = $env:AZURE_DEPLOYMENT_REGION

# Log the loaded environment variables
Write-Output "Azure Tenant ID: $AzureTenantID"
Write-Output "Azure Subscription ID: $AzureSubscriptionName"
Write-Output "Azure Resource Group Name: $AzureResourceGroupName"
Write-Output "Azure Region: $AzureRegion"

# Check if the Bicep file exists
if (-Not (Test-Path -Path $BicepFile)) {
    Write-Error "The Bicep file was not found at path: $BicepFile"
    exit 1
}

# Connect to Azure
#az login --tenant $AzureTenantID
#set the default subscription
#az account set --subscription $AzureSubscriptionID

az group list -o table

# Create a variable Deployment name using the script name and current date time
$DeploymentName = "part4_deploy_AppService" + (Get-Date).ToString("yyyyMMddHHmmss")

# Deploys the target bicep file in the referenced resource group
az deployment group create `
    --name $DeploymentName `
    --resource-group $AzureResourceGroupName `
    --template-file $BicepFile `
    --mode Incremental `
    --verbose

# Logs out of Azure
#az logout