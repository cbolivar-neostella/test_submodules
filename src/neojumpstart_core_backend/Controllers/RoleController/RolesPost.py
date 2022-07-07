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
    check_tenant_level_permissions, check_tenant_limit,
    check_user_level_permissions, confirm_transaction, create_transaction,
    delete_transaction, deserialize_rds_response, initialize,
    rds_execute_statement, send_to_coralogix, throttling_check,
    wait_for_threads, webhook_dispatch)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def create_role(user_id, role, data, tenant_id):
    if check_tenant_limit('roles_master', tenant_id):

        # TODO(?): ADD ONLY ROLE_PERMISSIONS TO A ROLE, NOT CREATE DUPLICATED ROLE
        sql = f"INSERT INTO roles_master( role, tenant_id, created_by) VALUES ( '{role}', '{tenant_id}', '{user_id}') RETURNING role_id"
        role_id = rds_execute_statement(sql)['records'][0][0]["stringValue"]

        # CREATE A FULL SQL WITH ALL THE INSERTS TO MAKE ONLY ONE EXECUTE STATEMENT INTO THE DATABASE
        complete_sql = ""
        # ITERATE IN ALL THE DATA KEY/VALUE PAIRS
        for module, components in data.items():
            sql = ""
            for component, subcomponents in components.items():
                for subcomponent, permissions in subcomponents.items():
                    sql = f"SELECT components_id FROM components_master WHERE is_active = true AND module = '{module}' AND component='{component}' AND subcomponent='{subcomponent}' "
                    component_id_result = rds_execute_statement(sql)
                    if component_id_result['records'][0]:
                        components_id = component_id_result['records'][0][0]["stringValue"]
                        sql = f"INSERT INTO role_permissions (tenant_id, role_id, components_id, created_by, "
                        sql_values = f"('{tenant_id}', '{role_id}', '{components_id}', '{user_id}', "
                        for permissions, permission in permissions.items():
                            sql += f"{permissions}, "
                            sql_values += f"{permission}, "
                        sql = sql[:-2] + ") VALUES " + sql_values[:-2] + ");\n"
                        complete_sql += sql
                    else:
                        continue

        rds_execute_statement(complete_sql)
        return (200, {'UUID': UUID, 'role_id': role_id, 'result': 'Role created'})
    else:
        return (403, {'UUID': UUID, 'code': 'tenant_permissions.ObjectLimitReached'})


@webhook_dispatch(object_name='roles_master', action='create')
def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exeeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        event_body = json.loads(event['body'])
        user_id, tenant_id = check_api_keys(event)
        if check_tenant_level_permissions(tenant_id, 'admin', 'roles', 'general'):
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'roles', 'general', 'can_create'):
                create_transaction()
                response = create_role(
                    user_id, event_body['role_name'], event_body['permissions'], tenant_id)
                confirm_transaction()
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
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers, tenant_id"
            }
        }
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        ERROR_MSG = f'Execution failed: {repr(e)}. Line: {str(exc_tb.tb_lineno)}.'
        delete_transaction()
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
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers, tenant_id"
            }
        }
