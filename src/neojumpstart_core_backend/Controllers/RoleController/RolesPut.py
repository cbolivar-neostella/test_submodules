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
    delete_transaction, deserialize_rds_response, initialize,
    rds_execute_statement, send_to_coralogix, throttling_check,
    wait_for_threads, webhook_dispatch)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def update_role_permissions(role_id, permissions, tenant_id, user_id):

    get_default_role_query = f"SELECT role_id FROM roles_master WHERE tenant_id = '{tenant_id}' AND type = 'default'"
    default_role_id = rds_execute_statement(get_default_role_query)['records']
    default_roles_list = []

    for role in default_role_id:
        default_roles_list.append(role[0]['stringValue'])

    if role_id in default_roles_list:
        pass
    else:
        for module, components in permissions.items():
            for component, subcomponents in components.items():
                for subcomponent, role_permissions in subcomponents.items():
                    sql = f"SELECT components_id FROM components_master WHERE is_active = true AND module = '{module}' AND component='{component}' AND subcomponent='{subcomponent}' "
                    component_id_result = rds_execute_statement(sql)
                    if component_id_result['records'][0]:
                        components_id = component_id_result['records'][0][0]["stringValue"]
                        can_create = role_permissions['can_create'] if "can_create" in role_permissions else "null"
                        can_read = role_permissions['can_read'] if "can_read" in role_permissions else "null"
                        can_update = role_permissions['can_update'] if "can_update" in role_permissions else "null"
                        can_delete = role_permissions['can_delete'] if "can_create" in role_permissions else "null"
                        update_role_query = f"UPDATE role_permissions SET can_create={can_create},can_read={can_read},"
                        update_role_query += f"can_update={can_update},can_delete={can_delete}, updated_by = '{user_id}', updated_at = NOW() "
                        update_role_query += f"WHERE role_id = '{role_id}' "
                        update_role_query += f"AND components_id = '{components_id}';"
                        rds_execute_statement(update_role_query)
                    else:
                        continue


@webhook_dispatch(object_name='roles_master', action='update')
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
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'roles', 'general', 'can_update'):
                create_transaction()

                role_id = event_body["role_id"]
                update_role_permissions(
                    role_id, event_body["permissions"], tenant_id, user_id)
                response = (
                    200, {'UUID': UUID, 'role_id': role_id, 'result': 'Role updated'})

                if "is_active" in event_body:
                    if event_body["is_active"]:
                        is_active = event_body["is_active"]
                        if check_tenant_limit("roles_master", tenant_id):
                            sql = f"UPDATE roles_master SET is_active = {is_active}, updated_by = '{user_id}', "\
                                f"updated_at = NOW() WHERE role_id='{role_id}'"
                            rds_execute_statement(sql)
                        else:
                            response = (
                                403, {'UUID': UUID, 'result': 'tenant_permissions.ObjectLimitReached'})
                    else:
                        # Search for role name
                        role_sql = f"SELECT type FROM roles_master WHERE role_id='{role_id}'"
                        basic_role_result = rds_execute_statement(role_sql)
                        role_type = basic_role_result['records'][0][0]['stringValue']
                        # Cannot delete admin nor default role
                        if role_type not in ["admin", "default"]:
                            # Create SQL statements and execute them
                            sql = f"UPDATE roles_master SET is_active = false, updated_by = '{user_id}', "\
                                f"updated_at = NOW() WHERE role_id='{role_id}'"
                            rds_execute_statement(sql)
                            sql = f"DELETE FROM user_roles WHERE role_id='{role_id}'"
                            rds_execute_statement(sql)

                confirm_transaction()

            else:
                response = (
                    403, {'UUID': UUID, 'code': 'role_permissions.UserDoesNotHaveAccessToThisFeature'})
        else:
            response = (403, {
                        'UUID': UUID, 'code': 'tenant_permissions.TenantDoesNotHaveAccessToThisFeature'})

        # Send logs to coralogix and return
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
