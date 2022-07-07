import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
#import Values
from src.neojumpstart_core_backend.functions import (APPKEY_SECRET_ARN, COGNITO_CLIENT, CORALOGIX_KEY,
                                                     CORALOGIX_SECRETS, DATABASE_NAME, DB_CLUSTER_ARN,
                                                     DB_CREDENTIALS_SECRETS_STORE_ARN, RDS_CLIENT,
                                                     REGION_NAME, RESOURCE_METHOD, SERVICE_NAME)
#import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (
    check_api_keys, check_tenant_level_permissions, check_tenant_limit,
    check_user_level_permissions, confirm_transaction, create_transaction,
    decode_key, delete_transaction, deserialize_rds_response, get_account_id,
    get_pool_id, get_secret, get_tenant_id, initialize, rds_execute_statement,
    send_to_coralogix, throttling_check, wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def decode_key(key):
    encoded_bytes = bytes(key, 'utf-8')
    decoded_str = str(base64.b64decode(encoded_bytes.decode('utf-8')), 'utf-8')
    tenant_id_from_key = decoded_str.split(':')[0]
    return tenant_id_from_key


def insert_key_record(user_id, tenant_id, secret_response):
    sql_create_tenant_keys = "CREATE TABLE IF NOT EXISTS tenant_keys ("\
        "tenant_key_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "tenant_id uuid NOT NULL, "\
        "secret_arn VARCHAR(200) NOT NULL, "\
        "secret_name VARCHAR(200) NOT NULL, "\
        "secret_version VARCHAR(200) NOT NULL, "\
        "created_by VARCHAR(50) DEFAULT NULL, "\
        "updated_by VARCHAR(50) DEFAULT NULL, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id)"\
        ")"
    rds_execute_statement(sql_create_tenant_keys)

    sql_insert_key_record = "INSERT INTO tenant_keys (tenant_id, secret_arn, secret_name, secret_version, created_by) "\
        "VALUES ("\
        f"'{tenant_id}', "\
        f"'{secret_response['ARN']}', "\
        f"'{secret_response['Name']}', "\
        f"'{secret_response['VersionId']}', "\
        f"'{user_id}' "\
        ")"
    rds_execute_statement(sql_insert_key_record)

    sql_insert_user = f"INSERT INTO users_master (cognito_user_id, first_name, email, tenant_id) "\
        "VALUES ("\
        f"uuid_generate_v4 (), "\
        f"'{secret_response['Name']}', "\
        f"'{secret_response['Name']}', "\
        f"'{tenant_id}'"\
        ")"
    rds_execute_statement(sql_insert_user)


def create_secret(secret_name, key_name, secret_value):
    SECRETS_CLIENT = boto3.client('secretsmanager', region_name=REGION_NAME)
    response = SECRETS_CLIENT.create_secret(
        Name=secret_name,
        SecretString=f'{{"{key_name}":"{secret_value}"}}'
    )
    return response


def validate_values(tenant_id=None, secret_name=None):

    if tenant_id is None:
        return False, "tenantKey.TenantIdIsRequired"

    if secret_name is None:
        return False, "tenantKey.SecretNameIsRequired"

    return True, "Succes"


def create_tenant_key(user_id=None, tenant_id=None, secret_name=None):
    valid, code = validate_values(tenant_id, secret_name)
    if not valid:
        return (403, {'UUID': UUID, 'code': code})

    secret_name = f"""{SERVICE_NAME.replace("-","/")}/TenantKey/{secret_name}"""
    data = tenant_id + ":" + UUID

    # Standard Base64 Encoding
    encodedBytes = base64.b64encode(data.encode("utf-8"))
    encodedStr = str(encodedBytes, "utf-8")

    curr_response = create_secret(secret_name, 'Key', encodedStr)

    insert_key_record(user_id, tenant_id, curr_response)

    return (200, {'UUID': UUID, 'code': 'Success', 'TenantKey': encodedStr})


def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exceeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        # Or use this for methods that include a body
        event_body = json.loads(event['body'])
        user_id, tenant_id = check_api_keys(event)
        account_id = get_account_id(user_id)
        # Check tenant level permissions (Adjunts the arguments of the function for your specific case)
        # TODO: Check permissions
        if check_tenant_level_permissions(tenant_id, 'admin', 'users', 'general'):
            # Check user level permissions (Adjunts the arguments of the function for your specific case)
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'users', 'general', 'can_create'):
                # Create a function to perform the required action and returns a tuple with the status code in the first item and the json object in the second one
                if account_id is not None:
                    response = (
                        403, {'UUID': UUID, 'code': 'user_permissions.UserDoesNotHaveAccessToThisFeature'})
                else:
                    response = create_tenant_key(
                        **event_body, user_id=user_id, tenant_id=tenant_id)
            else:
                response = (
                    403, {'UUID': UUID, 'code': 'role_permissions.UserDoesNotHaveAccessToThisFeature'})
        else:
            response = (403, {
                        'UUID': UUID, 'code': 'tenant_permissions.TenantDoesNotHaveAccessToThisFeature'})

        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Execution time': EXECUTION_TIME,
                                          'response': response[1]}, SERVICE_NAME, RESOURCE_METHOD, 3)
        wait_for_threads()
        return {
            'statusCode': response[0],
            'body': json.dumps(response[1]),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT,DELETE",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        ERROR_MSG = f'Execution failed: {repr(e)}. Line: {str(exc_tb.tb_lineno)}.'
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Status': 'Failure', 'Execution time': EXECUTION_TIME,
                                          'Error message': ERROR_MSG}, SERVICE_NAME, RESOURCE_METHOD, 5)
        wait_for_threads()
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': ERROR_MSG,
                'code': str(exc_type),
                'UUID': UUID
            }),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT,DELETE",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
