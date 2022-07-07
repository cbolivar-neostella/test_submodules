import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
#import src.neojumpstart_core_backend.functions as functions
#import Values
from src.neojumpstart_core_backend.functions import (
    CORALOGIX_KEY, DATABASE_NAME, DB_CLUSTER_ARN,
    DB_CREDENTIALS_SECRETS_STORE_ARN, RDS_CLIENT, RESOURCE_METHOD,
    SERVICE_NAME, deserialize_rds_response, initialize, rds_execute_statement,
    send_to_coralogix, throttling_check, wait_for_threads)


def get_tenant(tenant_name):
    sql = f"SELECT * FROM tenants_master WHERE tenant_name = '{tenant_name}'"
    send_to_coralogix(CORALOGIX_KEY, {
        'UUID': UUID, 'Query string': sql}, SERVICE_NAME, RESOURCE_METHOD, 3)
    rds_response = RDS_CLIENT.execute_statement(
        secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN,
        database=DATABASE_NAME,
        resourceArn=DB_CLUSTER_ARN,
        includeResultMetadata=True,
        sql=sql
    )
    return rds_response


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def get_tenant_permissions(tenant_id):
    sql = f"SELECT components_master.module, components_master.component, components_master.subcomponent "\
        "FROM tenant_permissions INNER JOIN components_master ON "\
        "components_master.components_id = tenant_permissions.components_id "\
        f"WHERE tenant_permissions.tenant_id = '{tenant_id}' AND components_master.is_active = true"
    send_to_coralogix(CORALOGIX_KEY, {
        'UUID': UUID, 'Query string': sql}, SERVICE_NAME, RESOURCE_METHOD, 3)
    rds_response = RDS_CLIENT.execute_statement(
        secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN,
        database=DATABASE_NAME,
        resourceArn=DB_CLUSTER_ARN,
        includeResultMetadata=True,
        sql=sql
    )
    return rds_response


def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exeeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        query_parameters = event['queryStringParameters']
        response = get_tenant(query_parameters['tenant_name'])
        tenant_data = {}
        col_count = 0
        for current_column in response['columnMetadata']:
            tenant_data[current_column['name']] = list(
                response['records'][0][col_count].values())[0]
            col_count += 1
        tenant_data["permissions"] = {}
        response = get_tenant_permissions(tenant_data['tenant_id'])
        col_count = 0
        for record in response['records']:
            col_count = 0
            for current_column in response['columnMetadata']:
                value = list(record[col_count].values())[0]
                if current_column['name'] == "module":
                    if value not in tenant_data["permissions"].keys():
                        tenant_data["permissions"][value] = {}
                    module = value
                elif current_column['name'] == "component":
                    if value not in tenant_data["permissions"][module].keys():
                        tenant_data["permissions"][module][value] = []
                    component = value
                elif current_column['name'] == "subcomponent":
                    if value not in tenant_data["permissions"][module][component]:
                        tenant_data["permissions"][module][component].append(
                            value)
                    subcomponent = value
                col_count += 1
        # ADD TENANT PERMISSIONS TO DATA
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Execution time': EXECUTION_TIME,
                                          'response': tenant_data}, SERVICE_NAME, RESOURCE_METHOD, 3)
        wait_for_threads()
        return {
            'statusCode': 200,
            'body': json.dumps(tenant_data),
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
