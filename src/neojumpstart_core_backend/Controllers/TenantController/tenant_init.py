import json
import os
import sys
import uuid

import boto3
from src.neojumpstart_core_backend.functions import sendCoralogix


def initialize():
    global UUID, REGION_NAME, COGNITO_CLIENT, RDS_CLIENT, DATABASE_NAME, \
        DB_CLUSTER_ARN, DB_CREDENTIALS_SECRETS_STORE_ARN, USER_POOL_ID, IDENTITY_POOL_ID, \
        USER_POOL_CLIENT_ID, USER_EMAIL, USER_FIRST_NAME, USER_LAST_NAME, TENANT_NAME, \
        CORALOGIX_SECRETS, CORALOGIX_KEY, SERVICE_NAME, RESOURCE_METHOD
    UUID = uuid.uuid4().hex
    REGION_NAME = os.environ['REGION_NAME']
    COGNITO_CLIENT = boto3.client('cognito-idp', region_name=REGION_NAME)
    RDS_CLIENT = boto3.client('rds-data', region_name=REGION_NAME)
    DATABASE_NAME = os.environ['DATABASE_NAME']
    DB_CLUSTER_ARN = os.environ['DB_CLUSTER_ARN']
    DB_CREDENTIALS_SECRETS_STORE_ARN = os.environ['DB_CREDENTIALS_SECRETS_STORE_ARN']
    USER_POOL_ID = os.environ['USER_POOL_ID']
    IDENTITY_POOL_ID = os.environ['IDENTITY_POOL_ID']
    USER_POOL_CLIENT_ID = os.environ['USER_POOL_CLIENT_ID']
    USER_EMAIL = os.environ['USER_EMAIL']
    USER_FIRST_NAME = os.environ['USER_FIRST_NAME']
    USER_LAST_NAME = os.environ['USER_LAST_NAME']
    TENANT_NAME = os.environ['TENANT_NAME']
    CORALOGIX_SECRETS = os.environ['CORALOGIX_SECRET']
    CORALOGIX_KEY = get_secret(CORALOGIX_SECRETS, REGION_NAME, 'CoralogixKey')
    SERVICE_NAME = os.environ['SERVICE_NAME']
    RESOURCE_METHOD = os.environ['RESOURCE_METHOD']


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


def rds_execute_statement(sql):
    # Execute sql statement through boto3
    sendCoralogix(CORALOGIX_KEY, {
                  'UUID': UUID, 'Query string': sql}, SERVICE_NAME, RESOURCE_METHOD, 3)
    response = RDS_CLIENT.execute_statement(
        secretArn=DB_CREDENTIALS_SECRETS_STORE_ARN,
        database=DATABASE_NAME,
        resourceArn=DB_CLUSTER_ARN,
        sql=sql,
        includeResultMetadata=True
    )
    return response


def create_databases():

    sql_add_extensions = "CREATE EXTENSION IF NOT EXISTS unaccent; "\
        "CREATE EXTENSION IF NOT EXISTS pg_trgm; "\
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'

    rds_execute_statement(sql_add_extensions)

    sql_create_tenants_master = "CREATE TABLE IF NOT EXISTS tenants_master ("\
        "tenant_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "is_active BOOL DEFAULT true, "\
        "user_pool_id VARCHAR(100) NOT NULL, "\
        "identity_pool_id VARCHAR(100) NOT NULL, "\
        "user_pool_client_id VARCHAR(100) NOT NULL, "\
        "tenant_name VARCHAR(50) NOT NULL, "\
        "created_by VARCHAR(50) DEFAULT NULL, "\
        "updated_by VARCHAR(50) DEFAULT NULL, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "UNIQUE (tenant_name)"\
                                ")"

    rds_execute_statement(sql_create_tenants_master)

    sql_create_currencies = """
        CREATE TABLE IF NOT EXISTS currencies_master(
        currency_id uuid DEFAULT uuid_generate_v4() PRIMARY KEY, 
        currency_name VARCHAR(10) NOT NULL UNIQUE, 
        tenant_id uuid NOT NULL,
        created_by uuid, 
        updated_by uuid, 
        created_at TIMESTAMP DEFAULT NOW(), 
        updated_at TIMESTAMP DEFAULT NULL,                            
        CONSTRAINT fk_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants_master(tenant_id)
        ); 
    """
    rds_execute_statement(sql_create_currencies)

    sql_create_accounts_master = "CREATE SEQUENCE IF NOT EXISTS account_number_serial START 500;"\
        "CREATE TABLE IF NOT EXISTS accounts_master("\
        "account_id uuid DEFAULT uuid_generate_v4() PRIMARY KEY, "\
        "account_name VARCHAR(50) NOT NULL UNIQUE, "\
        "account_number INT NOT NULL DEFAULT NEXTVAL('account_number_serial'), "\
        "is_active BOOL DEFAULT true, "\
        "dinvy_id VARCHAR(50) DEFAULT '', "\
        "salesforce_id VARCHAR(50) DEFAULT '', "\
        "currency_id uuid, "\
        "created_by VARCHAR(50) DEFAULT NULL, "\
        "updated_by VARCHAR(50) DEFAULT NULL, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "tenant_id uuid NOT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id),"\
        "CONSTRAINT fk_currency_id FOREIGN KEY(currency_id) REFERENCES currencies_master(currency_id)"\
        "); "\

    rds_execute_statement(sql_create_accounts_master)

    sql_create_users_master = "CREATE TABLE IF NOT EXISTS users_master ("\
        "cognito_user_id VARCHAR(100) PRIMARY KEY, "\
        "is_active BOOL DEFAULT true, "\
        "is_account_user BOOL DEFAULT false, "\
        "tenant_id uuid NOT NULL, "\
        "account_id uuid, "\
        "first_name VARCHAR(50) NOT NULL, "\
        "last_name VARCHAR(50) NOT NULL, "\
        "full_name VARCHAR(100), "\
        "email VARCHAR(50) NOT NULL, "\
        "time_zone VARCHAR(40) DEFAULT 'UTC', "\
        "created_by VARCHAR(50) DEFAULT NULL, "\
        "updated_by VARCHAR(50) DEFAULT NULL, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id), "\
        "CONSTRAINT fk_account_id "\
        "FOREIGN KEY(account_id) "\
        "REFERENCES accounts_master(account_id)"\
        "); "\

    rds_execute_statement(sql_create_users_master)

    sql_add_audit_contraints_accounts_tenants_currencies = """
        ALTER TABLE accounts_master ADD CONSTRAINT fk_created_by FOREIGN KEY (created_by) REFERENCES users_master(cognito_user_id);
        ALTER TABLE accounts_master ADD CONSTRAINT fk_updated_by FOREIGN KEY (updated_by) REFERENCES users_master(cognito_user_id);
        ALTER TABLE tenants_master ADD CONSTRAINT fk_created_by FOREIGN KEY (created_by) REFERENCES users_master(cognito_user_id);
        ALTER TABLE tenants_master ADD CONSTRAINT fk_updated_by FOREIGN KEY (updated_by) REFERENCES users_master(cognito_user_id);
        ALTER TABLE currencies_master ADD CONSTRAINT fk_created_by FOREIGN KEY (created_by) REFERENCES users_master(cognito_user_id);
        ALTER TABLE currencies_master ADD CONSTRAINT fk_updated_by FOREIGN KEY (updated_by) REFERENCES users_master(cognito_user_id);
    """
    rds_execute_statement(sql_add_audit_contraints_accounts_tenants_currencies)
    sql_create_components_master = "CREATE TABLE IF NOT EXISTS components_master (" + \
        "components_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "is_active BOOL DEFAULT true, "\
        "module VARCHAR(100) NOT NULL, "\
        "component VARCHAR(100) NOT NULL, "\
        "subcomponent VARCHAR(100) NOT NULL, "\
        "valid_for VARCHAR(30) DEFAULT 'both',"\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id),"\
        "UNIQUE (module, component, subcomponent)"\
        ")"
    rds_execute_statement(sql_create_components_master)

    sql_create_tenant_permissions = "CREATE TABLE IF NOT EXISTS tenant_permissions ("\
        "tenant_permission_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "tenant_id uuid NOT NULL, "\
        "components_id uuid NOT NULL, "\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id), "\
        "CONSTRAINT fk_components_id "\
        "FOREIGN KEY(components_id) "\
        "REFERENCES components_master(components_id), "\
        "CONSTRAINT fk_components_id "\
        "FOREIGN KEY(components_id) "\
        "REFERENCES components_master(components_id),"\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id)"\
                                    ")"
    rds_execute_statement(sql_create_tenant_permissions)

    sql_create_roles_master = "CREATE TABLE IF NOT EXISTS roles_master ("\
        "role_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "is_active BOOL DEFAULT true, "\
        "role VARCHAR(50) NOT NULL, "\
        "tenant_id uuid NOT NULL, "\
        "type VARCHAR(10) DEFAULT 'other', "\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id),"\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id)"\
        ")"
    rds_execute_statement(sql_create_roles_master)

    sql_create_role_permissions = "CREATE TABLE IF NOT EXISTS role_permissions ("\
        "role_permission_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "tenant_id uuid NOT NULL, "\
        "role_id uuid NOT NULL, "\
        "components_id uuid NOT NULL, "\
        "can_create BOOL  DEFAULT false, "\
        "can_read BOOL DEFAULT false, "\
        "can_update BOOL DEFAULT false, "\
        "can_delete BOOL DEFAULT false, "\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id), "\
        "CONSTRAINT fk_role_id "\
        "FOREIGN KEY(role_id) "\
        "REFERENCES roles_master(role_id), "\
        "CONSTRAINT fk_components_id "\
        "FOREIGN KEY(components_id) "\
        "REFERENCES components_master(components_id),"\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id)"\
        ")"
    rds_execute_statement(sql_create_role_permissions)

    sql_create_objects_master = "CREATE TABLE IF NOT EXISTS objects_master ("\
        "object_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "tenant_id uuid NOT NULL, "\
        "table_name VARCHAR(50) NOT NULL, "\
        "object_limit INT NOT NULL, "\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id), "\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id)"\
        ")"
    rds_execute_statement(sql_create_objects_master)

    sql_create_user_roles = "CREATE TABLE IF NOT EXISTS user_roles ("\
        "user_role_id uuid DEFAULT uuid_generate_v4 () PRIMARY KEY, "\
        "tenant_id uuid NOT NULL, "\
        "cognito_user_id uuid NOT NULL, "\
        "role_id uuid NOT NULL, "\
        "created_by uuid, "\
        "updated_by uuid, "\
        "created_at TIMESTAMP DEFAULT NOW(), "\
        "updated_at TIMESTAMP DEFAULT NULL, "\
        "CONSTRAINT fk_tenant_id "\
        "FOREIGN KEY(tenant_id) "\
        "REFERENCES tenants_master(tenant_id), "\
        "CONSTRAINT fk_cognito_user_id "\
        "FOREIGN KEY(cognito_user_id) "\
        "REFERENCES users_master(cognito_user_id), "\
        "CONSTRAINT fk_role_id "\
        "FOREIGN KEY(role_id) "\
        "REFERENCES roles_master(role_id),"\
        "CONSTRAINT fk_created_by FOREIGN KEY(created_by) REFERENCES users_master(cognito_user_id),"\
        "CONSTRAINT fk_updated_by FOREIGN KEY(updated_by) REFERENCES users_master(cognito_user_id)"\
                            ")"
    rds_execute_statement(sql_create_user_roles)

    sql_users_master_fullname = "CREATE OR REPLACE FUNCTION create_full_name() "\
                                "RETURNS trigger "\
                                "LANGUAGE plpgsql "\
                                "SECURITY DEFINER "\
                                "AS $BODY$ "\
                                "BEGIN "\
                                "NEW.full_name = CONCAT(NEW.first_name, ' ', New.last_name); "\
                                "RETURN NEW; "\
                                "END "\
                                "$BODY$; "\
                                "DROP TRIGGER IF EXISTS computed_full_name ON users_master; "\
                                "CREATE TRIGGER computed_full_name "\
                                "BEFORE INSERT OR UPDATE "\
                                "ON users_master "\
                                "FOR EACH ROW "\
                                "EXECUTE PROCEDURE create_full_name(); "
    rds_execute_statement(sql_users_master_fullname)

    sql_role_tenants_components = "CREATE OR REPLACE FUNCTION add_permissions() RETURNS TRIGGER AS "\
        "$BODY$ "\
        "declare "\
        "r record; "\
        "t record; "\
        "BEGIN "\
        "FOR t IN "\
        "SELECT b.tenant_id "\
        "FROM tenants_master b "\
        "LOOP "\
        "FOR r IN "\
        "SELECT DISTINCT a.role_id, a.type "\
        "FROM   roles_master a "\
        "WHERE a.tenant_id = t.tenant_id "\
        "LOOP "\
        "IF r.type ='admin' THEN "\
        "IF NEW.valid_for != 'account' THEN "\
        "INSERT INTO role_permissions(tenant_id, role_id, components_id, can_create, can_read, can_update, can_delete) VALUES(t.tenant_id, r.role_id, NEW.components_id, true, true, true, true); "\
        "ELSE "\
        "INSERT INTO role_permissions(tenant_id, role_id, components_id, can_create, can_read, can_update, can_delete) VALUES(t.tenant_id, r.role_id, NEW.components_id, false, false, false, false); "\
        "END IF; "\
        "ELSIF	r.type = 'default' AND NEW.module = 'user_settings' AND NEW.component = 'users' AND NEW.subcomponent = 'general' THEN "\
        "INSERT INTO role_permissions(tenant_id, role_id, components_id, can_create, can_read, can_update, can_delete) VALUES(t.tenant_id, r.role_id, NEW.components_id, false, true, true, false); "\
        "ELSE "\
        "INSERT INTO role_permissions(tenant_id, role_id, components_id, can_create, can_read, can_update, can_delete) VALUES(t.tenant_id, r.role_id, NEW.components_id, false, false, false, false); "\
        "END IF; "\
        "END LOOP; "\
        "INSERT INTO tenant_permissions(tenant_id, components_id) VALUES(t.tenant_id, NEW.components_id); "\
        "END LOOP; "\
        "RETURN NEW; "\
        "END; "\
        "$BODY$ "\
        "language plpgsql; "\
        "DROP TRIGGER IF EXISTS new_permissions ON components_master; "\
        "CREATE TRIGGER new_permissions "\
        "AFTER INSERT "\
        "ON components_master "\
        "FOR EACH ROW "\
        "EXECUTE PROCEDURE add_permissions(); "\


    rds_execute_statement(sql_role_tenants_components)


def insert_tenant():
    sql = f"""SELECT COUNT(*) FROM tenants_master WHERE tenant_name = '{TENANT_NAME}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_insert_tenant = "INSERT INTO tenants_master (user_pool_id, identity_pool_id, user_pool_client_id, tenant_name) "\
                            "VALUES ("\
            f"'{USER_POOL_ID}', "\
            f"'{IDENTITY_POOL_ID}', "\
            f"'{USER_POOL_CLIENT_ID}', "\
            f"'{TENANT_NAME}'"\
                            ")"
        rds_execute_statement(sql_insert_tenant)


def get_tenant_id():
    global TENANT_ID
    sql_tenant_id = f"SELECT tenant_id FROM tenants_master WHERE tenant_name='{TENANT_NAME}'"
    TENANT_ID = rds_execute_statement(
        sql_tenant_id)['records'][0][0]["stringValue"]


def create_default_role():
    global role_id
    sql = f"""SELECT COUNT(*) FROM roles_master WHERE role = 'default' AND type = 'default' AND  tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_default_role_creation = "INSERT INTO roles_master (role, tenant_id, type)"\
            "VALUES("\
            f"'default', "\
            f"'{TENANT_ID}',"\
            f"'default'"\
            ")"
        rds_execute_statement(sql_default_role_creation)

    sql = f"""SELECT COUNT(*) FROM roles_master WHERE role = 'account' AND type = 'other' AND  tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_create_account_role = "INSERT INTO roles_master ( role, tenant_id, type) "\
            "VALUES ("\
            f"'account', "\
            f"'{TENANT_ID}', "\
            f"'other'"\
            ") RETURNING role_id"
        role_id = rds_execute_statement(sql_create_account_role)[
            'records'][0][0]["stringValue"]
    else:
        sql = f"""SELECT role_id FROM roles_master WHERE role = 'account' AND type = 'other' AND  tenant_id = '{TENANT_ID}'"""
        role_id = rds_execute_statement(sql)['records'][0][0]["stringValue"]


def create_user():
    global cognito_user_id

    try:
        cognito_response = COGNITO_CLIENT.admin_get_user(
            UserPoolId=USER_POOL_ID,
            Username=USER_EMAIL
        )
        cognito_user_id = cognito_response['Username']

    except COGNITO_CLIENT.exceptions.UserNotFoundException as e:

        cognito_response = COGNITO_CLIENT.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=USER_EMAIL,
            UserAttributes=[
                {"Name": "email_verified", "Value": "True"},
                {"Name": "email", "Value": USER_EMAIL}
            ],
            DesiredDeliveryMediums=['EMAIL']
        )
        cognito_user_id = cognito_response['User']['Username']

    sql = f"""SELECT COUNT(*) FROM users_master WHERE cognito_user_id = '{cognito_user_id}' AND tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_insert_user = f"INSERT INTO users_master (cognito_user_id, first_name, last_name, email, tenant_id) "\
            "VALUES ("\
            f"'{cognito_user_id}', "\
            f"'{USER_FIRST_NAME}', "\
            f"'{USER_LAST_NAME}', "\
            f"'{USER_EMAIL}', "\
            f"'{TENANT_ID}'"\
            ")"
        rds_execute_statement(sql_insert_user)

    # assignation of the default role
    sql_default_role_id = f"SELECT role_id FROM roles_master WHERE tenant_id='{TENANT_ID}' AND type = 'default'"
    default_role_id = rds_execute_statement(sql_default_role_id)['records']

    ###TODO: PROBAR
    for role in default_role_id:
        sql = f"""SELECT COUNT(*) FROM user_roles WHERE cognito_user_id = '{cognito_user_id}' AND role_id = '{role[0]['stringValue']}' AND  tenant_id = '{TENANT_ID}'"""
        count = rds_execute_statement(sql)['records'][0][0]["longValue"]
        if not count:
            assign_default_role_query = f"INSERT INTO user_roles (tenant_id ,cognito_user_id ,role_id) VALUES('{TENANT_ID}','{cognito_user_id}','{role[0]['stringValue']}');"
            rds_execute_statement(assign_default_role_query)


def assign_role():
    sql = f"""SELECT COUNT(*) FROM roles_master WHERE role = 'admin' AND type = 'admin' AND  tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_create_role = "INSERT INTO roles_master ( role, tenant_id, type) "\
            "VALUES ("\
            f"'admin', "\
            f"'{TENANT_ID}', "\
            f"'admin'"\
            ")"
        rds_execute_statement(sql_create_role)

    sql_default_role_id = f"SELECT role_id FROM roles_master WHERE tenant_id='{TENANT_ID}' AND type = 'admin'"
    ROLE_ID = rds_execute_statement(sql_default_role_id)[
        'records'][0][0]["stringValue"]

    sql = f"""SELECT COUNT(*) FROM user_roles WHERE cognito_user_id = '{cognito_user_id}' AND role_id = '{ROLE_ID}' AND  tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_assign_role = f"INSERT INTO user_roles (tenant_id, cognito_user_id, role_id) "\
            "VALUES ("\
            f"'{TENANT_ID}', "\
            f"'{cognito_user_id}', "\
            f"'{ROLE_ID}'"\
            ")"
        rds_execute_statement(sql_assign_role)


def create_components():

    path = os.path.dirname(__file__)
    path = "/".join(path.split('/')[:-2])
    file = open(f'{path}/configuration.json')
    data = json.load(file)

    components = data["components"]

    components_sql = ""
    execute = False
    for component in components:
        sql = f"""SELECT COUNT(*) FROM components_master 
        WHERE module='{component[0]}' 
        AND component='{component[1]}' 
        AND subcomponent='{component[2]}'
        """
        count = rds_execute_statement(sql)['records'][0][0]["longValue"]
        if not count:
            execute = True
            components_sql += f"""INSERT INTO components_master(module,component,subcomponent,valid_for) 
            VALUES ('{component[0]}','{component[1]}','{component[2]}','{component[3]}'); \n"""

    if execute:
        rds_execute_statement(components_sql)


def create_object_limit():

    path = os.path.dirname(__file__)
    path = "/".join(path.split('/')[:-2])
    file = open(f'{path}/configuration.json')
    data = json.load(file)

    objects = data["objects"]

    objects_sql = ""
    execute = False

    for obj in objects:
        sql = f"""SELECT COUNT(*) FROM objects_master 
        WHERE table_name = '{obj[0]}' AND tenant_id = '{TENANT_ID}'
        """
        count = rds_execute_statement(sql)['records'][0][0]["longValue"]
        if not count:
            execute = True
            objects_sql += f"""INSERT INTO objects_master(tenant_id, table_name,object_limit) 
             VALUES('{TENANT_ID}', '{obj[0]}', {obj[1]}); \n"""

    if execute:
        rds_execute_statement(objects_sql)


def create_app_tenant_user():
    # Tenant user
    sql = f"""SELECT COUNT(*) FROM users_master WHERE first_name = 'Tenant' 
    AND last_name = 'Key' 
    AND email = 'Tenant-Key'
    AND tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_insert_user = f"INSERT INTO users_master (cognito_user_id, first_name, last_name, email, tenant_id) "\
            "VALUES ("\
            f"uuid_generate_v4(), "\
            f"'Tenant', "\
            f"'Key', "\
            f"'Tenant-Key', "\
            f"'{TENANT_ID}'"\
            ")"
        rds_execute_statement(sql_insert_user)

    # App user
    sql = f"""SELECT COUNT(*) FROM users_master WHERE first_name = 'App' 
    AND last_name = 'Key' 
    AND email = 'App-Key'
    AND tenant_id = '{TENANT_ID}'"""
    count = rds_execute_statement(sql)['records'][0][0]["longValue"]
    if not count:
        sql_insert_user = f"INSERT INTO users_master (cognito_user_id, first_name, last_name, email, tenant_id) "\
            "VALUES ("\
            f"uuid_generate_v4(), "\
            f"'App', "\
            f"'Key', "\
            f"'App-Key', "\
            f"'{TENANT_ID}'"\
            ")"
        rds_execute_statement(sql_insert_user)


def lambda_handler(event, context):

    try:
        initialize()
        create_databases()
        insert_tenant()
        get_tenant_id()
        create_default_role()
        create_user()
        assign_role()
        create_components()
        create_object_limit()
        create_app_tenant_user()
        return {
            'statusCode': 200,
            'body': 'Resources Created',
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
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': ERROR_MSG,
                'code': str(exc_type),
                'uuid': UUID
            }),
            'headers': {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
                "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers"
            }
        }
