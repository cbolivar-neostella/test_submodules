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
    CORALOGIX_KEY, RESOURCE_METHOD, SERVICE_NAME, check_api_keys,
    check_tenant_level_permissions, check_user_level_permissions,
    deserialize_rds_response, initialize, rds_execute_statement,
    send_to_coralogix, throttling_check, wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


TRANSLATIONS_BUCKET = os.environ['TRANSLATIONS_BUCKET']


def get_file(file_name, bucket_name):

    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=bucket_name, Key=file_name)
    return json.loads(response['Body'].read())


def lambda_handler(event, context):
    # TODO implement
    try:
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        user_id, tenant_id = check_api_keys(event)
        if check_tenant_level_permissions(tenant_id, "admin", "translations", "general"):
            if check_user_level_permissions(tenant_id, user_id, "admin", "translations", "general", "can_update"):
                event = json.loads(event["body"])
                bucket = TRANSLATIONS_BUCKET
                language = event["lang"]
                file_name = f'{tenant_id}.json'
                object_name = f'{tenant_id}.json'
                response = get_file(file_name, bucket)
                json_keys = event["key"].split(".")
                try:
                    current_level = response[language]
                except Exception as e:
                    response[language] = {}
                    current_level = response[language]

                for i, keys in enumerate(json_keys):
                    if i == len(json_keys)-1:
                        current_level[keys] = event["value"]
                    else:
                        if keys in current_level:
                            current_level = current_level[keys]
                        else:
                            current_level[keys] = {}
                            current_level = current_level[keys]

                # response[event["key"]] =
                s3_client = boto3.client('s3')
                object_name = bytes(json.dumps(response).encode('UTF-8'))
                s3_client.put_object(
                    Bucket=bucket, Key=file_name, Body=object_name)
                response = (
                    200, {'UUID': UUID, 'result': 'Custom translation added'})
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
