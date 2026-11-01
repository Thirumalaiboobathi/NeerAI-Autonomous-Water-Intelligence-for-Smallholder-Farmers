#!/usr/bin/env python3
"""NeerAI AWS CDK app (Python): serverless, Docker-free. One stack per stage: NeerAI-Dev / NeerAI-Prod.

  API Gateway HTTP API (Cognito JWT authorizer) -> Lambda (FastAPI/Mangum, 28 s)      short deterministic routes + job API
  POST /api/jobs -> DynamoDB job record + SQS -> Lambda worker (Strands + Bedrock, 120 s) -> DynamoDB   long agent runs
  Frontend: AWS Amplify Hosting (created in the console, Git-connected; see docs/deployment.md). Not part of this stack.

Context (cdk.json or -c key=value):
  stage            dev | prod                   (default dev)
  frontendOrigin   https://<branch>.<appId>.amplifyapp.com   REQUIRED: CORS allow-list + Cognito callback/logout URL
  extraCallbackUrls  comma list, e.g. http://localhost:5173/   (dev convenience only; never for prod)
  weatherProvider  openmeteo | auto | mock      (default openmeteo = strict live; mock = labelled simulation)
  alertEmail       optional: subscribes this address to the alarm topic
  createBudget     "true" to add a $25/month AWS Budget (needs budgetEmail)
  workerConcurrency  max concurrent agent runs (SQS event source max concurrency, 2..N; default 3)

Nothing here is deployed by synthesis. `cdk deploy` creates billable resources and needs explicit approval.
"""
from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack, Tags,
    aws_apigatewayv2 as apigw, aws_apigatewayv2_authorizers as authz, aws_apigatewayv2_integrations as integ,
    aws_budgets as budgets, aws_cloudwatch as cw, aws_cloudwatch_actions as cw_actions, aws_cognito as cognito,
    aws_dynamodb as ddb, aws_iam as iam, aws_lambda as _lambda, aws_lambda_event_sources as les, aws_logs as logs,
    aws_sns as sns, aws_sns_subscriptions as subs, aws_sqs as sqs,
)
from constructs import Construct

# Nova Pro in ap-south-1 is invokable only through the APAC cross-region inference profile.
INFERENCE_PROFILE_ID = "apac.amazon.nova-pro-v1:0"
FOUNDATION_MODEL_ID = "amazon.nova-pro-v1:0"
REGION = "ap-south-1"
PUBLIC_GET_ROUTES = ["/health/live", "/health/ready", "/api/health", "/api/reference/options", "/api/demo/scenarios"]
BUILD_DIR = Path(__file__).resolve().parents[2] / "backend" / "build" / "lambda"

WORKER_TIMEOUT_S = 120
JOB_TIMEOUT_S = 100  # app-level job deadline, comfortably below the Lambda timeout
QUEUE_VISIBILITY_S = 180  # must be >= worker timeout (Lambda enforces it); also bounds retry spacing


class NeerAIStack(Stack):
    def __init__(self, scope: Construct, id: str, *, stage: str, frontend_origin: str, weather_provider: str,
                 extra_callbacks: list[str], alert_email: str | None, budget_email: str | None, worker_concurrency: int, **kw) -> None:
        super().__init__(scope, id, **kw)
        prod = stage == "prod"
        retention = logs.RetentionDays.ONE_MONTH if prod else logs.RetentionDays.TWO_WEEKS

        # ───────── data ─────────
        table = ddb.Table(
            self, "Documents", partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING), billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True, time_to_live_attribute="ttl", encryption=ddb.TableEncryption.AWS_MANAGED,
            deletion_protection=prod, removal_policy=RemovalPolicy.RETAIN)

        dlq = sqs.Queue(self, "JobsDlq", retention_period=Duration.days(14), encryption=sqs.QueueEncryption.SQS_MANAGED, enforce_ssl=True)
        queue = sqs.Queue(
            self, "Jobs", visibility_timeout=Duration.seconds(QUEUE_VISIBILITY_S), retention_period=Duration.days(1),
            encryption=sqs.QueueEncryption.SQS_MANAGED, enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq))

        # ───────── identity ─────────
        pool = cognito.UserPool(
            self, "Users", self_sign_up_enabled=True, sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True), mfa=cognito.Mfa.OFF,
            password_policy=cognito.PasswordPolicy(min_length=10, require_digits=True, require_lowercase=True, require_uppercase=True, require_symbols=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY, removal_policy=RemovalPolicy.RETAIN,
            standard_attributes=cognito.StandardAttributes(email=cognito.StandardAttribute(required=True, mutable=True)))
        callbacks = [frontend_origin.rstrip("/") + "/", *extra_callbacks]
        client = pool.add_client(
            "Web", generate_secret=False, prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1), id_token_validity=Duration.hours(1), refresh_token_validity=Duration.days(30),
            o_auth=cognito.OAuthSettings(flows=cognito.OAuthFlows(authorization_code_grant=True),
                                         scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                                         callback_urls=callbacks, logout_urls=callbacks),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO])
        domain_prefix = f"neerai-{stage}-{(self.account or '000000')[-6:]}"
        pool.add_domain("HostedUi", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=domain_prefix))
        issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}"

        # ───────── compute ─────────
        env = {
            "NEERAI_ENV": "aws", "NEERAI_LOG_FORMAT": "json", "NEERAI_AGENT_MODE": "bedrock",
            "NEERAI_BEDROCK_MODEL_ID": INFERENCE_PROFILE_ID, "NEERAI_BEDROCK_REGION": self.region, "NEERAI_AWS_REGION": self.region,
            "NEERAI_REPOSITORY": "dynamodb", "NEERAI_DYNAMODB_TABLE": table.table_name,
            "NEERAI_QUEUE_BACKEND": "sqs", "NEERAI_JOBS_QUEUE_URL": queue.queue_url,
            # Explicit, never defaulted: openmeteo = strict live (outage is reported, never replaced by simulated data).
            "NEERAI_WEATHER_PROVIDER": weather_provider, "NEERAI_AUTO_SEED": "false",
            "NEERAI_AUTH_MODE": "cognito", "NEERAI_COGNITO_REGION": self.region, "NEERAI_COGNITO_USER_POOL_ID": pool.user_pool_id,
            "NEERAI_COGNITO_CLIENT_ID": client.user_pool_client_id, "NEERAI_CORS_ORIGINS": frontend_origin.rstrip("/"),
            "NEERAI_DEMO_DIR": "/var/task/data/demo", "NEERAI_AGENT_TIMEOUT_S": "90",
            "NEERAI_JOB_TIMEOUT_S": str(JOB_TIMEOUT_S), "NEERAI_JOB_MAX_ATTEMPTS": "3",
        }
        code = _lambda.Code.from_asset(str(BUILD_DIR))  # built by scripts/build_lambda.py (CI) - ZIP, no Docker

        api_fn = _lambda.Function(
            self, "ApiFn", runtime=_lambda.Runtime.PYTHON_3_12, architecture=_lambda.Architecture.X86_64, handler="app.lambda_handler.handler",
            code=code, timeout=Duration.seconds(28), memory_size=1024, environment=env,
            log_group=logs.LogGroup(self, "ApiLogs", retention=retention, removal_policy=RemovalPolicy.DESTROY))
        worker_fn = _lambda.Function(
            self, "WorkerFn", runtime=_lambda.Runtime.PYTHON_3_12, architecture=_lambda.Architecture.X86_64, handler="app.lambda_worker.handler",
            code=code, timeout=Duration.seconds(WORKER_TIMEOUT_S), memory_size=1536, environment=env,
            log_group=logs.LogGroup(self, "WorkerLogs", retention=retention, removal_policy=RemovalPolicy.DESTROY))
        worker_fn.add_event_source(les.SqsEventSource(queue, batch_size=1, max_concurrency=worker_concurrency, report_batch_item_failures=True))

        # Least privilege: only the table actions the repository uses; send-only for the API; one model/profile for Bedrock.
        ddb_actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"]
        bedrock = iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODEL_ID}",
                       f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{INFERENCE_PROFILE_ID}"])
        for fn in (api_fn, worker_fn):
            fn.add_to_role_policy(iam.PolicyStatement(actions=ddb_actions, resources=[table.table_arn]))
        queue.grant_send_messages(api_fn)
        worker_fn.add_to_role_policy(iam.PolicyStatement(actions=["sqs:ChangeMessageVisibility"], resources=[queue.queue_arn]))
        worker_fn.add_to_role_policy(bedrock)  # the API Lambda never calls Bedrock: long agent runs happen only in the worker

        # ───────── API ─────────
        jwt = authz.HttpJwtAuthorizer("Cognito", issuer, jwt_audience=[client.user_pool_client_id])
        integration = integ.HttpLambdaIntegration("ApiInt", api_fn)
        api = apigw.HttpApi(
            self, "HttpApi", default_integration=integration, default_authorizer=jwt, create_default_stage=True,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=[frontend_origin.rstrip("/"), *[u.rstrip("/") for u in extra_callbacks]],
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PATCH,
                               apigw.CorsHttpMethod.DELETE, apigw.CorsHttpMethod.OPTIONS],
                allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"], max_age=Duration.hours(1)))
        for p in PUBLIC_GET_ROUTES:
            api.add_routes(path=p, methods=[apigw.HttpMethod.GET], integration=integration, authorizer=apigw.HttpNoneAuthorizer())
        # Explicit route so it can carry its own, stricter throttle (everything else falls through to $default).
        api.add_routes(path="/api/jobs", methods=[apigw.HttpMethod.POST], integration=integration)
        access_logs = logs.LogGroup(self, "ApiAccessLogs", retention=retention, removal_policy=RemovalPolicy.DESTROY)
        stage_cfn = api.default_stage.node.default_child  # type: ignore[union-attr]
        stage_cfn.default_route_settings = {"throttlingRateLimit": 20, "throttlingBurstLimit": 40}  # type: ignore[attr-defined]
        # route_settings is an untyped map: CloudFormation property names are passed through verbatim (PascalCase)
        stage_cfn.route_settings = {"POST /api/jobs": {"ThrottlingRateLimit": 3, "ThrottlingBurstLimit": 6}}  # type: ignore[attr-defined]
        stage_cfn.access_log_settings = {  # type: ignore[attr-defined]
            "destinationArn": access_logs.log_group_arn,
            "format": '{"requestId":"$context.requestId","ip":"$context.identity.sourceIp","method":"$context.httpMethod",'
                      '"route":"$context.routeKey","status":"$context.status","latencyMs":"$context.responseLatency",'
                      '"integrationError":"$context.integrationErrorMessage","authError":"$context.authorizer.error"}'}

        # ───────── observability ─────────
        topic = sns.Topic(self, "Alarms", enforce_ssl=True)
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))
        action = cw_actions.SnsAction(topic)

        def alarm(name: str, metric: cw.IMetric, threshold: float, periods: int = 1, op=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, desc: str = ""):
            a = cw.Alarm(self, name, metric=metric, threshold=threshold, evaluation_periods=periods, comparison_operator=op,
                         treat_missing_data=cw.TreatMissingData.NOT_BREACHING, alarm_description=desc or name)
            a.add_alarm_action(action)
            return a

        five = Duration.minutes(5)
        alarm("ApiLambdaErrors", api_fn.metric_errors(period=five), 1, desc="API Lambda invocation errors")
        alarm("ApiLambdaThrottles", api_fn.metric_throttles(period=five), 1, desc="API Lambda throttled")
        alarm("WorkerLambdaErrors", worker_fn.metric_errors(period=five), 1, desc="Worker Lambda invocation errors/timeouts")
        alarm("WorkerLambdaThrottles", worker_fn.metric_throttles(period=five), 1, desc="Worker Lambda throttled")
        alarm("WorkerDurationP95", worker_fn.metric_duration(period=five, statistic="p95"), 90_000, 2, desc="Agent runs close to the timeout")
        alarm("QueueDepth", queue.metric_approximate_number_of_messages_visible(period=five), 10, desc="Jobs backing up")
        alarm("QueueOldestMessage", queue.metric_approximate_age_of_oldest_message(period=five), 600, desc="Oldest job waiting >10 min")
        alarm("DlqNotEmpty", dlq.metric_approximate_number_of_messages_visible(period=five), 1, desc="Jobs exhausted retries (inspect the DLQ)")
        alarm("Api5xx", api.metric_server_error(period=five), 3, desc="API Gateway 5xx responses")
        alarm("DynamoReadThrottle", cw.Metric(namespace="AWS/DynamoDB", metric_name="ReadThrottleEvents", period=five, statistic="Sum",
                                              dimensions_map={"TableName": table.table_name}), 1, desc="DynamoDB read throttling")
        alarm("DynamoWriteThrottle", cw.Metric(namespace="AWS/DynamoDB", metric_name="WriteThrottleEvents", period=five, statistic="Sum",
                                               dimensions_map={"TableName": table.table_name}), 1, desc="DynamoDB write throttling")
        job_failed = cw.Metric(namespace="NeerAI", metric_name="JobFailed", period=five, statistic="Sum")  # emitted via EMF by the app
        alarm("AgentJobsFailed", job_failed, 2, desc="Agent jobs ending in 'failed'")
        bedrock_dim = {"ModelId": INFERENCE_PROFILE_ID}  # NOTE: metric dimension for cross-region profiles not yet confirmed in a live account
        alarm("BedrockServerErrors", cw.Metric(namespace="AWS/Bedrock", metric_name="InvocationServerErrors", period=five, statistic="Sum",
                                               dimensions_map=bedrock_dim), 3, desc="Bedrock 5xx")
        alarm("BedrockThrottles", cw.Metric(namespace="AWS/Bedrock", metric_name="InvocationThrottles", period=five, statistic="Sum",
                                            dimensions_map=bedrock_dim), 3, desc="Bedrock throttling")

        dash = cw.Dashboard(self, "Dashboard", dashboard_name=f"NeerAI-{stage}")
        dash.add_widgets(
            cw.GraphWidget(title="API Lambda", left=[api_fn.metric_invocations(), api_fn.metric_errors(), api_fn.metric_throttles()]),
            cw.GraphWidget(title="Worker Lambda", left=[worker_fn.metric_invocations(), worker_fn.metric_errors()],
                           right=[worker_fn.metric_duration(statistic="p95")]),
            cw.GraphWidget(title="Job queue", left=[queue.metric_approximate_number_of_messages_visible(),
                                                    dlq.metric_approximate_number_of_messages_visible()],
                           right=[queue.metric_approximate_age_of_oldest_message()]),
            cw.GraphWidget(title="Agent jobs (EMF)", left=[cw.Metric(namespace="NeerAI", metric_name=n, statistic="Sum")
                                                           for n in ("JobSucceeded", "JobFailed", "JobAttemptFailed", "AgentFallbacks")]),
            cw.GraphWidget(title="HTTP API", left=[api.metric_count(), api.metric_server_error(), api.metric_client_error()],
                           right=[api.metric_latency(statistic="p95")]))

        if budget_email:
            budgets.CfnBudget(self, "Budget", budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"NeerAI-{stage}-monthly", budget_type="COST", time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=25, unit="USD"),
                cost_filters={"TagKeyValue": [f"user:Project${'NeerAI'}"]}),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(notification_type="ACTUAL", comparison_operator="GREATER_THAN",
                                                                            threshold=80, threshold_type="PERCENTAGE"),
                        subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=budget_email)]),
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(notification_type="FORECASTED", comparison_operator="GREATER_THAN",
                                                                            threshold=100, threshold_type="PERCENTAGE"),
                        subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=budget_email)])])

        # ───────── outputs (identifiers only - never secrets) ─────────
        CfnOutput(self, "ApiUrl", value=api.api_endpoint, description="VITE_API_URL for Amplify")
        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=client.user_pool_client_id, description="VITE_COGNITO_CLIENT_ID for Amplify")
        CfnOutput(self, "CognitoDomain", value=f"{domain_prefix}.auth.{self.region}.amazoncognito.com", description="VITE_COGNITO_DOMAIN for Amplify")
        CfnOutput(self, "JobsQueueUrl", value=queue.queue_url)
        CfnOutput(self, "JobsDlqUrl", value=dlq.queue_url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "AlarmTopicArn", value=topic.topic_arn)
        CfnOutput(self, "Issuer", value=issuer)


def main() -> None:
    app = cdk.App()
    ctx = app.node.try_get_context
    stage = str(ctx("stage") or "dev")
    if stage not in ("dev", "prod"):
        raise SystemExit("context stage must be 'dev' or 'prod'")
    origin = str(ctx("frontendOrigin") or "")
    if not origin.startswith("https://"):
        raise SystemExit("Pass -c frontendOrigin=https://<branch>.<appId>.amplifyapp.com (create the Amplify app first; see docs/deployment.md)")
    extra = [u.strip() for u in str(ctx("extraCallbackUrls") or "").split(",") if u.strip()]
    if stage == "prod" and any("localhost" in u for u in extra):
        raise SystemExit("localhost callback URLs are not allowed in prod")
    weather = str(ctx("weatherProvider") or "openmeteo")
    if weather not in ("openmeteo", "auto", "mock"):
        raise SystemExit("weatherProvider must be openmeteo, auto or mock")
    budget_email = str(ctx("budgetEmail") or "") if str(ctx("createBudget") or "").lower() == "true" else None
    if str(ctx("createBudget") or "").lower() == "true" and not budget_email:
        raise SystemExit("createBudget=true needs -c budgetEmail=<address>")
    region = str(ctx("region") or REGION)
    if region != REGION and str(ctx("allowOtherRegion")) != "true":
        raise SystemExit(f"NeerAI targets {REGION}; pass -c allowOtherRegion=true to override (Bedrock profile availability differs)")
    stack = NeerAIStack(
        app, f"NeerAI-{stage.capitalize()}", stage=stage, frontend_origin=origin, weather_provider=weather, extra_callbacks=extra,
        alert_email=str(ctx("alertEmail") or "") or None, budget_email=budget_email,
        worker_concurrency=int(ctx("workerConcurrency") or 3),
        env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=region),
        description="NeerAI serverless backend (API Gateway, Lambda, SQS, DynamoDB, Cognito)")
    for k, v in {"Project": "NeerAI", "Environment": stage, "ManagedBy": "CDK"}.items():
        Tags.of(stack).add(k, v)
    app.synth()


if __name__ == "__main__":
    main()
