import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (COGNITO_CLIENT,
                                                     CORALOGIX_KEY,
                                                     RESOURCE_METHOD,
                                                     SERVICE_NAME,
                                                     check_api_keys,
                                                     confirm_transaction,
                                                     create_transaction,
                                                     delete_transaction,
                                                     deserialize_rds_response,
                                                     get_account_id,
                                                     get_pool_id, initialize,
                                                     rds_execute_statement,
                                                     send_to_coralogix,
                                                     throttling_check,
                                                     wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def get_user(username, user_pool_id):
    # get user from userPool in Cognito
    try:
        result = COGNITO_CLIENT.admin_get_user(
            UserPoolId=user_pool_id,
            Username=username
        )

    except COGNITO_CLIENT.exceptions.UserNotFoundException as e:
        result = None

    return result


def create_query(data, tenant_id, account_id=None):
    # START QUERY STRING
    request_keys = list(data.keys())
    # If fields in data, add the fields to the query, else all are returned
    if "fields" in data:
        fields = data["fields"]
        request_keys.remove("fields")
        # always add cognito_user_id to get the status of the users
        if "cognito_user_id" not in fields:
            fields += ",cognito_user_id "
    else:
        fields = "*"

    # One query to know the number of records and another to get the records
    sql = f"SELECT {fields} FROM users_master WHERE tenant_id = '{tenant_id}' "
    sql_count = f"SELECT COUNT(*) FROM users_master WHERE tenant_id = '{tenant_id}' "

    if account_id is None and "account_id" in data:
        account_id = data["account_id"]

    if account_id is not None:
        sql += f" AND account_id = '{account_id}' "
        sql_count += f" AND account_id= '{account_id}' "

    # Iterate in keys and add them in the query
    for i, key in enumerate(data.keys()):
        if key not in ["fields", "is_active", "tenant_id", "cognito_user_id",
                       "limit", "page", "or", "first_name", "last_name", "full_name",
                       "is_account_user", "account_id"]:
            # Suppose all data is a string, search with ILIKE to search for the substring
            sql += f"AND UNACCENT({key}) ILIKE UNACCENT('%{data[key]}%') "
            sql_count += f"AND UNACCENT({key}) ILIKE UNACCENT('%{data[key]}%') "

        elif key == "cognito_user_id":
            # cognito_user_id must match
            sql += f"AND cognito_user_id = '{data['cognito_user_id']}' "
            sql_count += f"AND cognito_user_id = '{data['cognito_user_id']}' "
        elif key == "is_active":
            if data[key] == "enabled":
                sql += "AND is_active = true "
                sql_count += "AND is_active = true "
            elif data[key] == "disabled":
                sql += "AND is_active = false "
                sql_count += "AND is_active = false "
        # Query to filter by account_users
        elif key == "is_account_user":
            if data[key] == "enabled":
                sql += "AND is_account_user = true "
                sql_count += "AND is_account_user = true "
            elif data[key] == "disabled":
                sql += "AND is_account_user = false "
                sql_count += "AND is_account_user = false "
        elif key == "or":
            # or statement, only process one or key.
            or_statement = data[key].split("|")
            if len(or_statement):
                sql += "AND ("
                sql_count += "AND ("
                # add all the data inside the or splitted by | for th filters
                # and = for the key,value pair.
                # everything follows the next structure:
                #   AND (key1 ILIKE value1 OR key2 ILIKE value2 ...) AND
                for i, statement in enumerate(or_statement):
                    if i:
                        sql += "OR "
                        sql_count += "OR "
                    values = statement.split("=")
                    if values[0] in ["first_name", "last_name", "full_name"]:
                        similarity = 0.45
                        if len(data[key]) > 10:
                            similarity = 0.5
                        sql += f"(UNACCENT({values[0]}) ILIKE UNACCENT('%{values[1]}%') OR similarity(UNACCENT({values[0]}), UNACCENT('{values[1]}')) > {similarity}) "
                        sql_count += f"(UNACCENT({values[0]}) ILIKE UNACCENT('%{values[1]}%') OR similarity(UNACCENT({values[0]}), UNACCENT('{values[1]}')) > {similarity}) "
                    else:
                        sql += f"UNACCENT({values[0]}) ILIKE UNACCENT('%{values[1]}%') "
                        sql_count += f"UNACCENT({values[0]}) ILIKE UNACCENT('%{values[1]}%') "
                sql += ") "
                sql_count += ") "
        elif key in ["first_name", "last_name", "full_name"]:
            similarity = 0.45
            if len(data[key]) > 10:
                similarity = 0.5
            # in these keys, search by a value of similarity.
            # For example if the user is wrong in one letter, the
            # the query stills return the record
            sql += f"AND (UNACCENT({key}) ILIKE UNACCENT('%{data[key]}%') OR similarity(UNACCENT({key}), UNACCENT('{data[key]}')) > {similarity}) "
            sql_count += f"AND (UNACCENT({key}) ILIKE UNACCENT('%{data[key]}%') OR similarity(UNACCENT({key}), UNACCENT('{data[key]}')) > {similarity}) "

    sql += "ORDER BY full_name "

    # Check for limits, add it with the offset.
    # The function supposes that when a limit exists, an offset will exist too.
    if "limit" in data:
        limit = data["limit"]
        offset = str(int(data["limit"])*(int(data["page"])-1))

        # ADD LIMIT AND OFFSET
        sql += f" LIMIT {limit} OFFSET {offset} "

    return sql, sql_count


def lambda_handler(event, context):
    try:
        print(event['queryStringParameters'])
        # INITIATE GLOBAL DATABASE CREDENTIALS
        initialize_functions()
        # Send to Coralogix the request data
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        user_id, tenant_id = check_api_keys(event)
        account_id = get_account_id(user_id)
        user_pool_id = get_pool_id(tenant_id)
        # GET BODY
        create_transaction()
        # get data from url
        data = event['queryStringParameters']
        if data:
            sql, sql_count = create_query(data, tenant_id, account_id)
        else:
            sql = f"SELECT * FROM users_master WHERE tenant_id = '{tenant_id}' AND is_active = true "
            sql_count = f"SELECT COUNT(*) FROM users_master WHERE tenant_id = '{tenant_id}' AND is_active = true"
            if account_id is not None:
                sql += f" AND account_id='{account_id}' "
                sql_count += f" AND account_id= '{account_id}' "

        # Send the query to coralogix
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Query string': sql}, SERVICE_NAME, RESOURCE_METHOD, 3)
        # EXECUTE SQL QUERY
        rds_response = rds_execute_statement(sql)
        data_count = rds_execute_statement(sql_count)
        users_data = deserialize_rds_response(rds_response)

        for record in users_data:
            roles_query = f"SELECT role_id FROM user_roles WHERE cognito_user_id ='{record['cognito_user_id']}';"
            roles_id = rds_execute_statement(roles_query)['records']
            roles_list = []
            for role in roles_id:
                roles_list.append(role[0]['stringValue'])
            record["roles"] = roles_list
            user_data = get_user(record['cognito_user_id'], user_pool_id)
            if user_data is None:
                users_data.remove(record)
            else:
                record['status'] = user_data['UserStatus']

        count = int(list(data_count['records'][0][0].values())[0])
        # have the count and records data in the same response
        response_data = {
            "count": count,
            "records": users_data
        }
        confirm_transaction()
        EXECUTION_TIME = str(datetime.now()-CURRENT_DATETIME)
        # Send response and status to coralogix
        send_to_coralogix(CORALOGIX_KEY, {'UUID': UUID, 'Status': 'Success',
                                          'Execution time': EXECUTION_TIME}, SERVICE_NAME, RESOURCE_METHOD, 3)
        wait_for_threads()
        return {
            'statusCode': 200,
            'body': json.dumps(response_data),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
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
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
