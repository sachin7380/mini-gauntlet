# Deploying Mini Gauntlet on AWS

A design note, not a deployed system. Everything below sits in one AWS account
(the "scanner account"), separate from the customer accounts it scans.

## Architecture

```
Users ──HTTPS──▶ CloudFront ──▶ S3 (dashboard static files)
                      └─/api/*─▶ ALB (private VPC) ──▶ ECS Fargate: api
                                                          │
                                         RDS PostgreSQL ◀─┤
                                                          └─ sts:AssumeRole ─▶ customer accounts
```

| Concern | Choice |
|---|---|
| **Compute** | ECS on Fargate. The `api` service runs 2 tasks across 2 AZs behind an ALB; the image is the same one CI builds. Scans run in-process today. With many customers, a scan job would go on SQS and a separate Fargate worker service would consume it, so the API stays responsive. |
| **Dashboard** | `npm run build` output in a private S3 bucket behind CloudFront (Origin Access Control). CloudFront routes `/api/*` to the ALB, so the browser sees one origin: no CORS, and the CSP can be `connect-src 'self'`. |
| **Database** | RDS PostgreSQL (Multi-AZ, encrypted with KMS, automated backups, private subnets only). The app needs only `DATABASE_URL` changed to point at it. Schema changes would move to Alembic migrations. |
| **Networking** | A VPC with public subnets (ALB, NAT) and private subnets (Fargate, RDS). Security groups: ALB → api on 8000 only; api → RDS on 5432 only. AWS WAF on CloudFront. VPC endpoints for STS, ECR, Secrets Manager and CloudWatch Logs keep AWS traffic off the internet. |
| **Secrets** | The DB credentials live in Secrets Manager (with RDS-managed rotation) and are injected into the task as env vars through the task definition's `secrets` field. Nothing is in the image or the repo. Customer access uses cross-account IAM roles with an `ExternalId`, never stored keys. |
| **Logs & monitoring** | Containers log to CloudWatch Logs (`awslogs` driver, 30-day retention). Alarms cover ALB 5xx, unhealthy targets, RDS CPU and storage, and scans stuck in RUNNING or FAILED. CloudTrail is on in the scanner account. |
| **TLS / DNS** | ACM certificates on CloudFront and the ALB, with Route 53 for DNS. |

## CI/CD without long-lived keys

1. GitHub Actions (on `main`, after the existing lint/test/build jobs pass) requests an **OIDC token**.
2. An IAM role `gh-deploy` trusts `token.actions.githubusercontent.com`, with conditions
   `aud = sts.amazonaws.com` and `sub = repo:<org>/<repo>:ref:refs/heads/main`.
   `aws-actions/configure-aws-credentials` assumes it and gets 1-hour credentials.
3. The job pushes the api image to ECR (tagged with the git SHA, scanned on push), registers a new
   task definition and runs `aws ecs update-service`. ECS does a rolling deploy with a circuit
   breaker and automatic rollback.
4. It syncs the dashboard build to S3 and invalidates CloudFront.

The deploy role can only do this: ECR push to one repository, `ecs:RegisterTaskDefinition` /
`UpdateService` on one service, `iam:PassRole` for the two task roles, and S3 put + CloudFront
invalidation for the dashboard. GitHub stores no AWS access keys.

## Least-privilege permissions for a live scanner

The scanner's ECS task role may only call `sts:AssumeRole` on
`arn:aws:iam::*:role/MiniGauntletReadOnly` (with an `ExternalId` condition). Each customer creates
that role with this read-only policy, which covers every AWS check in the catalog:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "MiniGauntletReadOnly",
    "Effect": "Allow",
    "Action": [
      "s3:ListAllMyBuckets",
      "s3:GetBucketLocation",
      "s3:GetBucketPublicAccessBlock",
      "ec2:DescribeRegions",
      "ec2:DescribeSecurityGroups",
      "iam:ListUsers",
      "iam:GetLoginProfile",
      "iam:ListMFADevices",
      "iam:ListAccessKeys",
      "rds:DescribeDBInstances"
    ],
    "Resource": "*"
  }]
}
```

| Check | Calls |
|---|---|
| AWS-S3-01 | `ListAllMyBuckets`, `GetBucketLocation` (region), `GetBucketPublicAccessBlock` |
| AWS-EC2-01 | `DescribeRegions`, `DescribeSecurityGroups` (per region) |
| AWS-IAM-01 | `ListUsers`, `GetLoginProfile` (console access), `ListMFADevices` |
| AWS-IAM-02 | `ListUsers`, `ListAccessKeys` (status + `CreateDate`) |
| AWS-RDS-01 | `DescribeDBInstances` (per region; `PubliclyAccessible`) |

Every action is `List`/`Get`/`Describe`: nothing can read object data or secrets, and nothing can
change anything. A denied call shows up as a `CANNOT_SCAN` finding with the error code, exactly as
in the snapshot (`AccessDenied`).

The same model applies to the other clouds:
- **Azure:** a service principal with the built-in **Reader** role, or a custom role with
  `Microsoft.Storage/storageAccounts/read` and `Microsoft.Network/networkSecurityGroups/read`.
- **GCP:** a service account with `storage.buckets.list`, `storage.buckets.getIamPolicy` and
  `compute.firewalls.list`, using Workload Identity Federation from AWS so no key file is needed.
