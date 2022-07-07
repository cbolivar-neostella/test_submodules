import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (
    COGNITO_CLIENT, CORALOGIX_KEY, RESOURCE_METHOD, SERVICE_NAME,
    check_api_keys, check_tenant_level_permissions,
    check_user_level_permissions, delete_transaction, get_account_id,
    get_pool_id, initialize, send_to_coralogix, throttling_check,
    wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def resend_password(email, tenant_id):
    global COGNITO_POOL_ID

    COGNITO_POOL_ID = get_pool_id(tenant_id)
    cognito_response = COGNITO_CLIENT.admin_create_user(
        UserPoolId=COGNITO_POOL_ID,
        Username=email,
        UserAttributes=[
            {"Name": "email_verified", "Value": "True"},
            {"Name": "email", "Value": email}
        ],
        MessageAction='RESEND',
        DesiredDeliveryMediums=['EMAIL']
    )
    cognito_user_id = cognito_response['User']['Username']

    return (200, {'UUID': UUID, 'cognito_user_id': cognito_user_id, 'result': 'User password resended'})


def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exeeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        event_body = json.loads(event['body'])
        user_id, tenant_id = check_api_keys(event)
        account_id = get_account_id(user_id)
        # Check tenant level permissions
        if check_tenant_level_permissions(tenant_id, 'admin', 'users', 'general'):
            # Check user level permissions
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'users', 'general', 'can_update'):
                if account_id != None:
                    response = (
                        403, {'UUID': UUID, 'code': 'account_permissions.UserDoesNotHaveAccessToThisFeature'})
                else:
                    response = resend_password(event_body['email'], tenant_id)
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
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        ERROR_MSG = f'Execution failed: {repr(e)}. Line: {str(exc_tb.tb_lineno)}.'
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        delete_transaction()
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
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
