import os

from aws_cdk import (
    aws_codepipeline as _codepipeline,
    aws_sns as _sns,
    aws_lambda as _lambda,
    core
)
from cdk_constructs import adf_codepipeline
from cdk_constructs import adf_codebuild
from cdk_constructs import adf_jenkins
from cdk_constructs import adf_codecommit
from cdk_constructs import adf_github
from cdk_constructs import adf_s3
from cdk_constructs import adf_cloudformation
from cdk_constructs import adf_notifications
from logger import configure_logger

ADF_DEPLOYMENT_REGION = os.environ["AWS_REGION"]
ADF_DEPLOYMENT_ACCOUNT_ID = os.environ["ACCOUNT_ID"]
ADF_DEFAULT_BUILD_TIMEOUT = 20
LOGGER = configure_logger(__name__)

class PipelineStack(core.Stack):
    def __init__(self, scope: core.Construct, stack_input: dict, **kwargs) -> None:
        super().__init__(scope, stack_input['input']['name'], **kwargs)
        LOGGER.info('Pipeline creation/update of %s commenced', stack_input['input']['name'])
        _source_name = stack_input['input']["type"]["source"]["name"].lower()
        _build_name = stack_input['input']["type"]["build"]["name"].lower()
        _stages = []
        if stack_input['input'].get('notification_endpoint'):
            stack_input['input']["topic_arn"] = adf_notifications.Notifications(self, 'adf_notifications', stack_input['input']).topic_arn
        if 'codecommit' in _source_name:
            _stages.append(
                adf_codecommit.CodeCommit(
                    self,
                    'source',
                    stack_input['input']
                ).source
            )
        elif 'github' in _source_name:
            _stages.append(
                adf_github.GitHub(
                    self,
                    'source',
                    stack_input['input']
                ).source
            )
        elif 's3' in _source_name:
            _stages.append(
                adf_s3.S3(
                    self,
                    'source',
                    stack_input['input']
                ).source
            )
        if 'codebuild' in _build_name:
            _stages.append(
                adf_codebuild.CodeBuild(
                    self,
                    'build',
                    stack_input['ssm_params'][ADF_DEPLOYMENT_REGION]["modules"],
                    stack_input['ssm_params'][ADF_DEPLOYMENT_REGION]["kms"],
                    stack_input['input'],
                    {} # Empty target since this is a build only stage
                ).build
            )
        elif 'jenkins' in _build_name:
            _stages.append(
                adf_jenkins.Jenkins(
                    self,
                    'build',
                    stack_input['input']
                ).build
            )
        for index, targets in enumerate(stack_input['input'].get('environments', {}).get('targets', [])):
            _actions = []
            top_level_deployment_type = stack_input['input'].get('type', {}).get('deploy', {}).get('name', '') or 'cloudformation'
            top_level_action = stack_input['input'].get('type', {}).get('deploy', {}).get('action', '')
            for target in targets:
                if target.get('name') == 'approval' or target.get('type', {}).get('approval'):
                    _actions.extend([
                        adf_codepipeline.Action(
                            name="{0}".format(target['name']),
                            provider="Manual",
                            category="Approval",
                            target=target,
                            run_order=1,
                            map_params=stack_input['input'],
                            action_name="{0}".format(target['name'])
                        ).config
                    ])
                    continue
                regions = stack_input['input'].get('regions', target.get('regions'))
                for region in regions:
                    target_stage_override = target.get('type', {}).get('invoke', {}).get('name') or target.get('type', {}).get('deploy', {}).get('name') or top_level_deployment_type
                    if 'cloudformation' in target_stage_override:
                        target_action_mode = target.get('type', {}).get('deploy', {}).get('change_set')
                        if top_level_action and not target_action_mode:
                            _actions.extend([
                                adf_codepipeline.Action(
                                    name="{0}-{1}".format(target['name'], region),
                                    provider="CloudFormation",
                                    category="Deploy",
                                    region=region,
                                    target=target,
                                    action_mode=top_level_action,
                                    run_order=1,
                                    map_params=stack_input['input'],
                                    action_name="{0}-{1}".format(target['name'], region)
                                ).config
                            ])
                            continue
                        _actions.extend(adf_cloudformation.CloudFormation.generate_actions(target, region, stack_input['input']))
                    elif 'codedeploy' in target_stage_override:
                        _actions.extend([
                            adf_codepipeline.Action(
                                name="{0}-{1}".format(target['name'], region),
                                provider="CodeDeploy",
                                category="Deploy",
                                region=region,
                                target=target,
                                action_mode=top_level_action,
                                run_order=1,
                                map_params=stack_input['input'],
                                action_name="{0}-{1}".format(target['name'], region)
                            ).config
                        ])
                    elif 's3' in target_stage_override:
                        pass
                    elif 'lambda' in target_stage_override:
                        _actions.extend([
                            adf_codepipeline.Action(
                                name="{0}-{1}".format(target['name'], region),
                                provider="Lambda",
                                category="Invoke",
                                region=region,
                                target=target,
                                action_mode=top_level_action,
                                run_order=1,
                                map_params=stack_input['input'],
                                action_name="{0}-{1}".format(target['name'], region)
                            ).config
                        ])
                    elif 'codebuild' in target_stage_override:
                        _actions.extend([
                            adf_codebuild.CodeBuild(
                                self,
                                '{0}-stage-{1}'.format(target['name'], index + 1),
                                stack_input['ssm_params'][ADF_DEPLOYMENT_REGION]["modules"],
                                stack_input['ssm_params'][ADF_DEPLOYMENT_REGION]["kms"],
                                stack_input['input'],
                                target
                            ).deploy
                        ])
                    elif 'service_catalog' in target_stage_override:
                        _actions.extend([
                            adf_codepipeline.Action(
                                name="{0}-{1}".format(target['name'], region),
                                provider="ServiceCatalog",
                                category="Deploy",
                                region=region,
                                target=target,
                                action_mode=top_level_action,
                                run_order=1,
                                map_params=stack_input['input'],
                                action_name="{0}-{1}".format(target['name'], region)
                            ).config
                        ])
            _name = 'approval' if targets[0]['name'].startswith('approval') or targets[0].get('type', {}).get('approval') else 'deployment' # 0th Index since approvals won't be parallel
            _stages.append(
                _codepipeline.CfnPipeline.StageDeclarationProperty(
                    name=targets[0].get('step_name') or '{0}-stage-{1}'.format(_name, index + 1), # 0th Index since step names are for entire stages not per target
                    actions=_actions
                )
            )
        _pipeline = adf_codepipeline.Pipeline(self, 'code_pipeline', stack_input['input'], stack_input['ssm_params'], _stages)
        if 'github' in _source_name:
            adf_github.GitHub.create_webhook(self, _pipeline.cfn, stack_input['input'])
