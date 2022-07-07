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


def get_time_zone(name=None, limit=None, page=None):
    sql = f"""SELECT name, utc_offset FROM pg_timezone_names """
    sql_count = f"""SELECT COUNT(*) FROM pg_timezone_names """

    if name is not None:
        sql += f""" WHERE UNACCENT(name) ILIKE UNACCENT('%{name}%') """
        sql_count += f""" WHERE UNACCENT(name) ILIKE UNACCENT('%{name}%') """

    if limit is not None:
        offset = str(int(limit)*(int(page)-1))

        # ADD LIMIT AND OFFSET
        sql += f" LIMIT {limit} OFFSET {offset} "

    rds_response = rds_execute_statement(sql)
    time_zones = deserialize_rds_response(rds_response)

    for tz in time_zones:
        offset_hours = tz["utc_offset"].split("days")[1].split("hours")[
            0].replace(" ", "")
        if "-" in offset_hours and len(offset_hours) == 2:
            offset_hours = f"""-0{offset_hours.replace("-","")}"""
        offset_hours = f"0{offset_hours}" if len(
            offset_hours) == 1 else offset_hours

        offset_minutes = tz["utc_offset"].split("hours")[1].split("mins")[
            0].replace(" ", "")
        offset_minutes = f"0{offset_minutes}" if len(
            offset_minutes) == 1 else offset_minutes

        tz["utc_offset"] = f"""{offset_hours}:{offset_minutes}"""

    count = rds_execute_statement(sql_count)["records"][0][0]["longValue"]

    return (200, {"count": count, "time_zones": time_zones, "result": "Get time zones success"})


def lambda_handler(event, context):
    try:
        if throttling_check():
            raise Exception('Throttling threshold exceeded')
        initialize_functions()
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Event Received': event}, SERVICE_NAME, RESOURCE_METHOD, 3)
        query_parameters = event['queryStringParameters'] if event['queryStringParameters'] is not None else {
        }
        user_id, tenant_id = check_api_keys(event)

        if "name" not in query_parameters:
            query_parameters["name"] = None

        response = get_time_zone(**query_parameters)

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
