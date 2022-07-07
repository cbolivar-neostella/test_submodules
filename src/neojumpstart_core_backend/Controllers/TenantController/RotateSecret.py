import json
import os
import uuid
from datetime import datetime, timedelta

import boto3
import src.neojumpstart_core_backend.functions as functions
#import Values
#import src.neojumpstart_core_backend.functions as functions
from src.neojumpstart_core_backend.functions import (CORALOGIX_KEY,
                                                     REGION_NAME,
                                                     RESOURCE_METHOD,
                                                     SERVICE_NAME, get_secret,
                                                     initialize,
                                                     send_to_coralogix,
                                                     throttling_check,
                                                     wait_for_threads)


def initialize_functions():
    global UUID, CURRENT_DATETIME
    initialize()
    UUID = functions.UUID
    CURRENT_DATETIME = functions.CURRENT_DATETIME


def create_secret(service_client, arn, token):
    # Make sure the current secret exists
    service_client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")

    # Now try to get the secret version, if that fails, put a new secret
    try:
        service_client.get_secret_value(
            SecretId=arn, VersionId=token, VersionStage="AWSPENDING")
        curr_log = f"createSecret: Successfully retrieved secret for {arn}."
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
    except service_client.exceptions.ResourceNotFoundException:
        # Get exclude characters from environment variable
        exclude_characters = os.environ['EXCLUDE_CHARACTERS'] if 'EXCLUDE_CHARACTERS' in os.environ else '/@"\'\\'
        # Generate a random password
        passwd = service_client.get_random_password(
            ExcludeCharacters=exclude_characters)

        # Put the secret
        service_client.put_secret_value(SecretId=arn, ClientRequestToken=token,
                                        SecretString=passwd['RandomPassword'], VersionStages=['AWSPENDING'])
        curr_log = f"createSecret: Successfully put secret for ARN {arn} and version {token}."
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)


def set_secret(service_client, arn, token):
    # This is where the secret should be set in the service
    raise NotImplementedError


def test_secret(service_client, arn, token):
    # This is where the secret should be tested against the service
    raise NotImplementedError


def finish_secret(service_client, arn, token):
    # First describe the secret to get the current version
    metadata = service_client.describe_secret(SecretId=arn)
    current_version = None
    for version in metadata["VersionIdsToStages"]:
        if "AWSCURRENT" in metadata["VersionIdsToStages"][version]:
            if version == token:
                # The correct version is already marked as current, return
                curr_log = f"finishSecret: Version {version} already marked as AWSCURRENT for {arn}"
                send_to_coralogix(CORALOGIX_KEY, {
                    'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
                return
            current_version = version
            break

    # Finalize by staging the secret version current
    service_client.update_secret_version_stage(
        SecretId=arn, VersionStage="AWSCURRENT", MoveToVersionId=token, RemoveFromVersionId=current_version)
    curr_log = f"finishSecret: Successfully set AWSCURRENT stage to version {token} for secret {arn}."
    send_to_coralogix(CORALOGIX_KEY, {
        'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)


def lambda_handler(event, context):
    # Get initial values
    initialize_functions()
    arn = event['SecretId']
    token = event['ClientRequestToken']
    step = event['Step']

    # Setup the client
    #service_client = boto3.client('secretsmanager', endpoint_url=os.environ['SECRETS_MANAGER_ENDPOINT'])
    secrets_session = boto3.session.Session()
    service_client = secrets_session.client(
        service_name='secretsmanager',
        region_name=REGION_NAME
    )

    # Make sure the version is staged correctly
    metadata = service_client.describe_secret(SecretId=arn)
    if not metadata['RotationEnabled']:
        curr_log = f"Secret {arn} is not enabled for rotation"
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
        raise ValueError(f"Secret {arn} is not enabled for rotation")
    versions = metadata['VersionIdsToStages']
    if token not in versions:
        curr_log = f"Secret version {token} has no stage for rotation of secret {arn}."
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
        raise ValueError(
            f"Secret version {token} has no stage for rotation of secret {arn}.")
    if "AWSCURRENT" in versions[token]:
        curr_log = f"Secret version {token} already set as AWSCURRENT for secret {arn}."
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
        return
    elif "AWSPENDING" not in versions[token]:
        curr_log = f"Secret version {token} not set as AWSPENDING for rotation of secret {arn}."
        send_to_coralogix(CORALOGIX_KEY, {
            'UUID': UUID, 'response': curr_log}, SERVICE_NAME, RESOURCE_METHOD, 3)
        raise ValueError(
            f"Secret version {token} not set as AWSPENDING for rotation of secret {arn}.")

    if step == "createSecret":
        create_secret(service_client, arn, token)

    elif step == "setSecret":
        #set_secret(service_client, arn, token)
        pass

    elif step == "testSecret":
        #test_secret(service_client, arn, token)
        pass

    elif step == "finishSecret":
        finish_secret(service_client, arn, token)

    else:
        for thread in THREADS:
            thread.join()
        raise ValueError("Invalid step parameter")

    wait_for_threads()
