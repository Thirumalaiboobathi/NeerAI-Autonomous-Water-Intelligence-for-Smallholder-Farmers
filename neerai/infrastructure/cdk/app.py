#!/usr/bin/env python3
"""NeerAI AWS CDK app (Python). Cost-conscious: Lambda + HTTP API + Function URL + DynamoDB (on-demand) + S3 + CloudFront.

Synthesis validated (see docs/DEPLOYMENT.md). NOT deployed: deploying creates billable resources and needs explicit approval.

Synthesize:  CDK_OUTDIR=cdk.out python app.py -c originVerifySecret=<random>      (or `cdk synth -c originVerifySecret=...`)

Why two paths to one Lambda?  API Gateway HTTP APIs cap integrations at 30 s; a Bedrock multi-agent assessment measured
27-34 s. So `/api/agent/*` and `/api/irrigation/assess` go CloudFront -> Lambda Function URL (60 s), everything else goes
CloudFront -> API Gateway (throttled). Both origins receive a secret header the app verifies, so neither is usable directly.
"""
import aws_cdk as cdk
from aws_cdk import (
    CfnOutput, Duration, Fn, RemovalPolicy, Stack,
    aws_apigatewayv2 as apigw, aws_apigatewayv2_integrations as integrations, aws_cloudfront as cf,
    aws_cloudfront_origins as origins, aws_cloudwatch as cw, aws_dynamodb as ddb, aws_iam as iam, aws_lambda as _lambda,
    aws_logs as logs, aws_s3 as s3,
)
from constructs import Construct

# Nova Pro in ap-south-1 is only invokable through the APAC cross-region inference profile.
INFERENCE_PROFILE_ID = "apac.amazon.nova-pro-v1:0"
FOUNDATION_MODEL_ID = "amazon.nova-pro-v1:0"
AGENT_PATHS = ["/api/agent/*", "/api/irrigation/assess"]


class NeerAIStack(Stack):
    def __init__(self, scope: Construct, id: str, *, origin_secret: str, **kw) -> None:
        super().__init__(scope, id, **kw)

        table = ddb.Table(self, "Documents", partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
                          sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING), billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                          point_in_time_recovery=True, removal_policy=RemovalPolicy.RETAIN)
        reports = s3.Bucket(self, "Reports", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, encryption=s3.BucketEncryption.S3_MANAGED,
                            enforce_ssl=True, removal_policy=RemovalPolicy.RETAIN, lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))])
        site = s3.Bucket(self, "Site", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, encryption=s3.BucketEncryption.S3_MANAGED,
                         enforce_ssl=True, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)

        log_group = logs.LogGroup(self, "ApiLogs", retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY)
        fn = _lambda.Function(
            self, "Api", runtime=_lambda.Runtime.PYTHON_3_12, handler="app.lambda_handler.handler", timeout=Duration.seconds(90),
            memory_size=1024, log_group=log_group,
            # Build first with scripts/build_lambda.sh (Linux wheels + app + data/demo).
            code=_lambda.Code.from_asset("../../backend/build"),
            environment={
                "NEERAI_ENV": "aws", "NEERAI_AGENT_MODE": "bedrock", "NEERAI_BEDROCK_MODEL_ID": INFERENCE_PROFILE_ID,
                "NEERAI_BEDROCK_REGION": self.region, "NEERAI_REPOSITORY": "dynamodb", "NEERAI_DYNAMODB_TABLE": table.table_name,
                "NEERAI_REPORTS_BUCKET": reports.bucket_name,
                # Strict live weather: if Open-Meteo is down the app says so; it never substitutes simulated data.
                "NEERAI_WEATHER_PROVIDER": "openmeteo", "NEERAI_AGENT_TIMEOUT_S": "80",
                "NEERAI_DEMO_DIR": "/var/task/data/demo", "NEERAI_ORIGIN_VERIFY_SECRET": origin_secret,
                "NEERAI_CORS_ORIGINS": "https://invalid.example",  # same-origin via CloudFront; no cross-origin callers
            },
        )
        # Least privilege: only the DynamoDB actions the repository uses, put-only on reports, one model/profile.
        fn.add_to_role_policy(iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"],
                                                  resources=[table.table_arn]))
        fn.add_to_role_policy(iam.PolicyStatement(actions=["s3:PutObject"], resources=[reports.arn_for_objects("*")]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODEL_ID}",
                       f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{INFERENCE_PROFILE_ID}"]))

        # Short, throttled routes via API Gateway.
        api = apigw.HttpApi(self, "HttpApi", default_integration=integrations.HttpLambdaIntegration("LambdaInt", fn))
        stage_cfn = api.default_stage.node.default_child  # type: ignore[union-attr]
        stage_cfn.default_route_settings = {"throttlingRateLimit": 20, "throttlingBurstLimit": 40}  # type: ignore[attr-defined]
        # Long agent routes via Lambda Function URL (auth NONE, protected by the origin secret header).
        fn_url = fn.add_function_url(auth_type=_lambda.FunctionUrlAuthType.NONE)

        headers = {"x-origin-verify": origin_secret}
        api_origin = origins.HttpOrigin(Fn.select(2, Fn.split("/", api.api_endpoint)), custom_headers=headers,
                                        protocol_policy=cf.OriginProtocolPolicy.HTTPS_ONLY)
        agent_origin = origins.HttpOrigin(Fn.select(2, Fn.split("/", fn_url.url)), custom_headers=headers,
                                          protocol_policy=cf.OriginProtocolPolicy.HTTPS_ONLY, read_timeout=Duration.seconds(60))
        dyn = dict(viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY, allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                   cache_policy=cf.CachePolicy.CACHING_DISABLED, origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER)
        dist = cf.Distribution(
            self, "Cdn", default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(site),
                                                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS),
            additional_behaviors={**{p: cf.BehaviorOptions(origin=agent_origin, **dyn) for p in AGENT_PATHS},
                                  "/api/*": cf.BehaviorOptions(origin=api_origin, **dyn)},
            error_responses=[cf.ErrorResponse(http_status=403, response_http_status=200, response_page_path="/index.html"),
                             cf.ErrorResponse(http_status=404, response_http_status=200, response_page_path="/index.html")],
        )

        cw.Alarm(self, "LambdaErrors", metric=fn.metric_errors(), threshold=1, evaluation_periods=1)
        cw.Alarm(self, "LambdaThrottles", metric=fn.metric_throttles(), threshold=1, evaluation_periods=1)
        cw.Alarm(self, "LambdaDurationP95", metric=fn.metric_duration(statistic="p95"), threshold=60000, evaluation_periods=2)

        CfnOutput(self, "SiteUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "SiteBucket", value=site.bucket_name)
        CfnOutput(self, "DistributionId", value=dist.distribution_id)


app = cdk.App()
secret = app.node.try_get_context("originVerifySecret")
if not secret or len(str(secret)) < 16:
    raise SystemExit("Pass a random secret of >=16 chars: -c originVerifySecret=<random>  (never commit it)")
NeerAIStack(app, "NeerAIStack", origin_secret=str(secret),
            env=cdk.Environment(region=app.node.try_get_context("region") or "ap-south-1"))
app.synth()
