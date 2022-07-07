import base64
import json
import os
import uuid
from datetime import datetime
from threading import Thread
from urllib import response

import boto3
import requests


def get_secret(vault_name, region_name, secret_name):
    # This functions retrieves secrets from AWS Secrets Manager
    secrets_session = boto3.session.Session()
    secrets_client = secrets_session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    get_secret_value_response = secrets_client.get_secret_value(
        SecretId=vault_name)
    secrets = json.loads(get_secret_value_response['SecretString'])
    return secrets[secret_name]


SERVICE_NAME = os.environ['SERVICE_NAME']
RESOURCE_METHOD = os.environ['RESOURCE_METHOD']
REGION_NAME = os.environ['REGION_NAME']
COGNITO_CLIENT = boto3.client('cognito-idp', region_name=REGION_NAME)
RDS_CLIENT = boto3.client('rds-data', region_name=REGION_NAME)
DATABASE_NAME = os.environ['DATABASE_NAME']
DB_CLUSTER_ARN = os.environ['DB_CLUSTER_ARN']
DB_CREDENTIALS_SECRETS_STORE_ARN = os.environ['DB_CREDENTIALS_SECRETS_STORE_ARN']
CORALOGIX_SECRETS = os.environ['CORALOGIX_SECRET']
CORALOGIX_KEY = get_secret(CORALOGIX_SECRETS, REGION_NAME, 'CoralogixKey')
APPKEY_SECRET_ARN = os.environ['APPKEY_SECRET_ARN']
LOCATION_PATH = os.path.dirname(__file__)
TRANSACTION_ID = None
THREADS = []


def initialize():
    global UUID, CURRENT_DATETIME
    UUID = uuid.uuid4().hex
    CURRENT_DATETIME = datetime.now()


def sendCoralogix(private_key, logs, app_name, subsystem_name, severity, computer_name=None, class_name=None, category=None, method_name=None):
    """
    This function sends a request to Coralogix with the given data.
    private_key: Coralogix account private key, as String.
    logs: the logs text, as String.
    app_name: Application Name to be shown in Coralogix, as String.
    subsystem_name: Subsystem Name to be shown in Coralogix, as String.
    severity: Severity of the logs as String. Values: 1 – Debug, 2 – Verbose, 3 – Info, 4 – Warn, 5 – Error, 6 – Critical
    computer_name: Computer Name to be shown in Coralogix, as String.
    class_name: Class Name to be shown in Coralogix, as String.
    category: Category to be shown in Coralogix, as String.
    method_name: Method Name to be shown in Coralogix, as String.
    """

    url = "https://api.coralogix.com/api/v1/logs"
    # Get the datetime and change it to miliseconds
    now = datetime.now()

    data = {
        "privateKey": private_key,
        "applicationName": app_name,
        "subsystemName": subsystem_name,
        "logEntries": [
            {
                "timestamp": now.timestamp()*1000,  # 1457827957703.342,
                "text": logs,
                "severity": severity
            }
        ]
    }
    if computer_name:
        data["computerName"] = computer_name
    if class_name:
        data["logEntries"][0]["className"] = class_name
    if category:
        data["logEntries"][0]["category"] = category
    if method_name:
        data["logEntries"][0]["methodName"] = method_name

    # Make the request to coralogix
    requests.post(url, json=data)

    return True


def send_to_coralogix(private_key, logs, app_name, subsystem_name, severity, computer_name=None, class_name=None, category=None, method_name=None):
    global THREADS
    thread = Thread(target=sendCoralogix, args=(private_key, logs, app_name,
                    subsystem_name, severity, computer_name, class_name, category, method_name))
    THREADS.append(thread)
    thread.start()


def create_transaction():
    global TRANSACTION_ID
    if TRANSACTION_ID is None:
        response = RDS_CLIENT.begin_transaction(
            database=DATABASE_NAME,
            resourceArn=DB_CLUSTER_ARN,
            secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN
        )
        TRANSACTION_ID = response["transactionId"]


def confirm_transaction():
    global TRANSACTION_ID
    if TRANSACTION_ID is not None:
        response = RDS_CLIENT.commit_transaction(
            resourceArn=DB_CLUSTER_ARN,
            secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN,
            transactionId=TRANSACTION_ID
        )
        TRANSACTION_ID = None


def delete_transaction():
    global TRANSACTION_ID
    if TRANSACTION_ID is not None:
        response = RDS_CLIENT.rollback_transaction(
            resourceArn=DB_CLUSTER_ARN,
            secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN,
            transactionId=TRANSACTION_ID
        )
        TRANSACTION_ID = None


def rds_execute_statement(sql):
    # Execute sql statement through boto3
    if ('UUID' in globals()):
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'Query string': sql}, SERVICE_NAME, RESOURCE_METHOD, 3)
    params = {
        "secretArn": DB_CREDENTIALS_SECRETS_STORE_ARN,
        "database": DATABASE_NAME,
        "resourceArn": DB_CLUSTER_ARN,
        "sql": sql,
        "includeResultMetadata": True
    }
    if TRANSACTION_ID is not None:
        params["transactionId"] = TRANSACTION_ID

    response = RDS_CLIENT.execute_statement(**params)
    return response


def deserialize_rds_response(data):
    """
        function to return a dictionary of attribute-value of RDS response in boto3
    """
    records = data["records"]
    columns = data["columnMetadata"]
    result = []
    # print(records)
    for record in records:
        record_dict = {}
        col_count = 0
        for current_column in columns:
            attribute = current_column['name']
            key = list(record[col_count].keys())[0]
            value = list(record[col_count].values())[0]
            if key in ["booleanValue", "doubleValue", "longValue"]:
                record_dict[attribute] = value
            elif key == "stringValue":
                # Check if it is a json as a string or only a string
                try:
                    record_dict[attribute] = json.loads(value)
                except json.JSONDecodeError as e:
                    record_dict[attribute] = value
            elif key == "arrayValue":
                record_dict[attribute] = list(value.values())[0]
            elif key == "isNull":
                record_dict[attribute] = None
            # TODO check blobValue return
            elif key == "blobValue":
                record_dict[attribute] = value
            col_count += 1

        result.append(record_dict)

    return result


def get_tenant_id(user_id):
    sql = f"SELECT tenant_id FROM users_master WHERE cognito_user_id ='{user_id}'"
    rds_response = rds_execute_statement(sql)
    return rds_response['records'][0][0]['stringValue']


def get_pool_id(tenant_id):
    sql = f"SELECT user_pool_id FROM tenants_master WHERE tenant_id = '{tenant_id}'"
    rds_response = rds_execute_statement(sql)
    return rds_response['records'][0][0]['stringValue']


def check_tenant_level_permissions(tenant_id, module, component, subcomponent):
    sql = f"SELECT COUNT(*) from tenant_permissions INNER JOIN components_master ON "\
          f"tenant_permissions.components_id = components_master.components_id "\
          f"WHERE tenant_permissions.tenant_id = '{tenant_id}' AND "\
          f"components_master.module = '{module}' AND "\
          f"components_master.component = '{component}' AND "\
          f"components_master.subcomponent ='{subcomponent}' AND "\
          f"components_master.is_active = true "
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if count == 0:
        return False
    else:
        return True


def check_user_level_permissions(tenant_id, user_id, module, component, subcomponent, action):
    if ((user_id == 'Tenant Key') | (user_id == 'Application Key')):
        return True
    sql = f"SELECT COUNT(*) from role_permissions INNER JOIN components_master ON "\
        f"role_permissions.components_id = components_master.components_id "\
        f"WHERE role_permissions.tenant_id = '{tenant_id}' "\
        f"AND components_master.module = '{module}' "\
        f"AND components_master.component = '{component}' "\
        f"AND components_master.subcomponent ='{subcomponent}' "\
        f"AND role_permissions.{action} = TRUE "\
        f"AND components_master.is_active = true "\
        f"AND role_permissions.role_id IN "\
        f"("\
        f"SELECT role_id from user_roles WHERE cognito_user_id = '{user_id}'"\
        f")"
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if count == 0:
        return False
    else:
        return True


def check_tenant_limit(table, tenant_id):
    limit_query = f"SELECT object_limit FROM objects_master WHERE table_name = '{table}' AND tenant_id = '{tenant_id}'"
    limit = rds_execute_statement(limit_query)['records'][0][0]["longValue"]
    user_len_query = f"SELECT COUNT(*) from {table} WHERE tenant_id = '{tenant_id}' AND is_active = true"
    user_len = rds_execute_statement(user_len_query)[
        'records'][0][0]["longValue"]
    if limit == 0:
        return True
    if limit <= user_len:
        return False
    else:
        return True


def decode_key(key):
    # This function extracts the tenant_id from the Tenant Key
    encoded_bytes = bytes(key, 'utf-8')
    decoded_str = str(base64.b64decode(encoded_bytes.decode('utf-8')), 'utf-8')
    tenant_id_from_key = decoded_str.split(':')[0]
    return tenant_id_from_key


def get_account_id(user_id):
    sql = f"SELECT account_id FROM users_master WHERE cognito_user_id = '{user_id}' "
    rds_response = rds_execute_statement(sql)
    user_data = deserialize_rds_response(rds_response)
    if len(user_data):
        return user_data[0]["account_id"]
    else:
        return None


def check_api_keys(event):
    # This function determines the user_id and tenant_id according to the api key used
    if event['requestContext']['authorizer']['claims']['scope'] == 'aws.cognito.signin.user.admin':
        user_id = event['requestContext']['authorizer']['claims']['username']
        tenant_id = get_tenant_id(user_id)
        return (user_id, tenant_id)
    elif event['requestContext']['authorizer']['claims']['scope'] == 'apiauthidentifier/json.read':
        if 'Tenant-Key' in event['headers'].keys():
            tenant_key = event['headers']['Tenant-Key']
            tenant_id = decode_key(tenant_key)
            # Get vault names
            sql = f"SELECT secret_name from tenant_keys WHERE tenant_id = '{tenant_id}'"
            response = rds_execute_statement(sql)
            if len(response['records']) == 0:
                raise Exception('api_keys.ApiKeyNotFoundInHeaders')
            # Compare key with secrets
            for curr_vault in response['records']:
                curr_secret = get_secret(
                    curr_vault[0]['stringValue'], REGION_NAME, 'Key')
                if curr_secret == tenant_key:
                    sql = f"""SELECT cognito_user_id FROM users_master WHERE tenant_id = '{tenant_id}' 
                    AND first_name = '{curr_vault[0]['stringValue']}' AND email = '{curr_vault[0]['stringValue']}'"""
                    response = deserialize_rds_response(
                        rds_execute_statement(sql))
                    if len(response) == 0:
                        sql = f"""SELECT cognito_user_id FROM users_master WHERE tenant_id = '{tenant_id}' 
                        AND first_name = 'Tenant' AND last_name = 'Key'"""
                        response = deserialize_rds_response(
                            rds_execute_statement(sql))
                        user_id = response[0]["cognito_user_id"]
                    else:
                        user_id = response[0]["cognito_user_id"]
                    return (user_id, tenant_id)
            raise Exception('api_keys.InvalidTenantKey')
        elif 'App-Key' in event['headers'].keys():
            tenant_id = event['headers']['tenant_id']
            app_key = event['headers']['App-Key']
            sql = f"""SELECT cognito_user_id FROM users_master WHERE tenant_id = '{tenant_id}' 
            AND first_name = 'App' AND last_name = 'Key'"""
            user_id = rds_execute_statement(
                sql)['records'][0][0]["stringValue"]
            # Compare key with secrets
            secrets_session = boto3.session.Session()
            secrets_client = secrets_session.client(
                service_name='secretsmanager',
                region_name=REGION_NAME
            )
            secret_response = secrets_client.get_secret_value(
                SecretId=APPKEY_SECRET_ARN)
            secret_key = secret_response['SecretString']
            if secret_key == app_key:
                return (user_id, tenant_id)
            else:
                raise Exception('api_keys.InvalidApplicationKey')
        else:
            raise Exception('api_keys.ApiKeyNotFoundInHeaders')
    else:
        raise Exception('api_keys.ScopeNotSupported')


def throttling_check():
    return False


def wait_for_threads():
    for thread in THREADS:
        thread.join()


def send_sns_message(message):
    SNS_CLIENT = boto3.client('sns', region_name=REGION_NAME)
    SNS_ARN = os.environ['SNS_ARN']
    sns_message = {'default': json.dumps(message)}
    response = SNS_CLIENT.publish(
        TargetArn=SNS_ARN,
        Message=json.dumps(sns_message),
        MessageStructure='json'
    )
    send_to_coralogix(CORALOGIX_KEY, {
        'UUID': UUID, 'SNS Body': sns_message, 'Response': response}, SERVICE_NAME, RESOURCE_METHOD, 3)
    return response


def get_object_id(object_name, tenant_id):
    """
        Function to return the object id
    """
    sql = f"SELECT object_id FROM objects_master WHERE table_name = '{object_name}' and tenant_id = '{tenant_id}'"
    rds_response = rds_execute_statement(sql)
    object_data = deserialize_rds_response(rds_response)
    if len(object_data) > 0:
        return object_data[0]["object_id"]
    else:
        raise f"{object_name} object doesn't exists"


def get_table_columns(object_name):
    sql = f"""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{object_name}'
    """

    column_names = deserialize_rds_response(rds_execute_statement(sql))

    columns_query = []

    for column in column_names:
        column_name = column['column_name']

        # Get created_by or updated_by full name
        if column_name in ['created_by', 'updated_by']:
            column_name = f"""
                {column_name} AS {column_name}_id, (SELECT full_name FROM users_master WHERE cognito_user_id = o.{column_name}) as {column_name}
            """

        columns_query.append(column_name)

    columns_query = ", ".join(columns_query)

    return columns_query


def get_object_properties(object_name, primary_key_name, primary_key_value):
    """
        Function to return all properties of an object
    """
    columns = get_table_columns(object_name)
    sql = f"SELECT {columns} FROM {object_name} o WHERE {primary_key_name} = '{primary_key_value}'"
    rds_response = rds_execute_statement(sql)
    object_data = deserialize_rds_response(rds_response)
    if len(object_data) > 0:
        return object_data[0]
    else:
        raise f"{object_name} object with {primary_key_value} as primary key doesn't exists"


def get_object_primary_key(object_name):
    """
        Function to return the name of object primary key
    """

    sql = f"""SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid
                    AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = '{object_name}'::regclass
                AND i.indisprimary;
            """

    data = deserialize_rds_response(rds_execute_statement(sql))

    # Table primary key
    return data[0]['attname']


def webhook_dispatch(object_name, action):
    """
        Decorator to handle a webhook
    """
    def decorator(lambda_function):
        def wrapper(*args, **kwargs):
            if not (os.path.exists(f'{LOCATION_PATH}/../neojumpstart_events_backend') or os.path.exists(f'{LOCATION_PATH}/../../WebhooksProcess.py')):
                return lambda_function(*args, **kwargs)
            # get primary key name for object_name
            primary_key_name = get_object_primary_key(object_name)
            primary_key_value = ""
            event = args[0]
            event_body = json.loads(event['body'])
            user_id, tenant_id = check_api_keys(event)

            # get old properties (only if action is update)
            previous_properties = {}
            if action == 'update':
                # if the primary key doesn't exists in the event_body, then the lambda function will run without webhook
                if not (primary_key_name in event_body):
                    return lambda_function(*args, **kwargs)
                primary_key_value = event_body[primary_key_name]
                previous_properties = get_object_properties(
                    object_name, primary_key_name, primary_key_value)

            # excecute lambda function
            response = lambda_function(*args, **kwargs)
            response_status = response['statusCode']
            response_body = json.loads(response['body'])

            # Send the webhook event to sns
            if response_status == 200 and primary_key_name in response_body:
                primary_key_value = response_body[primary_key_name]
                # get new properties
                properties = get_object_properties(
                    object_name, primary_key_name, primary_key_value)

                # get object id
                object_id = get_object_id(
                    object_name, tenant_id)

                # Process uuid
                uuid_value = response_body['UUID']
                date = str(datetime.now())

                # Webhook event topic
                send_sns_message({
                    "tenant_id": tenant_id,
                    "object_id": object_id,
                    "record_id": primary_key_value,
                    "action": action,
                    "system_event_id": uuid_value,
                    "user_id": user_id,
                    "date": date,
                    "properties": properties,
                    "previous_properties": previous_properties
                })

            return response  # return lambda function response
        return wrapper
    return decorator
