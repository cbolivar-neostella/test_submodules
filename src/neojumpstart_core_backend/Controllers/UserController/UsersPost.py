import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (
    APPKEY_SECRET_ARN, COGNITO_CLIENT, CORALOGIX_KEY, REGION_NAME,
    RESOURCE_METHOD, SERVICE_NAME, check_api_keys,
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


def assign_roles(user_id, tenant_id, cognito_user_id, update_roles_list):
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
                f"VALUES('{tenant_id}','{cognito_user_id}','{role}', '{user_id}');"
            rds_execute_statement(insert_query)

    # assign the default roles
    get_default_role_query = f"SELECT role_id FROM roles_master WHERE tenant_id = '{tenant_id}' AND type = 'default'"
    rds_response = rds_execute_statement(roles_query)
    response = deserialize_rds_response(rds_response)
    default_role_id = [role["role_id"] for role in response]

    for role in default_role_id:
        if role in old_roles_list or role in default_role_id:
            pass
        else:
            assign_default_role_query = f"INSERT INTO user_roles (tenant_id, cognito_user_id, role_id, created_by)"\
                f" VALUES('{tenant_id}','{cognito_user_id}','{role}', '{user_id}');"
            rds_execute_statement(assign_default_role_query)


def create_user(user_id, email, first_name, last_name, roles, tenant_id, time_zone="UTC", account_id=None):
    global COGNITO_POOL_ID
    if check_tenant_limit('users_master', tenant_id):
        # Create user in Cognito
        COGNITO_POOL_ID = get_pool_id(tenant_id)
        cognito_response = COGNITO_CLIENT.admin_create_user(
            UserPoolId=COGNITO_POOL_ID,
            Username=email,
            UserAttributes=[
                {"Name": "email_verified", "Value": "True"},
                {"Name": "email", "Value": email}
            ],
            DesiredDeliveryMediums=['EMAIL']
        )
        cognito_user_id = cognito_response['User']['Username']

        # If it doesn't have an account_id it is a tenant user
        if account_id is None:
            is_account_user = "false"
            # Create user in users_master
            sql = f"INSERT INTO users_master (cognito_user_id, first_name, last_name, email, tenant_id, is_account_user, account_id, time_zone, created_by)"\
                f" VALUES ('{cognito_user_id}','{first_name}','{last_name}','{email}','{tenant_id}', {is_account_user}, null,'{time_zone}', '{user_id}')"
            rds_execute_statement(sql)

        else:
            is_account_user = "true"
            # Create user in users_master
            sql = f"INSERT INTO users_master (cognito_user_id, first_name, last_name, email, tenant_id, is_account_user, account_id, time_zone, created_by)"\
                f" VALUES ('{cognito_user_id}','{first_name}','{last_name}','{email}','{tenant_id}', {is_account_user}, '{account_id}', '{time_zone}', '{user_id}')"

            rds_execute_statement(sql)
            # If it is an account user, assign to it the account role
            get_account_role_query = f"SELECT role_id FROM roles_master WHERE tenant_id = '{tenant_id}' AND type = 'other' AND role = 'account'"
            rds_response = rds_execute_statement(get_account_role_query)
            response = deserialize_rds_response(rds_response)

            if len(response):
                assign_account_role_query = f"""INSERT INTO user_roles (tenant_id, cognito_user_id, role_id, created_by) 
                 VALUES('{tenant_id}','{cognito_user_id}','{response[0]["role_id"]}', '{user_id}');"""
                rds_execute_statement(assign_account_role_query)

        # Asign roles in user_roles
        assign_roles(user_id, tenant_id, cognito_user_id, roles)

        return (200, {'UUID': UUID, 'cognito_user_id': cognito_user_id, 'result': 'User created'})

    else:
        return (403, {'UUID': UUID, 'code': 'tenant_permissions.ObjectLimitReached'})


@webhook_dispatch(object_name='users_master', action='create')
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
            if check_user_level_permissions(tenant_id, user_id, 'admin', 'users', 'general', 'can_create'):
                create_transaction()
                # Create user
                # Account user can't create user
                if account_id is not None:
                    response = (
                        403, {'UUID': UUID, 'code': 'account_permissions.UserDoesNotHaveAccessToThisFeature'})
                else:
                    # if account_id is sent in the body, the user is an account_user
                    if "account_id" in event_body:
                        account_id = event_body['account_id']
                    time_zone = event_body.pop("time_zone", "UTC")
                    response = create_user(
                        user_id, event_body['email'], event_body['first_name'], event_body['last_name'], event_body['roles'],
                        tenant_id, account_id=account_id, time_zone=time_zone)
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
