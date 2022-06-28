# Submodules project test

## YML file example

```yml
service: submodules

frameworkVersion: "3"

plugins:
  - serverless-python-requirements
  - serverless-aws-documentation
provider:
  name: aws
  runtime: python3.8
  lambdaHashingVersion: 20201221

  region: ${file(./variables.json):AWSREGION}
  stage: ${file(./variables.json):AWSSTAGE}
  profile: ${file(./variables.json):PROFILE}

  memorySize: 1024
  timeout: 30

  environment:
    # ...

  httpApi:
    cors:
      allowedOrigins:
        - "*"
      allowedHeaders:
        - Access-Control-Allow-Headers
        - Origin
        - Accept
        - X-Requested-With
        - Content-Type
        - Access-Control-Request-Method
        - Access-Control-Request-Headers
        - Authorization
      allowedMethods:
        - GET
        - HEAD
        - OPTIONS
        - POST
        - PUT
        - DELETE
      allowCredentials: true
      exposedResponseHeaders:
        - Special-Response-Header
      maxAge: 6000 # In seconds

  iam:
    role:
      managedPolicies:
        # ...

  layers:
    - arn:aws:lambda:us-east-2:651364325517:layer:CoralogixRequests:2
    - Ref: PythonRequirementsLambdaLayer

functions:
  # ...

resources:
  # ...

custom:
  pythonRequirements:
    dockerizePip: true
    layer:
      name: ${self:service}-${self:provider.stage}-python-libraries
      description: Layer containing the python libraries necessary for project ${self:service}
      compatibleRuntimes:
        - python3.8
  documentation: ${file(./OpenAPI_Doc/serverless.doc.yml):documentation}
```
