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
from src.neojumpstart_core_backend.functions import (APPKEY_SECRET_ARN,
                                                     COGNITO_CLIENT,
                                                     CORALOGIX_KEY,
                                                     CORALOGIX_SECRETS,
                                                     DATABASE_NAME, RDS_CLIENT,
                                                     REGION_NAME,
                                                     RESOURCE_METHOD,
                                                     SERVICE_NAME,
                                                     check_api_keys,
                                                     confirm_transaction,
                                                     create_transaction,
                                                     delete_transaction,
                                                     deserialize_rds_response,
                                                     initialize,
                                                     rds_execute_statement,
                                                     send_to_coralogix,
                                                     throttling_check,
                                                     wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def get_roles(tenant_id, name, user_id, is_active=None):
    sql = f"SELECT role_id, role, type, is_active " + \
        "FROM roles_master " + \
        f"WHERE tenant_id = '{tenant_id}' "

    if is_active is not None:
        sql += f"AND is_active = {is_active} "

    if name is not None:
        sql += f"AND (UNACCENT(roles_master.role) ILIKE UNACCENT('%{name}%') OR similarity(UNACCENT(roles_master.role), UNACCENT('{name}')) > 0.45) "

    # EXECUTE SQL QUERY
    rds_response = rds_execute_statement(sql)

    # PROCESS QUERY TO RETURN AN ARRAY OF THE DATA
    roles_data = deserialize_rds_response(rds_response)

    return roles_data


def get_permissions(tenant_id, is_active=None):
    sql = f"SELECT components_master.valid_for, components_master.module, components_master.component, components_master.subcomponent, "\
        f"role_permissions.can_create, role_permissions.can_read, role_permissions.can_update, role_permissions.can_delete "\
        f"FROM role_permissions INNER JOIN roles_master ON roles_master.role_id = role_permissions.role_id "\
        f"INNER JOIN components_master ON components_master.components_id = role_permissions.components_id "\
        f"WHERE role_permissions.tenant_id = '{tenant_id}' AND roles_master.type = 'admin' "\

    if is_active is not None:
        sql += f"AND components_master.is_active = {is_active} "

    # EXECUTE SQL QUERY
    rds_response = rds_execute_statement(sql)

    # PROCESS QUERY TO RETURN AN ARRAY OF THE DATA
    records = deserialize_rds_response(rds_response)

    roles_data = {}
    # PROCESS QUERY TO RETURN AN ARRAY OF DICTIONARIES WITH THE MODULE
    # CONTAINING COMPONENTS, CONTAINING SUBCOMPONENTS AND CONTAINING THE PERMISSIONS
    for record in records:
        module = ""
        component = ""
        subcomponent = ""
        # The conditionals are done in order to have the desired structure in the dictionary
        for key, value in record.items():
            if key == "module":
                if value not in roles_data.keys():
                    roles_data[value] = {}
                module = value
            elif key == "component":
                if value not in roles_data[module].keys():
                    roles_data[module][value] = {}
                component = value
            elif key == "subcomponent":
                if value not in roles_data[module][component].keys():
                    roles_data[module][component][value] = []
                subcomponent = value
            elif key in ["can_read", "can_update", "can_create", "can_delete"]:
                if value is not None:
                    roles_data[module][component][subcomponent].append(key)
    return roles_data


def get_roles_permission(tenant_id, name, user_id, is_active=None):
    sql = f"SELECT roles_master.role_id, roles_master.role , roles_master.type, roles_master.is_active, " + \
        "components_master.module, components_master.component, " + \
        "components_master.subcomponent, role_permissions.role_permission_id, " + \
        "role_permissions.can_create, role_permissions.can_read, " + \
        "role_permissions.can_update, role_permissions.can_delete " + \
        "FROM role_permissions INNER JOIN roles_master ON roles_master.role_id = role_permissions.role_id " + \
        "INNER JOIN components_master ON components_master.components_id = role_permissions.components_id " + \
        f"WHERE role_permissions.tenant_id = '{tenant_id}' AND " + \
        f"components_master.is_active = true "\
        #f"AND roles_master.role_id IN ({','.join(roles_ids)})"

    if is_active is not None:
        sql += f"AND roles_master.is_active =  {is_active} "
    if name is not None:
        sql += f"AND (UNACCENT(roles_master.role) ILIKE UNACCENT('%{name}%') OR similarity(UNACCENT(roles_master.role), UNACCENT('{name}')) > 0.45) "

    # EXECUTE SQL QUERY
    rds_response = rds_execute_statement(sql)

    # PROCESS QUERY TO RETURN AN ARRAY OF THE DATA
    records = deserialize_rds_response(rds_response)

    # PROCESS QUERY TO RETURN AN ARRAY OF DICTIONARIES WITH THE KEYS AS THE ATTRIBUTES NAMES
    roles_data = []
    for record in records:
        result = {}
        col_count = 0
        role = ""
        module = ""
        component = ""
        subcomponent = ""
        add_new = False
        for key, value in record.items():
            # Check if the role had been already added
            if key == "role_id":
                exists = False
                for role_data in roles_data:
                    if value == role_data["role_id"]:
                        exists = True
                        result = role_data
                        break
                if not exists:
                    result = {
                        "role_id": value,
                        "role_permissions": {}
                    }
                    add_new = True
                role = value
            elif key == "role":
                result["role_name"] = value
            elif key == "type":
                result["type"] = value
            elif key == "is_active":
                result["is_active"] = value
            elif key == "module":
                if value not in result["role_permissions"]:
                    result["role_permissions"][value] = {}
                module = value
            elif key == "component":
                if value not in result["role_permissions"][module]:
                    result["role_permissions"][module][value] = {}
                component = value
            elif key == "subcomponent":
                if value not in result["role_permissions"][module][component]:
                    result["role_permissions"][module][component][value] = {}
                subcomponent = value
            elif key == "role_permission_id":
                result["role_permissions"][module][component][subcomponent]["role_permission_id"] = value
            elif key in ["can_create", "can_read", "can_update", "can_delete"]:
                result["role_permissions"][module][component][subcomponent][key] = value
        if add_new:
            roles_data.append(result)

    return roles_data


def lambda_handler(event, context):
    try:

        # INITIATE GLOBAL DATABASE CREDENTIALS
        initialize_functions()
        # Send to Coralogix the request data
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        # get tenant id from the user data
        user_id, tenant_id = check_api_keys(event)
        create_transaction()
        # get data from url
        data = event['queryStringParameters']
        type = data["data"]
        name = data["name"] if "name" in data else None
        if "is_active" in data:
            is_active = data["is_active"]

        #status = data["is_active"]
            if type == "roles":
                # return an array of all the roles in the tenant
                roles_data = get_roles(tenant_id, name, user_id, is_active)

            elif type == "permissions":
                # return all permissions, takes them from the "admin" role
                roles_data = get_permissions(tenant_id, is_active)

            elif type == "roles-permissions":
                # return all roles with its permissions
                roles_data = get_roles_permission(
                    tenant_id, name, user_id, is_active)

        else:
            if type == "roles":
                # return an array of all the roles in the tenant
                roles_data = get_roles(tenant_id, name, user_id)

            elif type == "permissions":
                # return all permissions, takes them from the "admin" role
                roles_data = get_permissions(tenant_id)

            elif type == "roles-permissions":
                # return all roles with its permissions
                roles_data = get_roles_permission(tenant_id, name, user_id)

        confirm_transaction()
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        # Send response and status to coralogix
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Status': 'Success',
                                          'Execution time': EXECUTION_TIME}, SERVICE_NAME, RESOURCE_METHOD, 3)
        wait_for_threads()
        return {
            'statusCode': 200,
            'body': json.dumps(roles_data),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT,DELETE",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }

    except Exception as e:
        # error
        exc_type, exc_obj, exc_tb = sys.exc_info()
        ERROR_MSG = f'Execution failed: {repr(e)}. Line: {str(exc_tb.tb_lineno)}.'
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        delete_transaction()
        # Send error message and status to coralogix
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Status': 'Failure', 'Execution time': EXECUTION_TIME,
                                          'Error message': ERROR_MSG}, SERVICE_NAME, RESOURCE_METHOD, 5)
        wait_for_threads()
        return {
            'statusCode': 500,
            'body': json.dumps({
                "message": ERROR_MSG,
                "code": str(exc_type),
                "UUID": UUID
            }),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT,DELETE",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
