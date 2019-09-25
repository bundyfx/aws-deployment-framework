# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
from aws_cdk import (
    aws_codepipeline as _codepipeline,
    aws_codepipeline_actions as _codepipeline_actions,
    aws_codecommit as _codecommit,
    aws_codebuild as _codebuild,
    aws_s3 as _s3,
    aws_iam as _iam,
    aws_kms as _kms,
    aws_ssm as _ssm,
    core
)

from cdk_constructs.adf_codepipeline import Action

ADF_DEPLOYMENT_REGION = os.environ["AWS_REGION"]
ADF_DEPLOYMENT_ACCOUNT_ID = os.environ["ACCOUNT_ID"]

class CodeBuild(core.Construct):
    def __init__(self, scope: core.Construct, id: str, shared_modules_bucket: str, deployment_region_kms: str, map_params: dict, target, **kwargs):
        super().__init__(scope, id, **kwargs)
        ADF_DEFAULT_BUILD_ROLE = 'arn:aws:iam::{0}:role/adf-codebuild-role'.format(ADF_DEPLOYMENT_ACCOUNT_ID)
        ADF_DEFAULT_BUILD_TIMEOUT = 20
        # if CodeBuild is being used as a deployment action we want to allow target specific values.
        if target:
            _build_role = 'arn:aws:iam::{0}:role/{1}'.format(
                ADF_DEPLOYMENT_ACCOUNT_ID,
                target['params'].get('role')
            ) if target.get('params', {}).get('role') else ADF_DEFAULT_BUILD_ROLE
            _timeout = target.get('params', {}).get('timeout') or ADF_DEFAULT_BUILD_TIMEOUT
            _env = _codebuild.BuildEnvironment(
                build_image=target.get('params', {}).get('image') or getattr(_codebuild.LinuxBuildImage, map_params['type']['build'].get('image', "UBUNTU_14_04_PYTHON_3_7_1").upper()),
                compute_type=target.get('params', {}).get('compute_type') or getattr(_codebuild.ComputeType, map_params['type']['build'].get('size', "SMALL").upper()),
                environment_variables=CodeBuild.generate_build_env_variables(_codebuild, shared_modules_bucket, map_params['name'], target),
                privileged=target.get('params', {}).get('privileged', False) or map_params['type']['build'].get('privileged', False)
            )
            # Core difference from CodeBuild as deployment as opposed to build is we allow the buildspec file to be passed in dynamically
            _spec = map_params['type']['deploy'].get('spec') or target.get('type', {}).get('deploy', {}).get('spec') or 'deployspec.yml'
            _codebuild.PipelineProject(
                self,
                'project',
                environment=_env,
                encryption_key=_kms.Key.from_key_arn(self, 'default_deployment_account_key', key_arn=deployment_region_kms),
                description="ADF CodeBuild Project for {0}".format(target['name']),
                project_name="adf-deploy-{0}".format(target['name']),
                timeout=core.Duration.minutes(_timeout),
                role=_iam.Role.from_role_arn(self, 'build_role', role_arn=_build_role),
                build_spec=_codebuild.BuildSpec.from_source_filename(_spec)
            )
            self.deploy = Action(
                name="{0}".format(target['name']),
                provider="CodeBuild",
                category="Build",
                run_order=1,
                target=target,
                map_params=map_params,
                action_name="{0}".format(target['name'])
            ).config
        else:
            _build_role = 'arn:aws:iam::{0}:role/{1}'.format(
                ADF_DEPLOYMENT_ACCOUNT_ID,
                map_params['type']['build'].get('role')
            ) if map_params['type']['build'].get('role') else ADF_DEFAULT_BUILD_ROLE
            _timeout = map_params['type']['build'].get('timeout') or ADF_DEFAULT_BUILD_TIMEOUT
            _env = _codebuild.BuildEnvironment(
                build_image=getattr(_codebuild.LinuxBuildImage, map_params['type']['build'].get('image', "UBUNTU_14_04_PYTHON_3_7_1")),
                compute_type=getattr(_codebuild.ComputeType, map_params['type']['build'].get('size', "SMALL").upper()),
                environment_variables=CodeBuild.generate_build_env_variables(_codebuild, shared_modules_bucket, map_params['name']),
                privileged=map_params['type']['build'].get('privileged', False)
            )
            if map_params['type']['build'].get('role'):
                ADF_DEFAULT_BUILD_ROLE = 'arn:aws:iam::{0}:role/{1}'.format(ADF_DEPLOYMENT_ACCOUNT_ID, map_params['type']['build']['role'])
            _codebuild.PipelineProject(
                self,
                'project',
                environment=_env,
                encryption_key=_kms.Key.from_key_arn(self, 'DefaultDeploymentAccountKey', key_arn=deployment_region_kms),
                description="ADF CodeBuild Project for {0}".format(map_params['name']),
                project_name="adf-build-{0}".format(map_params['name']),
                timeout=core.Duration.minutes(_timeout),
                role=_iam.Role.from_role_arn(self, 'default_build_role', role_arn=_build_role)
            )
            self.build = _codepipeline.CfnPipeline.StageDeclarationProperty(
                name="Build",
                actions=[
                    Action(
                        name="Build",
                        provider="CodeBuild",
                        category="Build",
                        run_order=1,
                        map_params=map_params,
                        action_name="build"
                    ).config
                ]
            )


    @staticmethod
    def generate_build_env_variables(codebuild, shared_modules_bucket, name, target=None):
        _output = {
            "PYTHONPATH": codebuild.BuildEnvironmentVariable(value='./adf-build/python'),
            "ADF_PROJECT_NAME": codebuild.BuildEnvironmentVariable(value=name),
            "S3_BUCKET_NAME": codebuild.BuildEnvironmentVariable(value=shared_modules_bucket),
            "ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=core.Aws.ACCOUNT_ID)
        }
        if target:
            _output["TARGET_NAME"] = codebuild.BuildEnvironmentVariable(value=target['name'])
            _output["TARGET_ACCOUNT_ID"] = codebuild.BuildEnvironmentVariable(value=target['id'])
            if target.get('params', {}).get('deployment_role'):
                _output["DEPLOYMENT_ROLE"] = codebuild.BuildEnvironmentVariable(value=target['params']['deployment_role'])
        return _output