import logging
from pathlib import Path
from typing import Union
import os
from functools import partial

import boto3

from magnus import defaults


logger = logging.getLogger(defaults.NAME)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('s3transfer').setLevel(logging.CRITICAL)


class AWSConfigMixin:
    """
    A Mixin to provide common utilities for AWS services
    """

    def __init__(self, config):
        self.config = config or {}

    def get_aws_profile(self) -> Union[str, None]:
        """
        Return the aws profile as set by the config or None if config is empty

        Returns:
            str: The AWS profile name or None
        """
        return self.config.get('aws_profile', None)

    def remove_aws_profile(self):
        """
        Removes the user mentioned AWS profile from the boto session.

        This is useful in cases where we are doing role based auth instead of profile based.
        """
        self.config['aws_profile'] = None

    def set_to_use_credentials(self):
        """
        Sets the use_credentials flag in the config to True
        """
        self.config['use_credentials'] = True

    def get_region_name(self) -> str:
        """
        Return the AWS region as per the config or the default eu-west-1.

        Returns:
            str: The region name as per the config or eu-west-1
        """
        return self.config.get('region', defaults.AWS_REGION)

    def get_aws_credentials_file(self) -> str:
        """
        Return the AWS credentials file if provided in the config or default to $HOME/.aws/credentials

        Returns:
            str: The location of the credentials file
        """
        if 'aws_credentials_file' in self.config:
            return self.config['aws_credentials_file']

        return str(Path.home() / '.aws' / 'credentials')

    def get_aws_credentials_from_env(self) -> dict:
        """
        Look for AWS credentials in the environment variables

        Returns:
            dict: AWS credentials as dictionary
        """

        aws_credentials = {}
        try:
            aws_credentials['AWS_ACCESS_KEY_ID'] = os.environ['AWS_ACCESS_KEY_ID']
            aws_credentials['AWS_SECRET_ACCESS_KEY'] = os.environ['AWS_SECRET_ACCESS_KEY']
            aws_credentials['AWS_SESSION_TOKEN'] = os.environ.get('AWS_SESSION_TOKEN', None)
        except KeyError as _e:
            msg = (
                "Expected AWS credentials as part of the environment. Please set AWS_ACCESS_KEY_ID,"
                "AWS_SECRET_ACCESS_KEY as part of the environment"
            )
            raise Exception(msg) from _e

        return aws_credentials

    def get_boto3_session(self):
        """
        Returns a boto3 session

        If we are not using any credentials, we return either a named session or the default session.
        If we are using AWS credentials, we get a session based on the credentials and assume the role.

        Returns:
            [type]: [description]
        """
        profile = self.get_aws_profile()
        region = self.get_region_name()

        # If we are not using credentials from environment variables, return the session
        if not self.config.get('use_credentials', False):
            return boto3.session.Session(profile_name=profile, region_name=region)

        # If we are using creds from environment, there are 2 possible scenarios
        # 1). We want a session with just aws access key and secret
        # 2). We want a session with a role_arn which might require session_id set up

        aws_creds = self.get_aws_credentials_from_env()

        partial_sess = partial(boto3.session.Session, aws_access_key_id=aws_creds['AWS_ACCESS_KEY_ID'],
                               aws_secret_access_key=aws_creds['AWS_SECRET_ACCESS_KEY'],
                               region_name=region)

        if 'role_arn' not in self.config:
            logger.info("No Role ARN present in config, assuming a simple session with no STS")
            return partial_sess()  # Enough information to call the partial

        sess = partial_sess(aws_session_token=aws_creds['AWS_SESSION_TOKEN'])

        sts_connection = sess.client('sts')
        assume_role_object = sts_connection.assume_role(
            RoleArn=self.config['role_arn'],
            RoleSessionName='temp-session',
            DurationSeconds=900)
        credentials = assume_role_object['Credentials']

        tmp_access_key = credentials['AccessKeyId']
        tmp_secret_key = credentials['SecretAccessKey']
        tmp_security_token = credentials['SessionToken']

        return boto3.session.Session(
            aws_access_key_id=tmp_access_key,
            aws_secret_access_key=tmp_secret_key, aws_session_token=tmp_security_token,
            region_name=region
        )
