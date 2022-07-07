# Core Submodule

## Serverless file

Add the following content to the `serverless.yml` file

```yml

# ...
  environment:
    SERVICE_NAME: ${self:service}-${self:provider.stage}
    REGION_NAME: ${self:provider.region}
    DATABASE_NAME: ${self:resources.0.Resources.MasterUserDB.Properties.DatabaseName}
    DB_CLUSTER_ARN: arn:aws:rds:${self:provider.region}:${aws:accountId}:cluster:${self:resources.0.Resources.MasterUserDB.Properties.DBClusterIdentifier}
    CORALOGIX_SECRET: ${self:resources.0.Resources.CoralogixKey.Properties.Name}
    DB_CREDENTIALS_SECRETS_STORE_ARN:
      Ref: DatabaseKeys
    APPKEY_SECRET_ARN:
      Ref: ApplicationKey

# ...

  iam:
    role:
      managedPolicies:
        - arn:aws:iam::aws:policy/AmazonRDSDataFullAccess
        - arn:aws:iam::aws:policy/AmazonCognitoPowerUser
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
        - arn:aws:iam::aws:policy/SecretsManagerReadWrite
        - arn:aws:iam::aws:policy/AmazonS3FullAccess
        - arn:aws:iam::aws:policy/IAMFullAccess

# ...

functions:
  - ${file(./src/neojumpstart_core_backend/Controllers/UserController/serverless.yml):functions}
  - ${file(./src/neojumpstart_core_backend/Controllers/RoleController/serverless.yml):functions}
  - ${file(./src/neojumpstart_core_backend/Controllers/TenantController/serverless.yml):functions}
  - ${file(./src/neojumpstart_core_backend/Controllers/TranslationController/serverless.yml):functions}
  - ${file(./src/neojumpstart_core_backend/TenantResources/tenant_neostella.yml):functions}

resources:
  # Core Resources
  - ${file(./src/neojumpstart_core_backend/init.yml):resources}

  # Cognito AppKeys
  - ${file(./src/neojumpstart_core_backend/cognito_app_keys.yml):resources}

  # Cognito Neostella
  - ${file(./src/neojumpstart_core_backend/TenantResources/tenant_neostella.yml):resources}

```

## Serverless doc file

Add the following content to the `OpenAPI_Doc/serverless.doc.yml` file

```yml
# ...

models:
  - name: "UsersPostRequest"
    description: "Model for creating a new user"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/UsersPostRequest.json)}
  - name: "UsersPutRequest"
    description: "Model for updating an user"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/UsersPutRequest.json)}
  - name: "UsersGetResponse"
    description: "Model for get user data response"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/UsersGetResponse.json)}
  - name: "RolesGetResponse"
    description: "Model for get role data response"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/RolesGetResponse.json)}
  - name: "RolesPostRequest"
    description: "Model for creating a new role"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/RolesPostRequest.json)}
  - name: "RolesPutRequest"
    description: "Model for updating a role"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/RolesPutRequest.json)}
  - name: "TranslationsPostRequest"
    description: "Model for creating a new custom translation"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/TranslationsPostRequest.json)}
  - name: "TranslationsGetResponse"
    description: "Model for the response of the translations"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/TranslationsGetResponse.json)}
  - name: "TranslationsDeleteRequest"
    description: "Model for deleting a custom translation"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/TranslationsDeleteRequest.json)}
  - name: "TenantsGetResponse"
    description: "Response received when requesting tenant information"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/TenantsGetResponse.json)}
  - name: "TimeZonesGetResponse"
    description: "Model for get time zones data response."
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/TimeZonesGetResponse.json)}
  - name: "ResendPasswordPostRequest"
    description: "Model for resend password to a user"
    contentType: "application/json"
    schema: ${file(./src/neojumpstart_core_backend/OpenAPI_Doc/Models/ResendPasswordPostRequest.json)}
# ...
```
