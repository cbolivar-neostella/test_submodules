import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (
    CORALOGIX_KEY, RESOURCE_METHOD, SERVICE_NAME, check_api_keys,
    check_tenant_level_permissions, check_tenant_limit,
    check_user_level_permissions, confirm_transaction, create_transaction,
    delete_transaction, deserialize_rds_response, get_account_id, get_pool_id,
    initialize, rds_execute_statement, send_to_coralogix, throttling_check,
    wait_for_threads, webhook_dispatch)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def update_user(user_id, cognito_user_id, update_dict, account_id=None, time_zone=None):
    if time_zone is not None:
        update_dict["time_zone"] = time_zone
    update_list = [f"{key} = '{value}'" for key, value in update_dict.items()]
    sql = f"UPDATE users_master SET {', '.join(update_list)}, updated_by = '{user_id}', updated_at = NOW() WHERE cognito_user_id = '{cognito_user_id}'"
    if account_id is not None:
        sql += f" AND account_id = '{account_id}'"
    rds_response = rds_execute_statement(sql)


def update_status(user_id, tenant_id, cognito_user_id, status, account_id=None):
    # Update user status in cognito
    client = boto3.client('cognito-idp')
    COGNITO_POOL_ID = get_pool_id(tenant_id)
    if status:
        if check_tenant_limit('users_master', tenant_id):
            sql = f"UPDATE users_master SET is_active = true, updated_by = '{user_id}', updated_at = NOW() WHERE cognito_user_id = '{cognito_user_id}'"
            # Filter by account id if sent
            if account_id is not None:
                sql += f" AND account_id = '{account_id}'"

            rds_response = rds_execute_statement(sql)

            client.admin_enable_user(
                UserPoolId=COGNITO_POOL_ID,
                Username=cognito_user_id
            )
            return True
        else:
            return False
    else:
        sql = f"UPDATE users_master SET is_active = false, updated_by = '{user_id}', updated_at = NOW() WHERE cognito_user_id = '{cognito_user_id}'"
        # Filter by account id if sent
        if account_id is not None:
            sql += f" AND account_id = '{account_id}'"
        rds_response = rds_execute_statement(sql)

        client.admin_disable_user(
            UserPoolId=COGNITO_POOL_ID,
            Username=cognito_user_id
        )
        return True


def update_roles(user_id, tenant_id, cognito_user_id, update_roles_list):
    roles_query = f"SELECT role_id FROM user_roles WHERE cognito_user_id = '{cognito_user_id}';"
    rds_response = rds_execute_statement(roles_query)
    response = deserialize_rds_response(rds_response)
    old_roles_list = [role["role_id"] for role in response]

    # Insert Roles
    for role in update_roles_list:
        if role in old_roles_list:
            pass
        else:
            insert_query = f"INSERT INTO user_roles (tenant_id, cognito_user_id, role_id, created_by) "\
                f"VALUES('{tenant_id}', '{cognito_user_id}', '{role}', '{user_id}');"
            rds_execute_statement(insert_query)

    get_default_role_query = f"SELECT role_id FROM roles_master WHERE tenant_id = '{tenant_id}' AND type = 'default'"
    rds_response = rds_execute_statement(get_default_role_query)
    response = deserialize_rds_response(rds_response)
    default_roles_list = [role["role_id"] for role in response]

    # Delete Roles From User
    for role in old_roles_list:
        if role in update_roles_list or role in default_roles_list:
            pass
        else:
            delete_query = f"DELETE FROM user_roles WHERE role_id = '{role}' AND cognito_user_id = '{cognito_user_id}';"
            rds_execute_statement(delete_query)


@webhook_dispatch(object_name='users_master', action='update')
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
        cognito_user_id = event_body['cognito_user_id']
        # Check tenant level permissions
        if ((check_tenant_level_permissions(tenant_id, 'admin', 'users', 'general') & (user_id != cognito_user_id)) |
                (check_tenant_level_permissions(tenant_id, 'user_settings', 'users', 'general') & (user_id == cognito_user_id))):
            # Check user level permissions
            if ((check_user_level_permissions(tenant_id, user_id, 'admin', 'users', 'general', 'can_update') & (user_id != cognito_user_id)) |
                    (check_user_level_permissions(tenant_id, user_id, 'user_settings', 'users', 'general', 'can_update') & (user_id == cognito_user_id))):
                # Update User
                get_pool_id(tenant_id)
                create_transaction()
                updated = True

                # print(old_user)

                # Update user status in Cognito

                if "is_active" in event_body:
                    updated = update_status(user_id, tenant_id,
                                            cognito_user_id, event_body['is_active'], account_id=account_id)

                if updated:

                    # Update user_roles
                    if 'roles' in event_body and account_id is None:
                        update_roles(user_id, tenant_id,
                                     cognito_user_id, event_body['roles'])

                    # Update users_master
                    allowed_keys = ['first_name', 'last_name']
                    filtered_body = dict(
                        filter(lambda item: item[0] in allowed_keys, event_body.items()))
                    time_zone = event_body.pop("time_zone", None)
                    update_user(
                        user_id, event_body['cognito_user_id'], filtered_body, account_id=account_id, time_zone=time_zone)

                    response = (
                        200, {'UUID': UUID, 'result': 'User updated', 'cognito_user_id': cognito_user_id})
                else:
                    response = (
                        403, {'UUID': UUID, 'code': 'tenant_permissions.ObjectLimitReached'})
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
