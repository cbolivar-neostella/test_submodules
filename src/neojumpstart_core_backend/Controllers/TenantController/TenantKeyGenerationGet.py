import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
#import Values
#import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (
    APPKEY_SECRET_ARN, COGNITO_CLIENT, CORALOGIX_KEY, CORALOGIX_SECRETS,
    DATABASE_NAME, DB_CLUSTER_ARN, DB_CREDENTIALS_SECRETS_STORE_ARN,
    RDS_CLIENT, REGION_NAME, RESOURCE_METHOD, SERVICE_NAME, check_api_keys,
    check_tenant_level_permissions, check_tenant_limit,
    check_user_level_permissions, confirm_transaction, create_transaction,
    decode_key, delete_transaction, deserialize_rds_response, get_account_id,
    get_pool_id, get_secret, get_tenant_id, initialize, rds_execute_statement,
    send_to_coralogix, throttling_check, wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def get_tenant_key(tenant_id=None):
    sql_get_tenant_keys = f"""SELECT tenant_id, tenant_key_id, secret_name, secret_arn FROM tenant_keys WHERE tenant_id = '{tenant_id}'"""
    tenant_keys = deserialize_rds_response(
        rds_execute_statement(sql_get_tenant_keys))
    print(tenant_keys)
    response = (200, {'UUID': UUID, 'records': tenant_keys})
    return response


def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exceeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        # Or use this for methods that include a body
        #event_body = json.loads(event['body'])
        user_id, tenant_id = check_api_keys(event)
        account_id = get_account_id(user_id)
        # Check tenant level permissions (Adjunts the arguments of the function for your specific case)
        # TODO: Check permissions
        if check_tenant_level_permissions(tenant_id, 'admin', 'tenant_keys', 'general'):
            # Check user level permissions (Adjunts the arguments of the function for your specific case)
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'tenant_keys', 'general', 'can_read'):
                # Create a function to perform the required action and returns a tuple with the status code in the first item and the json object in the second one
                if account_id is not None:
                    response = (
                        403, {'UUID': UUID, 'code': 'user_permissions.UserDoesNotHaveAccessToThisFeature'})
                else:
                    response = get_tenant_key(tenant_id=tenant_id)
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
